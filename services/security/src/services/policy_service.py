"""Security policy service layer."""

from datetime import date, datetime, timezone
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import SecurityPolicy


def _utcnow():
    return datetime.now(timezone.utc)


async def create_policy(
    db: AsyncSession,
    organization_id: UUID,
    name: str,
    category: str,
    content: str,
    description: str | None = None,
    effective_date: str | None = None,
    review_date: str | None = None,
    approved_by: UUID | None = None,
) -> SecurityPolicy:
    policy = SecurityPolicy(
        organization_id=organization_id,
        name=name,
        category=category,
        content=content,
        description=description,
        effective_date=date.fromisoformat(effective_date) if effective_date else None,
        review_date=date.fromisoformat(review_date) if review_date else None,
        approved_by=approved_by,
        status="active",
    )
    db.add(policy)
    await db.flush()
    return policy


async def get_policies(
    db: AsyncSession,
    organization_id: UUID | None = None,
    category: str | None = None,
    status: str | None = None,
    skip: int = 0,
    limit: int = 50,
) -> list[SecurityPolicy]:
    stmt = select(SecurityPolicy)
    if organization_id is not None:
        stmt = stmt.where(SecurityPolicy.organization_id == organization_id)
    if category:
        stmt = stmt.where(SecurityPolicy.category == category)
    if status:
        stmt = stmt.where(SecurityPolicy.status == status)
    stmt = stmt.order_by(SecurityPolicy.created_at.desc()).offset(skip).limit(limit)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_policy_by_id(
    db: AsyncSession, policy_id: UUID, organization_id: UUID | None = None
) -> SecurityPolicy | None:
    """Look up a policy; ``organization_id`` restricts it to one org (``None``: admin, any org)."""
    stmt = select(SecurityPolicy).where(SecurityPolicy.id == policy_id)
    if organization_id is not None:
        stmt = stmt.where(SecurityPolicy.organization_id == organization_id)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def update_policy(
    db: AsyncSession,
    policy_id: UUID,
    organization_id: UUID | None = None,
    name: str | None = None,
    description: str | None = None,
    category: str | None = None,
    content: str | None = None,
    status: str | None = None,
    effective_date: str | None = None,
    review_date: str | None = None,
) -> SecurityPolicy | None:
    policy = await get_policy_by_id(db, policy_id, organization_id)
    if not policy:
        return None
    if name is not None:
        policy.name = name
    if description is not None:
        policy.description = description
    if category is not None:
        policy.category = category
    if content is not None:
        policy.content = content
    if status is not None:
        policy.status = status
    if effective_date is not None:
        policy.effective_date = date.fromisoformat(effective_date)  # type: ignore[assignment]
    if review_date is not None:
        policy.review_date = date.fromisoformat(review_date)  # type: ignore[assignment]
    policy.updated_at = _utcnow()
    await db.flush()
    return policy


async def mark_policy_reviewed(
    db: AsyncSession,
    policy_id: UUID,
    approved_by: UUID,
    new_review_date: date | None = None,
    organization_id: UUID | None = None,
) -> SecurityPolicy | None:
    policy = await get_policy_by_id(db, policy_id, organization_id)
    if not policy:
        return None
    policy.version += 1
    policy.approved_by = approved_by
    if new_review_date:
        policy.review_date = new_review_date  # type: ignore[assignment]
    policy.updated_at = _utcnow()
    await db.flush()
    return policy


async def count_policies_due_review(
    db: AsyncSession, organization_id: UUID | None = None
) -> int:
    today = date.today()
    stmt = (
        select(func.count())
        .select_from(SecurityPolicy)
        .where(
            SecurityPolicy.status == "active",
            SecurityPolicy.review_date <= today,
            SecurityPolicy.review_date.isnot(None),
        )
    )
    if organization_id is not None:
        stmt = stmt.where(SecurityPolicy.organization_id == organization_id)
    result = await db.execute(stmt)
    return result.scalar() or 0
