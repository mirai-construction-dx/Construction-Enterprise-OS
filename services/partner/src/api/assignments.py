"""プロジェクトアサイン管理エンドポイント"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from ..middleware.auth import get_current_user
from ..middleware.tenant import create_org, scope_org
from ..models.base import get_db
from ..schemas import (
    APIResponse,
    AssignmentCreate,
    AssignmentResponse,
    TokenData,
)
from ..services import assignment_service, contract_service, partner_service

assign_router = APIRouter()
project_router = APIRouter()


def _partner_not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={"code": "PARTNER_NOT_FOUND", "message": "協力会社が見つかりません。"},
    )


def _contract_not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={"code": "CONTRACT_NOT_FOUND", "message": "契約が見つかりません。"},
    )


def _assignment_to_response(assignment) -> AssignmentResponse:
    return AssignmentResponse(
        id=assignment.id,
        organization_id=assignment.organization_id,
        partner_id=assignment.partner_id,
        project_id=assignment.project_id,
        contract_id=assignment.contract_id,
        role=assignment.role,
        scope_of_work=assignment.scope_of_work,
        start_date=assignment.start_date,
        end_date=assignment.end_date,
        status=assignment.status,
        created_at=assignment.created_at,
    )


@assign_router.post("", response_model=APIResponse[AssignmentResponse], status_code=status.HTTP_201_CREATED)
async def create_assignment(
    request: Request,
    body: AssignmentCreate,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    # AssignmentCreate has no organization_id: the assignment belongs to the referenced partner's
    # organization. The partner (and contract, if any) must be visible to the caller and belong
    # to the same organization.
    partner = await partner_service.get_partner_by_id(db, body.partner_id, scope_org(current_user))
    if not partner:
        raise _partner_not_found()
    org_id = create_org(current_user, partner.organization_id)
    if body.contract_id is not None:
        if not await contract_service.get_contract_by_id(db, body.contract_id, org_id):
            raise _contract_not_found()
    assignment = await assignment_service.create_assignment(db, org_id, body.model_dump())
    await db.flush()
    await db.refresh(assignment)
    return APIResponse(data=_assignment_to_response(assignment))


@assign_router.get("", response_model=APIResponse[list[AssignmentResponse]])
async def list_assignments(
    request: Request,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    partner_id: UUID | None = Query(None),
    project_id: UUID | None = Query(None),
    status: str | None = Query(None),
    organization_id: UUID | None = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    assignments, total = await assignment_service.list_assignments(
        db,
        organization_id=scope_org(current_user, organization_id),
        page=page,
        per_page=per_page,
        partner_id=partner_id,
        project_id=project_id,
        status=status,
    )
    total_pages = max((total + per_page - 1) // per_page, 1) if total > 0 else 0
    return APIResponse(
        data=[_assignment_to_response(a) for a in assignments],
        meta={
            "page": page,
            "per_page": per_page,
            "total": total,
            "total_pages": total_pages,
        },
    )


@project_router.get("/{project_id}/assignments", response_model=APIResponse[list[AssignmentResponse]])
async def get_project_assignments(
    request: Request,
    project_id: UUID,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    assignments, total = await assignment_service.get_project_assignments(
        db, project_id, page=page, per_page=per_page, organization_id=scope_org(current_user)
    )
    total_pages = max((total + per_page - 1) // per_page, 1) if total > 0 else 0
    return APIResponse(
        data=[_assignment_to_response(a) for a in assignments],
        meta={
            "page": page,
            "per_page": per_page,
            "total": total,
            "total_pages": total_pages,
        },
    )
