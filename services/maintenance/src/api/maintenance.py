"""Maintenance record API endpoints."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from ..middleware.auth import TokenData, get_current_user
from ..middleware.tenant import create_org, scope_org
from ..models.base import get_db
from ..schemas import APIResponse, MaintenanceRecordCreate, MaintenanceRecordUpdate
from ..services import maintenance_service as svc

router = APIRouter()


def _record_to_response(mr) -> dict:
    return {
        "id": str(mr.id),
        "organization_id": str(mr.organization_id),
        "project_id": str(mr.project_id) if mr.project_id else None,
        "asset_name": mr.asset_name,
        "asset_type": mr.asset_type,
        "maintenance_type": mr.maintenance_type,
        "status": mr.status,
        "description": mr.description,
        "work_performed": mr.work_performed,
        "cost": str(mr.cost) if mr.cost else None,
        "contractor": mr.contractor,
        "scheduled_date": mr.scheduled_date.isoformat() if mr.scheduled_date else None,
        "completed_date": mr.completed_date.isoformat() if mr.completed_date else None,
        "next_maintenance_date": mr.next_maintenance_date.isoformat() if mr.next_maintenance_date else None,
        "location": mr.location,
        "performed_by": str(mr.performed_by) if mr.performed_by else None,
        "notes": mr.notes,
        "created_at": mr.created_at.isoformat() if mr.created_at else None,
        "updated_at": mr.updated_at.isoformat() if mr.updated_at else None,
    }


@router.post("/records", status_code=status.HTTP_201_CREATED)
async def create_record(
    body: MaintenanceRecordCreate,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    record = await svc.create_maintenance_record(
        db,
        organization_id=create_org(current_user, body.organization_id),
        asset_name=body.asset_name,
        asset_type=body.asset_type,
        maintenance_type=body.maintenance_type,
        description=body.description,
        project_id=body.project_id,
        cost=body.cost,
        contractor=body.contractor,
        scheduled_date=body.scheduled_date,
        next_maintenance_date=body.next_maintenance_date,
        location=body.location,
        performed_by=body.performed_by,
        notes=body.notes,
    )
    return APIResponse(data=_record_to_response(record))


@router.get("/records")
async def list_records(
    organization_id: UUID | None = Query(None),
    asset_type: str | None = Query(None),
    maintenance_type: str | None = Query(None),
    status: str | None = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    records = await svc.get_maintenance_records(
        db,
        organization_id=scope_org(current_user, organization_id),
        asset_type=asset_type,
        maintenance_type=maintenance_type,
        status=status,
        skip=skip,
        limit=limit,
    )
    return APIResponse(data=[_record_to_response(r) for r in records])


@router.get("/records/overdue")
async def get_overdue_records(
    organization_id: UUID | None = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    records = await svc.get_overdue_maintenance(
        db, organization_id=scope_org(current_user, organization_id)
    )
    return APIResponse(data=[_record_to_response(r) for r in records])


@router.get("/records/{record_id}")
async def get_record(
    record_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    record = await svc.get_maintenance_record_by_id(db, record_id, scope_org(current_user))
    if not record:
        raise HTTPException(
            status_code=404,
            detail={"code": "NOT_FOUND", "message": "Maintenance record not found."},
        )
    return APIResponse(data=_record_to_response(record))


@router.put("/records/{record_id}")
async def update_record(
    record_id: UUID,
    body: MaintenanceRecordUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    record = await svc.update_maintenance_record(
        db,
        record_id,
        organization_id=scope_org(current_user),
        asset_name=body.asset_name,
        status=body.status,
        work_performed=body.work_performed,
        cost=body.cost,
        contractor=body.contractor,
        completed_date=body.completed_date,
        next_maintenance_date=body.next_maintenance_date,
        performed_by=body.performed_by,
        notes=body.notes,
    )
    if not record:
        raise HTTPException(
            status_code=404,
            detail={"code": "NOT_FOUND", "message": "Maintenance record not found."},
        )
    return APIResponse(data=_record_to_response(record))
