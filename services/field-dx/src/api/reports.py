"""作業日報 API"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from ..middleware.auth import TokenData, get_current_user
from ..middleware.tenant import create_org, scope_org
from ..models.base import get_db
from ..schemas import (
    DailyReportCreateRequest,
    DailyReportListResponse,
    DailyReportResponse,
    DailyReportUpdateRequest,
)
from ..services import field_service

router = APIRouter()


@router.post(
    "/reports",
    response_model=DailyReportResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_report(
    body: DailyReportCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    org_id = create_org(current_user, body.organization_id)
    data = body.model_dump()
    data["organization_id"] = org_id
    data["created_by"] = UUID(current_user.sub)
    report = await field_service.create_daily_report(db, data)
    return report


@router.get("/reports", response_model=DailyReportListResponse)
async def list_reports(
    project_id: UUID | None = Query(None),
    status: str | None = Query(None),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    items, total = await field_service.list_daily_reports(
        db,
        organization_id=scope_org(current_user),
        project_id=project_id,
        status=status,
        date_from=date_from,
        date_to=date_to,
        page=page,
        per_page=per_page,
    )
    return DailyReportListResponse(
        items=items, total=total, page=page, per_page=per_page  # type: ignore[arg-type]
    )


@router.get("/reports/{report_id}", response_model=DailyReportResponse)
async def get_report(
    report_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    org_id = scope_org(current_user)
    report = await field_service.get_daily_report(db, report_id)
    if not report or (org_id is not None and report.organization_id != org_id):
        raise HTTPException(status_code=404, detail="日報が見つかりません")
    return report


@router.put("/reports/{report_id}", response_model=DailyReportResponse)
async def update_report(
    report_id: UUID,
    body: DailyReportUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    org_id = scope_org(current_user)
    report = await field_service.get_daily_report(db, report_id)
    if not report or (org_id is not None and report.organization_id != org_id):
        raise HTTPException(status_code=404, detail="日報が見つかりません")
    return await field_service.update_daily_report(
        db, report, body.model_dump(exclude_none=True)
    )


@router.post(
    "/reports/{report_id}/submit",
    response_model=DailyReportResponse,
)
async def submit_report(
    report_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    org_id = scope_org(current_user)
    report = await field_service.get_daily_report(db, report_id)
    if not report or (org_id is not None and report.organization_id != org_id):
        raise HTTPException(status_code=404, detail="日報が見つかりません")
    try:
        return await field_service.submit_daily_report(db, report)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post(
    "/reports/{report_id}/approve",
    response_model=DailyReportResponse,
)
async def approve_report(
    report_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    org_id = scope_org(current_user)
    report = await field_service.get_daily_report(db, report_id)
    if not report or (org_id is not None and report.organization_id != org_id):
        raise HTTPException(status_code=404, detail="日報が見つかりません")
    approved_by = UUID(current_user.sub)
    try:
        return await field_service.approve_daily_report(db, report, approved_by)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
