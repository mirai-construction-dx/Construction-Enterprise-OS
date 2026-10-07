"""工程スケジュール API"""

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
    GanttDataResponse,
    ScheduleCreateRequest,
    ScheduleListResponse,
    ScheduleResponse,
    ScheduleUpdateRequest,
)
from ..services import construction_service
from ._tenant_refs import ensure_wbs_in_org

router = APIRouter()


@router.post("/schedules", response_model=ScheduleResponse, status_code=status.HTTP_201_CREATED)
async def create_schedule(
    body: ScheduleCreateRequest,
    db: AsyncSession = Depends(get_db),
    user: TokenData = Depends(get_current_user),
):
    org = create_org(user, body.organization_id)
    await ensure_wbs_in_org(db, user, body.wbs_item_id, org)
    data = body.model_dump()
    data["organization_id"] = org
    return await construction_service.create_schedule(db, data)


@router.get("/schedules", response_model=ScheduleListResponse)
async def list_schedules(
    organization_id: UUID | None = Query(None),
    project_id: UUID | None = Query(None),
    schedule_type: str | None = Query(None),
    status: str | None = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    user: TokenData = Depends(get_current_user),
):
    items, total = await construction_service.list_schedules(
        db,
        organization_id=scope_org(user, organization_id),
        project_id=project_id,
        schedule_type=schedule_type,
        status=status,
        page=page,
        per_page=per_page,
    )
    return ScheduleListResponse(items=items, total=total, page=page, per_page=per_page)  # type: ignore[arg-type]


@router.get("/schedules/{schedule_id}", response_model=ScheduleResponse)
async def get_schedule(
    schedule_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: TokenData = Depends(get_current_user),
):
    schedule = await construction_service.get_schedule(db, schedule_id, scope_org(user))
    if not schedule:
        raise HTTPException(status_code=404, detail="スケジュールが見つかりません")
    return schedule


@router.put("/schedules/{schedule_id}", response_model=ScheduleResponse)
async def update_schedule(
    schedule_id: UUID,
    body: ScheduleUpdateRequest,
    db: AsyncSession = Depends(get_db),
    user: TokenData = Depends(get_current_user),
):
    schedule = await construction_service.get_schedule(db, schedule_id, scope_org(user))
    if not schedule:
        raise HTTPException(status_code=404, detail="スケジュールが見つかりません")
    return await construction_service.update_schedule(db, schedule, body.model_dump(exclude_none=True))


@router.delete("/schedules/{schedule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_schedule(
    schedule_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: TokenData = Depends(get_current_user),
):
    schedule = await construction_service.get_schedule(db, schedule_id, scope_org(user))
    if not schedule:
        raise HTTPException(status_code=404, detail="スケジュールが見つかりません")
    require_any_role(user, MANAGEMENT_ROLES)  # 削除には管理ロールを要求する
    await db.delete(schedule)


@router.get("/projects/{project_id}/critical-path", response_model=list[ScheduleResponse])
async def get_critical_path(
    project_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: TokenData = Depends(get_current_user),
):
    return await construction_service.get_critical_path(db, project_id, scope_org(user))


@router.get("/projects/{project_id}/gantt", response_model=list[GanttDataResponse])
async def get_gantt_data(
    project_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: TokenData = Depends(get_current_user),
):
    return await construction_service.get_gantt_data(db, project_id, scope_org(user))
