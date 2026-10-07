"""プロジェクトアサイン管理エンドポイント"""

from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from ..middleware.auth import get_current_user, require_organization_id
from ..models.base import get_db
from ..schemas import (
    APIResponse,
    AssignmentCreate,
    AssignmentResponse,
    TokenData,
)
from ..services import assignment_service

assign_router = APIRouter()
project_router = APIRouter()


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
    org_id = require_organization_id(current_user)
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
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    assignments, total = await assignment_service.list_assignments(
        db,
        organization_id=require_organization_id(current_user),
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
        db,
        project_id,
        require_organization_id(current_user),
        page=page,
        per_page=per_page,
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
