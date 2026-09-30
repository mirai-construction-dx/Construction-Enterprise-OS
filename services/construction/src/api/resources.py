"""資源管理 API"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from ..middleware.auth import TokenData, get_current_user
from ..middleware.tenant import create_org, scope_org
from ..models.base import get_db
from ..schemas import (
    ResourceAllocationRequest,
    ResourceCostSummary,
    ResourceCreateRequest,
    ResourceListResponse,
    ResourceResponse,
    ResourceUpdateRequest,
)
from ..services import construction_service
from ._tenant_refs import ensure_wbs_in_org

router = APIRouter()


@router.post("/resources", response_model=ResourceResponse, status_code=status.HTTP_201_CREATED)
async def create_resource(
    body: ResourceCreateRequest,
    db: AsyncSession = Depends(get_db),
    user: TokenData = Depends(get_current_user),
):
    org = create_org(user, body.organization_id)
    await ensure_wbs_in_org(db, user, body.wbs_item_id, org)
    data = body.model_dump()
    data["organization_id"] = org
    return await construction_service.create_resource(db, data)


@router.get("/resources", response_model=ResourceListResponse)
async def list_resources(
    organization_id: UUID | None = Query(None),
    project_id: UUID | None = Query(None),
    resource_type: str | None = Query(None),
    status: str | None = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    user: TokenData = Depends(get_current_user),
):
    items, total = await construction_service.list_resources(
        db,
        organization_id=scope_org(user, organization_id),
        project_id=project_id,
        resource_type=resource_type,
        status=status,
        page=page,
        per_page=per_page,
    )
    return ResourceListResponse(items=items, total=total, page=page, per_page=per_page)  # type: ignore[arg-type]


@router.get("/resources/{resource_id}", response_model=ResourceResponse)
async def get_resource(
    resource_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: TokenData = Depends(get_current_user),
):
    resource = await construction_service.get_resource(db, resource_id, scope_org(user))
    if not resource:
        raise HTTPException(status_code=404, detail="リソースが見つかりません")
    return resource


@router.put("/resources/{resource_id}", response_model=ResourceResponse)
async def update_resource(
    resource_id: UUID,
    body: ResourceUpdateRequest,
    db: AsyncSession = Depends(get_db),
    user: TokenData = Depends(get_current_user),
):
    resource = await construction_service.get_resource(db, resource_id, scope_org(user))
    if not resource:
        raise HTTPException(status_code=404, detail="リソースが見つかりません")
    return await construction_service.update_resource(db, resource, body.model_dump(exclude_none=True))


@router.delete("/resources/{resource_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_resource(
    resource_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: TokenData = Depends(get_current_user),
):
    resource = await construction_service.get_resource(db, resource_id, scope_org(user))
    if not resource:
        raise HTTPException(status_code=404, detail="リソースが見つかりません")
    await db.delete(resource)


@router.patch("/resources/{resource_id}/allocation", response_model=ResourceResponse)
async def update_resource_allocation(
    resource_id: UUID,
    body: ResourceAllocationRequest,
    db: AsyncSession = Depends(get_db),
    user: TokenData = Depends(get_current_user),
):
    resource = await construction_service.get_resource(db, resource_id, scope_org(user))
    if not resource:
        raise HTTPException(status_code=404, detail="リソースが見つかりません")
    return await construction_service.update_resource_allocation(db, resource, body.status)


@router.get("/projects/{project_id}/resource-cost-summary", response_model=list[ResourceCostSummary])
async def get_resource_cost_summary(
    project_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: TokenData = Depends(get_current_user),
):
    return await construction_service.get_resource_cost_summary(
        db, project_id, scope_org(user)
    )
