"""BIレポート API"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from ..middleware.auth import (
    MANAGEMENT_ROLES,
    TokenData,
    get_current_user,
    require_any_role,
)
from ..middleware.tenant import create_org, scope_org
from ..models.base import get_db
from ..schemas import (
    ReportCreateRequest,
    ReportExportResponse,
    ReportGenerateResponse,
    ReportListResponse,
    ReportResponse,
    ReportUpdateRequest,
)
from ..services import analytics_service as service

router = APIRouter()


@router.post(
    "/reports",
    response_model=ReportResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_report(
    body: ReportCreateRequest,
    db: AsyncSession = Depends(get_db),
    user: TokenData = Depends(get_current_user),
):
    data = body.model_dump()
    data["organization_id"] = create_org(user, body.organization_id)
    report = await service.create_report(db, data)
    return report


@router.get("/reports", response_model=ReportListResponse)
async def list_reports(
    organization_id: UUID | None = Query(None),
    report_type: str | None = Query(None),
    status: str | None = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    user: TokenData = Depends(get_current_user),
):
    items, total = await service.list_reports(
        db,
        organization_id=scope_org(user, organization_id),
        report_type=report_type,
        status=status,
        page=page,
        per_page=per_page,
    )
    return ReportListResponse(
        items=items, total=total, page=page, per_page=per_page  # type: ignore[arg-type]
    )


@router.get("/reports/{report_id}", response_model=ReportResponse)
async def get_report(
    report_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: TokenData = Depends(get_current_user),
):
    report = await service.get_report(db, report_id, scope_org(user))
    if not report:
        raise HTTPException(status_code=404, detail="レポートが見つかりません")
    return report


@router.put("/reports/{report_id}", response_model=ReportResponse)
async def update_report(
    report_id: UUID,
    body: ReportUpdateRequest,
    db: AsyncSession = Depends(get_db),
    user: TokenData = Depends(get_current_user),
):
    report = await service.get_report(db, report_id, scope_org(user))
    if not report:
        raise HTTPException(status_code=404, detail="レポートが見つかりません")
    return await service.update_report(
        db, report, body.model_dump(exclude_none=True)
    )


@router.delete("/reports/{report_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_report(
    report_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: TokenData = Depends(get_current_user),
):
    org = scope_org(user)
    require_any_role(user, MANAGEMENT_ROLES)
    report = await service.get_report(db, report_id, org)
    if not report:
        raise HTTPException(status_code=404, detail="レポートが見つかりません")
    await service.delete_report(db, report)


@router.post(
    "/reports/{report_id}/generate",
    response_model=ReportGenerateResponse,
)
async def generate_report(
    report_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: TokenData = Depends(get_current_user),
):
    report = await service.get_report(db, report_id, scope_org(user))
    if not report:
        raise HTTPException(status_code=404, detail="レポートが見つかりません")
    result = await service.generate_report(db, report)
    return result


@router.post(
    "/reports/{report_id}/export",
    response_model=ReportExportResponse,
)
async def export_report(
    report_id: UUID,
    format: str = Query("json", pattern="^(csv|json)$"),
    db: AsyncSession = Depends(get_db),
    user: TokenData = Depends(get_current_user),
):
    report = await service.get_report(db, report_id, scope_org(user))
    if not report:
        raise HTTPException(status_code=404, detail="レポートが見つかりません")
    result = await service.export_report(db, report, format)
    return result
