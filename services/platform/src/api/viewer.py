"""Viewer 設定・シーン管理 API"""

from math import ceil
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..middleware.auth import TokenData, get_current_user
from ..middleware.tenant import create_org, scope_org
from ..models import ViewerConfig, ViewerScene
from ..models.base import get_db
from ..schemas import (
    APIResponse,
    MetaInfo,
    ViewerConfigCreate,
    ViewerConfigResponse,
    ViewerSceneCreate,
    ViewerSceneResponse,
    ViewerConfigWithScenesResponse,
)

router = APIRouter()


def _api_response(data=None, meta=None, error=None, success=True):
    return APIResponse(success=success, data=data, error=error, meta=meta)


def _config_to_response(c: ViewerConfig) -> dict:
    return ViewerConfigResponse.model_validate(c).model_dump(mode="json")


def _scene_to_response(s: ViewerScene) -> dict:
    return ViewerSceneResponse.model_validate(s).model_dump(mode="json")


def _config_not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={"code": "NOT_FOUND", "message": "ビューア設定が見つかりません。"},
    )


def _config_by_id(config_id: UUID, organization_id: UUID | None):
    """Select a viewer config; ``organization_id=None`` is reserved for cross-org admins."""
    stmt = select(ViewerConfig).where(ViewerConfig.id == config_id)
    if organization_id is not None:
        stmt = stmt.where(ViewerConfig.organization_id == organization_id)
    return stmt


# === Viewer Configs ===

@router.post("/configs")
async def create_viewer_config(
    body: ViewerConfigCreate,
    token_data: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = create_org(token_data, body.organization_id)
    config = ViewerConfig(
        organization_id=org_id,
        project_id=body.project_id,
        name=body.name,
        viewer_type=body.viewer_type,
        model_ids=body.model_ids,
        layer_ids=body.layer_ids,
        camera_state=body.camera_state,
        visible_categories=body.visible_categories,
        clipping_planes=body.clipping_planes,
        theme=body.theme,
        created_by=UUID(token_data.sub),
    )
    db.add(config)
    await db.flush()
    await db.refresh(config)
    return _api_response(data=_config_to_response(config))


@router.get("/configs")
async def list_viewer_configs(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    viewer_type: str | None = Query(None),
    project_id: UUID | None = Query(None),
    organization_id: UUID | None = Query(None),
    token_data: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    query = select(ViewerConfig)
    count_query = select(func.count(ViewerConfig.id))

    org_id = scope_org(token_data, organization_id)
    if org_id is not None:
        query = query.where(ViewerConfig.organization_id == org_id)
        count_query = count_query.where(ViewerConfig.organization_id == org_id)

    if viewer_type:
        query = query.where(ViewerConfig.viewer_type == viewer_type)
        count_query = count_query.where(ViewerConfig.viewer_type == viewer_type)
    if project_id:
        query = query.where(ViewerConfig.project_id == project_id)
        count_query = count_query.where(ViewerConfig.project_id == project_id)

    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0
    total_pages = ceil(total / per_page) if total > 0 else 0

    query = query.order_by(ViewerConfig.created_at.desc())
    query = query.offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(query)
    configs = result.scalars().all()

    meta = MetaInfo(page=page, per_page=per_page, total=total, total_pages=total_pages)
    return _api_response(
        data=[_config_to_response(c) for c in configs], meta=meta
    )


@router.get("/configs/{config_id}")
async def get_viewer_config(
    config_id: UUID,
    token_data: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        _config_by_id(config_id, scope_org(token_data)).options(
            selectinload(ViewerConfig.scenes)
        )
    )
    config = result.scalar_one_or_none()
    if not config:
        raise _config_not_found()
    data = ViewerConfigWithScenesResponse.model_validate(config).model_dump(mode="json")
    return _api_response(data=data)


@router.delete("/configs/{config_id}")
async def delete_viewer_config(
    config_id: UUID,
    token_data: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(_config_by_id(config_id, scope_org(token_data)))
    config = result.scalar_one_or_none()
    if not config:
        raise _config_not_found()
    await db.delete(config)
    await db.flush()
    return _api_response(data={"deleted": True})


# === Viewer Scenes ===

@router.post("/configs/{config_id}/scenes")
async def create_viewer_scene(
    config_id: UUID,
    body: ViewerSceneCreate,
    token_data: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(_config_by_id(config_id, scope_org(token_data)))
    config = result.scalar_one_or_none()
    if not config:
        raise _config_not_found()

    scene = ViewerScene(
        config_id=config_id,
        name=body.name,
        description=body.description,
        camera_state=body.camera_state,
        annotations=body.annotations,
        measurements=body.measurements,
        created_by=UUID(token_data.sub),
    )
    db.add(scene)
    await db.flush()
    await db.refresh(scene)
    return _api_response(data=_scene_to_response(scene))


@router.get("/scenes/{scene_id}")
async def get_viewer_scene(
    scene_id: UUID,
    token_data: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # A scene has no organization of its own: it is scoped through its parent config.
    stmt = select(ViewerScene).where(ViewerScene.id == scene_id)
    org_id = scope_org(token_data)
    if org_id is not None:
        stmt = stmt.join(ViewerConfig, ViewerScene.config_id == ViewerConfig.id).where(
            ViewerConfig.organization_id == org_id
        )
    result = await db.execute(stmt)
    scene = result.scalar_one_or_none()
    if not scene:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "NOT_FOUND", "message": "シーンが見つかりません。"},
        )
    return _api_response(data=_scene_to_response(scene))
