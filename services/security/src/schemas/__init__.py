"""API request/response schemas."""

from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, Field


# ── Common ──

class APIResponse(BaseModel):
    success: bool = True
    data: dict | list | None = None
    error: dict | None = None
    meta: dict | None = None


# ── Incident ──

class IncidentCreate(BaseModel):
    organization_id: UUID
    title: str = Field(min_length=1, max_length=500)
    description: str | None = None
    severity: str = Field(min_length=1, max_length=20)
    incident_type: str = Field(min_length=1, max_length=50)
    source_ip: str | None = None
    affected_systems: list[str] | None = None
    detected_by: str | None = None


class IncidentUpdate_request(BaseModel):
    status: str | None = None
    severity: str | None = None
    assigned_to: UUID | None = None
    resolution: str | None = None


class IncidentUpdateCreate(BaseModel):
    update_type: str = Field(min_length=1, max_length=50)
    content: str = Field(min_length=1)


class IncidentUpdateResponse(BaseModel):
    id: int
    incident_id: UUID
    user_id: UUID
    update_type: str
    content: str
    created_at: datetime

    model_config = {"from_attributes": True}


class IncidentResponse(BaseModel):
    id: UUID
    organization_id: UUID
    title: str
    description: str | None
    severity: str
    incident_type: str
    status: str
    source_ip: str | None
    affected_systems: list[str] | None
    detected_by: str | None
    assigned_to: UUID | None
    resolution: str | None
    resolved_at: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class IncidentDetailResponse(IncidentResponse):
    updates: list[IncidentUpdateResponse] = Field(default_factory=list)


# ── Vulnerability ──

class VulnerabilityCreate(BaseModel):
    organization_id: UUID
    title: str = Field(min_length=1, max_length=500)
    description: str | None = None
    severity: str = Field(min_length=1, max_length=20)
    cve_id: str | None = None
    cvss_score: float | None = None
    affected_component: str | None = None
    remediation: str | None = None


class VulnerabilityUpdate(BaseModel):
    status: str | None = None
    severity: str | None = None
    remediation: str | None = None
    cvss_score: float | None = None


class VulnerabilityResponse(BaseModel):
    id: UUID
    organization_id: UUID
    title: str
    description: str | None
    severity: str
    cve_id: str | None
    cvss_score: float | None
    affected_component: str | None
    status: str
    remediation: str | None
    discovered_at: datetime
    fixed_at: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ── Policy ──

class PolicyCreate(BaseModel):
    organization_id: UUID
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    category: str = Field(min_length=1, max_length=50)
    content: str = Field(min_length=1)
    # `str` で受けると形式検証が入らず、サービス層の date.fromisoformat() で
    # 例外 → 500 になる。境界で date として検証し、不正は 422 で返す。
    effective_date: date | None = None
    review_date: date | None = None


class PolicyUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    category: str | None = None
    content: str | None = None
    status: str | None = None
    effective_date: date | None = None
    review_date: date | None = None


class PolicyResponse(BaseModel):
    id: UUID
    organization_id: UUID
    name: str
    description: str | None
    category: str
    content: str
    version: int
    status: str
    effective_date: datetime | None
    review_date: datetime | None
    approved_by: UUID | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ── Dashboard ──

class SeverityCounts(BaseModel):
    critical: int = 0
    high: int = 0
    medium: int = 0
    low: int = 0
    info: int = 0


class DashboardResponse(BaseModel):
    open_incidents: SeverityCounts
    open_vulnerabilities: SeverityCounts
    recent_incidents: list[IncidentResponse]
    policies_due_review: int
    latest_audit_status: str | None
