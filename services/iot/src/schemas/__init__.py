"""API リクエスト/レスポンス スキーマ"""

from datetime import datetime
from uuid import UUID

from typing import Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


# ============================================
# 共通
# ============================================
class APIResponse(BaseModel, Generic[T]):
    success: bool = True
    data: T | None = None
    error: "ErrorDetail | None" = None
    meta: "MetaInfo | None" = None


class ErrorDetail(BaseModel):
    code: str
    message: str
    details: list[dict] | None = None


class MetaInfo(BaseModel):
    page: int | None = None
    per_page: int | None = None
    total: int | None = None
    total_pages: int | None = None


# ============================================
# デバイス
# ============================================
class DeviceCreateRequest(BaseModel):
    organization_id: UUID
    project_id: UUID | None = None
    site_id: UUID | None = None
    name: str = Field(min_length=1, max_length=255)
    device_type: str = Field(min_length=1, max_length=50)
    serial_number: str | None = None
    firmware_version: str | None = None
    metadata: dict = Field(default_factory=dict)


class DeviceUpdateRequest(BaseModel):
    name: str | None = None
    project_id: UUID | None = None
    site_id: UUID | None = None
    firmware_version: str | None = None
    status: str | None = None
    battery_level: int | None = Field(default=None, ge=0, le=100)
    location: str | None = None
    metadata: dict | None = None


class DeviceHeartbeatRequest(BaseModel):
    battery_level: int | None = Field(default=None, ge=0, le=100)
    location: str | None = None
    firmware_version: str | None = None


class SensorResponse(BaseModel):
    id: UUID
    device_id: UUID
    name: str
    sensor_type: str
    unit: str | None
    min_value: float | None
    max_value: float | None
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class DeviceResponse(BaseModel):
    id: UUID
    organization_id: UUID
    project_id: UUID | None
    site_id: UUID | None
    name: str
    device_type: str
    serial_number: str | None
    firmware_version: str | None
    status: str
    battery_level: int | None
    location: str | None
    # SQLAlchemy の宣言的Baseでは `metadata` が MetaData 予約属性になるため、
    # ORM の実属性名 `metadata_` から読み取る(直すと読み取りAPIが500になる)。
    metadata: dict | None = Field(default=None, validation_alias="metadata_")
    last_seen_at: datetime | None
    registered_at: datetime
    updated_at: datetime
    sensors: list[SensorResponse] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class DeviceListResponse(BaseModel):
    devices: list[DeviceResponse]
    total: int


# ============================================
# センサー
# ============================================
class SensorCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    sensor_type: str = Field(min_length=1, max_length=50)
    unit: str | None = None
    min_value: float | None = None
    max_value: float | None = None
    metadata: dict = Field(default_factory=dict)


# ============================================
# テレメトリ
# ============================================
class TelemetryPoint(BaseModel):
    device_id: UUID
    sensor_id: UUID | None = None
    metric_name: str = Field(min_length=1, max_length=100)
    value: float
    unit: str | None = None
    timestamp: datetime | None = None
    metadata: dict = Field(default_factory=dict)


class TelemetryIngestRequest(BaseModel):
    data: list[TelemetryPoint] = Field(min_length=1, max_length=1000)


class TelemetryQueryParams(BaseModel):
    start_time: datetime
    end_time: datetime
    metric_name: str | None = None
    limit: int = Field(default=100, ge=1, le=10000)


class LatestTelemetryValue(BaseModel):
    sensor_id: UUID | None
    metric_name: str
    value: float
    unit: str | None
    timestamp: datetime


# ============================================
# アラート
# ============================================
class AlertRuleCreateRequest(BaseModel):
    organization_id: UUID
    device_id: UUID | None = None
    sensor_id: UUID | None = None
    name: str = Field(min_length=1, max_length=255)
    metric_name: str = Field(min_length=1, max_length=100)
    condition: str = Field(pattern="^(gt|lt|gte|lte|eq)$")
    threshold: float
    severity: str = Field(
        default="warning", pattern="^(info|warning|critical|emergency)$"
    )
    is_active: bool = True
    cooldown_minutes: int = Field(default=5, ge=1, le=1440)
    notification_channels: list[str] = Field(default_factory=lambda: ["in_app"])


class AlertRuleResponse(BaseModel):
    id: UUID
    organization_id: UUID
    device_id: UUID | None
    sensor_id: UUID | None
    name: str
    metric_name: str
    condition: str
    threshold: float
    severity: str
    is_active: bool
    cooldown_minutes: int
    notification_channels: list[str] | None
    created_at: datetime

    model_config = {"from_attributes": True}


class AlertHistoryResponse(BaseModel):
    id: int
    rule_id: UUID | None
    device_id: UUID
    sensor_id: UUID | None
    metric_name: str
    current_value: float
    threshold: float
    severity: str
    message: str
    acknowledged_by: UUID | None
    acknowledged_at: datetime | None
    resolved_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


class AlertHistoryListResponse(BaseModel):
    alerts: list[AlertHistoryResponse]
    total: int
