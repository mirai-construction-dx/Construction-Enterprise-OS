"""センサーメタデータ管理エンドポイント"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from ..middleware.auth import get_current_user, require_organization_id
from ..models.base import get_db
from ..schemas import (
    APIResponse,
    SensorCreateRequest,
    SensorResponse,
)
from ..services.device_service import add_sensor, get_sensors_by_device

router = APIRouter()


@router.post("/{device_id}/sensors", response_model=APIResponse[SensorResponse], status_code=status.HTTP_201_CREATED)
async def create_sensor(
    request: Request,
    device_id: UUID,
    body: SensorCreateRequest,
    db: AsyncSession = Depends(get_db),
    _current_user=Depends(get_current_user),
):
    org_id = require_organization_id(_current_user)
    sensor = await add_sensor(db, device_id, org_id, body.model_dump())
    if not sensor:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "DEVICE_NOT_FOUND", "message": "デバイスが見つかりません。"},
        )
    return APIResponse(data=SensorResponse.model_validate(sensor))


@router.get("/{device_id}/sensors", response_model=APIResponse[list[SensorResponse]])
async def list_sensors(
    request: Request,
    device_id: UUID,
    db: AsyncSession = Depends(get_db),
    _current_user=Depends(get_current_user),
):
    org_id = require_organization_id(_current_user)
    sensors = await get_sensors_by_device(db, device_id, org_id)
    if sensors is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "DEVICE_NOT_FOUND", "message": "デバイスが見つかりません。"},
        )
    return APIResponse(data=[SensorResponse.model_validate(s) for s in sensors])
