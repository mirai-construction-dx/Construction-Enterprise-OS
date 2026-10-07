"""協力会社管理ビジネスロジック"""

import uuid

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..models import Partner, PartnerContact, Evaluation


async def create_partner(
    db: AsyncSession, organization_id: uuid.UUID, data: dict
) -> Partner:
    partner = Partner(
        id=uuid.uuid4(),
        organization_id=organization_id,
        **data,
    )
    db.add(partner)
    return partner


async def get_partner_by_id(
    db: AsyncSession,
    partner_id: uuid.UUID,
    organization_id: uuid.UUID,
) -> Partner | None:
    stmt = (
        select(Partner)
        .options(
            selectinload(Partner.contacts),
        )
        .where(Partner.id == partner_id)
    )
    if organization_id is not None:
        stmt = stmt.where(Partner.organization_id == organization_id)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def list_partners(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    page: int = 1,
    per_page: int = 20,
    company_type: str | None = None,
    status: str | None = None,
    specialization: str | None = None,
    search: str | None = None,
) -> tuple[list[Partner], int]:
    conditions = []
    if organization_id is not None:
        conditions.append(Partner.organization_id == organization_id)
    if company_type:
        conditions.append(Partner.company_type == company_type)
    if status:
        conditions.append(Partner.status == status)
    if specialization:
        conditions.append(Partner.specializations.any(specialization))  # type: ignore[arg-type]
    if search:
        conditions.append(
            or_(
                Partner.name.ilike(f"%{search}%"),
                Partner.name_kana.ilike(f"%{search}%"),
                Partner.email.ilike(f"%{search}%"),
            )
        )

    base_query = select(Partner)
    if conditions:
        base_query = base_query.where(*conditions)

    count_query = select(func.count()).select_from(Partner)
    if conditions:
        count_query = count_query.where(*conditions)
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    offset = (page - 1) * per_page
    query = (
        base_query.order_by(Partner.registered_at.desc()).offset(offset).limit(per_page)
    )
    result = await db.execute(query)
    partners = list(result.scalars().all())
    return partners, total


async def update_partner(
    db: AsyncSession,
    partner_id: uuid.UUID,
    update_data: dict,
    organization_id: uuid.UUID,
) -> Partner | None:
    partner = await get_partner_by_id(db, partner_id, organization_id)
    if not partner:
        return None

    for field, value in update_data.items():
        if value is not None:
            setattr(partner, field, value)
    return partner


async def add_contact(
    db: AsyncSession, partner_id: uuid.UUID, contact_data: dict
) -> PartnerContact:
    contact = PartnerContact(
        id=uuid.uuid4(),
        partner_id=partner_id,
        **contact_data,
    )
    db.add(contact)
    return contact


async def list_contacts(
    db: AsyncSession, partner_id: uuid.UUID
) -> list[PartnerContact]:
    result = await db.execute(
        select(PartnerContact).where(PartnerContact.partner_id == partner_id)
    )
    return list(result.scalars().all())


async def calculate_partner_rating(
    db: AsyncSession,
    partner_id: uuid.UUID,
    organization_id: uuid.UUID,
) -> float | None:
    stmt = select(func.avg(Evaluation.overall_score)).where(
        Evaluation.partner_id == partner_id
    )
    if organization_id is not None:
        stmt = stmt.where(Evaluation.organization_id == organization_id)
    result = await db.execute(stmt)
    avg = result.scalar()
    # 平均 0.0 は falsy のため ``if avg`` では欠測(None)と区別できない。
    # evaluation_service.get_partner_rating と挙動を揃える（P-8）。
    return round(float(avg), 1) if avg is not None else 0.0
