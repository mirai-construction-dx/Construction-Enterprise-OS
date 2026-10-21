"""API request/response schemas."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


# ── Common ──

class APIResponse(BaseModel):
    success: bool = True
    data: dict | list | None = None
    error: dict | None = None
    meta: dict | None = None


# ── SafetyInspection ──

class InspectionCreate(BaseModel):
    organization_id: UUID
    project_id: UUID | None = None
    site_id: UUID | None = None
    title: str = Field(min_length=1, max_length=500)
    inspection_type: str = Field(min_length=1, max_length=50)
    inspector_id: UUID
    inspection_date: datetime | None = None
    location: str | None = Field(None, max_length=500)


class InspectionUpdate(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=500)
    status: str | None = None
    inspector_id: UUID | None = None
    inspection_date: datetime | None = None
    location: str | None = Field(None, max_length=500)
    findings: str | None = None
    corrective_actions: str | None = None
    score: int | None = Field(None, ge=0, le=100)
    is_safe: bool | None = None


class InspectionComplete(BaseModel):
    is_safe: bool
    findings: str | None = None
    corrective_actions: str | None = None
    score: int = Field(ge=0, le=100)


# ── HazardReport ──

class HazardCreate(BaseModel):
    organization_id: UUID
    project_id: UUID | None = None
    site_id: UUID | None = None
    title: str = Field(min_length=1, max_length=500)
    description: str = Field(min_length=1)
    hazard_type: str = Field(min_length=1, max_length=50)
    risk_level: str = Field(min_length=1, max_length=20)
    severity: str = Field(min_length=1, max_length=20)
    location: str | None = Field(None, max_length=500)
    # #139: 報告者はトークンの sub から設定する（本文では受け付けない）。
    assigned_to: UUID | None = None


class HazardUpdate(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=500)
    description: str | None = None
    status: str | None = None
    risk_level: str | None = None
    severity: str | None = None
    assigned_to: UUID | None = None
    mitigation: str | None = None


# ── SafetyIncident ──

class IncidentCreate(BaseModel):
    organization_id: UUID
    project_id: UUID | None = None
    site_id: UUID | None = None
    title: str = Field(min_length=1, max_length=500)
    description: str = Field(min_length=1)
    incident_type: str = Field(min_length=1, max_length=50)
    severity: str = Field(min_length=1, max_length=20)
    incident_date: datetime
    location: str | None = Field(None, max_length=500)
    injured_count: int = Field(0, ge=0)
    fatality_count: int = Field(0, ge=0)
    # #139: 報告者はトークンの sub から設定する（本文では受け付けない）。
    is_osha_reportable: bool = False


class IncidentUpdate(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=500)
    description: str | None = None
    status: str | None = None
    severity: str | None = None
    # #139: 調査者はトークンの sub から設定する（本文では受け付けない）。
    root_cause: str | None = None
    corrective_actions: str | None = None
    injured_count: int | None = Field(None, ge=0)
    fatality_count: int | None = Field(None, ge=0)
    is_osha_reportable: bool | None = None
