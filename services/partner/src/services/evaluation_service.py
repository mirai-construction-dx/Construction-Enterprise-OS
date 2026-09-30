"""評価管理ビジネスロジック"""

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Evaluation, Partner


async def create_evaluation(
    db: AsyncSession, organization_id: uuid.UUID, evaluator_id: uuid.UUID, data: dict
) -> Evaluation:
    evaluation = Evaluation(
        id=uuid.uuid4(),
        organization_id=organization_id,
        evaluator_id=evaluator_id,
        **data,
    )
    db.add(evaluation)
    return evaluation


async def list_evaluations(
    db: AsyncSession,
    *,
    page: int = 1,
    per_page: int = 20,
    partner_id: uuid.UUID | None = None,
    project_id: uuid.UUID | None = None,
    organization_id: uuid.UUID | None = None,
) -> tuple[list[Evaluation], int]:
    conditions = []
    if organization_id is not None:
        conditions.append(Evaluation.organization_id == organization_id)
    if partner_id:
        conditions.append(Evaluation.partner_id == partner_id)
    if project_id:
        conditions.append(Evaluation.project_id == project_id)

    base_query = select(Evaluation)
    if conditions:
        base_query = base_query.where(*conditions)

    count_query = select(func.count()).select_from(Evaluation)
    if conditions:
        count_query = count_query.where(*conditions)
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    offset = (page - 1) * per_page
    query = (
        base_query
        .order_by(Evaluation.created_at.desc())
        .offset(offset)
        .limit(per_page)
    )
    result = await db.execute(query)
    evaluations = list(result.scalars().all())
    return evaluations, total


async def get_partner_evaluations(
    db: AsyncSession,
    partner_id: uuid.UUID,
    page: int = 1,
    per_page: int = 20,
    organization_id: uuid.UUID | None = None,
) -> tuple[list[Evaluation], int]:
    return await list_evaluations(
        db, page=page, per_page=per_page, partner_id=partner_id, organization_id=organization_id
    )


async def get_partner_rating(
    db: AsyncSession, partner_id: uuid.UUID, organization_id: uuid.UUID | None = None
) -> tuple[float, int]:
    stmt = select(
        func.avg(Evaluation.overall_score),
        func.count(Evaluation.id),
    ).where(Evaluation.partner_id == partner_id)
    if organization_id is not None:
        stmt = stmt.where(Evaluation.organization_id == organization_id)
    result = await db.execute(stmt)
    avg, count = result.one_or_none() or (None, 0)
    rating = round(float(avg), 1) if avg else 0.0
    return rating, count


async def update_partner_rating(
    db: AsyncSession, partner_id: uuid.UUID, organization_id: uuid.UUID | None = None
) -> None:
    """Recompute the partner rating from evaluations of the partner's organization."""
    rating, _ = await get_partner_rating(db, partner_id, organization_id)
    stmt = select(Partner).where(Partner.id == partner_id)
    if organization_id is not None:
        stmt = stmt.where(Partner.organization_id == organization_id)
    result = await db.execute(stmt)
    partner = result.scalar_one_or_none()
    if partner:
        partner.rating = rating if rating > 0 else None
