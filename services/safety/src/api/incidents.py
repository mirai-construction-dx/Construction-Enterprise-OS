"""Safety incident API endpoints."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from ..middleware.auth import TokenData, get_current_user
from ..middleware.tenant import create_org, scope_org
from ..models.base import get_db
from ..schemas import APIResponse, IncidentCreate, IncidentUpdate
from ..services import safety_service

router = APIRouter()


def _incident_to_response(inc) -> dict:
    return {
        "id": str(inc.id),
        "organization_id": str(inc.organization_id),
        "project_id": str(inc.project_id) if inc.project_id else None,
        "site_id": str(inc.site_id) if inc.site_id else None,
        "title": inc.title,
        "description": inc.description,
        "incident_type": inc.incident_type,
        "severity": inc.severity,
        "status": inc.status,
        "incident_date": inc.incident_date.isoformat() if inc.incident_date else None,
        "location": inc.location,
        "injured_count": inc.injured_count,
        "fatality_count": inc.fatality_count,
        "root_cause": inc.root_cause,
        "corrective_actions": inc.corrective_actions,
        "reported_by": str(inc.reported_by),
        "investigated_by": str(inc.investigated_by) if inc.investigated_by else None,
        "resolved_at": inc.resolved_at.isoformat() if inc.resolved_at else None,
        "is_osha_reportable": inc.is_osha_reportable,
        "created_at": inc.created_at.isoformat() if inc.created_at else None,
        "updated_at": inc.updated_at.isoformat() if inc.updated_at else None,
    }


@router.post("/incidents", status_code=status.HTTP_201_CREATED)
async def create_incident(
    body: IncidentCreate,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    org_id = create_org(current_user, body.organization_id)
    incident = await safety_service.create_safety_incident(
        db,
        organization_id=org_id,
        title=body.title,
        description=body.description,
        incident_type=body.incident_type,
        severity=body.severity,
        incident_date=body.incident_date,
        reported_by=UUID(current_user.sub),
        project_id=body.project_id,
        site_id=body.site_id,
        location=body.location,
        injured_count=body.injured_count,
        fatality_count=body.fatality_count,
        is_osha_reportable=body.is_osha_reportable,
    )
    return APIResponse(data=_incident_to_response(incident))


@router.get("/incidents")
async def list_incidents(
    organization_id: UUID | None = Query(None),
    incident_type: str | None = Query(None),
    severity: str | None = Query(None),
    status: str | None = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    incidents = await safety_service.get_safety_incidents(
        db,
        organization_id=scope_org(current_user, organization_id),
        incident_type=incident_type,
        severity=severity,
        status=status,
        skip=skip,
        limit=limit,
    )
    return APIResponse(data=[_incident_to_response(i) for i in incidents])


@router.get("/incidents/{incident_id}")
async def get_incident(
    incident_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    incident = await safety_service.get_safety_incident_by_id(db, incident_id, scope_org(current_user))
    if not incident:
        raise HTTPException(
            status_code=404,
            detail={"code": "NOT_FOUND", "message": "Incident not found."},
        )
    return APIResponse(data=_incident_to_response(incident))


@router.put("/incidents/{incident_id}")
async def update_incident(
    incident_id: UUID,
    body: IncidentUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    incident = await safety_service.update_safety_incident(
        db,
        incident_id,
        organization_id=scope_org(current_user),
        title=body.title,
        description=body.description,
        status=body.status,
        severity=body.severity,
        investigated_by=UUID(current_user.sub),
        root_cause=body.root_cause,
        corrective_actions=body.corrective_actions,
        injured_count=body.injured_count,
        fatality_count=body.fatality_count,
        is_osha_reportable=body.is_osha_reportable,
    )
    if not incident:
        raise HTTPException(
            status_code=404,
            detail={"code": "NOT_FOUND", "message": "Incident not found."},
        )
    return APIResponse(data=_incident_to_response(incident))
