"""WBS (Work Breakdown Structure) API"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from ..middleware.auth import (
    MANAGEMENT_ROLES,
    TokenData,
    get_current_user,
    require_any_role,
)
from ..middleware.tenant import create_org, scope_org
from ..models.base import get_db
from ..schemas import (
    WBSProgressUpdateRequest,
    WBSCreateRequest,
    WBSListResponse,
    WBSResponse,
    WBSTreeResponse,
    WBSUpdateRequest,
)
from ..services import construction_service
from ._tenant_refs import ensure_wbs_in_org

router = APIRouter()


@router.post("/wbs", response_model=WBSResponse, status_code=status.HTTP_201_CREATED)
async def create_wbs(
    body: WBSCreateRequest,
    db: AsyncSession = Depends(get_db),
    user: TokenData = Depends(get_current_user),
):
    org = create_org(user, body.organization_id)
    await ensure_wbs_in_org(db, user, body.parent_id, org)
    data = body.model_dump()
    data["organization_id"] = org
    return await construction_service.create_wbs(db, data)


@router.get("/wbs", response_model=WBSListResponse)
async def list_wbs(
    organization_id: UUID | None = Query(None),
    project_id: UUID | None = Query(None),
    status: str | None = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    user: TokenData = Depends(get_current_user),
):
    items, total = await construction_service.list_wbs(
        db,
        organization_id=scope_org(user, organization_id),
        project_id=project_id,
        status=status,
        page=page,
        per_page=per_page,
    )
    return WBSListResponse(items=items, total=total, page=page, per_page=per_page)  # type: ignore[arg-type]


# 定義順マッチのため、固定パス /wbs/tree は /wbs/{wbs_id} より前に置く（422 回避）
@router.get("/wbs/tree", response_model=list[WBSTreeResponse])
async def get_wbs_tree(
    project_id: UUID = Query(...),
    db: AsyncSession = Depends(get_db),
    user: TokenData = Depends(get_current_user),
):
    return await construction_service.build_wbs_tree(
        db, project_id=project_id, organization_id=scope_org(user)
    )


@router.get("/wbs/{wbs_id}", response_model=WBSResponse)
async def get_wbs(
    wbs_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: TokenData = Depends(get_current_user),
):
    wbs = await construction_service.get_wbs(db, wbs_id, scope_org(user))
    if not wbs:
        raise HTTPException(status_code=404, detail="WBSアイテムが見つかりません")
    return wbs


@router.put("/wbs/{wbs_id}", response_model=WBSResponse)
async def update_wbs(
    wbs_id: UUID,
    body: WBSUpdateRequest,
    db: AsyncSession = Depends(get_db),
    user: TokenData = Depends(get_current_user),
):
    wbs = await construction_service.get_wbs(db, wbs_id, scope_org(user))
    if not wbs:
        raise HTTPException(status_code=404, detail="WBSアイテムが見つかりません")
    return await construction_service.update_wbs(
        db, wbs, body.model_dump(exclude_none=True)
    )


@router.delete("/wbs/{wbs_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_wbs(
    wbs_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: TokenData = Depends(get_current_user),
):
    wbs = await construction_service.get_wbs(db, wbs_id, scope_org(user))
    if not wbs:
        raise HTTPException(status_code=404, detail="WBSアイテムが見つかりません")
    require_any_role(user, MANAGEMENT_ROLES)  # 削除には管理ロールを要求する
    await db.delete(wbs)


@router.get("/wbs/{wbs_id}/children", response_model=list[WBSResponse])
async def get_wbs_children(
    wbs_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: TokenData = Depends(get_current_user),
):
    wbs = await construction_service.get_wbs(db, wbs_id, scope_org(user))
    if not wbs:
        raise HTTPException(status_code=404, detail="WBSアイテムが見つかりません")
    return await construction_service.get_wbs_children(
        db, wbs_id, wbs.organization_id
    )


@router.patch("/wbs/{wbs_id}/progress", response_model=WBSResponse)
async def update_wbs_progress(
    wbs_id: UUID,
    body: WBSProgressUpdateRequest,
    db: AsyncSession = Depends(get_db),
    user: TokenData = Depends(get_current_user),
):
    wbs = await construction_service.get_wbs(db, wbs_id, scope_org(user))
    if not wbs:
        raise HTTPException(status_code=404, detail="WBSアイテムが見つかりません")
    return await construction_service.update_wbs_progress(
        db, wbs, body.model_dump(exclude_none=True)
    )
