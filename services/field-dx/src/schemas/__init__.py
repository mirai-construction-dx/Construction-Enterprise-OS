"""API リクエスト/レスポンス スキーマ"""

from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


# ============================================
# 作業日報 (DailyReport)
# ============================================
class DailyReportCreateRequest(BaseModel):
    organization_id: UUID
    project_id: UUID
    site_id: UUID | None = None
    report_date: date
    weather: str | None = None
    temperature: float | None = None
    work_description: str
    work_results: str | None = None
    worker_count: int | None = None
    equipment_used: list[str] | None = None
    materials_used: list[str] | None = None
    issues: str | None = None
    next_plan: str | None = None


class DailyReportUpdateRequest(BaseModel):
    report_date: date | None = None
    weather: str | None = None
    temperature: float | None = None
    work_description: str | None = None
    work_results: str | None = None
    worker_count: int | None = None
    equipment_used: list[str] | None = None
    materials_used: list[str] | None = None
    issues: str | None = None
    next_plan: str | None = None


class DailyReportResponse(BaseModel):
    id: UUID
    organization_id: UUID
    project_id: UUID
    site_id: UUID | None
    report_date: date
    weather: str | None
    temperature: float | None
    work_description: str
    work_results: str | None
    worker_count: int | None
    equipment_used: list[str] | None
    materials_used: list[str] | None
    issues: str | None
    next_plan: str | None
    status: str
    created_by: UUID
    approved_by: UUID | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class DailyReportListResponse(BaseModel):
    items: list[DailyReportResponse]
    total: int
    page: int
    per_page: int


# ============================================
# 出来形・進捗記録 (ProgressRecord)
# ============================================
class ProgressCreateRequest(BaseModel):
    organization_id: UUID
    project_id: UUID
    activity_name: str = Field(max_length=500)
    activity_code: str | None = None
    planned_quantity: float | None = None
    actual_quantity: float | None = None
    unit: str | None = None
    planned_start: date | None = None
    planned_end: date | None = None
    actual_start: date | None = None
    actual_end: date | None = None
    progress_percent: float | None = Field(default=None, ge=0, le=100)
    status: str = "pending"
    notes: str | None = None


class ProgressUpdateRequest(BaseModel):
    activity_name: str | None = None
    activity_code: str | None = None
    planned_quantity: float | None = None
    actual_quantity: float | None = None
    unit: str | None = None
    planned_start: date | None = None
    planned_end: date | None = None
    actual_start: date | None = None
    actual_end: date | None = None
    progress_percent: float | None = Field(default=None, ge=0, le=100)
    status: str | None = None
    notes: str | None = None


class ProgressResponse(BaseModel):
    id: UUID
    organization_id: UUID
    project_id: UUID
    activity_name: str
    activity_code: str | None
    planned_quantity: float | None
    actual_quantity: float | None
    unit: str | None
    planned_start: date | None
    planned_end: date | None
    actual_start: date | None
    actual_end: date | None
    progress_percent: float | None
    status: str
    notes: str | None
    recorded_by: UUID
    recorded_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ProgressListResponse(BaseModel):
    items: list[ProgressResponse]
    total: int
    page: int
    per_page: int


class ProgressSummaryResponse(BaseModel):
    project_id: UUID
    total_activities: int
    completed: int
    in_progress: int
    delayed: int
    pending: int
    overall_progress: float


# ============================================
# 品質管理 (QualityCheck)
# ============================================
class QualityCheckCreateRequest(BaseModel):
    organization_id: UUID
    project_id: UUID
    check_item: str = Field(max_length=500)
    check_type: str = Field(max_length=50)
    standard_value: str | None = None
    measured_value: str | None = None
    is_conforming: bool | None = None
    check_date: date
    location: str | None = None
    notes: str | None = None
    status: str = "pending"

    @model_validator(mode="after")
    def _require_measurement_for_conformance(self) -> "QualityCheckCreateRequest":
        # 合否の根拠（測定値）なしに「適合/不適合」を申告する入力を拒否する。
        if self.is_conforming is not None and not self.measured_value:
            raise ValueError("測定値なしでは合否を確定できません")
        return self


class QualityCheckUpdateRequest(BaseModel):
    standard_value: str | None = None
    measured_value: str | None = None
    is_conforming: bool | None = None
    check_date: date | None = None
    location: str | None = None
    notes: str | None = None
    status: str | None = None


class QualityCheckResponse(BaseModel):
    id: UUID
    organization_id: UUID
    project_id: UUID
    check_item: str
    check_type: str
    standard_value: str | None
    measured_value: str | None
    is_conforming: bool | None
    check_date: date
    location: str | None
    inspector_id: UUID
    notes: str | None
    status: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class QualityCheckListResponse(BaseModel):
    items: list[QualityCheckResponse]
    total: int
    page: int
    per_page: int


class QualityStatsResponse(BaseModel):
    project_id: UUID
    total_checks: int
    passed: int
    failed: int
    pending: int
    action_required: int
    conformance_rate: float
