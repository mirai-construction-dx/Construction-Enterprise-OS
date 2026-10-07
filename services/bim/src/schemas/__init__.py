"""BIM API リクエスト・レスポンス スキーマ"""

from datetime import date, datetime
from typing import Any, Generic, TypeVar
from uuid import UUID

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
# BIM Model
# ============================================
class BIMModelCreate(BaseModel):
    model_config = {"protected_namespaces": ()}

    # organization_id はトークンの org クレームから導出するため、
    # ボディでは任意（不一致はエンドポイントで拒否する）。必須にすると
    # ボディ由来のテナント指定を許容してしまう。
    organization_id: UUID | None = None
    project_id: UUID | None = None
    name: str = Field(max_length=500)
    description: str | None = None
    model_type: str = Field(max_length=50)
    file_format: str = Field(max_length=50)
    file_size: int | None = None
    file_key: str | None = Field(default=None, max_length=1000)
    version: str | None = Field(default=None, max_length=50)
    status: str = Field(default="draft", max_length=20)
    author: str | None = Field(default=None, max_length=255)
    software: str | None = Field(default=None, max_length=255)
    coordinate_system: str | None = Field(default=None, max_length=100)
    bounding_box: dict[str, Any] | None = None
    discipline: str | None = Field(default=None, max_length=100)
    lod: str | None = Field(default=None, max_length=20)
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class BIMModelUpdate(BaseModel):
    model_config = {"protected_namespaces": ()}

    name: str | None = Field(default=None, max_length=500)
    description: str | None = None
    model_type: str | None = Field(default=None, max_length=50)
    file_format: str | None = Field(default=None, max_length=50)
    file_size: int | None = None
    file_key: str | None = Field(default=None, max_length=1000)
    version: str | None = Field(default=None, max_length=50)
    status: str | None = Field(default=None, max_length=20)
    author: str | None = Field(default=None, max_length=255)
    software: str | None = Field(default=None, max_length=255)
    coordinate_system: str | None = Field(default=None, max_length=100)
    bounding_box: dict[str, Any] | None = None
    discipline: str | None = Field(default=None, max_length=100)
    lod: str | None = Field(default=None, max_length=20)
    tags: list[str] | None = None
    metadata: dict[str, Any] | None = None


class BIMModelResponse(BaseModel):
    model_config = {"from_attributes": True, "protected_namespaces": ()}

    id: UUID
    organization_id: UUID
    project_id: UUID | None = None
    name: str
    description: str | None = None
    model_type: str
    file_format: str
    file_size: int | None = None
    file_key: str | None = None
    version: str | None = None
    status: str
    author: str | None = None
    software: str | None = None
    coordinate_system: str | None = None
    bounding_box: dict[str, Any] | None = None
    discipline: str | None = None
    lod: str | None = None
    tags: list[str] | None = None
    # SQLAlchemy の宣言的Baseでは `metadata` が MetaData 予約属性になるため、
    # ORM の実属性名 `metadata_` から読み取る(直すと読み取りAPIが500になる)。
    metadata: dict[str, Any] | None = Field(default=None, validation_alias="metadata_")
    uploaded_by: UUID | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True, "protected_namespaces": ()}


# ============================================
# BIM Element
# ============================================
class BIMElementCreate(BaseModel):
    model_config = {"protected_namespaces": ()}
    model_id: UUID
    element_id: str | None = Field(default=None, max_length=255)
    name: str | None = Field(default=None, max_length=500)
    element_type: str | None = Field(default=None, max_length=100)
    category: str | None = Field(default=None, max_length=100)
    properties: dict[str, Any] = Field(default_factory=dict)
    quantity: float | None = None
    unit: str | None = Field(default=None, max_length=50)
    level_name: str | None = Field(default=None, max_length=100)
    building_name: str | None = Field(default=None, max_length=255)
    bounding_box: dict[str, Any] | None = None


class BIMElementResponse(BaseModel):
    model_config = {"from_attributes": True, "protected_namespaces": ()}

    id: UUID
    model_id: UUID
    element_id: str | None = None
    name: str | None = None
    element_type: str | None = None
    category: str | None = None
    properties: dict[str, Any] | None = None
    quantity: float | None = None
    unit: str | None = None
    level_name: str | None = None
    building_name: str | None = None
    bounding_box: dict[str, Any] | None = None
    created_at: datetime


class BIMElementCategoryGroup(BaseModel):
    category: str
    count: int
    elements: list[BIMElementResponse]


class BIMElementLevelGroup(BaseModel):
    level_name: str
    count: int
    elements: list[BIMElementResponse]


# ============================================
# Point Cloud
# ============================================
class PointCloudCreate(BaseModel):
    # organization_id はトークンの org クレームから導出するため任意。
    organization_id: UUID | None = None
    project_id: UUID | None = None
    name: str = Field(max_length=500)
    description: str | None = None
    capture_method: str | None = Field(default=None, max_length=50)
    capture_date: date | None = None
    point_count: int | None = None
    file_size: int | None = None
    file_format: str | None = Field(default=None, max_length=50)
    file_key: str | None = Field(default=None, max_length=1000)
    coordinate_system: str | None = Field(default=None, max_length=100)
    bounding_box: dict[str, Any] | None = None
    density: float | None = None
    accuracy_mm: float | None = None
    is_colorized: bool = False
    is_classified: bool = False
    version: str | None = Field(default=None, max_length=50)
    source_model_id: UUID | None = None
    source_video_id: str | None = Field(default=None, max_length=255)
    metadata: dict[str, Any] = Field(default_factory=dict)


class PointCloudUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=500)
    description: str | None = None
    capture_method: str | None = Field(default=None, max_length=50)
    capture_date: date | None = None
    point_count: int | None = None
    file_size: int | None = None
    file_format: str | None = Field(default=None, max_length=50)
    file_key: str | None = Field(default=None, max_length=1000)
    coordinate_system: str | None = Field(default=None, max_length=100)
    bounding_box: dict[str, Any] | None = None
    density: float | None = None
    accuracy_mm: float | None = None
    is_colorized: bool | None = None
    is_classified: bool | None = None
    metadata: dict[str, Any] | None = None


class PointCloudResponse(BaseModel):
    id: UUID
    organization_id: UUID
    project_id: UUID | None = None
    name: str
    description: str | None = None
    capture_method: str | None = None
    capture_date: date | None = None
    point_count: int | None = None
    file_size: int | None = None
    file_format: str | None = None
    file_key: str | None = None
    coordinate_system: str | None = None
    bounding_box: dict[str, Any] | None = None
    density: float | None = None
    accuracy_mm: float | None = None
    is_colorized: bool = False
    is_classified: bool = False
    version: str | None = None
    source_model_id: UUID | None = None
    source_video_id: str | None = None
    # SQLAlchemy の宣言的Baseでは `metadata` が MetaData 予約属性になるため、
    # ORM の実属性名 `metadata_` から読み取る(直すと読み取りAPIが500になる)。
    metadata: dict[str, Any] | None = Field(default=None, validation_alias="metadata_")
    uploaded_by: UUID | None = None
    created_at: datetime

    model_config = {"from_attributes": True}
