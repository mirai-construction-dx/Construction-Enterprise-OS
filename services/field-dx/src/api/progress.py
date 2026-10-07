"""出来形・進捗管理 API"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ..middleware.auth import (
    TokenData,
    get_current_user,
    require_actor_id,
    require_organization_id,
)
from ..models.base import get_db
from ..schemas import (
    ProgressCreateRequest,
    ProgressListResponse,
    ProgressResponse,
    ProgressSummaryResponse,
    ProgressUpdateRequest,
)
from ..services import field_service

router = APIRouter()


class ZoneProgressItem(BaseModel):
    id: str
    zone_name: str
    plan_pct: float
    actual_pct: float
    diff: float
    status: str


class WorkReportItem(BaseModel):
    id: str
    time: str
    content: str
    worker: str
    zone: str
    note: str | None = None


_MOCK_ZONES = [
    ZoneProgressItem(
        id="z1",
        zone_name="第1工区",
        plan_pct=75.0,
        actual_pct=72.3,
        diff=-2.7,
        status="behind",
    ),
    ZoneProgressItem(
        id="z2",
        zone_name="第2工区",
        plan_pct=60.0,
        actual_pct=63.5,
        diff=3.5,
        status="ahead",
    ),
    ZoneProgressItem(
        id="z3",
        zone_name="第3工区",
        plan_pct=90.0,
        actual_pct=85.2,
        diff=-4.8,
        status="behind",
    ),
    ZoneProgressItem(
        id="z4",
        zone_name="仮設工区",
        plan_pct=100.0,
        actual_pct=100.0,
        diff=0.0,
        status="complete",
    ),
]

_MOCK_TODAY_REPORTS = [
    WorkReportItem(
        id="r1",
        time="08:30",
        content="コンクリート打設開始（第1工区東側）",
        worker="山田 太郎",
        zone="第1工区",
        note=None,
    ),
    WorkReportItem(
        id="r2",
        time="10:15",
        content="鉄筋検査完了",
        worker="鈴木 次郎",
        zone="第2工区",
        note="写真撮影済み",
    ),
    WorkReportItem(
        id="r3",
        time="11:00",
        content="掘削作業完了",
        worker="佐藤 三郎",
        zone="第3工区",
        note=None,
    ),
    WorkReportItem(
        id="r4",
        time="13:30",
        content="型枠設置開始",
        worker="田中 花子",
        zone="第1工区",
        note="工程表通り進捗",
    ),
    WorkReportItem(
        id="r5",
        time="14:45",
        content="品質検査（コンクリート）",
        worker="高橋 五郎",
        zone="第2工区",
        note="強度試験実施",
    ),
]


@router.get("/progress/zones")
async def get_progress_zones(
    _user: TokenData = Depends(get_current_user),
):
    return {"data": [z.model_dump() for z in _MOCK_ZONES]}


@router.get("/progress/reports/today")
async def get_today_reports(
    _user: TokenData = Depends(get_current_user),
):
    return {"data": [r.model_dump() for r in _MOCK_TODAY_REPORTS]}


@router.post(
    "/progress",
    response_model=ProgressResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_progress(
    body: ProgressCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    org_id = require_organization_id(current_user)
    if body.organization_id != org_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="組織が異なるため作成できません",
        )
    data = body.model_dump()
    data["organization_id"] = org_id
    data["recorded_by"] = require_actor_id(current_user)
    record = await field_service.create_progress_record(db, data)
    return record


@router.get("/progress", response_model=ProgressListResponse)
async def list_progress(
    project_id: UUID | None = Query(None),
    status: str | None = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    items, total = await field_service.list_progress_records(
        db,
        organization_id=require_organization_id(current_user),
        project_id=project_id,
        status=status,
        page=page,
        per_page=per_page,
    )
    return ProgressListResponse(
        items=[ProgressResponse.model_validate(item) for item in items],
        total=total,
        page=page,
        per_page=per_page,
    )


@router.put("/progress/{record_id}", response_model=ProgressResponse)
async def update_progress(
    record_id: UUID,
    body: ProgressUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    org_id = require_organization_id(current_user)
    record = await field_service.get_progress_record(db, record_id)
    if not record or record.organization_id != org_id:
        raise HTTPException(status_code=404, detail="進捗記録が見つかりません")
    return await field_service.update_progress_record(
        db, record, body.model_dump(exclude_none=True)
    )


@router.get("/progress/{record_id}", response_model=ProgressResponse)
async def get_progress(
    record_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    org_id = require_organization_id(current_user)
    record = await field_service.get_progress_record(db, record_id)
    if not record or record.organization_id != org_id:
        raise HTTPException(status_code=404, detail="進捗記録が見つかりません")
    return record


@router.get(
    "/progress/{project_id}/summary",
    response_model=ProgressSummaryResponse,
)
async def progress_summary(
    project_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    return await field_service.get_progress_summary(
        db, project_id, require_organization_id(current_user)
    )
