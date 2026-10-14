"""Prompt テンプレート管理エンドポイント"""

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from ..middleware.auth import (
    MANAGEMENT_ROLES,
    TokenData,
    get_current_user,
    require_any_role,
)
from ..middleware.tenant import scope_org, token_org
from ..models.base import get_db
from ..schemas import (
    MetaInfo,
    PromptTemplateCreate,
    PromptTemplateListResponse,
    PromptTemplateResponse,
    PromptTemplateUpdate,
)
from ..services.prompt_service import PromptService

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/prompts")
async def create_prompt(
    body: PromptTemplateCreate,
    token_data: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = token_org(token_data)
    template = await PromptService.create_template(
        db=db,
        organization_id=org_id,
        data=body.model_dump(),
        created_by=UUID(token_data.sub),
    )
    return {
        "success": True,
        "data": PromptTemplateResponse.model_validate(template).model_dump(),
    }


@router.get("/prompts")
async def list_prompts(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    category: str | None = Query(None),
    is_active: bool | None = Query(None),
    token_data: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = scope_org(token_data)
    templates, pagination = await PromptService.list_templates(
        db=db,
        organization_id=org_id,
        page=page,
        per_page=per_page,
        category=category,
        is_active=is_active,
    )

    template_list = [PromptTemplateResponse.model_validate(t) for t in templates]
    result = PromptTemplateListResponse(
        templates=template_list,
        pagination=pagination,  # type: ignore[arg-type]
    )

    meta = MetaInfo(
        page=pagination["page"],
        per_page=pagination["per_page"],
        total=pagination["total"],
        total_pages=pagination["total_pages"],
    )
    return {
        "success": True,
        "data": result.model_dump(),
        "meta": meta.model_dump(),
    }


@router.get("/prompts/{template_id}")
async def get_prompt(
    template_id: UUID,
    token_data: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = scope_org(token_data)
    template = await PromptService.get_template(db, template_id, org_id)
    if not template:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "NOT_FOUND",
                "message": "プロンプトテンプレートが見つかりません。",
            },
        )
    return {
        "success": True,
        "data": PromptTemplateResponse.model_validate(template).model_dump(),
    }


@router.put("/prompts/{template_id}")
async def update_prompt(
    template_id: UUID,
    body: PromptTemplateUpdate,
    token_data: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = scope_org(token_data)
    template = await PromptService.update_template(
        db=db,
        template_id=template_id,
        organization_id=org_id,
        data=body.model_dump(exclude_none=True),
    )
    if not template:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "NOT_FOUND",
                "message": "プロンプトテンプレートが見つかりません。",
            },
        )
    return {
        "success": True,
        "data": PromptTemplateResponse.model_validate(template).model_dump(),
    }


@router.delete("/prompts/{template_id}")
async def delete_prompt(
    template_id: UUID,
    token_data: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = scope_org(token_data)
    require_any_role(token_data, MANAGEMENT_ROLES)
    deleted = await PromptService.delete_template(db, template_id, org_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "NOT_FOUND",
                "message": "プロンプトテンプレートが見つかりません。",
            },
        )
    return {"success": True, "data": None}
