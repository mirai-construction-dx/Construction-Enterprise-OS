"""Disaster report and recovery plan API endpoints."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from ..middleware.auth import TokenData, get_current_user
from ..middleware.tenant import create_org, scope_org
from ..models.base import get_db
from ..schemas import (
    APIResponse,
    DisasterCreate,
    DisasterUpdate,
    RecoveryPlanCreate,
    RecoveryPlanUpdate,
)
from ..services import maintenance_service as svc

router = APIRouter()


def _disaster_to_response(dr) -> dict:
    return {
        "id": str(dr.id),
        "organization_id": str(dr.organization_id),
        "project_id": str(dr.project_id) if dr.project_id else None,
        "title": dr.title,
        "disaster_type": dr.disaster_type,
        "severity": dr.severity,
        "status": dr.status,
        "occurred_at": dr.occurred_at.isoformat() if dr.occurred_at else None,
        "location": dr.location,
        "description": dr.description,
        "damage_assessment": dr.damage_assessment,
        "estimated_cost": str(dr.estimated_cost) if dr.estimated_cost else None,
        "casualties": dr.casualties,
        "evacuation_required": dr.evacuation_required,
        "reported_by": str(dr.reported_by),
        "created_at": dr.created_at.isoformat() if dr.created_at else None,
        "updated_at": dr.updated_at.isoformat() if dr.updated_at else None,
    }


def _plan_to_response(rp) -> dict:
    return {
        "id": str(rp.id),
        "organization_id": str(rp.organization_id),
        "disaster_report_id": str(rp.disaster_report_id) if rp.disaster_report_id else None,
        "title": rp.title,
        "description": rp.description,
        "priority": rp.priority,
        "status": rp.status,
        "estimated_duration_days": rp.estimated_duration_days,
        "estimated_cost": str(rp.estimated_cost) if rp.estimated_cost else None,
        "actual_cost": str(rp.actual_cost) if rp.actual_cost else None,
        "start_date": rp.start_date.isoformat() if rp.start_date else None,
        "completed_date": rp.completed_date.isoformat() if rp.completed_date else None,
        "contractor": rp.contractor,
        "resources_needed": rp.resources_needed,
        "progress_percent": str(rp.progress_percent) if rp.progress_percent else None,
        "created_by": str(rp.created_by),
        "created_at": rp.created_at.isoformat() if rp.created_at else None,
        "updated_at": rp.updated_at.isoformat() if rp.updated_at else None,
    }


@router.post("/disasters", status_code=status.HTTP_201_CREATED)
async def create_disaster(
    body: DisasterCreate,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    report = await svc.create_disaster_report(
        db,
        organization_id=create_org(current_user, body.organization_id),
        title=body.title,
        disaster_type=body.disaster_type,
        severity=body.severity,
        occurred_at=body.occurred_at,
        description=body.description,
        reported_by=body.reported_by,
        project_id=body.project_id,
        location=body.location,
        estimated_cost=body.estimated_cost,
        casualties=body.casualties,
        evacuation_required=body.evacuation_required,
    )
    return APIResponse(data=_disaster_to_response(report))


@router.get("/disasters")
async def list_disasters(
    organization_id: UUID | None = Query(None),
    disaster_type: str | None = Query(None),
    severity: str | None = Query(None),
    status: str | None = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    reports = await svc.get_disaster_reports(
        db,
        organization_id=scope_org(current_user, organization_id),
        disaster_type=disaster_type,
        severity=severity,
        status=status,
        skip=skip,
        limit=limit,
    )
    return APIResponse(data=[_disaster_to_response(r) for r in reports])


@router.get("/disasters/{disaster_id}")
async def get_disaster(
    disaster_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    org = scope_org(current_user)
    report = await svc.get_disaster_report_by_id(db, disaster_id, org)
    if not report:
        raise HTTPException(
            status_code=404,
            detail={"code": "NOT_FOUND", "message": "Disaster report not found."},
        )
    plans = await svc.get_recovery_plans_for_disaster(db, disaster_id, org)
    return APIResponse(
        data={
            "report": _disaster_to_response(report),
            "recovery_plans": [_plan_to_response(p) for p in plans],
        }
    )


@router.put("/disasters/{disaster_id}")
async def update_disaster(
    disaster_id: UUID,
    body: DisasterUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    report = await svc.update_disaster_report(
        db,
        disaster_id,
        organization_id=scope_org(current_user),
        title=body.title,
        status=body.status,
        severity=body.severity,
        damage_assessment=body.damage_assessment,
        estimated_cost=body.estimated_cost,
        casualties=body.casualties,
        evacuation_required=body.evacuation_required,
    )
    if not report:
        raise HTTPException(
            status_code=404,
            detail={"code": "NOT_FOUND", "message": "Disaster report not found."},
        )
    return APIResponse(data=_disaster_to_response(report))


@router.post("/disasters/{disaster_id}/recovery-plans", status_code=status.HTTP_201_CREATED)
async def create_recovery_plan(
    disaster_id: UUID,
    body: RecoveryPlanCreate,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    plan_org = create_org(current_user, body.organization_id)
    report = await svc.get_disaster_report_by_id(db, disaster_id, scope_org(current_user))
    if not report:
        raise HTTPException(
            status_code=404,
            detail={"code": "NOT_FOUND", "message": "Disaster report not found."},
        )
    if report.organization_id != plan_org:
        # Only reachable by cross-org admins: a plan must belong to its disaster's organization.
        raise HTTPException(
            status_code=400,
            detail={
                "code": "RECOVERY_PLAN_ORG_MISMATCH",
                "message": "復旧計画の組織が災害報告の組織と一致しません。",
            },
        )
    plan = await svc.create_recovery_plan(
        db,
        organization_id=plan_org,
        disaster_report_id=disaster_id,
        title=body.title,
        created_by=body.created_by,
        description=body.description,
        priority=body.priority,
        estimated_duration_days=body.estimated_duration_days,
        estimated_cost=body.estimated_cost,
        start_date=body.start_date,
        contractor=body.contractor,
        resources_needed=body.resources_needed,
    )
    return APIResponse(data=_plan_to_response(plan))


@router.get("/recovery-plans/{plan_id}")
async def get_recovery_plan(
    plan_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    plan = await svc.get_recovery_plan_by_id(db, plan_id, scope_org(current_user))
    if not plan:
        raise HTTPException(
            status_code=404,
            detail={"code": "NOT_FOUND", "message": "Recovery plan not found."},
        )
    return APIResponse(data=_plan_to_response(plan))


@router.put("/recovery-plans/{plan_id}")
async def update_recovery_plan(
    plan_id: UUID,
    body: RecoveryPlanUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    plan = await svc.update_recovery_plan(
        db,
        plan_id,
        organization_id=scope_org(current_user),
        title=body.title,
        description=body.description,
        priority=body.priority,
        status=body.status,
        estimated_duration_days=body.estimated_duration_days,
        estimated_cost=body.estimated_cost,
        actual_cost=body.actual_cost,
        start_date=body.start_date,
        completed_date=body.completed_date,
        contractor=body.contractor,
        resources_needed=body.resources_needed,
        progress_percent=body.progress_percent,
    )
    if not plan:
        raise HTTPException(
            status_code=404,
            detail={"code": "NOT_FOUND", "message": "Recovery plan not found."},
        )
    return APIResponse(data=_plan_to_response(plan))
