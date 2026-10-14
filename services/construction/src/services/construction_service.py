"""施工管理サービス"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import WBSItem, Resource, Schedule, MethodStatement


# ============================================
# WBS
# ============================================
async def create_wbs(db: AsyncSession, data: dict) -> WBSItem:
    wbs = WBSItem(**data)
    db.add(wbs)
    await db.flush()
    await db.refresh(wbs)
    return wbs


async def get_wbs(
    db: AsyncSession, wbs_id: uuid.UUID, organization_id: uuid.UUID | None = None
) -> WBSItem | None:
    wbs = await db.get(WBSItem, wbs_id)
    if (
        wbs is not None
        and organization_id is not None
        and wbs.organization_id != organization_id
    ):
        return None
    return wbs


async def list_wbs(
    db: AsyncSession,
    organization_id: uuid.UUID | None = None,
    project_id: uuid.UUID | None = None,
    status: str | None = None,
    page: int = 1,
    per_page: int = 20,
) -> tuple[list[WBSItem], int]:
    query = select(WBSItem)
    count_query = select(func.count(WBSItem.id))

    if organization_id is not None:
        query = query.where(WBSItem.organization_id == organization_id)
        count_query = count_query.where(WBSItem.organization_id == organization_id)
    if project_id:
        query = query.where(WBSItem.project_id == project_id)
        count_query = count_query.where(WBSItem.project_id == project_id)
    if status:
        query = query.where(WBSItem.status == status)
        count_query = count_query.where(WBSItem.status == status)

    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    query = query.order_by(WBSItem.wbs_code)
    query = query.offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(query)
    items = list(result.scalars().all())

    return items, total


async def update_wbs(db: AsyncSession, wbs: WBSItem, data: dict) -> WBSItem:
    for key, value in data.items():
        if value is not None:
            setattr(wbs, key, value)
    wbs.updated_at = datetime.now(timezone.utc)
    await db.flush()
    await db.refresh(wbs)
    return wbs


async def get_wbs_children(
    db: AsyncSession, parent_id: uuid.UUID, organization_id: uuid.UUID | None = None
) -> list[WBSItem]:
    query = select(WBSItem).where(WBSItem.parent_id == parent_id)
    if organization_id is not None:
        query = query.where(WBSItem.organization_id == organization_id)
    result = await db.execute(query.order_by(WBSItem.wbs_code))
    # SQL の WHERE に加え、ORM が返した行に対しても防御的に同一組織のみへ絞る
    # （モック等で WHERE が無視される状況でも他テナントを混入させない）。
    children = list(result.scalars().all())
    if organization_id is not None:
        children = [c for c in children if c.organization_id == organization_id]
    return children


async def build_wbs_tree(
    db: AsyncSession,
    root_id: uuid.UUID | None = None,
    project_id: uuid.UUID | None = None,
    organization_id: uuid.UUID | None = None,
) -> list[dict]:
    if root_id:
        query = select(WBSItem).where(WBSItem.id == root_id)
    elif project_id:
        query = select(WBSItem).where(
            WBSItem.project_id == project_id, WBSItem.parent_id.is_(None)
        )
    else:
        query = select(WBSItem).where(WBSItem.parent_id.is_(None))

    if organization_id is not None:
        query = query.where(WBSItem.organization_id == organization_id)

    result = await db.execute(query.order_by(WBSItem.wbs_code))
    roots = list(result.scalars().all())

    trees = []
    for root in roots:
        tree = await _build_subtree(db, root)
        trees.append(tree)
    return trees


async def _build_subtree(db: AsyncSession, node: WBSItem) -> dict:
    # Children must belong to the same organization as their (already scoped) parent.
    children = await get_wbs_children(db, node.id, node.organization_id)
    child_trees = []
    for child in children:
        child_trees.append(await _build_subtree(db, child))
    return {
        **{c.name: getattr(node, c.name) for c in node.__table__.columns},
        "children": child_trees,
    }


async def update_wbs_progress(db: AsyncSession, wbs: WBSItem, data: dict) -> WBSItem:
    if "progress_percent" in data:
        wbs.progress_percent = float(data["progress_percent"])
    if "status" in data:
        wbs.status = data["status"]
    wbs.updated_at = datetime.now(timezone.utc)
    await db.flush()
    await db.refresh(wbs)
    return wbs


# ============================================
# Resource
# ============================================
async def create_resource(db: AsyncSession, data: dict) -> Resource:
    resource = Resource(**data)
    _calculate_resource_total_cost(resource)
    db.add(resource)
    await db.flush()
    await db.refresh(resource)
    return resource


async def get_resource(
    db: AsyncSession, resource_id: uuid.UUID, organization_id: uuid.UUID | None = None
) -> Resource | None:
    obj = await db.get(Resource, resource_id)
    if (
        obj is not None
        and organization_id is not None
        and obj.organization_id != organization_id
    ):
        return None
    return obj


async def list_resources(
    db: AsyncSession,
    organization_id: uuid.UUID | None = None,
    project_id: uuid.UUID | None = None,
    resource_type: str | None = None,
    status: str | None = None,
    page: int = 1,
    per_page: int = 20,
) -> tuple[list[Resource], int]:
    query = select(Resource)
    count_query = select(func.count(Resource.id))

    if organization_id is not None:
        query = query.where(Resource.organization_id == organization_id)
        count_query = count_query.where(Resource.organization_id == organization_id)
    if project_id:
        query = query.where(Resource.project_id == project_id)
        count_query = count_query.where(Resource.project_id == project_id)
    if resource_type:
        query = query.where(Resource.resource_type == resource_type)
        count_query = count_query.where(Resource.resource_type == resource_type)
    if status:
        query = query.where(Resource.status == status)
        count_query = count_query.where(Resource.status == status)

    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    query = query.order_by(Resource.name)
    query = query.offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(query)
    items = list(result.scalars().all())

    return items, total


async def update_resource(db: AsyncSession, resource: Resource, data: dict) -> Resource:
    for key, value in data.items():
        if value is not None:
            setattr(resource, key, value)
    _calculate_resource_total_cost(resource)
    await db.flush()
    await db.refresh(resource)
    return resource


async def update_resource_allocation(
    db: AsyncSession, resource: Resource, status: str
) -> Resource:
    resource.status = status
    await db.flush()
    await db.refresh(resource)
    return resource


async def get_resource_cost_summary(
    db: AsyncSession, project_id: uuid.UUID, organization_id: uuid.UUID | None = None
) -> list[dict]:
    query = (
        select(
            Resource.resource_type,
            func.count(Resource.id).label("count"),
            func.coalesce(
                func.sum(Resource.planned_quantity * Resource.unit_cost), 0
            ).label("total_planned"),
            func.coalesce(
                func.sum(Resource.actual_quantity * Resource.unit_cost), 0
            ).label("total_actual"),
        )
        .where(Resource.project_id == project_id)
        .group_by(Resource.resource_type)
    )
    if organization_id is not None:
        query = query.where(Resource.organization_id == organization_id)
    result = await db.execute(query)
    return [
        {
            "resource_type": row.resource_type,
            "count": row.count,
            "total_planned_cost": float(row.total_planned),
            "total_actual_cost": float(row.total_actual),
        }
        for row in result.all()
    ]


def _calculate_resource_total_cost(resource: Resource) -> None:
    if resource.actual_quantity is not None:
        qty = float(resource.actual_quantity)
    elif resource.planned_quantity is not None:
        qty = float(resource.planned_quantity)
    else:
        qty = 0.0
    cost = float(resource.unit_cost or 0)
    resource.total_cost = qty * cost


# ============================================
# Schedule
# ============================================
async def create_schedule(db: AsyncSession, data: dict) -> Schedule:
    schedule = Schedule(**data)
    db.add(schedule)
    await db.flush()
    await db.refresh(schedule)
    return schedule


async def get_schedule(
    db: AsyncSession, schedule_id: uuid.UUID, organization_id: uuid.UUID | None = None
) -> Schedule | None:
    obj = await db.get(Schedule, schedule_id)
    if (
        obj is not None
        and organization_id is not None
        and obj.organization_id != organization_id
    ):
        return None
    return obj


async def list_schedules(
    db: AsyncSession,
    organization_id: uuid.UUID | None = None,
    project_id: uuid.UUID | None = None,
    schedule_type: str | None = None,
    status: str | None = None,
    page: int = 1,
    per_page: int = 20,
) -> tuple[list[Schedule], int]:
    query = select(Schedule)
    count_query = select(func.count(Schedule.id))

    if organization_id is not None:
        query = query.where(Schedule.organization_id == organization_id)
        count_query = count_query.where(Schedule.organization_id == organization_id)
    if project_id:
        query = query.where(Schedule.project_id == project_id)
        count_query = count_query.where(Schedule.project_id == project_id)
    if schedule_type:
        query = query.where(Schedule.schedule_type == schedule_type)
        count_query = count_query.where(Schedule.schedule_type == schedule_type)
    if status:
        query = query.where(Schedule.status == status)
        count_query = count_query.where(Schedule.status == status)

    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    query = query.order_by(Schedule.planned_start)
    query = query.offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(query)
    items = list(result.scalars().all())

    return items, total


async def update_schedule(db: AsyncSession, schedule: Schedule, data: dict) -> Schedule:
    for key, value in data.items():
        if value is not None:
            setattr(schedule, key, value)
    schedule.updated_at = datetime.now(timezone.utc)
    await db.flush()
    await db.refresh(schedule)
    return schedule


async def get_critical_path(
    db: AsyncSession, project_id: uuid.UUID, organization_id: uuid.UUID | None = None
) -> list[Schedule]:
    query = select(Schedule).where(
        Schedule.project_id == project_id, Schedule.critical_path.is_(True)
    )
    if organization_id is not None:
        query = query.where(Schedule.organization_id == organization_id)
    result = await db.execute(query.order_by(Schedule.planned_start))
    return list(result.scalars().all())


async def get_gantt_data(
    db: AsyncSession, project_id: uuid.UUID, organization_id: uuid.UUID | None = None
) -> list[dict]:
    query = select(Schedule).where(Schedule.project_id == project_id)
    if organization_id is not None:
        query = query.where(Schedule.organization_id == organization_id)
    result = await db.execute(query.order_by(Schedule.planned_start))
    schedules = list(result.scalars().all())
    return [
        {
            "schedule_id": s.id,
            "name": s.name,
            "wbs_item_id": s.wbs_item_id,
            "planned_start": s.planned_start,
            "planned_end": s.planned_end,
            "actual_start": s.actual_start,
            "actual_end": s.actual_end,
            "critical_path": s.critical_path,
            "progress_percent": float(s.progress_percent),
            "status": s.status,
        }
        for s in schedules
    ]


# ============================================
# Method Statement
# ============================================
async def create_method(db: AsyncSession, data: dict) -> MethodStatement:
    method = MethodStatement(**data)
    db.add(method)
    await db.flush()
    await db.refresh(method)
    return method


async def get_method(
    db: AsyncSession, method_id: uuid.UUID, organization_id: uuid.UUID | None = None
) -> MethodStatement | None:
    obj = await db.get(MethodStatement, method_id)
    if (
        obj is not None
        and organization_id is not None
        and obj.organization_id != organization_id
    ):
        return None
    return obj


async def list_methods(
    db: AsyncSession,
    organization_id: uuid.UUID | None = None,
    project_id: uuid.UUID | None = None,
    document_type: str | None = None,
    status: str | None = None,
    page: int = 1,
    per_page: int = 20,
) -> tuple[list[MethodStatement], int]:
    query = select(MethodStatement)
    count_query = select(func.count(MethodStatement.id))

    if organization_id is not None:
        query = query.where(MethodStatement.organization_id == organization_id)
        count_query = count_query.where(
            MethodStatement.organization_id == organization_id
        )
    if project_id:
        query = query.where(MethodStatement.project_id == project_id)
        count_query = count_query.where(MethodStatement.project_id == project_id)
    if document_type:
        query = query.where(MethodStatement.document_type == document_type)
        count_query = count_query.where(MethodStatement.document_type == document_type)
    if status:
        query = query.where(MethodStatement.status == status)
        count_query = count_query.where(MethodStatement.status == status)

    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    query = query.order_by(MethodStatement.created_at.desc())
    query = query.offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(query)
    items = list(result.scalars().all())

    return items, total


async def update_method(
    db: AsyncSession, method: MethodStatement, data: dict
) -> MethodStatement:
    for key, value in data.items():
        if value is not None:
            setattr(method, key, value)
    method.updated_at = datetime.now(timezone.utc)
    await db.flush()
    await db.refresh(method)
    return method


async def submit_for_approval(
    db: AsyncSession, method: MethodStatement
) -> MethodStatement:
    if method.status != "draft":
        raise ValueError("only draft documents can be submitted for approval")
    method.status = "review"
    method.updated_at = datetime.now(timezone.utc)
    await db.flush()
    await db.refresh(method)
    return method


async def approve_method(
    db: AsyncSession, method: MethodStatement, approved_by: uuid.UUID
) -> MethodStatement:
    if method.status not in ("review",):
        raise ValueError("only documents in review can be approved")
    method.status = "approved"
    method.approved_by = approved_by
    method.approved_at = datetime.now(timezone.utc)
    method.updated_at = datetime.now(timezone.utc)
    await db.flush()
    await db.refresh(method)
    return method


async def reject_method(db: AsyncSession, method: MethodStatement) -> MethodStatement:
    if method.status not in ("review",):
        raise ValueError("only documents in review can be rejected")
    method.status = "draft"
    method.updated_at = datetime.now(timezone.utc)
    await db.flush()
    await db.refresh(method)
    return method
