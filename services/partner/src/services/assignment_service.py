"""プロジェクトアサイン管理ビジネスロジック"""

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import ProjectAssignment


async def create_assignment(
    db: AsyncSession, organization_id: uuid.UUID, data: dict
) -> ProjectAssignment:
    assignment = ProjectAssignment(
        id=uuid.uuid4(),
        organization_id=organization_id,
        **data,
    )
    db.add(assignment)
    return assignment


async def list_assignments(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID | None = None,
    page: int = 1,
    per_page: int = 20,
    partner_id: uuid.UUID | None = None,
    project_id: uuid.UUID | None = None,
    status: str | None = None,
) -> tuple[list[ProjectAssignment], int]:
    conditions = []
    if organization_id is not None:
        conditions.append(ProjectAssignment.organization_id == organization_id)
    if partner_id:
        conditions.append(ProjectAssignment.partner_id == partner_id)
    if project_id:
        conditions.append(ProjectAssignment.project_id == project_id)
    if status:
        conditions.append(ProjectAssignment.status == status)

    base_query = select(ProjectAssignment)
    if conditions:
        base_query = base_query.where(*conditions)

    count_query = select(func.count()).select_from(ProjectAssignment)
    if conditions:
        count_query = count_query.where(*conditions)
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    offset = (page - 1) * per_page
    query = (
        base_query
        .order_by(ProjectAssignment.created_at.desc())
        .offset(offset)
        .limit(per_page)
    )
    result = await db.execute(query)
    assignments = list(result.scalars().all())
    return assignments, total


async def get_project_assignments(
    db: AsyncSession, project_id: uuid.UUID, page: int = 1, per_page: int = 20
) -> tuple[list[ProjectAssignment], int]:
    return await list_assignments(db, page=page, per_page=per_page, project_id=project_id)
