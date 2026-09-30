"""Inspection schedule API endpoints."""

import json
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from ..middleware.auth import TokenData, get_current_user
from ..middleware.tenant import create_org, scope_org
from ..models.base import get_db
from ..schemas import APIResponse, InspectionComplete, InspectionCreate
from ..services import maintenance_service as svc

router = APIRouter()


def _inspection_to_response(insp) -> dict:
    checklist = insp.checklist
    if isinstance(checklist, str):
        try:
            checklist = json.loads(checklist)
        except (json.JSONDecodeError, TypeError):
            checklist = None
    return {
        "id": str(insp.id),
        "organization_id": str(insp.organization_id),
        "asset_name": insp.asset_name,
        "asset_type": insp.asset_type,
        "inspection_type": insp.inspection_type,
        "frequency": insp.frequency,
        "last_inspection_date": insp.last_inspection_date.isoformat() if insp.last_inspection_date else None,
        "next_inspection_date": insp.next_inspection_date.isoformat() if insp.next_inspection_date else None,
        "status": insp.status,
        "inspector": insp.inspector,
        "checklist": checklist,
        "notes": insp.notes,
        "created_at": insp.created_at.isoformat() if insp.created_at else None,
        "updated_at": insp.updated_at.isoformat() if insp.updated_at else None,
    }


@router.post("/inspections", status_code=status.HTTP_201_CREATED)
async def create_inspection(
    body: InspectionCreate,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    inspection = await svc.create_inspection_schedule(
        db,
        organization_id=create_org(current_user, body.organization_id),
        asset_name=body.asset_name,
        asset_type=body.asset_type,
        inspection_type=body.inspection_type,
        frequency=body.frequency,
        next_inspection_date=body.next_inspection_date,
        inspector=body.inspector,
        notes=body.notes,
    )
    return APIResponse(data=_inspection_to_response(inspection))


@router.get("/inspections")
async def list_inspections(
    organization_id: UUID | None = Query(None),
    status: str | None = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    inspections = await svc.get_inspection_schedules(
        db,
        organization_id=scope_org(current_user, organization_id),
        status=status,
        skip=skip,
        limit=limit,
    )
    return APIResponse(data=[_inspection_to_response(i) for i in inspections])


@router.get("/inspections/upcoming")
async def get_upcoming_inspections(
    organization_id: UUID | None = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    inspections = await svc.get_upcoming_inspections(
        db, organization_id=scope_org(current_user, organization_id)
    )
    return APIResponse(data=[_inspection_to_response(i) for i in inspections])


@router.get("/inspections/overdue")
async def get_overdue_inspections(
    organization_id: UUID | None = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    inspections = await svc.get_overdue_inspections(
        db, organization_id=scope_org(current_user, organization_id)
    )
    return APIResponse(data=[_inspection_to_response(i) for i in inspections])


@router.get("/inspections/{inspection_id}")
async def get_inspection(
    inspection_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    inspection = await svc.get_inspection_schedule_by_id(
        db, inspection_id, scope_org(current_user)
    )
    if not inspection:
        raise HTTPException(
            status_code=404,
            detail={"code": "NOT_FOUND", "message": "Inspection schedule not found."},
        )
    return APIResponse(data=_inspection_to_response(inspection))


@router.put("/inspections/{inspection_id}")
async def complete_inspection(
    inspection_id: UUID,
    body: InspectionComplete,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    inspection = await svc.complete_inspection(
        db,
        inspection_id,
        organization_id=scope_org(current_user),
        checklist=body.checklist,
        notes=body.notes,
    )
    if not inspection:
        raise HTTPException(
            status_code=404,
            detail={"code": "NOT_FOUND", "message": "Inspection schedule not found."},
        )
    return APIResponse(data=_inspection_to_response(inspection))
