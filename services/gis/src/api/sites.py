"""工事現場 (Construction Sites) API"""

from math import ceil
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from geoalchemy2 import Geography
from sqlalchemy import cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..middleware.auth import (
    MANAGEMENT_ROLES,
    TokenData,
    get_current_user,
    require_any_role,
)
from ..middleware.tenant import create_org, scope_org
from ..models import ConstructionSite
from ..models.base import get_db
from ..schemas import (
    APIResponse,
    GeoJSONFeature,
    GeoJSONFeatureCollection,
    MetaInfo,
    SiteCreate,
    SiteUpdate,
)
from ..services.geo_service import geojson_to_wkt, wkb_to_geojson_geometry

router = APIRouter()


def _api_response(data=None, meta=None, error=None, success=True):
    return APIResponse(success=success, data=data, error=error, meta=meta)


def _site_to_geojson(site: ConstructionSite) -> GeoJSONFeature:
    location_geom = None
    if site.location is not None:
        bin_data = _to_wkb_bytes(site.location)
        location_geom = wkb_to_geojson_geometry(bin_data)

    work_area_geom = None
    if site.work_area is not None:
        bin_data = _to_wkb_bytes(site.work_area)
        work_area_geom = wkb_to_geojson_geometry(bin_data)

    return GeoJSONFeature(
        type="Feature",
        geometry=location_geom,
        properties={
            "id": str(site.id),
            "organization_id": str(site.organization_id),
            "project_id": str(site.project_id) if site.project_id else None,
            "name": site.name,
            "site_code": site.site_code,
            "site_type": site.site_type,
            "status": site.status,
            "address": site.address,
            "elevation": site.elevation,
            "area_sqm": site.area_sqm,
            "start_date": site.start_date.isoformat() if site.start_date else None,
            "end_date": site.end_date.isoformat() if site.end_date else None,
            "work_area": work_area_geom.model_dump() if work_area_geom else None,
            "metadata": site.metadata_,
            "created_by": str(site.created_by) if site.created_by else None,
            "created_at": site.created_at.isoformat() if site.created_at else None,
            "updated_at": site.updated_at.isoformat() if site.updated_at else None,
        },
    )


def _to_wkb_bytes(value):
    """GeoAlchemy2のジオメトリ値をWKBバイト列またはWKT文字列として取り出す"""
    if value is None:
        return None
    if isinstance(value, bytes):
        return value
    if isinstance(value, str):
        return value
    if hasattr(value, "data"):
        return bytes(value.data) if value.data else None
    return str(value)


async def get_scoped_site(
    db: AsyncSession, site_id: UUID, organization_id: UUID | None
) -> ConstructionSite | None:
    """Look up a site by id within the caller's organization (``None`` = admin, no filter).

    A site of another organization is indistinguishable from a missing one (404).
    """
    stmt = select(ConstructionSite).where(ConstructionSite.id == site_id)
    if organization_id is not None:
        stmt = stmt.where(ConstructionSite.organization_id == organization_id)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


@router.post("")
async def create_site(
    body: SiteCreate,
    token_data: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = create_org(token_data, body.organization_id)
    location_wkt = geojson_to_wkt(body.location)
    work_area_wkt = geojson_to_wkt(body.work_area) if body.work_area else None

    site = ConstructionSite(
        organization_id=org_id,
        project_id=body.project_id,
        name=body.name,
        site_code=body.site_code,
        location=location_wkt,
        work_area=work_area_wkt,
        site_type=body.site_type,
        status=body.status,
        address=body.address,
        elevation=body.elevation,
        area_sqm=body.area_sqm,
        start_date=body.start_date,
        end_date=body.end_date,
        metadata_=body.metadata,
        created_by=UUID(token_data.sub),
    )
    db.add(site)
    await db.flush()
    await db.refresh(site)
    return _api_response(data=_site_to_geojson(site).model_dump())


@router.get("")
async def list_sites(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    site_type: str | None = Query(None),
    status_filter: str | None = Query(None, alias="status"),
    organization_id: UUID | None = Query(None),
    token_data: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org = scope_org(token_data, organization_id)
    query = select(ConstructionSite)
    count_query = select(func.count(ConstructionSite.id))

    if org is not None:
        query = query.where(ConstructionSite.organization_id == org)
        count_query = count_query.where(ConstructionSite.organization_id == org)

    if site_type:
        query = query.where(ConstructionSite.site_type == site_type)
        count_query = count_query.where(ConstructionSite.site_type == site_type)
    if status_filter:
        query = query.where(ConstructionSite.status == status_filter)
        count_query = count_query.where(ConstructionSite.status == status_filter)

    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0
    total_pages = ceil(total / per_page) if total > 0 else 0

    query = query.order_by(ConstructionSite.created_at.desc())
    query = query.offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(query)
    sites = result.scalars().all()

    features = [_site_to_geojson(s) for s in sites]
    collection = GeoJSONFeatureCollection(type="FeatureCollection", features=features)

    meta = MetaInfo(page=page, per_page=per_page, total=total, total_pages=total_pages)
    return _api_response(data=collection.model_dump(), meta=meta)


@router.get("/nearby")
async def find_nearby_sites(
    lat: float = Query(ge=-90, le=90),
    lng: float = Query(ge=-180, le=180),
    radius_m: float = Query(gt=0, default=1000),
    organization_id: UUID | None = Query(None),
    token_data: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """指定座標から半径radius_m以内の現場を検索 (ST_DWithin / geography)"""
    org = scope_org(token_data, organization_id)
    point_wkt = f"SRID=4326;POINT({lng} {lat})"
    query = select(ConstructionSite).where(
        func.ST_DWithin(
            cast(ConstructionSite.location, Geography(srid=4326)),
            cast(func.ST_GeomFromText(point_wkt), Geography(srid=4326)),
            radius_m,
        )
    )
    if org is not None:
        query = query.where(ConstructionSite.organization_id == org)
    query = query.order_by(ConstructionSite.created_at.desc())
    result = await db.execute(query)
    sites = result.scalars().all()

    features = [_site_to_geojson(s) for s in sites]
    collection = GeoJSONFeatureCollection(type="FeatureCollection", features=features)
    return _api_response(data=collection.model_dump())


@router.get("/in-area")
async def find_sites_in_area(
    min_lat: float = Query(ge=-90, le=90),
    min_lng: float = Query(ge=-180, le=180),
    max_lat: float = Query(ge=-90, le=90),
    max_lng: float = Query(ge=-180, le=180),
    organization_id: UUID | None = Query(None),
    token_data: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """バウンディングボックス内の現場を検索 (ST_Intersects)"""
    if min_lat > max_lat or min_lng > max_lng:
        # 逆転した bbox は自己交差 POLYGON となり検索結果が不定になるため拒否する。
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "code": "INVALID_BBOX",
                "message": "min は max 以下である必要があります。",
            },
        )
    org = scope_org(token_data, organization_id)
    bbox_wkt = (
        f"SRID=4326;POLYGON(({min_lng} {min_lat}, {max_lng} {min_lat}, "
        f"{max_lng} {max_lat}, {min_lng} {max_lat}, {min_lng} {min_lat}))"
    )
    query = select(ConstructionSite).where(
        func.ST_Intersects(
            ConstructionSite.location,
            func.ST_GeomFromText(bbox_wkt),
        )
    )
    if org is not None:
        query = query.where(ConstructionSite.organization_id == org)
    query = query.order_by(ConstructionSite.created_at.desc())
    result = await db.execute(query)
    sites = result.scalars().all()

    features = [_site_to_geojson(s) for s in sites]
    collection = GeoJSONFeatureCollection(type="FeatureCollection", features=features)
    return _api_response(data=collection.model_dump())


@router.get("/{site_id}")
async def get_site(
    site_id: UUID,
    token_data: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    site = await get_scoped_site(db, site_id, scope_org(token_data))
    if not site:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "NOT_FOUND", "message": "工事現場が見つかりません。"},
        )
    return _api_response(data=_site_to_geojson(site).model_dump())


@router.put("/{site_id}")
async def update_site(
    site_id: UUID,
    body: SiteUpdate,
    token_data: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    site = await get_scoped_site(db, site_id, scope_org(token_data))
    if not site:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "NOT_FOUND", "message": "工事現場が見つかりません。"},
        )

    update_data = body.model_dump(exclude_unset=True)
    if "location" in update_data:
        update_data["location"] = geojson_to_wkt(update_data["location"])
    if "work_area" in update_data and update_data["work_area"]:
        update_data["work_area"] = geojson_to_wkt(update_data["work_area"])
    if update_data.get("work_area") is None and "work_area" in update_data:
        update_data["work_area"] = None
    if "metadata" in update_data:
        update_data["metadata_"] = update_data.pop("metadata")

    for key, value in update_data.items():
        setattr(site, key, value)

    await db.flush()
    await db.refresh(site)
    return _api_response(data=_site_to_geojson(site).model_dump())


@router.delete("/{site_id}")
async def delete_site(
    site_id: UUID,
    token_data: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    site = await get_scoped_site(db, site_id, scope_org(token_data))
    if not site:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "NOT_FOUND", "message": "工事現場が見つかりません。"},
        )
    require_any_role(token_data, MANAGEMENT_ROLES)
    await db.delete(site)
    await db.flush()
    return _api_response(data={"deleted": True})
