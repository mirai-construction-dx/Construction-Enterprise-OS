"""通知テンプレート API ルーター"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from ..middleware.auth import (
    MANAGEMENT_ROLES,
    TokenData,
    get_current_user,
    require_any_role,
)
from ..models.base import get_db
from ..schemas import (
    APIResponse,
    MetaInfo,
    NotificationTemplateCreate,
    NotificationTemplateListResponse,
    NotificationTemplateResponse,
    NotificationTemplateUpdate,
)
from ..services.template_service import (
    create_template,
    delete_template,
    get_template_by_code,
    get_template_by_id,
    get_templates,
    update_template,
)

router = APIRouter()


def _api_response(data=None, meta=None, error=None, success=True):
    return APIResponse(success=success, data=data, error=error, meta=meta)


@router.get("")
async def list_templates(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    category: str | None = Query(None),
    token_data: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    templates, pmeta = await get_templates(
        db, page=page, per_page=per_page, category=category
    )
    tlist = [NotificationTemplateResponse.model_validate(t) for t in templates]
    result = NotificationTemplateListResponse(templates=tlist, pagination=pmeta)

    meta = MetaInfo(
        page=pmeta.page,
        per_page=pmeta.per_page,
        total=pmeta.total,
        total_pages=pmeta.total_pages,
    )
    return _api_response(data=result.model_dump(), meta=meta)


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_notification_template(
    data: NotificationTemplateCreate,
    token_data: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    existing = await get_template_by_code(db, data.code)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "DUPLICATE", "message": f"テンプレートコード '{data.code}' は既に存在します。"},
        )

    template = await create_template(db, data)
    return _api_response(
        data=NotificationTemplateResponse.model_validate(template).model_dump()
    )


@router.get("/{code}")
async def get_template(
    code: str,
    token_data: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    template = await get_template_by_code(db, code)
    if not template:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "NOT_FOUND", "message": "テンプレートが見つかりません。"},
        )
    return _api_response(
        data=NotificationTemplateResponse.model_validate(template).model_dump()
    )


@router.put("/{template_id}")
async def update_notification_template(
    template_id: UUID,
    data: NotificationTemplateUpdate,
    token_data: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    template = await get_template_by_id(db, template_id)
    if not template:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "NOT_FOUND", "message": "テンプレートが見つかりません。"},
        )

    updated = await update_template(db, template, data.model_dump(exclude_unset=True))
    return _api_response(
        data=NotificationTemplateResponse.model_validate(updated).model_dump()
    )


@router.delete("/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_notification_template(
    template_id: UUID,
    token_data: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    template = await get_template_by_id(db, template_id)
    if not template:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "NOT_FOUND", "message": "テンプレートが見つかりません。"},
        )
    require_any_role(token_data, MANAGEMENT_ROLES)  # 削除には管理ロールを要求する
    await delete_template(db, template)
    return None
