"""API request/response schemas."""

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field


# ── Common ──


class APIResponse(BaseModel):
    success: bool = True
    data: dict | list | None = None
    error: dict | None = None
    meta: dict | None = None


# ── DisasterReport ──


class DisasterCreate(BaseModel):
    organization_id: UUID
    project_id: UUID | None = None
    title: str = Field(min_length=1, max_length=500)
    disaster_type: str = Field(min_length=1, max_length=50)
    severity: str = Field(min_length=1, max_length=20)
    occurred_at: datetime
    location: str | None = Field(None, max_length=500)
    description: str = Field(min_length=1)
    estimated_cost: Decimal | None = None
    casualties: int = Field(0, ge=0)
    evacuation_required: bool = False
    # #139: 作成者 (reported_by) はトークンの sub から設定する。本文では受け付けない。


class DisasterUpdate(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=500)
    status: str | None = None
    severity: str | None = None
    damage_assessment: str | None = None
    estimated_cost: Decimal | None = None
    casualties: int | None = Field(None, ge=0)
    evacuation_required: bool | None = None


# ── RecoveryPlan ──


class RecoveryPlanCreate(BaseModel):
    organization_id: UUID
    title: str = Field(min_length=1, max_length=500)
    description: str | None = None
    priority: str = Field("medium", max_length=20)
    estimated_duration_days: int | None = Field(None, ge=1)
    estimated_cost: Decimal | None = None
    start_date: date | None = None
    contractor: str | None = Field(None, max_length=255)
    resources_needed: str | None = None
    # #139: 作成者 (created_by) はトークンの sub から設定する。本文では受け付けない。


class RecoveryPlanUpdate(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=500)
    description: str | None = None
    priority: str | None = None
    status: str | None = None
    estimated_duration_days: int | None = Field(None, ge=1)
    estimated_cost: Decimal | None = None
    actual_cost: Decimal | None = None
    start_date: date | None = None
    completed_date: date | None = None
    contractor: str | None = Field(None, max_length=255)
    resources_needed: str | None = None
    progress_percent: Decimal | None = Field(None, ge=0, le=100)


# ── MaintenanceRecord ──


class MaintenanceRecordCreate(BaseModel):
    organization_id: UUID
    project_id: UUID | None = None
    asset_name: str = Field(min_length=1, max_length=500)
    asset_type: str = Field(min_length=1, max_length=50)
    maintenance_type: str = Field(min_length=1, max_length=50)
    description: str = Field(min_length=1)
    cost: Decimal | None = None
    contractor: str | None = Field(None, max_length=255)
    scheduled_date: date | None = None
    next_maintenance_date: date | None = None
    location: str | None = Field(None, max_length=500)
    # #139: 作業者 (performed_by) はトークンの sub から設定する。本文では受け付けない。
    notes: str | None = None


class MaintenanceRecordUpdate(BaseModel):
    asset_name: str | None = Field(None, min_length=1, max_length=500)
    status: str | None = None
    work_performed: str | None = None
    cost: Decimal | None = None
    contractor: str | None = Field(None, max_length=255)
    completed_date: date | None = None
    next_maintenance_date: date | None = None
    notes: str | None = None


# ── InspectionSchedule ──


class InspectionCreate(BaseModel):
    organization_id: UUID
    asset_name: str = Field(min_length=1, max_length=500)
    asset_type: str = Field(min_length=1, max_length=50)
    inspection_type: str = Field(min_length=1, max_length=50)
    frequency: str = Field(min_length=1, max_length=20)
    next_inspection_date: date
    inspector: str | None = Field(None, max_length=255)
    notes: str | None = None


class InspectionComplete(BaseModel):
    status: str = "completed"
    checklist: list | None = None
    notes: str | None = None
