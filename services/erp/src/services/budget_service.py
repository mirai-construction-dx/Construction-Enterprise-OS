"""予算管理サービス"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.models import Budget


async def create_budget(db: AsyncSession, ledger_id: uuid.UUID, data: dict) -> Budget:
    budget = Budget(ledger_id=ledger_id, **data)
    db.add(budget)
    await db.flush()
    await db.refresh(budget)
    return budget


async def get_budget(
    db: AsyncSession,
    budget_id: uuid.UUID,
    organization_id: uuid.UUID | None = None,
) -> Budget | None:
    """Fetch a budget item; when ``organization_id`` is given, other organizations' rows are not found."""
    if organization_id is None:
        return await db.get(Budget, budget_id)
    result = await db.execute(
        select(Budget).where(
            Budget.id == budget_id, Budget.organization_id == organization_id
        )
    )
    return result.scalar_one_or_none()


async def list_budgets(
    db: AsyncSession,
    ledger_id: uuid.UUID,
    organization_id: uuid.UUID | None = None,
) -> list[Budget]:
    """List a ledger's budget items.

    When ``organization_id`` is given, the child rows themselves are also filtered by
    organization (defense in depth on top of the parent-ledger check, ADR-0004).
    """
    query = select(Budget).where(Budget.ledger_id == ledger_id)
    if organization_id is not None:
        query = query.where(Budget.organization_id == organization_id)
    result = await db.execute(query.order_by(Budget.category))
    return list(result.scalars().all())


async def update_budget(
    db: AsyncSession, budget: Budget, data: dict
) -> Budget:
    for key, value in data.items():
        if value is not None:
            setattr(budget, key, value)
    budget.updated_at = datetime.now(timezone.utc)
    await db.flush()
    await db.refresh(budget)
    return budget


async def get_budget_summary(
    db: AsyncSession,
    ledger_id: uuid.UUID,
    organization_id: uuid.UUID | None = None,
) -> dict:
    budgets = await list_budgets(db, ledger_id, organization_id)
    total_planned = sum(float(b.planned_amount) for b in budgets)
    total_actual = sum(float(b.actual_amount) for b in budgets)
    return {
        "ledger_id": ledger_id,
        "budget_items": budgets,
        "total_planned": total_planned,
        "total_actual": total_actual,
        "total_variance": total_planned - total_actual,
    }
