"""API リクエスト/レスポンス スキーマ"""

from datetime import datetime
from uuid import UUID

from typing import Generic, TypeVar

from pydantic import BaseModel, Field


# ============================================
# 共通
# ============================================
T = TypeVar("T")


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
# Autonomous Agent
# ============================================
class AgentCreateRequest(BaseModel):
    organization_id: UUID
    name: str = Field(min_length=1, max_length=255)
    agent_type: str = Field(min_length=1, max_length=50)
    target_resource: str | None = None
    config: dict = Field(default_factory=dict)
    is_enabled: bool = True


class AgentUpdateRequest(BaseModel):
    name: str | None = None
    agent_type: str | None = None
    target_resource: str | None = None
    config: dict | None = None
    is_enabled: bool | None = None


class AgentResponse(BaseModel):
    id: UUID
    organization_id: UUID
    name: str
    agent_type: str
    status: str
    target_resource: str | None
    config: dict
    last_run_at: datetime | None
    run_count: int
    error_count: int
    is_enabled: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class AgentListResponse(BaseModel):
    agents: list[AgentResponse]
    total: int


# ============================================
# Digital Twin
# ============================================
class TwinCreateRequest(BaseModel):
    organization_id: UUID
    project_id: UUID | None = None
    name: str = Field(min_length=1, max_length=500)
    twin_type: str = Field(min_length=1, max_length=50)
    bim_model_id: UUID | None = None
    iot_device_ids: list[UUID] = Field(default_factory=list)
    sync_interval_seconds: int = Field(default=60, ge=1, le=86400)
    data_sources: dict = Field(default_factory=dict)
    metadata: dict = Field(default_factory=dict)


class TwinUpdateRequest(BaseModel):
    name: str | None = None
    project_id: UUID | None = None
    bim_model_id: UUID | None = None
    iot_device_ids: list[UUID] | None = None
    sync_interval_seconds: int | None = None
    data_sources: dict | None = None
    metadata: dict | None = None


class TwinSyncRequest(BaseModel):
    current_state: dict = Field(default_factory=dict)


class TwinResponse(BaseModel):
    id: UUID
    organization_id: UUID
    project_id: UUID | None
    name: str
    twin_type: str
    status: str
    bim_model_id: UUID | None
    iot_device_ids: list
    last_sync_at: datetime | None
    sync_interval_seconds: int
    data_sources: dict
    current_state: dict
    # SQLAlchemy の宣言的Baseでは `metadata` が MetaData 予約属性になるため、
    # ORM の実属性名 `metadata_` から読み取る(直すと読み取りAPIが500になる)。
    metadata: dict = Field(validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class TwinCurrentStateResponse(BaseModel):
    twin_id: UUID
    name: str
    status: str
    current_state: dict
    last_sync_at: datetime | None


class TwinListResponse(BaseModel):
    twins: list[TwinResponse]
    total: int


# ============================================
# Autonomous Task
# ============================================
class TaskCreateRequest(BaseModel):
    organization_id: UUID
    agent_id: UUID | None = None
    digital_twin_id: UUID | None = None
    title: str = Field(min_length=1, max_length=500)
    task_type: str = Field(min_length=1, max_length=50)
    priority: str = Field(default="normal", pattern="^(low|normal|high|critical)$")
    input_data: dict | None = None


class TaskResponse(BaseModel):
    id: UUID
    organization_id: UUID
    agent_id: UUID | None
    digital_twin_id: UUID | None
    title: str
    task_type: str
    priority: str
    status: str
    input_data: dict | None
    output_data: dict | None
    error_message: str | None
    started_at: datetime | None
    completed_at: datetime | None
    duration_ms: int | None
    created_at: datetime

    model_config = {"from_attributes": True}


class TaskListResponse(BaseModel):
    tasks: list[TaskResponse]
    total: int


# ============================================
# Construction Simulation
# ============================================
class SimulationCreateRequest(BaseModel):
    organization_id: UUID
    project_id: UUID | None = None
    digital_twin_id: UUID | None = None
    name: str = Field(min_length=1, max_length=500)
    simulation_type: str = Field(min_length=1, max_length=50)
    parameters: dict = Field(default_factory=dict)
    # #139: 作成者はトークンの sub から設定する（本文では受け付けない）。


class SimulationResponse(BaseModel):
    id: UUID
    organization_id: UUID
    project_id: UUID | None
    digital_twin_id: UUID | None
    name: str
    simulation_type: str
    status: str
    parameters: dict
    results: dict
    progress_percent: float
    started_at: datetime | None
    completed_at: datetime | None
    created_by: UUID | None
    created_at: datetime

    model_config = {"from_attributes": True}


class SimulationListResponse(BaseModel):
    simulations: list[SimulationResponse]
    total: int


# ============================================
# Autonomous Operations
# ============================================
class OperationCreateRequest(BaseModel):
    organization_id: UUID
    project_id: UUID | None = None
    digital_twin_id: UUID | None = None
    name: str = Field(min_length=1, max_length=500)
    operation_type: str = Field(min_length=1, max_length=50)
    equipment_id: UUID | None = None
    plan_data: dict = Field(default_factory=dict)
    area: dict | None = None
    operator_id: UUID | None = None


class OperationUpdateRequest(BaseModel):
    name: str | None = None
    operation_type: str | None = None
    equipment_id: UUID | None = None
    plan_data: dict | None = None
    area: dict | None = None
    operator_id: UUID | None = None


class OperationResponse(BaseModel):
    id: UUID
    organization_id: UUID
    project_id: UUID | None
    digital_twin_id: UUID | None
    name: str
    operation_type: str
    equipment_id: UUID | None
    status: str
    plan_data: dict
    execution_log: list
    progress_percent: float
    safety_status: str
    area: dict | None
    start_time: datetime | None
    end_time: datetime | None
    operator_id: UUID | None
    created_at: datetime

    model_config = {"from_attributes": True}


class OperationListResponse(BaseModel):
    operations: list[OperationResponse]
    total: int


class OperationProgressResponse(BaseModel):
    operation_id: UUID
    name: str
    status: str
    progress_percent: float
    safety_status: str
    execution_log: list


# ============================================
# Marine Robotics
# ============================================
class MarineRobotCreateRequest(BaseModel):
    organization_id: UUID
    project_id: UUID | None = None
    robot_name: str = Field(min_length=1, max_length=255)
    robot_type: str = Field(min_length=1, max_length=50)
    mission_type: str | None = None
    location: dict | None = None
    depth_meters: float | None = None
    battery_level: int | None = Field(None, ge=0, le=100)
    mission_plan: dict = Field(default_factory=dict)


class MarineRobotUpdateRequest(BaseModel):
    robot_name: str | None = None
    robot_type: str | None = None
    mission_type: str | None = None
    location: dict | None = None
    depth_meters: float | None = None
    battery_level: int | None = Field(None, ge=0, le=100)
    mission_plan: dict | None = None


class MarineRobotResponse(BaseModel):
    id: UUID
    organization_id: UUID
    project_id: UUID | None
    robot_name: str
    robot_type: str
    status: str
    mission_type: str | None
    location: dict | None
    depth_meters: float | None
    battery_level: int | None
    mission_plan: dict
    telemetry: dict
    last_contact: datetime | None
    deployed_at: datetime | None
    recovered_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


class MarineRobotListResponse(BaseModel):
    robots: list[MarineRobotResponse]
    total: int


class MarineRobotTelemetryResponse(BaseModel):
    robot_id: UUID
    robot_name: str
    status: str
    telemetry: dict
    battery_level: int | None
    location: dict | None
    last_contact: datetime | None


class MissionPlanRequest(BaseModel):
    mission_plan: dict = Field(default_factory=dict)


# ============================================
# Autonomous Controls
# ============================================
class ControlSendRequest(BaseModel):
    organization_id: UUID
    target_id: UUID
    target_type: str = Field(min_length=1, max_length=50)
    command_type: str = Field(min_length=1, max_length=50)
    parameters: dict = Field(default_factory=dict)
    issued_by: UUID


class ControlResponse(BaseModel):
    id: UUID
    organization_id: UUID
    target_id: UUID
    target_type: str
    command_type: str
    parameters: dict
    status: str
    issued_by: UUID
    executed_at: datetime | None
    result: dict | None
    error_message: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class ControlListResponse(BaseModel):
    controls: list[ControlResponse]
    total: int


# ============================================
# Autonomous Machines
# ============================================
class MachineResponse(BaseModel):
    id: str
    machine_no: str
    machine_type: str
    status: str
    location: str | None = None
    battery_level: float | None = None
    current_task: str | None = None
    last_updated: str | None = None


class MachineListResponse(BaseModel):
    items: list[MachineResponse]
    total: int


# ============================================
# Drone Flights
# ============================================
class DroneFlightResponse(BaseModel):
    id: str
    flight_id: str
    date: str
    pilot: str
    area: str
    altitude: float
    flight_time_min: int
    photo_count: int
    status: str
    coverage: float


class DroneFlightListResponse(BaseModel):
    items: list[DroneFlightResponse]
    total: int


# ============================================
# RPA Tasks (autonomous/rpa)
# ============================================
class RpaTaskResponse(BaseModel):
    id: str
    name: str
    trigger: str
    schedule: str | None = None
    last_result: str
    last_run: str | None = None
    avg_duration_min: float
    runs_this_month: int
    is_active: bool


class RpaTaskListResponse(BaseModel):
    items: list[RpaTaskResponse]
    total: int


# ============================================
# Twin Sensors
# ============================================
class TwinSensorResponse(BaseModel):
    id: str
    sensor_id: str
    twin_id: str | None = None
    sensor_type: str
    location: str
    value: float
    unit: str
    status: str
    last_updated: str | None = None


class TwinSensorListResponse(BaseModel):
    items: list[TwinSensorResponse]
    total: int


# ============================================
# Activities
# ============================================
class ActivityResponse(BaseModel):
    id: str
    time: str
    activity_type: str
    message: str
    severity: str | None = None


class ActivityListResponse(BaseModel):
    items: list[ActivityResponse]
    total: int


# ============================================
# Error Logs
# ============================================
class ErrorLogResponse(BaseModel):
    id: str
    machine_no: str
    error_code: str
    message: str
    severity: str
    occurred_at: str
    resolved_at: str | None = None
    status: str


class ErrorLogListResponse(BaseModel):
    items: list[ErrorLogResponse]
    total: int
