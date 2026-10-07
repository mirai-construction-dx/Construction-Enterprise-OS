"""契約管理ビジネスロジック"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Contract


async def create_contract(
    db: AsyncSession, organization_id: uuid.UUID, data: dict
) -> Contract:
    contract = Contract(
        id=uuid.uuid4(),
        organization_id=organization_id,
        **data,
    )
    db.add(contract)
    return contract


async def get_contract_by_id(
    db: AsyncSession, contract_id: uuid.UUID, organization_id: uuid.UUID | None = None
) -> Contract | None:
    """Fetch a contract; ``organization_id`` restricts the lookup (None only for cross-org admin)."""
    stmt = select(Contract).where(Contract.id == contract_id)
    if organization_id is not None:
        stmt = stmt.where(Contract.organization_id == organization_id)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def list_contracts(
    db: AsyncSession,
    *,
    page: int = 1,
    per_page: int = 20,
    partner_id: uuid.UUID | None = None,
    project_id: uuid.UUID | None = None,
    status: str | None = None,
    contract_type: str | None = None,
    organization_id: uuid.UUID | None = None,
) -> tuple[list[Contract], int]:
    conditions = []
    if organization_id is not None:
        conditions.append(Contract.organization_id == organization_id)
    if partner_id:
        conditions.append(Contract.partner_id == partner_id)
    if project_id:
        conditions.append(Contract.project_id == project_id)
    if status:
        conditions.append(Contract.status == status)
    if contract_type:
        conditions.append(Contract.contract_type == contract_type)

    base_query = select(Contract)
    if conditions:
        base_query = base_query.where(*conditions)

    count_query = select(func.count()).select_from(Contract)
    if conditions:
        count_query = count_query.where(*conditions)
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    offset = (page - 1) * per_page
    query = (
        base_query
        .order_by(Contract.created_at.desc())
        .offset(offset)
        .limit(per_page)
    )
    result = await db.execute(query)
    contracts = list(result.scalars().all())
    return contracts, total


async def update_contract(
    db: AsyncSession,
    contract_id: uuid.UUID,
    update_data: dict,
    organization_id: uuid.UUID | None = None,
) -> Contract | None:
    contract = await get_contract_by_id(db, contract_id, organization_id)
    if not contract:
        return None
    return apply_contract_update(contract, update_data)


def apply_contract_update(contract: Contract, update_data: dict) -> Contract:
    """Apply non-null fields to an already loaded (and authorized) contract."""
    for field, value in update_data.items():
        if value is not None:
            setattr(contract, field, value)
    return contract


class ContractStateError(ValueError):
    """署名できない契約状態。"""


# 署名してはならない状態（終端・取消）
UNSIGNABLE_STATUSES = frozenset({"terminated", "expired", "cancelled"})


async def sign_contract(
    db: AsyncSession,
    contract_id: uuid.UUID,
    signed_by_our: uuid.UUID,
    signed_by_partner: str,
    organization_id: uuid.UUID | None = None,
) -> Contract | None:
    contract = await get_contract_by_id(db, contract_id, organization_id)
    if not contract:
        return None
    if contract.status in UNSIGNABLE_STATUSES:
        raise ContractStateError(
            f"contract {contract_id} is {contract.status} and cannot be signed"
        )
    if contract.signed_at is not None:
        # 先行署名を上書きしない（証跡の否認不能性を守る）
        raise ContractStateError(f"contract {contract_id} is already signed")

    contract.status = "active"
    contract.signed_by_our = signed_by_our
    contract.signed_by_partner = signed_by_partner
    contract.signed_at = datetime.now(timezone.utc)
    return contract


async def list_contracts_for_partner(
    db: AsyncSession,
    partner_id: uuid.UUID,
    page: int = 1,
    per_page: int = 20,
    organization_id: uuid.UUID | None = None,
) -> tuple[list[Contract], int]:
    return await list_contracts(
        db, page=page, per_page=per_page, partner_id=partner_id, organization_id=organization_id
    )
