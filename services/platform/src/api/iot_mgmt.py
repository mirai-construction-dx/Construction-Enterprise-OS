"""IoTデバイス管理・ダッシュボード API"""

from math import ceil
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..middleware.auth import TokenData, get_current_user
from ..middleware.tenant import create_org, scope_org
from ..models import IoTDashboard, DeviceGroup
from ..models.base import get_db
from ..schemas import (
    APIResponse,
    MetaInfo,
    IoTDashboardCreate,
    IoTDashboardResponse,
    IoTDashboardUpdate,
    DeviceGroupCreate,
    DeviceGroupResponse,
    DeviceGroupUpdate,
)

router = APIRouter()


def _api_response(data=None, meta=None, error=None, success=True):
    return APIResponse(success=success, data=data, error=error, meta=meta)


def _dashboard_to_response(d: IoTDashboard) -> dict:
    return IoTDashboardResponse.model_validate(d).model_dump(mode="json")


def _group_to_response(g: DeviceGroup) -> dict:
    return DeviceGroupResponse.model_validate(g).model_dump(mode="json")


def _dashboard_not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={"code": "NOT_FOUND", "message": "ダッシュボードが見つかりません。"},
    )


def _group_not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={"code": "NOT_FOUND", "message": "デバイスグループが見つかりません。"},
    )


def _parent_group_not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={"code": "PARENT_GROUP_NOT_FOUND", "message": "親デバイスグループが見つかりません。"},
    )


def _parent_group_org_mismatch() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail={
            "code": "PARENT_GROUP_ORG_MISMATCH",
            "message": "異なる組織のデバイスグループは親に指定できません。",
        },
    )


async def _get_group(
    db: AsyncSession, group_id: UUID, organization_id: UUID | None
) -> DeviceGroup | None:
    """Fetch a device group; ``organization_id=None`` is reserved for cross-org admins."""
    stmt = select(DeviceGroup).where(DeviceGroup.id == group_id)
    if organization_id is not None:
        stmt = stmt.where(DeviceGroup.organization_id == organization_id)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def _ensure_parent_group(
    db: AsyncSession, token_data: TokenData, parent_group_id: UUID, group_org: UUID
) -> None:
    """The parent group must be visible to the caller and belong to the same organization.

    Regular users: a parent of another organization is not visible -> 404 (no existence leak).
    Cross-org admins: the parent is visible, but mixing organizations is rejected -> 400.
    """
    parent = await _get_group(db, parent_group_id, scope_org(token_data))
    if not parent:
        raise _parent_group_not_found()
    if parent.organization_id != group_org:
        raise _parent_group_org_mismatch()


# === IoT Dashboards ===

@router.post("/dashboards")
async def create_dashboard(
    body: IoTDashboardCreate,
    token_data: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = create_org(token_data, body.organization_id)
    dashboard = IoTDashboard(
        organization_id=org_id,
        project_id=body.project_id,
        name=body.name,
        description=body.description,
        layout=body.layout,
        refresh_interval_seconds=body.refresh_interval_seconds,
        is_public=body.is_public,
        created_by=UUID(token_data.sub),
    )
    db.add(dashboard)
    await db.flush()
    await db.refresh(dashboard)
    return _api_response(data=_dashboard_to_response(dashboard))


@router.get("/dashboards")
async def list_dashboards(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    project_id: UUID | None = Query(None),
    is_public: bool | None = Query(None),
    organization_id: UUID | None = Query(None),
    token_data: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    query = select(IoTDashboard)
    count_query = select(func.count(IoTDashboard.id))

    org_id = scope_org(token_data, organization_id)
    if org_id is not None:
        query = query.where(IoTDashboard.organization_id == org_id)
        count_query = count_query.where(IoTDashboard.organization_id == org_id)

    if project_id:
        query = query.where(IoTDashboard.project_id == project_id)
        count_query = count_query.where(IoTDashboard.project_id == project_id)
    if is_public is not None:
        query = query.where(IoTDashboard.is_public == is_public)
        count_query = count_query.where(IoTDashboard.is_public == is_public)

    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0
    total_pages = ceil(total / per_page) if total > 0 else 0

    query = query.order_by(IoTDashboard.created_at.desc())
    query = query.offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(query)
    dashboards = result.scalars().all()

    meta = MetaInfo(page=page, per_page=per_page, total=total, total_pages=total_pages)
    return _api_response(
        data=[_dashboard_to_response(d) for d in dashboards], meta=meta
    )


@router.put("/dashboards/{dashboard_id}")
async def update_dashboard(
    dashboard_id: UUID,
    body: IoTDashboardUpdate,
    token_data: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = scope_org(token_data)
    stmt = select(IoTDashboard).where(IoTDashboard.id == dashboard_id)
    if org_id is not None:
        stmt = stmt.where(IoTDashboard.organization_id == org_id)
    result = await db.execute(stmt)
    dashboard = result.scalar_one_or_none()
    if not dashboard:
        raise _dashboard_not_found()

    update_data = body.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(dashboard, key, value)

    await db.flush()
    await db.refresh(dashboard)
    return _api_response(data=_dashboard_to_response(dashboard))


# === Device Groups ===

@router.post("/device-groups")
async def create_device_group(
    body: DeviceGroupCreate,
    token_data: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = create_org(token_data, body.organization_id)
    if body.parent_group_id is not None:
        await _ensure_parent_group(db, token_data, body.parent_group_id, org_id)
    group = DeviceGroup(
        organization_id=org_id,
        name=body.name,
        description=body.description,
        device_ids=body.device_ids,
        group_type=body.group_type,
        parent_group_id=body.parent_group_id,
    )
    db.add(group)
    await db.flush()
    await db.refresh(group)
    return _api_response(data=_group_to_response(group))


@router.get("/device-groups")
async def list_device_groups(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    group_type: str | None = Query(None),
    parent_group_id: UUID | None = Query(None),
    organization_id: UUID | None = Query(None),
    token_data: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    query = select(DeviceGroup)
    count_query = select(func.count(DeviceGroup.id))

    org_id = scope_org(token_data, organization_id)
    if org_id is not None:
        query = query.where(DeviceGroup.organization_id == org_id)
        count_query = count_query.where(DeviceGroup.organization_id == org_id)

    if group_type:
        query = query.where(DeviceGroup.group_type == group_type)
        count_query = count_query.where(DeviceGroup.group_type == group_type)
    if parent_group_id is not None:
        query = query.where(DeviceGroup.parent_group_id == parent_group_id)
        count_query = count_query.where(DeviceGroup.parent_group_id == parent_group_id)

    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0
    total_pages = ceil(total / per_page) if total > 0 else 0

    query = query.order_by(DeviceGroup.created_at.desc())
    query = query.offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(query)
    groups = result.scalars().all()

    meta = MetaInfo(page=page, per_page=per_page, total=total, total_pages=total_pages)
    return _api_response(
        data=[_group_to_response(g) for g in groups], meta=meta
    )


@router.put("/device-groups/{group_id}/devices")
async def update_device_group_devices(
    group_id: UUID,
    body: DeviceGroupUpdate,
    token_data: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    group = await _get_group(db, group_id, scope_org(token_data))
    if not group:
        raise _group_not_found()

    update_data = body.model_dump(exclude_unset=True)
    new_parent = update_data.get("parent_group_id")
    if new_parent is not None:
        await _ensure_parent_group(db, token_data, new_parent, group.organization_id)
    for key, value in update_data.items():
        setattr(group, key, value)

    await db.flush()
    await db.refresh(group)
    return _api_response(data=_group_to_response(group))


@router.get("/device-groups/{group_id}")
async def get_device_group(
    group_id: UUID,
    token_data: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    group = await _get_group(db, group_id, scope_org(token_data))
    if not group:
        raise _group_not_found()
    return _api_response(data=_group_to_response(group))
