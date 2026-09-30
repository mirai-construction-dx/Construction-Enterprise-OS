"""災害危険区域 (Hazard Zones) API"""

from math import ceil
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..middleware.auth import TokenData, get_current_user
from ..middleware.tenant import create_org, scope_org
from ..models import HazardZone
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
from .sites import get_scoped_site

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
    area_wkt = geojson_to_wkt(body.zone_area)

    zone = HazardZone(
        organization_id=create_org(token_data, body.organization_id),
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
    organization_id: UUID | None = Query(None),
    token_data: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org = scope_org(token_data, organization_id)
    query = select(HazardZone)
    count_query = select(func.count(HazardZone.id))

    if org is not None:
        query = query.where(HazardZone.organization_id == org)
        count_query = count_query.where(HazardZone.organization_id == org)

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
    organization_id: UUID | None = Query(None),
    token_data: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """指定工事現場と重複する危険区域を検索 (ST_Intersects)"""
    # The parent site lookup and the child spatial query use the same organization filter.
    org = scope_org(token_data, organization_id)
    site = await get_scoped_site(db, site_id, org)
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

    query = select(HazardZone).where(
        func.ST_Intersects(
            HazardZone.zone_area,
            site.work_area,
        )
    )
    if org is not None:
        query = query.where(HazardZone.organization_id == org)
    query = query.order_by(HazardZone.risk_level.desc())
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
    stmt = select(HazardZone).where(HazardZone.id == zone_id)
    org = scope_org(token_data)
    if org is not None:
        stmt = stmt.where(HazardZone.organization_id == org)
    result = await db.execute(stmt)
    zone = result.scalar_one_or_none()
    if not zone:
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
    stmt = select(HazardZone).where(HazardZone.id == zone_id)
    org = scope_org(token_data)
    if org is not None:
        stmt = stmt.where(HazardZone.organization_id == org)
    result = await db.execute(stmt)
    zone = result.scalar_one_or_none()
    if not zone:
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
    stmt = select(HazardZone).where(HazardZone.id == zone_id)
    org = scope_org(token_data)
    if org is not None:
        stmt = stmt.where(HazardZone.organization_id == org)
    result = await db.execute(stmt)
    zone = result.scalar_one_or_none()
    if not zone:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "NOT_FOUND", "message": "危険区域が見つかりません。"},
        )
    await db.delete(zone)
    await db.flush()
    return _api_response(data={"deleted": True})
