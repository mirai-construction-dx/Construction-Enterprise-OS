"""センサーメタデータ管理エンドポイント"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from ..middleware.auth import TokenData, get_current_user
from ..middleware.tenant import scope_org
from ..models.base import get_db
from ..schemas import (
    APIResponse,
    SensorCreateRequest,
    SensorResponse,
)
from ..services.device_service import add_sensor, get_device_by_id, get_sensors_by_device

router = APIRouter()


def _device_not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={"code": "DEVICE_NOT_FOUND", "message": "デバイスが見つかりません。"},
    )


@router.post("/{device_id}/sensors", response_model=APIResponse[SensorResponse], status_code=status.HTTP_201_CREATED)
async def create_sensor(
    request: Request,
    device_id: UUID,
    body: SensorCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    # The parent device is looked up within the caller's organization (other org: 404).
    sensor = await add_sensor(db, device_id, body.model_dump(), scope_org(current_user))
    if not sensor:
        raise _device_not_found()
    return APIResponse(data=SensorResponse.model_validate(sensor))


@router.get("/{device_id}/sensors", response_model=APIResponse[list[SensorResponse]])
async def list_sensors(
    request: Request,
    device_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    org = scope_org(current_user)
    # Parent device must be visible to the caller; another org's device is 404 (no existence leak).
    if not await get_device_by_id(db, device_id, org):
        raise _device_not_found()
    sensors = await get_sensors_by_device(db, device_id, org)
    return APIResponse(data=[SensorResponse.model_validate(s) for s in sensors])
