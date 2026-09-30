"""Hazard report API endpoints."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from ..middleware.auth import TokenData, get_current_user
from ..middleware.tenant import create_org, scope_org
from ..models.base import get_db
from ..schemas import APIResponse, HazardCreate, HazardUpdate
from ..services import safety_service

router = APIRouter()


def _hazard_to_response(h) -> dict:
    return {
        "id": str(h.id),
        "organization_id": str(h.organization_id),
        "project_id": str(h.project_id) if h.project_id else None,
        "site_id": str(h.site_id) if h.site_id else None,
        "title": h.title,
        "description": h.description,
        "hazard_type": h.hazard_type,
        "risk_level": h.risk_level,
        "severity": h.severity,
        "status": h.status,
        "location": h.location,
        "reported_by": str(h.reported_by),
        "assigned_to": str(h.assigned_to) if h.assigned_to else None,
        "mitigation": h.mitigation,
        "resolved_at": h.resolved_at.isoformat() if h.resolved_at else None,
        "created_at": h.created_at.isoformat() if h.created_at else None,
    }


@router.post("/hazards", status_code=status.HTTP_201_CREATED)
async def create_hazard(
    body: HazardCreate,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    hazard = await safety_service.create_hazard(
        db,
        organization_id=create_org(current_user, body.organization_id),
        title=body.title,
        description=body.description,
        hazard_type=body.hazard_type,
        risk_level=body.risk_level,
        severity=body.severity,
        reported_by=body.reported_by,
        project_id=body.project_id,
        site_id=body.site_id,
        location=body.location,
        assigned_to=body.assigned_to,
    )
    return APIResponse(data=_hazard_to_response(hazard))


@router.get("/hazards")
async def list_hazards(
    organization_id: UUID | None = Query(None),
    hazard_type: str | None = Query(None),
    risk_level: str | None = Query(None),
    status: str | None = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    hazards = await safety_service.get_hazards(
        db,
        organization_id=scope_org(current_user, organization_id),
        hazard_type=hazard_type,
        risk_level=risk_level,
        status=status,
        skip=skip,
        limit=limit,
    )
    return APIResponse(data=[_hazard_to_response(h) for h in hazards])


@router.get("/hazards/open")
async def list_open_hazards(
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    hazards = await safety_service.get_open_hazards(db, scope_org(current_user))
    return APIResponse(data=[_hazard_to_response(h) for h in hazards])


@router.put("/hazards/{hazard_id}")
async def update_hazard(
    hazard_id: UUID,
    body: HazardUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    hazard = await safety_service.update_hazard(
        db,
        hazard_id,
        organization_id=scope_org(current_user),
        title=body.title,
        description=body.description,
        status=body.status,
        risk_level=body.risk_level,
        severity=body.severity,
        assigned_to=body.assigned_to,
        mitigation=body.mitigation,
    )
    if not hazard:
        raise HTTPException(
            status_code=404,
            detail={"code": "NOT_FOUND", "message": "Hazard report not found."},
        )
    return APIResponse(data=_hazard_to_response(hazard))
