"""原価管理サービス"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.models import Budget, CostItem, ProjectLedger


async def create_cost(
    db: AsyncSession, ledger_id: uuid.UUID, data: dict
) -> CostItem:
    cost = CostItem(ledger_id=ledger_id, **data)
    db.add(cost)
    await db.flush()
    await db.refresh(cost)
    return cost


async def get_cost(
    db: AsyncSession,
    cost_id: uuid.UUID,
    organization_id: uuid.UUID | None = None,
) -> CostItem | None:
    """Fetch a cost item; when ``organization_id`` is given, other organizations' rows are not found."""
    if organization_id is None:
        return await db.get(CostItem, cost_id)
    result = await db.execute(
        select(CostItem).where(
            CostItem.id == cost_id, CostItem.organization_id == organization_id
        )
    )
    return result.scalar_one_or_none()


async def list_costs(
    db: AsyncSession,
    ledger_id: uuid.UUID,
    status: str | None = None,
    page: int = 1,
    per_page: int = 20,
) -> tuple[list[CostItem], int]:
    query = select(CostItem).where(CostItem.ledger_id == ledger_id)
    count_query = select(func.count(CostItem.id)).where(
        CostItem.ledger_id == ledger_id
    )

    if status:
        query = query.where(CostItem.status == status)
        count_query = count_query.where(CostItem.status == status)

    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    query = query.order_by(CostItem.created_at.desc())
    query = query.offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(query)
    items = list(result.scalars().all())

    return items, total


async def update_cost(
    db: AsyncSession, cost: CostItem, data: dict
) -> CostItem:
    if cost.status != "pending":
        raise ValueError("承認済みまたは却下された原価は編集できません")
    for key, value in data.items():
        if value is not None:
            setattr(cost, key, value)
    await db.flush()
    await db.refresh(cost)
    return cost


async def approve_cost(
    db: AsyncSession, cost: CostItem, approved_by: uuid.UUID
) -> CostItem:
    if cost.status != "pending":
        raise ValueError("既に承認済みまたは却下された原価です")

    cost.status = "approved"
    cost.approved_by = approved_by
    cost.approved_at = datetime.now(timezone.utc)

    # Side effects never cross the tenant boundary (ADR-0004): a budget / ledger of
    # another organization is left untouched even if the cost references it.
    # Update budget actual_amount
    if cost.budget_id:
        budget = await db.get(Budget, cost.budget_id)
        if budget and budget.organization_id == cost.organization_id:
            budget.actual_amount = float(budget.actual_amount) + float(cost.amount)
            budget.updated_at = datetime.now(timezone.utc)

    # Update ledger actual_cost
    if cost.ledger_id:
        ledger = await db.get(ProjectLedger, cost.ledger_id)
        if ledger and ledger.organization_id == cost.organization_id:
            ledger.actual_cost = float(ledger.actual_cost) + float(cost.amount)
            ledger.estimated_profit = (
                float(ledger.contract_amount) - float(ledger.actual_cost)
            )
            ledger.updated_at = datetime.now(timezone.utc)

    await db.flush()
    await db.refresh(cost)
    return cost


async def delete_cost(db: AsyncSession, cost: CostItem) -> bool:
    if cost.status != "pending":
        return False
    await db.delete(cost)
    await db.flush()
    return True
