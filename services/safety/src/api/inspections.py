"""Safety inspection API endpoints."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from ..middleware.auth import TokenData, get_current_user
from ..middleware.tenant import create_org, scope_org
from ..models.base import get_db
from ..schemas import (
    APIResponse,
    InspectionComplete,
    InspectionCreate,
    InspectionUpdate,
)
from ..services import safety_service

router = APIRouter()


def _inspection_to_response(insp) -> dict:
    return {
        "id": str(insp.id),
        "organization_id": str(insp.organization_id),
        "project_id": str(insp.project_id) if insp.project_id else None,
        "site_id": str(insp.site_id) if insp.site_id else None,
        "title": insp.title,
        "inspection_type": insp.inspection_type,
        "status": insp.status,
        "inspector_id": str(insp.inspector_id),
        "inspection_date": insp.inspection_date.isoformat() if insp.inspection_date else None,
        "location": insp.location,
        "findings": insp.findings,
        "corrective_actions": insp.corrective_actions,
        "score": insp.score,
        "is_safe": insp.is_safe,
        "created_at": insp.created_at.isoformat() if insp.created_at else None,
        "updated_at": insp.updated_at.isoformat() if insp.updated_at else None,
    }


@router.post("/inspections", status_code=status.HTTP_201_CREATED)
async def create_inspection(
    body: InspectionCreate,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    inspection = await safety_service.create_inspection(
        db,
        organization_id=create_org(current_user, body.organization_id),
        title=body.title,
        inspection_type=body.inspection_type,
        inspector_id=body.inspector_id,
        project_id=body.project_id,
        site_id=body.site_id,
        inspection_date=body.inspection_date,
        location=body.location,
    )
    return APIResponse(data=_inspection_to_response(inspection))


@router.get("/inspections")
async def list_inspections(
    organization_id: UUID | None = Query(None),
    inspection_type: str | None = Query(None),
    status: str | None = Query(None),
    project_id: UUID | None = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    inspections = await safety_service.get_inspections(
        db,
        organization_id=scope_org(current_user, organization_id),
        inspection_type=inspection_type,
        status=status,
        project_id=project_id,
        skip=skip,
        limit=limit,
    )
    return APIResponse(data=[_inspection_to_response(i) for i in inspections])


@router.get("/inspections/stats")
async def inspection_stats(
    organization_id: UUID | None = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    stats = await safety_service.get_inspection_stats(
        db, scope_org(current_user, organization_id)
    )
    return APIResponse(data=stats)


@router.get("/inspections/{inspection_id}")
async def get_inspection(
    inspection_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    inspection = await safety_service.get_inspection_by_id(db, inspection_id, scope_org(current_user))
    if not inspection:
        raise HTTPException(
            status_code=404,
            detail={"code": "NOT_FOUND", "message": "Inspection not found."},
        )
    return APIResponse(data=_inspection_to_response(inspection))


@router.put("/inspections/{inspection_id}")
async def update_inspection(
    inspection_id: UUID,
    body: InspectionUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    inspection = await safety_service.update_inspection(
        db,
        inspection_id,
        organization_id=scope_org(current_user),
        title=body.title,
        status=body.status,
        inspector_id=body.inspector_id,
        inspection_date=body.inspection_date,
        location=body.location,
        findings=body.findings,
        corrective_actions=body.corrective_actions,
        score=body.score,
        is_safe=body.is_safe,
    )
    if not inspection:
        raise HTTPException(
            status_code=404,
            detail={"code": "NOT_FOUND", "message": "Inspection not found."},
        )
    return APIResponse(data=_inspection_to_response(inspection))


@router.post("/inspections/{inspection_id}/complete")
async def complete_inspection(
    inspection_id: UUID,
    body: InspectionComplete,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    inspection = await safety_service.complete_inspection(
        db,
        inspection_id,
        organization_id=scope_org(current_user),
        is_safe=body.is_safe,
        findings=body.findings,
        corrective_actions=body.corrective_actions,
        score=body.score,
    )
    if not inspection:
        raise HTTPException(
            status_code=404,
            detail={"code": "NOT_FOUND", "message": "Inspection not found."},
        )
    return APIResponse(data=_inspection_to_response(inspection))
