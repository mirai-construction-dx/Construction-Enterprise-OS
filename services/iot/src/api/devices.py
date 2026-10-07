"""デバイス登録・管理エンドポイント"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from ..middleware.auth import (
    get_current_client,
    get_current_user,
    require_organization_id,
)
from ..models.base import get_db
from ..schemas import (
    APIResponse,
    DeviceCreateRequest,
    DeviceHeartbeatRequest,
    DeviceListResponse,
    DeviceResponse,
    DeviceUpdateRequest,
    MetaInfo,
    SensorResponse,
)
from ..services.device_service import (
    register_device,
    get_device_by_id,
    get_devices_paginated,
    update_device as update_device_svc,
    delete_device as delete_device_svc,
    device_heartbeat as device_heartbeat_svc,
)

router = APIRouter()


def _device_to_response(device) -> DeviceResponse:
    return DeviceResponse(
        id=device.id,
        organization_id=device.organization_id,
        project_id=device.project_id,
        site_id=device.site_id,
        name=device.name,
        device_type=device.device_type,
        serial_number=device.serial_number,
        firmware_version=device.firmware_version,
        status=device.status,
        battery_level=device.battery_level,
        location=device.location,
        metadata=device.metadata_,
        last_seen_at=device.last_seen_at,
        registered_at=device.registered_at,
        updated_at=device.updated_at,
        sensors=[
            SensorResponse(
                id=s.id,
                device_id=s.device_id,
                name=s.name,
                sensor_type=s.sensor_type,
                unit=s.unit,
                min_value=s.min_value,
                max_value=s.max_value,
                is_active=s.is_active,
                created_at=s.created_at,
            )
            for s in (device.sensors or [])
        ],
    )


@router.post("", response_model=APIResponse[DeviceResponse], status_code=status.HTTP_201_CREATED)
async def create_device(
    request: Request,
    body: DeviceCreateRequest,
    db: AsyncSession = Depends(get_db),
    _current_user=Depends(get_current_user),
):
    data = body.model_dump()
    data["organization_id"] = require_organization_id(_current_user)
    device = await register_device(db, data)
    return APIResponse(data=_device_to_response(device))


@router.get("", response_model=APIResponse[DeviceListResponse])
async def list_devices(
    request: Request,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    device_type: str | None = Query(None),
    status: str | None = Query(None),
    project_id: UUID | None = Query(None),
    organization_id: UUID | None = Query(None),
    db: AsyncSession = Depends(get_db),
    _current_user=Depends(get_current_user),
):
    devices, total = await get_devices_paginated(
        db,
        page=page,
        per_page=per_page,
        device_type=device_type,
        status=status,
        project_id=project_id,
        organization_id=require_organization_id(_current_user),
    )
    total_pages = max((total + per_page - 1) // per_page, 1) if total > 0 else 0

    return APIResponse(
        data=DeviceListResponse(
            devices=[_device_to_response(d) for d in devices],
            total=total,
        ),
        meta=MetaInfo(
            page=page,
            per_page=per_page,
            total=total,
            total_pages=total_pages,
        ),
    )


@router.get("/{device_id}", response_model=APIResponse[DeviceResponse])
async def get_device(
    request: Request,
    device_id: UUID,
    db: AsyncSession = Depends(get_db),
    _current_user=Depends(get_current_user),
):
    org_id = require_organization_id(_current_user)
    device = await get_device_by_id(db, device_id, org_id)
    if not device or device.organization_id != org_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "DEVICE_NOT_FOUND", "message": "デバイスが見つかりません。"},
        )
    return APIResponse(data=_device_to_response(device))


@router.put("/{device_id}", response_model=APIResponse[DeviceResponse])
async def update_device(
    request: Request,
    device_id: UUID,
    body: DeviceUpdateRequest,
    db: AsyncSession = Depends(get_db),
    _current_user=Depends(get_current_user),
):
    org_id = require_organization_id(_current_user)
    device = await update_device_svc(
        db, device_id, org_id, body.model_dump(exclude_unset=True)
    )
    if not device:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "DEVICE_NOT_FOUND", "message": "デバイスが見つかりません。"},
        )
    return APIResponse(data=_device_to_response(device))


@router.delete("/{device_id}", response_model=APIResponse)
async def delete_device(
    request: Request,
    device_id: UUID,
    db: AsyncSession = Depends(get_db),
    _current_user=Depends(get_current_user),
):
    org_id = require_organization_id(_current_user)
    deleted = await delete_device_svc(db, device_id, org_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "DEVICE_NOT_FOUND", "message": "デバイスが見つかりません。"},
        )
    return APIResponse(data={"message": "デバイスを削除しました。"})


@router.post("/{device_id}/heartbeat", response_model=APIResponse[DeviceResponse])
async def device_heartbeat(
    request: Request,
    device_id: UUID,
    body: DeviceHeartbeatRequest,
    db: AsyncSession = Depends(get_db),
    _current_client=Depends(get_current_client),
):
    org_id = require_organization_id(_current_client)
    device = await device_heartbeat_svc(
        db, device_id, org_id, body.model_dump(exclude_unset=True)
    )
    if not device:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "DEVICE_NOT_FOUND", "message": "デバイスが見つかりません。"},
        )
    return APIResponse(data=_device_to_response(device))
