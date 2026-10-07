"""工事台帳サービス"""

import uuid
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.models import Budget, CostItem, ProjectLedger


async def create_ledger(db: AsyncSession, data: dict) -> ProjectLedger:
    ledger = ProjectLedger(**data)
    db.add(ledger)
    await db.flush()
    await db.refresh(ledger)
    return ledger


async def get_ledger(db: AsyncSession, ledger_id: uuid.UUID) -> ProjectLedger | None:
    return await db.get(ProjectLedger, ledger_id)


async def list_ledgers(
    db: AsyncSession,
    organization_id: uuid.UUID,
    status: str | None = None,
    project_type: str | None = None,
    page: int = 1,
    per_page: int = 20,
) -> tuple[list[ProjectLedger], int]:
    query = select(ProjectLedger).where(
        ProjectLedger.organization_id == organization_id
    )
    count_query = select(func.count(ProjectLedger.id)).where(
        ProjectLedger.organization_id == organization_id
    )

    if status:
        query = query.where(ProjectLedger.status == status)
        count_query = count_query.where(ProjectLedger.status == status)
    if project_type:
        query = query.where(ProjectLedger.project_type == project_type)
        count_query = count_query.where(ProjectLedger.project_type == project_type)

    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    query = query.order_by(ProjectLedger.created_at.desc())
    query = query.offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(query)
    items = list(result.scalars().all())

    return items, total


async def update_ledger(
    db: AsyncSession, ledger: ProjectLedger, data: dict
) -> ProjectLedger:
    for key, value in data.items():
        if value is not None:
            setattr(ledger, key, value)
    ledger.updated_at = datetime.now(timezone.utc)
    _recalculate_profit(ledger)
    await db.flush()
    await db.refresh(ledger)
    return ledger


async def get_ledger_detail(
    db: AsyncSession, ledger: ProjectLedger
) -> dict:
    result = await db.execute(
        select(Budget).where(Budget.ledger_id == ledger.id)
    )
    budgets = list(result.scalars().all())

    result = await db.execute(
        select(
            CostItem.category,
            func.sum(CostItem.amount).label("total"),
        )
        .where(CostItem.ledger_id == ledger.id)
        .group_by(CostItem.category)
    )
    cost_summary = {row.category: row.total for row in result.all()}

    return {
        "ledger": ledger,
        "budgets": budgets,
        "cost_summary": cost_summary,
    }


async def get_financial_summary(
    ledger: ProjectLedger,
) -> dict:
    _recalculate_profit(ledger)
    contract = Decimal(str(ledger.contract_amount))
    actual = Decimal(str(ledger.actual_cost))
    budget = Decimal(str(ledger.budget_amount))
    estimated = contract - actual
    profit_margin = (
        ((estimated / contract) * Decimal("100")).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        if contract > 0
        else Decimal("0")
    )
    budget_utilization = (
        ((actual / budget) * Decimal("100")).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        if budget > 0
        else Decimal("0")
    )

    return {
        "contract_amount": contract,
        "budget_amount": budget,
        "actual_cost": actual,
        "estimated_profit": estimated,
        "profit_margin": profit_margin,
        "progress_rate": Decimal(str(ledger.progress_rate)),
        "budget_utilization": budget_utilization,
    }


def _recalculate_profit(ledger: ProjectLedger) -> None:
    ledger.estimated_profit = Decimal(str(ledger.contract_amount)) - Decimal(
        str(ledger.actual_cost)
    )


async def get_overall_summary(db: AsyncSession, organization_id: uuid.UUID) -> dict:
    """組織内の工事台帳を集計した全社サマリー。

    以前は固定定数を返すスタブで、実データを参照していなかった（画面・MCP が
    実データ前提で消費していた）。ここでは組織スコープで実データを集計する。
    売上総利益のみ算出し、販管費（SG&A）はモデル化されていないため
    営業利益・営業利益率は None（未算出）を返す。
    """
    result = await db.execute(
        select(ProjectLedger).where(ProjectLedger.organization_id == organization_id)
    )
    ledgers = list(result.scalars().all())

    total_revenue = sum(Decimal(str(ledger.contract_amount or 0)) for ledger in ledgers)
    total_cost = sum(Decimal(str(ledger.actual_cost or 0)) for ledger in ledgers)
    gross_profit = total_revenue - total_cost
    projects_count = len(ledgers)

    return {
        "total_revenue": total_revenue,
        "total_cost": total_cost,
        "gross_profit": gross_profit,
        "operating_profit": None,
        "projects_count": projects_count,
        "gross_margin": (
            float(gross_profit / total_revenue) if total_revenue > 0 else 0.0
        ),
        "operating_margin": None,
    }
