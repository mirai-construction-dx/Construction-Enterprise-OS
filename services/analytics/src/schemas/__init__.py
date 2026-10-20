"""API リクエスト/レスポンス スキーマ"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


# ============================================
# データソース (DataSource)
# ============================================
class DataSourceCreateRequest(BaseModel):
    organization_id: UUID
    name: str = Field(max_length=255)
    source_type: str = Field(max_length=50)
    connection_config: dict = Field(default_factory=dict)
    status: str = "active"
    description: str | None = None
    created_by: UUID | None = None


class DataSourceUpdateRequest(BaseModel):
    name: str | None = None
    connection_config: dict | None = None
    status: str | None = None
    description: str | None = None


class DataSourceResponse(BaseModel):
    """データソース応答。

    `connection_config` は認証情報を含み得るため **write-only** とし、応答には含めない
    （#138）。受け取った値は保存にのみ使い、クライアントへ返さない。
    """

    id: UUID
    organization_id: UUID
    name: str
    source_type: str
    status: str
    description: str | None
    created_by: UUID | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class DataSourceListResponse(BaseModel):
    items: list[DataSourceResponse]
    total: int
    page: int
    per_page: int


class DataSourceTestResponse(BaseModel):
    success: bool
    message: str
    source_type: str


# ============================================
# パイプライン (DataPipeline)
# ============================================
class PipelineCreateRequest(BaseModel):
    organization_id: UUID
    name: str = Field(max_length=255)
    source_id: UUID | None = None
    target_id: UUID | None = None
    transform_logic: dict = Field(default_factory=dict)
    schedule: str | None = None
    status: str = "draft"
    created_by: UUID | None = None


class PipelineUpdateRequest(BaseModel):
    name: str | None = None
    source_id: UUID | None = None
    target_id: UUID | None = None
    transform_logic: dict | None = None
    schedule: str | None = None
    status: str | None = None


class PipelineResponse(BaseModel):
    id: UUID
    organization_id: UUID
    name: str
    source_id: UUID | None
    target_id: UUID | None
    transform_logic: dict
    schedule: str | None
    status: str
    last_run: datetime | None
    created_by: UUID | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class PipelineListResponse(BaseModel):
    items: list[PipelineResponse]
    total: int
    page: int
    per_page: int


class PipelineRunResponse(BaseModel):
    pipeline_id: UUID
    status: str
    started_at: datetime
    finished_at: datetime | None
    message: str


# ============================================
# レポート (AnalyticsReport)
# ============================================
class ReportCreateRequest(BaseModel):
    organization_id: UUID
    name: str = Field(max_length=255)
    report_type: str = Field(max_length=50)
    query_config: dict = Field(default_factory=dict)
    schedule: str | None = None
    status: str = "draft"
    created_by: UUID | None = None


class ReportUpdateRequest(BaseModel):
    name: str | None = None
    query_config: dict | None = None
    schedule: str | None = None
    status: str | None = None


class ReportResponse(BaseModel):
    id: UUID
    organization_id: UUID
    name: str
    report_type: str
    query_config: dict
    schedule: str | None
    status: str
    created_by: UUID | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ReportListResponse(BaseModel):
    items: list[ReportResponse]
    total: int
    page: int
    per_page: int


class ReportGenerateResponse(BaseModel):
    report_id: UUID
    generated_at: datetime
    data: list[dict]
    summary: dict


class ReportExportResponse(BaseModel):
    report_id: UUID
    format: str
    generated_at: datetime
    content: str
