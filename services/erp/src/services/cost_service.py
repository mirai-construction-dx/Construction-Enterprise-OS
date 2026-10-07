"""原価管理サービス"""

import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.models import Budget, CostItem, ProjectLedger


async def create_cost(
    db: AsyncSession,
    ledger_id: uuid.UUID,
    data: dict,
    organization_id: uuid.UUID,
    actor_id: uuid.UUID,
) -> CostItem:
    # 予算の誤帰属防止（D9）: budget_id は当該台帳・同一テナントに属すること
    budget_id = data.get("budget_id")
    if budget_id:
        budget = await db.get(Budget, budget_id)
        if (
            not budget
            or budget.ledger_id != ledger_id
            or budget.organization_id != organization_id
        ):
            raise ValueError("予算がこの台帳に属していません")

    cost = CostItem(
        ledger_id=ledger_id,
        organization_id=organization_id,
        created_by=actor_id,
        **data,
    )
    db.add(cost)
    await db.flush()
    await db.refresh(cost)
    return cost


async def get_cost(db: AsyncSession, cost_id: uuid.UUID) -> CostItem | None:
    return await db.get(CostItem, cost_id)


async def list_costs(
    db: AsyncSession,
    ledger_id: uuid.UUID,
    organization_id: uuid.UUID,
    status: str | None = None,
    page: int = 1,
    per_page: int = 20,
) -> tuple[list[CostItem], int]:
    query = select(CostItem).where(
        CostItem.ledger_id == ledger_id,
        CostItem.organization_id == organization_id,
    )
    count_query = select(func.count(CostItem.id)).where(
        CostItem.ledger_id == ledger_id,
        CostItem.organization_id == organization_id,
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

    # 予算の誤帰属防止（D9）: 承認時も budget の台帳・テナント整合を検査する
    budget = None
    if cost.budget_id:
        budget = await db.get(Budget, cost.budget_id)
        if (
            not budget
            or budget.ledger_id != cost.ledger_id
            or budget.organization_id != cost.organization_id
        ):
            raise ValueError("予算がこの台帳に属していません")

    cost.status = "approved"
    cost.approved_by = approved_by
    cost.approved_at = datetime.now(timezone.utc)

    # 金額は Decimal で加算し、float 起因の丸め誤差（0.30000000000000004 等）を防ぐ
    if budget is not None:
        budget.actual_amount = Decimal(str(budget.actual_amount)) + Decimal(
            str(cost.amount)
        )
        budget.updated_at = datetime.now(timezone.utc)

    if cost.ledger_id:
        ledger = await db.get(ProjectLedger, cost.ledger_id)
        if ledger:
            ledger.actual_cost = Decimal(str(ledger.actual_cost)) + Decimal(
                str(cost.amount)
            )
            ledger.estimated_profit = Decimal(str(ledger.contract_amount)) - Decimal(
                str(ledger.actual_cost)
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
