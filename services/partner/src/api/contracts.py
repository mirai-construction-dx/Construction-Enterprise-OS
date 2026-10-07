"""契約管理エンドポイント"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from ..middleware.auth import (
    get_current_user,
    require_actor_id,
    require_organization_id,
)
from ..models.base import get_db
from ..schemas import (
    APIResponse,
    ContractCreate,
    ContractResponse,
    ContractSignRequest,
    ContractUpdate,
    TokenData,
)
from ..services import contract_service
from ..services.contract_service import ContractStateError

router = APIRouter()


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
    org_id = require_organization_id(current_user)
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
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    contracts, total = await contract_service.list_contracts(
        db,
        organization_id=require_organization_id(current_user),
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
    org_id = require_organization_id(current_user)
    contract = await contract_service.get_contract_by_id(db, contract_id, org_id)
    if not contract or contract.organization_id != org_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "CONTRACT_NOT_FOUND", "message": "契約が見つかりません。"},
        )
    return APIResponse(data=_contract_to_response(contract))


@router.put("/{contract_id}", response_model=APIResponse[ContractResponse])
async def update_contract(
    request: Request,
    contract_id: UUID,
    body: ContractUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    org_id = require_organization_id(current_user)
    existing = await contract_service.get_contract_by_id(db, contract_id, org_id)
    if not existing or existing.organization_id != org_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "CONTRACT_NOT_FOUND", "message": "契約が見つかりません。"},
        )
    payload = body.model_dump(exclude_unset=True)
    if payload.get("status") == "active" and existing.signed_at is None:
        # 署名を経由せずに active へ遷移させることを禁じる（署名の迂回防止）
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "SIGNATURE_REQUIRED",
                "message": "active への変更は署名 API を使用してください。",
            },
        )
    contract = await contract_service.update_contract(db, contract_id, payload, org_id)
    if not contract:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "CONTRACT_NOT_FOUND", "message": "契約が見つかりません。"},
        )
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
            require_actor_id(current_user),
            body.signed_by_partner,
            organization_id=require_organization_id(current_user),
        )
    except ContractStateError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "INVALID_TRANSITION", "message": str(exc)},
        ) from exc
    if not contract:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "CONTRACT_NOT_FOUND", "message": "契約が見つかりません。"},
        )
    return APIResponse(data=_contract_to_response(contract))
