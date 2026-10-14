"""BIMサービス — CRUD operations and spatial utilities"""

from uuid import UUID

from geoalchemy2 import WKTElement
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import BIMModel
from ..schemas import BIMModelCreate, BIMModelUpdate


# ── Spatial utilities ──────────────────────────────────────────────────────────


def geojson_to_wkt_element(geometry: dict) -> WKTElement | None:
    """Convert GeoJSON geometry dict to WKTElement for PostGIS insert."""
    if not geometry:
        return None
    geom_type = geometry.get("type", "").upper()
    coords = geometry.get("coordinates", [])

    if geom_type == "POINT":
        return WKTElement(f"POINT({coords[0]} {coords[1]})", srid=4326)
    elif geom_type == "POLYGON":
        rings = []
        for ring in coords:
            pts = ", ".join(f"{p[0]} {p[1]}" for p in ring)
            rings.append(f"({pts})")
        return WKTElement(f"POLYGON({', '.join(rings)})", srid=4326)
    elif geom_type == "POINTZ":
        return WKTElement(f"POINT Z({coords[0]} {coords[1]} {coords[2]})", srid=4326)

    return None


# ── BIM Model CRUD ─────────────────────────────────────────────────────────────


async def create_bim_model(
    db: AsyncSession,
    body: BIMModelCreate,
    uploaded_by: UUID,
    organization_id: UUID,
) -> BIMModel:
    model = BIMModel(
        organization_id=organization_id,
        project_id=body.project_id,
        name=body.name,
        description=body.description,
        model_type=body.model_type,
        file_format=body.file_format,
        file_size=body.file_size,
        file_key=body.file_key,
        version=body.version or "v1",
        status=body.status,
        author=body.author,
        software=body.software,
        coordinate_system=body.coordinate_system,
        bounding_box=body.bounding_box,
        discipline=body.discipline,
        lod=body.lod,
        tags=body.tags,
        metadata_=body.metadata,
        uploaded_by=uploaded_by,
    )
    db.add(model)
    await db.flush()
    await db.refresh(model)
    return model


async def list_bim_models(
    db: AsyncSession,
    *,
    page: int = 1,
    per_page: int = 20,
    model_type: str | None = None,
    status: str | None = None,
    project_id: UUID | None = None,
    organization_id: UUID | None = None,
) -> tuple[list[BIMModel], int]:
    query = select(BIMModel)
    count_query = select(func.count(BIMModel.id))

    # None means "all organizations" and is only allowed for cross-org admins
    if organization_id is not None:
        query = query.where(BIMModel.organization_id == organization_id)
        count_query = count_query.where(BIMModel.organization_id == organization_id)

    if model_type:
        query = query.where(BIMModel.model_type == model_type)
        count_query = count_query.where(BIMModel.model_type == model_type)
    if status:
        query = query.where(BIMModel.status == status)
        count_query = count_query.where(BIMModel.status == status)
    if project_id:
        query = query.where(BIMModel.project_id == project_id)
        count_query = count_query.where(BIMModel.project_id == project_id)

    total = (await db.execute(count_query)).scalar() or 0
    query = (
        query.order_by(BIMModel.created_at.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
    )
    models = (await db.execute(query)).scalars().all()
    return list(models), total


async def get_bim_model(
    db: AsyncSession, model_id: UUID, organization_id: UUID | None = None
) -> BIMModel | None:
    stmt = select(BIMModel).where(BIMModel.id == model_id)
    if organization_id is not None:
        stmt = stmt.where(BIMModel.organization_id == organization_id)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def update_bim_model(
    db: AsyncSession,
    model_id: UUID,
    body: BIMModelUpdate,
    organization_id: UUID | None = None,
) -> BIMModel | None:
    model = await get_bim_model(db, model_id, organization_id)
    if not model:
        return None

    update_data = body.model_dump(exclude_unset=True)
    if "metadata" in update_data:
        update_data["metadata_"] = update_data.pop("metadata")

    for key, value in update_data.items():
        setattr(model, key, value)

    await db.flush()
    await db.refresh(model)
    return model
