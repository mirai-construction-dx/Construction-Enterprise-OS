"""GeoJSON / API リクエスト・レスポンス スキーマ"""

from datetime import date, datetime
from typing import Any, Generic, TypeVar
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

T = TypeVar("T")

# ============================================
# GeoJSON 座標検証（WGS84 / EPSG:4326 前提）
# ============================================
_SUPPORTED_GEOMETRY_TYPES = {"Point", "Polygon", "LineString", "MultiPoint"}
_LON_MIN, _LON_MAX = -180.0, 180.0
_LAT_MIN, _LAT_MAX = -90.0, 90.0


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _validate_position(pos: Any) -> None:
    """GeoJSON 座標要素 [経度, 緯度] を検証する（WGS84 範囲）。"""
    if not isinstance(pos, (list, tuple)) or len(pos) < 2:
        raise ValueError("GeoJSON 座標は [経度, 緯度] の2要素が必要です。")
    lng, lat = pos[0], pos[1]
    if not _is_number(lng):
        raise ValueError("経度は数値である必要があります。")
    if not _is_number(lat):
        raise ValueError("緯度は数値である必要があります。")
    if lng < _LON_MIN or lng > _LON_MAX:
        raise ValueError("経度は -180 から 180 の範囲である必要があります。")
    if lat < _LAT_MIN or lat > _LAT_MAX:
        raise ValueError("緯度は -90 から 90 の範囲である必要があります。")


def _validate_geometry_coordinates(geom_type: str, coordinates: Any) -> None:
    """既知のジオメトリ型について座標範囲を検証する。"""
    if geom_type not in _SUPPORTED_GEOMETRY_TYPES:
        # 未知の型は geojson_to_wkt 側で拒否する（スキーマでは通過させる）。
        return
    if geom_type == "Point":
        _validate_position(coordinates)
    elif geom_type in ("LineString", "MultiPoint"):
        if not isinstance(coordinates, (list, tuple)):
            raise ValueError("LineString/MultiPoint の coordinates は座標列である必要があります。")
        for pos in coordinates:
            _validate_position(pos)
    elif geom_type == "Polygon":
        if not isinstance(coordinates, (list, tuple)):
            raise ValueError("Polygon の coordinates はリングの列である必要があります。")
        for ring in coordinates:
            if not isinstance(ring, (list, tuple)):
                raise ValueError("Polygon のリングは座標列である必要があります。")
            for pos in ring:
                _validate_position(pos)


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
# GeoJSON Geometry
# ============================================
class GeoJSONGeometry(BaseModel):
    type: str  # Point / Polygon / LineString / MultiPoint
    coordinates: Any  # 型はジオメトリによって異なる

    @model_validator(mode="after")
    def _validate_coordinates(self) -> "GeoJSONGeometry":
        _validate_geometry_coordinates(self.type, self.coordinates)
        return self


# ============================================
# GeoJSON Feature
# ============================================
class GeoJSONFeature(BaseModel):
    type: str = "Feature"
    geometry: GeoJSONGeometry | None = None
    properties: dict[str, Any] = Field(default_factory=dict)


class GeoJSONFeatureCollection(BaseModel):
    type: str = "FeatureCollection"
    features: list[GeoJSONFeature] = Field(default_factory=list)


# ============================================
# 工事現場 (Construction Site)
# ============================================
class SiteCreate(BaseModel):
    organization_id: UUID
    project_id: UUID | None = None
    name: str = Field(max_length=500)
    site_code: str | None = Field(default=None, max_length=100)
    location: GeoJSONGeometry  # Point
    work_area: GeoJSONGeometry | None = None  # Polygon
    site_type: str | None = Field(default=None, max_length=50)
    status: str = Field(default="active", max_length=20)
    address: str | None = Field(default=None, max_length=500)
    elevation: float | None = None
    area_sqm: float | None = None
    start_date: date | None = None
    end_date: date | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class SiteUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=500)
    site_code: str | None = Field(default=None, max_length=100)
    location: GeoJSONGeometry | None = None
    work_area: GeoJSONGeometry | None = None
    site_type: str | None = Field(default=None, max_length=50)
    status: str | None = Field(default=None, max_length=20)
    address: str | None = Field(default=None, max_length=500)
    elevation: float | None = None
    area_sqm: float | None = None
    start_date: date | None = None
    end_date: date | None = None
    metadata: dict[str, Any] | None = None


class SiteResponse(BaseModel):
    id: UUID
    organization_id: UUID
    project_id: UUID | None = None
    name: str
    site_code: str | None = None
    site_type: str | None = None
    status: str
    address: str | None = None
    elevation: float | None = None
    area_sqm: float | None = None
    start_date: date | None = None
    end_date: date | None = None
    # SQLAlchemy の宣言的Baseでは `metadata` が MetaData 予約属性になるため、
    # ORM の実属性名 `metadata_` から読み取る(直すと読み取りAPIが500になる)。
    metadata: dict[str, Any] | None = Field(default=None, validation_alias="metadata_")
    created_by: UUID | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class SiteGeoJSONResponse(GeoJSONFeature):
    pass


# ============================================
# インフラ設備 (Infrastructure)
# ============================================
class InfrastructureCreate(BaseModel):
    organization_id: UUID
    name: str = Field(max_length=500)
    infra_type: str = Field(max_length=50)
    location: GeoJSONGeometry  # Point
    line_geom: GeoJSONGeometry | None = None  # LineString
    status: str = Field(default="active", max_length=20)
    metadata: dict[str, Any] = Field(default_factory=dict)


class InfrastructureUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=500)
    infra_type: str | None = Field(default=None, max_length=50)
    location: GeoJSONGeometry | None = None
    line_geom: GeoJSONGeometry | None = None
    status: str | None = Field(default=None, max_length=20)
    metadata: dict[str, Any] | None = None


class InfrastructureResponse(BaseModel):
    id: UUID
    organization_id: UUID
    name: str
    infra_type: str
    status: str
    # SQLAlchemy の宣言的Baseでは `metadata` が MetaData 予約属性になるため、
    # ORM の実属性名 `metadata_` から読み取る(直すと読み取りAPIが500になる)。
    metadata: dict[str, Any] | None = Field(default=None, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class InfrastructureGeoJSONResponse(GeoJSONFeature):
    pass


# ============================================
# 災害危険区域 (Hazard Zone)
# ============================================
class HazardZoneCreate(BaseModel):
    organization_id: UUID
    name: str = Field(max_length=500)
    hazard_type: str = Field(max_length=50)
    zone_area: GeoJSONGeometry  # Polygon
    risk_level: str = Field(default="medium", max_length=20)
    description: str | None = None
    valid_from: date | None = None
    valid_to: date | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class HazardZoneUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=500)
    hazard_type: str | None = Field(default=None, max_length=50)
    zone_area: GeoJSONGeometry | None = None
    risk_level: str | None = Field(default=None, max_length=20)
    description: str | None = None
    valid_from: date | None = None
    valid_to: date | None = None
    metadata: dict[str, Any] | None = None


class HazardZoneResponse(BaseModel):
    id: UUID
    organization_id: UUID
    name: str
    hazard_type: str
    risk_level: str
    description: str | None = None
    valid_from: date | None = None
    valid_to: date | None = None
    # SQLAlchemy の宣言的Baseでは `metadata` が MetaData 予約属性になるため、
    # ORM の実属性名 `metadata_` から読み取る(直すと読み取りAPIが500になる)。
    metadata: dict[str, Any] | None = Field(default=None, validation_alias="metadata_")
    created_at: datetime

    model_config = {"from_attributes": True}


class HazardZoneGeoJSONResponse(GeoJSONFeature):
    pass


# ============================================
# Nearby Search
# ============================================
class NearbyQuery(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)
    radius_m: float = Field(gt=0, default=1000)


class BoundingBoxQuery(BaseModel):
    min_lat: float = Field(ge=-90, le=90)
    min_lng: float = Field(ge=-180, le=180)
    max_lat: float = Field(ge=-90, le=90)
    max_lng: float = Field(ge=-180, le=180)
