"""災害危険区域 (Hazard Zones) API"""

from math import ceil
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..middleware.auth import (
    TokenData,
    get_current_user,
    require_organization_id,
)
from ..models import ConstructionSite, HazardZone
from ..models.base import get_db
from ..schemas import (
    APIResponse,
    GeoJSONFeature,
    GeoJSONFeatureCollection,
    HazardZoneCreate,
    HazardZoneUpdate,
    MetaInfo,
)
from ..services.geo_service import geojson_to_wkt, wkb_to_geojson_geometry

router = APIRouter()


def _api_response(data=None, meta=None, error=None, success=True):
    return APIResponse(success=success, data=data, error=error, meta=meta)


def _zone_to_geojson(zone: HazardZone) -> GeoJSONFeature:
    area_geom = None
    if zone.zone_area is not None:
        bin_data = _to_wkb_bytes(zone.zone_area)
        area_geom = wkb_to_geojson_geometry(bin_data)

    return GeoJSONFeature(
        type="Feature",
        geometry=area_geom,
        properties={
            "id": str(zone.id),
            "organization_id": str(zone.organization_id),
            "name": zone.name,
            "hazard_type": zone.hazard_type,
            "risk_level": zone.risk_level,
            "description": zone.description,
            "valid_from": zone.valid_from.isoformat() if zone.valid_from else None,
            "valid_to": zone.valid_to.isoformat() if zone.valid_to else None,
            "metadata": zone.metadata_,
            "created_at": zone.created_at.isoformat() if zone.created_at else None,
        },
    )


def _to_wkb_bytes(value):
    if value is None:
        return None
    if isinstance(value, bytes):
        return value
    if isinstance(value, str):
        return value
    if hasattr(value, "data"):
        return bytes(value.data) if value.data else None
    return str(value)


@router.post("")
async def create_hazard_zone(
    body: HazardZoneCreate,
    token_data: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = require_organization_id(token_data)
    if body.organization_id != org_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "ORG_MISMATCH",
                "message": "トークンの組織とボディの組織が一致しません。",
            },
        )
    area_wkt = geojson_to_wkt(body.zone_area)

    zone = HazardZone(
        organization_id=org_id,
        name=body.name,
        hazard_type=body.hazard_type,
        zone_area=area_wkt,
        risk_level=body.risk_level,
        description=body.description,
        valid_from=body.valid_from,
        valid_to=body.valid_to,
        metadata_=body.metadata,
    )
    db.add(zone)
    await db.flush()
    await db.refresh(zone)
    return _api_response(data=_zone_to_geojson(zone).model_dump())


@router.get("")
async def list_hazard_zones(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    hazard_type: str | None = Query(None),
    risk_level: str | None = Query(None),
    token_data: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = require_organization_id(token_data)
    query = select(HazardZone).where(HazardZone.organization_id == org_id)
    count_query = select(func.count(HazardZone.id)).where(
        HazardZone.organization_id == org_id
    )

    if hazard_type:
        query = query.where(HazardZone.hazard_type == hazard_type)
        count_query = count_query.where(HazardZone.hazard_type == hazard_type)
    if risk_level:
        query = query.where(HazardZone.risk_level == risk_level)
        count_query = count_query.where(HazardZone.risk_level == risk_level)

    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0
    total_pages = ceil(total / per_page) if total > 0 else 0

    query = query.order_by(HazardZone.created_at.desc())
    query = query.offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(query)
    zones = result.scalars().all()

    features = [_zone_to_geojson(z) for z in zones]
    collection = GeoJSONFeatureCollection(type="FeatureCollection", features=features)

    meta = MetaInfo(page=page, per_page=per_page, total=total, total_pages=total_pages)
    return _api_response(data=collection.model_dump(), meta=meta)


@router.get("/intersecting/{site_id}")
async def hazard_zones_intersecting_site(
    site_id: UUID,
    token_data: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """指定工事現場と重複する危険区域を検索 (ST_Intersects)"""
    org_id = require_organization_id(token_data)
    site_result = await db.execute(
        select(ConstructionSite).where(
            ConstructionSite.id == site_id,
            ConstructionSite.organization_id == org_id,
        )
    )
    site = site_result.scalar_one_or_none()
    if not site:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "NOT_FOUND", "message": "工事現場が見つかりません。"},
        )

    if site.work_area is None:
        return _api_response(
            data=GeoJSONFeatureCollection(
                type="FeatureCollection", features=[]
            ).model_dump()
        )

    # 危険度の高い順（critical → high → medium → low）に並べる。
    # 文字列降順では severity 順にならないため、CASE で数値化してソートする。
    severity_order = case(
        (HazardZone.risk_level == "critical", 0),
        (HazardZone.risk_level == "high", 1),
        (HazardZone.risk_level == "medium", 2),
        (HazardZone.risk_level == "low", 3),
        else_=4,
    )
    query = select(HazardZone).where(
        HazardZone.organization_id == org_id,
        func.ST_Intersects(
            HazardZone.zone_area,
            site.work_area,
        ),
    )
    query = query.order_by(severity_order)
    result = await db.execute(query)
    zones = result.scalars().all()

    features = [_zone_to_geojson(z) for z in zones]
    collection = GeoJSONFeatureCollection(type="FeatureCollection", features=features)
    return _api_response(data=collection.model_dump())


@router.get("/{zone_id}")
async def get_hazard_zone(
    zone_id: UUID,
    token_data: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = require_organization_id(token_data)
    result = await db.execute(
        select(HazardZone).where(
            HazardZone.id == zone_id,
            HazardZone.organization_id == org_id,
        )
    )
    zone = result.scalar_one_or_none()
    if not zone or zone.organization_id != org_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "NOT_FOUND", "message": "危険区域が見つかりません。"},
        )
    return _api_response(data=_zone_to_geojson(zone).model_dump())


@router.put("/{zone_id}")
async def update_hazard_zone(
    zone_id: UUID,
    body: HazardZoneUpdate,
    token_data: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = require_organization_id(token_data)
    result = await db.execute(
        select(HazardZone).where(
            HazardZone.id == zone_id,
            HazardZone.organization_id == org_id,
        )
    )
    zone = result.scalar_one_or_none()
    if not zone or zone.organization_id != org_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "NOT_FOUND", "message": "危険区域が見つかりません。"},
        )

    update_data = body.model_dump(exclude_unset=True)
    if "zone_area" in update_data and update_data["zone_area"]:
        update_data["zone_area"] = geojson_to_wkt(update_data["zone_area"])
    if "metadata" in update_data:
        update_data["metadata_"] = update_data.pop("metadata")

    for key, value in update_data.items():
        setattr(zone, key, value)

    await db.flush()
    await db.refresh(zone)
    return _api_response(data=_zone_to_geojson(zone).model_dump())


@router.delete("/{zone_id}")
async def delete_hazard_zone(
    zone_id: UUID,
    token_data: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = require_organization_id(token_data)
    result = await db.execute(
        select(HazardZone).where(
            HazardZone.id == zone_id,
            HazardZone.organization_id == org_id,
        )
    )
    zone = result.scalar_one_or_none()
    if not zone or zone.organization_id != org_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "NOT_FOUND", "message": "危険区域が見つかりません。"},
        )
    await db.delete(zone)
    await db.flush()
    return _api_response(data={"deleted": True})
