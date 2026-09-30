"""Security incident API endpoints."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from ..middleware.auth import TokenData, get_current_user
from ..middleware.tenant import create_org, scope_org
from ..models.base import get_db
from ..schemas import (
    APIResponse,
    IncidentCreate,
    IncidentUpdateCreate,
    IncidentUpdate_request,
)
from ..services import incident_service

router = APIRouter()


def _incident_to_response(inc) -> dict:
    return {
        "id": str(inc.id),
        "organization_id": str(inc.organization_id),
        "title": inc.title,
        "description": inc.description,
        "severity": inc.severity,
        "incident_type": inc.incident_type,
        "status": inc.status,
        "source_ip": str(inc.source_ip) if inc.source_ip else None,
        "affected_systems": inc.affected_systems,
        "detected_by": inc.detected_by,
        "assigned_to": str(inc.assigned_to) if inc.assigned_to else None,
        "resolution": inc.resolution,
        "resolved_at": inc.resolved_at.isoformat() if inc.resolved_at else None,
        "created_at": inc.created_at.isoformat() if inc.created_at else None,
        "updated_at": inc.updated_at.isoformat() if inc.updated_at else None,
    }


def _update_to_response(upd) -> dict:
    return {
        "id": upd.id,
        "incident_id": str(upd.incident_id),
        "user_id": str(upd.user_id),
        "update_type": upd.update_type,
        "content": upd.content,
        "created_at": upd.created_at.isoformat() if upd.created_at else None,
    }


@router.post("/incidents", status_code=status.HTTP_201_CREATED)
async def create_incident(
    body: IncidentCreate,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    incident = await incident_service.create_incident(
        db,
        organization_id=create_org(current_user, body.organization_id),
        title=body.title,
        severity=body.severity,
        incident_type=body.incident_type,
        description=body.description,
        source_ip=body.source_ip,
        affected_systems=body.affected_systems,
        detected_by=body.detected_by,
    )
    return APIResponse(data=_incident_to_response(incident))


@router.get("/incidents")
async def list_incidents(
    organization_id: UUID | None = Query(None),
    severity: str | None = Query(None),
    status: str | None = Query(None),
    incident_type: str | None = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    incidents = await incident_service.get_incidents(
        db,
        organization_id=scope_org(current_user, organization_id),
        severity=severity,
        status=status,
        incident_type=incident_type,
        skip=skip,
        limit=limit,
    )
    return APIResponse(data=[_incident_to_response(i) for i in incidents])


@router.get("/incidents/active")
async def get_active_count(
    organization_id: UUID | None = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    count = await incident_service.get_active_incident_count(
        db, scope_org(current_user, organization_id)
    )
    return APIResponse(data={"active_incidents": count})


@router.get("/incidents/{incident_id}")
async def get_incident(
    incident_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    incident = await incident_service.get_incident_by_id(
        db, incident_id, scope_org(current_user)
    )
    if not incident:
        raise HTTPException(
            status_code=404,
            detail={"code": "NOT_FOUND", "message": "Incident not found."},
        )
    data = _incident_to_response(incident)
    data["updates"] = [_update_to_response(u) for u in (incident.updates or [])]
    return APIResponse(data=data)


@router.put("/incidents/{incident_id}")
async def update_incident(
    incident_id: UUID,
    body: IncidentUpdate_request,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    incident = await incident_service.update_incident(
        db,
        incident_id,
        organization_id=scope_org(current_user),
        status=body.status,
        severity=body.severity,
        assigned_to=body.assigned_to,
        resolution=body.resolution,
    )
    if not incident:
        raise HTTPException(
            status_code=404,
            detail={"code": "NOT_FOUND", "message": "Incident not found."},
        )
    return APIResponse(data=_incident_to_response(incident))


@router.post("/incidents/{incident_id}/updates", status_code=status.HTTP_201_CREATED)
async def add_update(
    incident_id: UUID,
    body: IncidentUpdateCreate,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    update = await incident_service.add_incident_update(
        db,
        incident_id,
        user_id=UUID(current_user.sub),
        update_type=body.update_type,
        content=body.content,
        organization_id=scope_org(current_user),
    )
    if not update:
        raise HTTPException(
            status_code=404,
            detail={"code": "NOT_FOUND", "message": "Incident not found."},
        )
    return APIResponse(data=_update_to_response(update))
