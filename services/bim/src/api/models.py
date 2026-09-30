"""BIMモデル管理 API"""

from math import ceil
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from ..middleware.auth import TokenData, get_current_user
from ..middleware.tenant import create_org, scope_org
from ..models.base import get_db
from ..schemas import (
    APIResponse,
    BIMModelCreate,
    BIMModelResponse,
    BIMModelUpdate,
    MetaInfo,
)
from ..services.bim_service import (
    create_bim_model,
    delete_bim_model,
    get_bim_model,
    list_bim_models,
    update_bim_model,
)

router = APIRouter()


def _api_response(data=None, meta=None, error=None, success=True):
    return APIResponse(success=success, data=data, error=error, meta=meta)


def _model_to_response(m) -> dict:
    return BIMModelResponse.model_validate(m).model_dump(mode="json")


@router.post("")
async def create_model(
    body: BIMModelCreate,
    token_data: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org = create_org(token_data, body.organization_id)
    model = await create_bim_model(db, body, UUID(token_data.sub), org)
    return _api_response(data=_model_to_response(model))


@router.get("")
async def list_models(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    model_type: str | None = Query(None),
    status_filter: str | None = Query(None, alias="status"),
    project_id: UUID | None = Query(None),
    organization_id: UUID | None = Query(None),
    token_data: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org = scope_org(token_data, organization_id)
    models, total = await list_bim_models(
        db,
        page=page,
        per_page=per_page,
        model_type=model_type,
        status=status_filter,
        project_id=project_id,
        organization_id=org,
    )
    total_pages = ceil(total / per_page) if total > 0 else 0
    meta = MetaInfo(page=page, per_page=per_page, total=total, total_pages=total_pages)
    return _api_response(data=[_model_to_response(m) for m in models], meta=meta)


@router.get("/{model_id}")
async def get_model(
    model_id: UUID,
    token_data: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    model = await get_bim_model(db, model_id, scope_org(token_data))
    if not model:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "NOT_FOUND", "message": "BIMモデルが見つかりません。"},
        )
    return _api_response(data=_model_to_response(model))


@router.put("/{model_id}")
async def update_model(
    model_id: UUID,
    body: BIMModelUpdate,
    token_data: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    model = await update_bim_model(db, model_id, body, scope_org(token_data))
    if not model:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "NOT_FOUND", "message": "BIMモデルが見つかりません。"},
        )
    return _api_response(data=_model_to_response(model))


@router.delete("/{model_id}")
async def delete_model(
    model_id: UUID,
    token_data: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    deleted = await delete_bim_model(db, model_id, scope_org(token_data))
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "NOT_FOUND", "message": "BIMモデルが見つかりません。"},
        )
    return _api_response(data={"deleted": True})
