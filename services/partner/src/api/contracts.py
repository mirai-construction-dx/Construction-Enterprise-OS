"""契約管理エンドポイント"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from ..middleware.auth import get_current_user
from ..middleware.tenant import create_org, is_cross_org_admin, scope_org
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
from ..services.contract_service import ContractStateError

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


def _partner_org_mismatch() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail={
            "code": "PARTNER_ORG_MISMATCH",
            "message": "契約と異なる組織の協力会社は指定できません。",
        },
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
    # Load the contract first (regular users: token org only; admin: any org) so that a
    # partner re-point can be validated against the contract's own organization.
    contract = await contract_service.get_contract_by_id(db, contract_id, scope_org(current_user))
    if not contract:
        raise _contract_not_found()
    update_data = body.model_dump(exclude_unset=True)
    if update_data.get("status") == "active" and contract.signed_at is None:
        # 署名を経由せずに active へ遷移させることを禁じる（署名の迂回防止）
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "SIGNATURE_REQUIRED",
                "message": "active への変更は署名 API を使用してください。",
            },
        )
    if update_data.get("partner_id") is not None:
        # A contract belongs to its partner's organization, so the new partner must belong to
        # the contract's organization (admin included). For regular users the contract's org is
        # their token org, so another org's partner is simply not found (404).
        if is_cross_org_admin(current_user):
            partner = await partner_service.get_partner_by_id(db, update_data["partner_id"])
            if not partner:
                raise _partner_not_found()
            if partner.organization_id != contract.organization_id:
                # Admin can see both records, so hiding the partner (404) would be misleading;
                # the request itself is invalid because it would move the contract across orgs.
                raise _partner_org_mismatch()
        elif not await partner_service.get_partner_by_id(
            db, update_data["partner_id"], contract.organization_id
        ):
            raise _partner_not_found()
    contract_service.apply_contract_update(contract, update_data)
    return APIResponse(data=_contract_to_response(contract))


@router.post("/{contract_id}/sign", response_model=APIResponse[ContractResponse])
async def sign_contract(
    request: Request,
    contract_id: UUID,
    body: ContractSignRequest,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    try:
        contract = await contract_service.sign_contract(
            db,
            contract_id,
            UUID(current_user.sub),
            body.signed_by_partner,
            scope_org(current_user),
        )
    except ContractStateError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "INVALID_TRANSITION", "message": str(exc)},
        ) from exc
    if not contract:
        raise _contract_not_found()
    return APIResponse(data=_contract_to_response(contract))
