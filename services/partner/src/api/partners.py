"""協力会社管理エンドポイント"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from ..middleware.auth import get_current_user, require_organization_id
from ..models.base import get_db
from ..schemas import (
    APIResponse,
    ContractResponse,
    EvaluationResponse,
    PartnerContactCreate,
    PartnerContactResponse,
    PartnerCreate,
    PartnerDetailResponse,
    PartnerRatingResponse,
    PartnerResponse,
    PartnerUpdate,
    TokenData,
)
from ..services import partner_service, contract_service, evaluation_service
from .contracts import _contract_to_response
from .evaluations import _evaluation_to_response

router = APIRouter()


def _partner_to_response(partner) -> PartnerResponse:
    return PartnerResponse(
        id=partner.id,
        organization_id=partner.organization_id,
        name=partner.name,
        name_kana=partner.name_kana,
        company_type=partner.company_type,
        tax_id=partner.tax_id,
        address=partner.address,
        phone=partner.phone,
        email=partner.email,
        website=partner.website,
        representative_name=partner.representative_name,
        employee_count=partner.employee_count,
        established_year=partner.established_year,
        specializations=partner.specializations,
        license_info=partner.license_info,
        insurance_info=partner.insurance_info,
        status=partner.status,
        rating=partner.rating,
        registered_at=partner.registered_at,
        updated_at=partner.updated_at,
    )


def _contact_to_response(contact) -> PartnerContactResponse:
    return PartnerContactResponse(
        id=contact.id,
        partner_id=contact.partner_id,
        name=contact.name,
        title=contact.title,
        department=contact.department,
        email=contact.email,
        phone=contact.phone,
        is_primary=contact.is_primary,
        created_at=contact.created_at,
    )


@router.post("", response_model=APIResponse[PartnerResponse], status_code=status.HTTP_201_CREATED)
async def create_partner(
    request: Request,
    body: PartnerCreate,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    org_id = require_organization_id(current_user)
    partner = await partner_service.create_partner(db, org_id, body.model_dump())
    await db.flush()
    await db.refresh(partner)
    return APIResponse(data=_partner_to_response(partner))


@router.get("", response_model=APIResponse[list[PartnerResponse]])
async def list_partners(
    request: Request,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    company_type: str | None = Query(None),
    status: str | None = Query(None),
    specialization: str | None = Query(None),
    search: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    partners, total = await partner_service.list_partners(
        db,
        organization_id=require_organization_id(current_user),
        page=page,
        per_page=per_page,
        company_type=company_type,
        status=status,
        specialization=specialization,
        search=search,
    )
    total_pages = max((total + per_page - 1) // per_page, 1) if total > 0 else 0
    return APIResponse(
        data=[_partner_to_response(p) for p in partners],
        meta={
            "page": page,
            "per_page": per_page,
            "total": total,
            "total_pages": total_pages,
        },
    )


@router.get("/{partner_id}", response_model=APIResponse[PartnerDetailResponse])
async def get_partner(
    request: Request,
    partner_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    org_id = require_organization_id(current_user)
    partner = await partner_service.get_partner_by_id(db, partner_id, org_id)
    if not partner or partner.organization_id != org_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "PARTNER_NOT_FOUND", "message": "協力会社が見つかりません。"},
        )

    contracts, _ = await contract_service.list_contracts_for_partner(
        db, partner_id, page=1, per_page=5, organization_id=org_id
    )
    contracts_summary = [
        {"id": c.id, "title": c.title, "contract_type": c.contract_type, "status": c.status, "amount": float(c.amount)}
        for c in contracts
    ]

    return APIResponse(data=PartnerDetailResponse(
        **_partner_to_response(partner).model_dump(),
        contacts=[_contact_to_response(c) for c in partner.contacts],
        contracts_summary=contracts_summary,
    ))


@router.put("/{partner_id}", response_model=APIResponse[PartnerResponse])
async def update_partner(
    request: Request,
    partner_id: UUID,
    body: PartnerUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    partner = await partner_service.update_partner(db, partner_id, body.model_dump(exclude_unset=True))
    if not partner:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "PARTNER_NOT_FOUND", "message": "協力会社が見つかりません。"},
        )
    return APIResponse(data=_partner_to_response(partner))


@router.post("/{partner_id}/contacts", response_model=APIResponse[PartnerContactResponse], status_code=status.HTTP_201_CREATED)
async def add_contact(
    request: Request,
    partner_id: UUID,
    body: PartnerContactCreate,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    org_id = require_organization_id(current_user)
    partner = await partner_service.get_partner_by_id(db, partner_id, org_id)
    if not partner or partner.organization_id != org_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "PARTNER_NOT_FOUND", "message": "協力会社が見つかりません。"},
        )

    contact = await partner_service.add_contact(db, partner_id, body.model_dump())
    await db.flush()
    await db.refresh(contact)
    return APIResponse(data=_contact_to_response(contact))


@router.get("/{partner_id}/contacts", response_model=APIResponse[list[PartnerContactResponse]])
async def list_contacts(
    request: Request,
    partner_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    org_id = require_organization_id(current_user)
    partner = await partner_service.get_partner_by_id(db, partner_id, org_id)
    if not partner or partner.organization_id != org_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "PARTNER_NOT_FOUND", "message": "協力会社が見つかりません。"},
        )

    contacts = await partner_service.list_contacts(db, partner_id)
    return APIResponse(data=[_contact_to_response(c) for c in contacts])


@router.get("/{partner_id}/contracts", response_model=APIResponse[list[ContractResponse]])
async def get_partner_contracts(
    request: Request,
    partner_id: UUID,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    contracts_, total = await contract_service.list_contracts_for_partner(
        db,
        partner_id,
        page=page,
        per_page=per_page,
        organization_id=require_organization_id(current_user),
    )
    total_pages = max((total + per_page - 1) // per_page, 1) if total > 0 else 0
    return APIResponse(
        data=[_contract_to_response(c) for c in contracts_],
        meta={
            "page": page,
            "per_page": per_page,
            "total": total,
            "total_pages": total_pages,
        },
    )


@router.get("/{partner_id}/evaluations", response_model=APIResponse[list[EvaluationResponse]])
async def get_partner_evaluations(
    request: Request,
    partner_id: UUID,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    evaluations, total = await evaluation_service.get_partner_evaluations(
        db,
        partner_id,
        page=page,
        per_page=per_page,
        organization_id=require_organization_id(current_user),
    )
    total_pages = max((total + per_page - 1) // per_page, 1) if total > 0 else 0
    return APIResponse(
        data=[_evaluation_to_response(e) for e in evaluations],
        meta={
            "page": page,
            "per_page": per_page,
            "total": total,
            "total_pages": total_pages,
        },
    )


@router.get("/{partner_id}/rating", response_model=APIResponse[PartnerRatingResponse])
async def get_partner_rating(
    request: Request,
    partner_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    rating, count = await evaluation_service.get_partner_rating(
        db, partner_id, require_organization_id(current_user)
    )
    return APIResponse(data=PartnerRatingResponse(
        partner_id=partner_id,
        average_rating=rating,
        evaluation_count=count,
    ))
