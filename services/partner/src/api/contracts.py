"""契約管理エンドポイント"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from ..middleware.auth import get_current_user
from ..middleware.tenant import create_org, scope_org
from ..models.base import get_db
from ..schemas import (
    APIResponse,
    ContractCreate,
    ContractResponse,
    ContractSignRequest,
    ContractUpdate,
    TokenData,
)
from ..services import contract_service, partner_service

router = APIRouter()


def _contract_not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={"code": "CONTRACT_NOT_FOUND", "message": "契約が見つかりません。"},
    )


def _partner_not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={"code": "PARTNER_NOT_FOUND", "message": "協力会社が見つかりません。"},
    )


def _contract_to_response(contract) -> ContractResponse:
    return ContractResponse(
        id=contract.id,
        organization_id=contract.organization_id,
        partner_id=contract.partner_id,
        project_id=contract.project_id,
        contract_number=contract.contract_number,
        title=contract.title,
        contract_type=contract.contract_type,
        amount=float(contract.amount),
        currency=contract.currency,
        start_date=contract.start_date,
        end_date=contract.end_date,
        status=contract.status,
        terms=contract.terms,
        signed_by_our=contract.signed_by_our,
        signed_by_partner=contract.signed_by_partner,
        signed_at=contract.signed_at,
        created_at=contract.created_at,
        updated_at=contract.updated_at,
    )


@router.post("", response_model=APIResponse[ContractResponse], status_code=status.HTTP_201_CREATED)
async def create_contract(
    request: Request,
    body: ContractCreate,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    # ContractCreate has no organization_id: the contract belongs to the referenced partner's
    # organization, which must be visible to the caller (regular users: their token org).
    partner = await partner_service.get_partner_by_id(db, body.partner_id, scope_org(current_user))
    if not partner:
        raise _partner_not_found()
    org_id = create_org(current_user, partner.organization_id)
    contract = await contract_service.create_contract(db, org_id, body.model_dump())
    await db.flush()
    await db.refresh(contract)
    return APIResponse(data=_contract_to_response(contract))


@router.get("", response_model=APIResponse[list[ContractResponse]])
async def list_contracts(
    request: Request,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    partner_id: UUID | None = Query(None),
    project_id: UUID | None = Query(None),
    status: str | None = Query(None),
    contract_type: str | None = Query(None),
    organization_id: UUID | None = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    contracts, total = await contract_service.list_contracts(
        db,
        organization_id=scope_org(current_user, organization_id),
        page=page,
        per_page=per_page,
        partner_id=partner_id,
        project_id=project_id,
        status=status,
        contract_type=contract_type,
    )
    total_pages = max((total + per_page - 1) // per_page, 1) if total > 0 else 0
    return APIResponse(
        data=[_contract_to_response(c) for c in contracts],
        meta={
            "page": page,
            "per_page": per_page,
            "total": total,
            "total_pages": total_pages,
        },
    )


@router.get("/{contract_id}", response_model=APIResponse[ContractResponse])
async def get_contract(
    request: Request,
    contract_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    contract = await contract_service.get_contract_by_id(db, contract_id, scope_org(current_user))
    if not contract:
        raise _contract_not_found()
    return APIResponse(data=_contract_to_response(contract))


@router.put("/{contract_id}", response_model=APIResponse[ContractResponse])
async def update_contract(
    request: Request,
    contract_id: UUID,
    body: ContractUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    org = scope_org(current_user)
    update_data = body.model_dump(exclude_unset=True)
    if update_data.get("partner_id") is not None:
        # Re-pointing a contract to another partner requires that partner to be visible too.
        if not await partner_service.get_partner_by_id(db, update_data["partner_id"], org):
            raise _partner_not_found()
    contract = await contract_service.update_contract(db, contract_id, update_data, org)
    if not contract:
        raise _contract_not_found()
    return APIResponse(data=_contract_to_response(contract))


@router.post("/{contract_id}/sign", response_model=APIResponse[ContractResponse])
async def sign_contract(
    request: Request,
    contract_id: UUID,
    body: ContractSignRequest,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    contract = await contract_service.sign_contract(
        db, contract_id, body.signed_by_our, body.signed_by_partner, scope_org(current_user)
    )
    if not contract:
        raise _contract_not_found()
    return APIResponse(data=_contract_to_response(contract))
