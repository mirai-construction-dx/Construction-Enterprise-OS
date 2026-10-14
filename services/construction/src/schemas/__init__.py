"""API リクエスト/レスポンス スキーマ"""

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field


# ============================================
# WBS (Work Breakdown Structure)
# ============================================
class WBSCreateRequest(BaseModel):
    organization_id: UUID
    project_id: UUID
    parent_id: UUID | None = None
    wbs_code: str = Field(max_length=50)
    name: str = Field(max_length=500)
    description: str | None = None
    level: int
    planned_start: date | None = None
    planned_end: date | None = None
    planned_cost: Decimal | None = None
    weight_percent: Decimal | None = None
    responsible_person: UUID | None = None


class WBSUpdateRequest(BaseModel):
    wbs_code: str | None = None
    name: str | None = None
    description: str | None = None
    planned_start: date | None = None
    planned_end: date | None = None
    actual_start: date | None = None
    actual_end: date | None = None
    planned_cost: Decimal | None = None
    actual_cost: Decimal | None = None
    weight_percent: Decimal | None = None
    progress_percent: Decimal | None = Field(None, ge=0, le=100)
    status: str | None = None
    responsible_person: UUID | None = None


class WBSProgressUpdateRequest(BaseModel):
    progress_percent: Decimal = Field(ge=0, le=100)
    status: str | None = None


class WBSResponse(BaseModel):
    id: UUID
    organization_id: UUID
    project_id: UUID
    parent_id: UUID | None
    wbs_code: str
    name: str
    description: str | None
    level: int
    planned_start: date | None
    planned_end: date | None
    actual_start: date | None
    actual_end: date | None
    planned_cost: Decimal | None
    actual_cost: Decimal | None
    weight_percent: Decimal | None
    progress_percent: Decimal | None = None
    status: str | None = None
    responsible_person: UUID | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class WBSListResponse(BaseModel):
    items: list[WBSResponse]
    total: int
    page: int
    per_page: int


class WBSTreeResponse(WBSResponse):
    children: list["WBSTreeResponse"] = []


# ============================================
# Resource
# ============================================
class ResourceCreateRequest(BaseModel):
    organization_id: UUID
    project_id: UUID
    wbs_item_id: UUID | None = None
    resource_type: str = Field(max_length=50)
    name: str = Field(max_length=500)
    specification: str | None = None
    unit: str | None = None
    planned_quantity: Decimal | None = None
    actual_quantity: Decimal | None = None
    unit_cost: Decimal | None = None
    total_cost: Decimal | None = None
    allocation_start: date | None = None
    allocation_end: date | None = None
    status: str = "planned"


class ResourceUpdateRequest(BaseModel):
    specification: str | None = None
    unit: str | None = None
    planned_quantity: Decimal | None = None
    actual_quantity: Decimal | None = None
    unit_cost: Decimal | None = None
    total_cost: Decimal | None = None
    allocation_start: date | None = None
    allocation_end: date | None = None
    status: str | None = None


class ResourceAllocationRequest(BaseModel):
    status: str  # allocated/in_use/demobilized


class ResourceCostSummary(BaseModel):
    resource_type: str
    count: int
    total_planned_cost: Decimal
    total_actual_cost: Decimal


class ResourceResponse(BaseModel):
    id: UUID
    organization_id: UUID
    project_id: UUID
    wbs_item_id: UUID | None
    resource_type: str
    name: str
    specification: str | None
    unit: str | None
    planned_quantity: Decimal | None
    actual_quantity: Decimal | None
    unit_cost: Decimal | None
    total_cost: Decimal | None
    allocation_start: date | None
    allocation_end: date | None
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}


class ResourceListResponse(BaseModel):
    items: list[ResourceResponse]
    total: int
    page: int
    per_page: int


# ============================================
# Schedule
# ============================================
class ScheduleCreateRequest(BaseModel):
    organization_id: UUID
    project_id: UUID
    wbs_item_id: UUID | None = None
    name: str = Field(max_length=500)
    schedule_type: str = Field(max_length=50)
    planned_start: date
    planned_end: date
    actual_start: date | None = None
    actual_end: date | None = None
    duration_days: int | None = None
    predecessor_ids: list[UUID] = []
    successor_ids: list[UUID] = []
    float_days: int | None = None
    critical_path: bool = False
    status: str = "planned"
    progress_percent: Decimal = Decimal("0")


class ScheduleUpdateRequest(BaseModel):
    name: str | None = None
    schedule_type: str | None = None
    planned_start: date | None = None
    planned_end: date | None = None
    actual_start: date | None = None
    actual_end: date | None = None
    duration_days: int | None = None
    predecessor_ids: list[UUID] | None = None
    successor_ids: list[UUID] | None = None
    float_days: int | None = None
    critical_path: bool | None = None
    status: str | None = None
    progress_percent: Decimal | None = None


class ScheduleResponse(BaseModel):
    id: UUID
    organization_id: UUID
    project_id: UUID
    wbs_item_id: UUID | None
    name: str
    schedule_type: str
    planned_start: date
    planned_end: date
    actual_start: date | None
    actual_end: date | None
    duration_days: int | None
    predecessor_ids: list[UUID] | None = None
    successor_ids: list[UUID] | None = None
    float_days: int | None
    critical_path: bool
    status: str | None = None
    progress_percent: Decimal | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ScheduleListResponse(BaseModel):
    items: list[ScheduleResponse]
    total: int
    page: int
    per_page: int


class GanttDataResponse(BaseModel):
    schedule_id: UUID
    name: str
    wbs_item_id: UUID | None
    planned_start: date
    planned_end: date
    actual_start: date | None
    actual_end: date | None
    critical_path: bool
    progress_percent: Decimal
    status: str


# ============================================
# Method Statement
# ============================================
class MethodCreateRequest(BaseModel):
    organization_id: UUID
    project_id: UUID
    wbs_item_id: UUID | None = None
    title: str = Field(max_length=500)
    document_type: str = Field(max_length=50)
    content: str | None = None
    safety_measures: str | None = None
    environmental_measures: str | None = None
    quality_control_points: str | None = None
    required_equipment: list[str] | None = None
    required_materials: list[str] | None = None
    required_labor: str | None = None
    attachments: list[str] = []
    created_by: UUID | None = None


class MethodUpdateRequest(BaseModel):
    title: str | None = None
    document_type: str | None = None
    content: str | None = None
    safety_measures: str | None = None
    environmental_measures: str | None = None
    quality_control_points: str | None = None
    required_equipment: list[str] | None = None
    required_materials: list[str] | None = None
    required_labor: str | None = None
    attachments: list[str] | None = None


class MethodApprovalRequest(BaseModel):
    # 後方互換のため受理するが、承認者同定には使用しない（トークン由来に変更）。
    approved_by: UUID | None = None


class MethodResponse(BaseModel):
    id: UUID
    organization_id: UUID
    project_id: UUID
    wbs_item_id: UUID | None
    title: str
    document_type: str
    content: str | None
    safety_measures: str | None
    environmental_measures: str | None
    quality_control_points: str | None
    required_equipment: list[str] | None
    required_materials: list[str] | None
    required_labor: str | None
    attachments: list[str]
    status: str
    approved_by: UUID | None
    approved_at: datetime | None
    created_by: UUID | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class MethodListResponse(BaseModel):
    items: list[MethodResponse]
    total: int
    page: int
    per_page: int
