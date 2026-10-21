"""インフラ設備 (Infrastructure) API"""

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
from ..models import ConstructionSite, Infrastructure
from ..models.base import get_db
from ..schemas import (
    APIResponse,
    GeoJSONFeature,
    GeoJSONFeatureCollection,
    InfrastructureCreate,
    InfrastructureUpdate,
)
from ..services.geo_service import geojson_to_wkt, wkb_to_geojson_geometry
from .sites import get_scoped_site

router = APIRouter()


def _api_response(data=None, meta=None, error=None, success=True):
    return APIResponse(success=success, data=data, error=error, meta=meta)


def _infra_to_geojson(infra: Infrastructure) -> GeoJSONFeature:
    location_geom = None
    if infra.location is not None:
        bin_data = _to_wkb_bytes(infra.location)
        location_geom = wkb_to_geojson_geometry(bin_data)

    line_geom = None
    if infra.line_geom is not None:
        bin_data = _to_wkb_bytes(infra.line_geom)
        line_geom = wkb_to_geojson_geometry(bin_data)

    geometry = line_geom if line_geom is not None else location_geom

    return GeoJSONFeature(
        type="Feature",
        geometry=geometry,
        properties={
            "id": str(infra.id),
            "organization_id": str(infra.organization_id),
            "name": infra.name,
            "infra_type": infra.infra_type,
            "status": infra.status,
            "metadata": infra.metadata_,
            "created_at": infra.created_at.isoformat() if infra.created_at else None,
            "updated_at": infra.updated_at.isoformat() if infra.updated_at else None,
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
async def create_infrastructure(
    body: InfrastructureCreate,
    token_data: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    location_wkt = geojson_to_wkt(body.location)
    line_wkt = geojson_to_wkt(body.line_geom) if body.line_geom else None

    infra = Infrastructure(
        organization_id=create_org(token_data, body.organization_id),
        name=body.name,
        infra_type=body.infra_type,
        location=location_wkt,
        line_geom=line_wkt,
        status=body.status,
        metadata_=body.metadata,
    )
    db.add(infra)
    await db.flush()
    await db.refresh(infra)
    return _api_response(data=_infra_to_geojson(infra).model_dump())


@router.get("")
async def list_infrastructure(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    infra_type: str | None = Query(None),
    status_filter: str | None = Query(None, alias="status"),
    organization_id: UUID | None = Query(None),
    token_data: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from math import ceil

    from ..schemas import MetaInfo

    org = scope_org(token_data, organization_id)
    query = select(Infrastructure)
    count_query = select(func.count(Infrastructure.id))

    if org is not None:
        query = query.where(Infrastructure.organization_id == org)
        count_query = count_query.where(Infrastructure.organization_id == org)

    if infra_type:
        query = query.where(Infrastructure.infra_type == infra_type)
        count_query = count_query.where(Infrastructure.infra_type == infra_type)
    if status_filter:
        query = query.where(Infrastructure.status == status_filter)
        count_query = count_query.where(Infrastructure.status == status_filter)

    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0
    total_pages = ceil(total / per_page) if total > 0 else 0

    query = query.order_by(Infrastructure.created_at.desc())
    query = query.offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(query)
    infras = result.scalars().all()

    features = [_infra_to_geojson(i) for i in infras]
    collection = GeoJSONFeatureCollection(type="FeatureCollection", features=features)

    meta = MetaInfo(page=page, per_page=per_page, total=total, total_pages=total_pages)
    return _api_response(data=collection.model_dump(), meta=meta)


@router.get("/near-site/{site_id}")
async def infrastructure_near_site(
    site_id: UUID,
    radius_m: float = Query(gt=0, default=1000),
    organization_id: UUID | None = Query(None),
    token_data: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """指定工事現場の近くにあるインフラ設備を検索 (ST_DWithin / geography)"""
    # The parent site lookup and the child spatial query use the same organization filter.
    org = scope_org(token_data, organization_id)
    site = await get_scoped_site(db, site_id, org)
    if not site:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "NOT_FOUND", "message": "工事現場が見つかりません。"},
        )

    # geometry 同士の ST_DWithin は radius_m を度として解釈するため、
    # 両オペランドを geography にキャストしてメートル評価にする（#133）。
    # site.location は ORM インスタンスの値（WKBElement）でバインド型が曖昧になるため、
    # 列式（geometry, SRID=4326）を副問い合わせで参照して確実にキャストする。
    site_location = (
        select(ConstructionSite.location)
        .where(ConstructionSite.id == site.id)
        .scalar_subquery()
    )
    query = select(Infrastructure).where(
        func.ST_DWithin(
            cast(Infrastructure.location, Geography(srid=4326)),
            cast(site_location, Geography(srid=4326)),
            radius_m,
        )
    )
    if org is not None:
        query = query.where(Infrastructure.organization_id == org)
    query = query.order_by(Infrastructure.created_at.desc())
    result = await db.execute(query)
    infras = result.scalars().all()

    features = [_infra_to_geojson(i) for i in infras]
    collection = GeoJSONFeatureCollection(type="FeatureCollection", features=features)
    return _api_response(data=collection.model_dump())


@router.get("/{infra_id}")
async def get_infrastructure(
    infra_id: UUID,
    token_data: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Infrastructure).where(Infrastructure.id == infra_id)
    org = scope_org(token_data)
    if org is not None:
        stmt = stmt.where(Infrastructure.organization_id == org)
    result = await db.execute(stmt)
    infra = result.scalar_one_or_none()
    if not infra:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "NOT_FOUND", "message": "インフラ設備が見つかりません。"},
        )
    return _api_response(data=_infra_to_geojson(infra).model_dump())


@router.put("/{infra_id}")
async def update_infrastructure(
    infra_id: UUID,
    body: InfrastructureUpdate,
    token_data: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Infrastructure).where(Infrastructure.id == infra_id)
    org = scope_org(token_data)
    if org is not None:
        stmt = stmt.where(Infrastructure.organization_id == org)
    result = await db.execute(stmt)
    infra = result.scalar_one_or_none()
    if not infra:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "NOT_FOUND", "message": "インフラ設備が見つかりません。"},
        )

    update_data = body.model_dump(exclude_unset=True)
    if "location" in update_data:
        # location は必須属性。null での消去は許可せず 422 にする
        # （修正前は geojson_to_wkt(None) の AttributeError が 500 になっていた）。
        if body.location is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={
                    "code": "INVALID_LOCATION",
                    "message": "location は null にできません。",
                },
            )
        # model_dump() は GeoJSONGeometry を dict にするため、WKT 化には検証済みの
        # モデル（body.location）を使う（dict を渡すと AttributeError で 500 になる）。
        update_data["location"] = geojson_to_wkt(body.location)
    if "line_geom" in update_data:
        update_data["line_geom"] = (
            geojson_to_wkt(body.line_geom) if body.line_geom is not None else None
        )
    if "metadata" in update_data:
        update_data["metadata_"] = update_data.pop("metadata")

    for key, value in update_data.items():
        setattr(infra, key, value)

    await db.flush()
    await db.refresh(infra)
    return _api_response(data=_infra_to_geojson(infra).model_dump())


@router.delete("/{infra_id}")
async def delete_infrastructure(
    infra_id: UUID,
    token_data: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Infrastructure).where(Infrastructure.id == infra_id)
    org = scope_org(token_data)
    if org is not None:
        stmt = stmt.where(Infrastructure.organization_id == org)
    result = await db.execute(stmt)
    infra = result.scalar_one_or_none()
    if not infra:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "NOT_FOUND", "message": "インフラ設備が見つかりません。"},
        )
    require_any_role(token_data, MANAGEMENT_ROLES)
    await db.delete(infra)
    await db.flush()
    return _api_response(data={"deleted": True})
