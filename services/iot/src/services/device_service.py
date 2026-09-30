"""デバイス管理サービス"""

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..models import Device as DeviceModel
from ..models import Sensor as SensorModel


async def register_device(db: AsyncSession, data: dict) -> DeviceModel:
    device = DeviceModel(
        organization_id=data["organization_id"],
        project_id=data.get("project_id"),
        site_id=data.get("site_id"),
        name=data["name"],
        device_type=data["device_type"],
        serial_number=data.get("serial_number"),
        firmware_version=data.get("firmware_version"),
        metadata_=data.get("metadata", {}),
        status="offline",
    )
    db.add(device)
    await db.flush()
    return device


def _scoped_device_stmt(device_id: UUID, organization_id: UUID | None):
    """Device lookup; ``organization_id`` None means no org filter (cross-org admin only)."""
    stmt = select(DeviceModel).where(DeviceModel.id == device_id)
    if organization_id is not None:
        stmt = stmt.where(DeviceModel.organization_id == organization_id)
    return stmt


async def get_device_by_id(
    db: AsyncSession, device_id: UUID, organization_id: UUID | None = None
) -> DeviceModel | None:
    result = await db.execute(
        _scoped_device_stmt(device_id, organization_id).options(
            selectinload(DeviceModel.sensors)
        )
    )
    return result.scalar_one_or_none()


async def get_devices_paginated(
    db: AsyncSession,
    page: int = 1,
    per_page: int = 20,
    device_type: str | None = None,
    status: str | None = None,
    project_id: UUID | None = None,
    organization_id: UUID | None = None,
) -> tuple[list[DeviceModel], int]:
    query = select(DeviceModel).options(selectinload(DeviceModel.sensors))
    count_query = select(func.count(DeviceModel.id))

    if device_type:
        query = query.where(DeviceModel.device_type == device_type)
        count_query = count_query.where(DeviceModel.device_type == device_type)
    if status:
        query = query.where(DeviceModel.status == status)
        count_query = count_query.where(DeviceModel.status == status)
    if project_id:
        query = query.where(DeviceModel.project_id == project_id)
        count_query = count_query.where(DeviceModel.project_id == project_id)
    if organization_id is not None:
        query = query.where(DeviceModel.organization_id == organization_id)
        count_query = count_query.where(DeviceModel.organization_id == organization_id)

    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    query = query.order_by(DeviceModel.registered_at.desc())
    query = query.offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(query)
    devices = list(result.scalars().all())

    return devices, total


async def update_device(
    db: AsyncSession, device_id: UUID, data: dict, organization_id: UUID | None = None
) -> DeviceModel | None:
    result = await db.execute(_scoped_device_stmt(device_id, organization_id))
    device = result.scalar_one_or_none()
    if not device:
        return None

    for key, value in data.items():
        if hasattr(device, key) and value is not None:
            if key == "metadata":
                setattr(device, "metadata_", value)
            else:
                setattr(device, key, value)

    await db.flush()
    return device


async def delete_device(
    db: AsyncSession, device_id: UUID, organization_id: UUID | None = None
) -> bool:
    result = await db.execute(_scoped_device_stmt(device_id, organization_id))
    device = result.scalar_one_or_none()
    if not device:
        return False
    await db.delete(device)
    await db.flush()
    return True


async def device_heartbeat(
    db: AsyncSession, device_id: UUID, data: dict
) -> DeviceModel | None:
    result = await db.execute(select(DeviceModel).where(DeviceModel.id == device_id))
    device = result.scalar_one_or_none()
    if not device:
        return None

    now = datetime.now(timezone.utc)
    device.last_seen_at = now
    device.status = "online"

    if data.get("battery_level") is not None:
        device.battery_level = data["battery_level"]
    if data.get("location") is not None:
        device.location = data["location"]
    if data.get("firmware_version") is not None:
        device.firmware_version = data["firmware_version"]

    await db.flush()
    return device


async def add_sensor(
    db: AsyncSession, device_id: UUID, data: dict, organization_id: UUID | None = None
) -> SensorModel | None:
    result = await db.execute(_scoped_device_stmt(device_id, organization_id))
    device = result.scalar_one_or_none()
    if not device:
        return None

    sensor = SensorModel(
        device_id=device_id,
        name=data["name"],
        sensor_type=data["sensor_type"],
        unit=data.get("unit"),
        min_value=data.get("min_value"),
        max_value=data.get("max_value"),
        metadata_=data.get("metadata", {}),
    )
    db.add(sensor)
    await db.flush()
    return sensor


async def get_sensors_by_device(
    db: AsyncSession, device_id: UUID, organization_id: UUID | None = None
) -> list[SensorModel]:
    stmt = select(SensorModel).where(SensorModel.device_id == device_id)
    if organization_id is not None:
        # Sensors have no organization column: scope through the parent device.
        stmt = stmt.where(
            SensorModel.device_id.in_(
                select(DeviceModel.id).where(DeviceModel.organization_id == organization_id)
            )
        )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_sensor_by_id(
    db: AsyncSession, sensor_id: UUID, organization_id: UUID | None = None
) -> SensorModel | None:
    """Sensor lookup scoped through its parent device's organization."""
    stmt = select(SensorModel).options(selectinload(SensorModel.device)).where(
        SensorModel.id == sensor_id
    )
    if organization_id is not None:
        stmt = stmt.join(DeviceModel, SensorModel.device_id == DeviceModel.id).where(
            DeviceModel.organization_id == organization_id
        )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()
