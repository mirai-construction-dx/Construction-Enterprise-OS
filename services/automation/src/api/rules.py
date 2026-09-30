"""自動化ルール管理エンドポイント"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from ..middleware.auth import TokenData, get_current_user
from ..middleware.tenant import create_org, scope_org
from ..models.base import get_db
from ..schemas import (
    APIResponse,
    RuleCreateRequest,
    RuleListResponse,
    RuleResponse,
    RuleTestRequest,
    RuleTestResponse,
    RuleUpdateRequest,
)
from ..services.automation_service import (
    create_rule,
    delete_rule,
    disable_rule,
    enable_rule,
    get_rule_by_id,
    get_rules_paginated,
    test_rule_execution,
    update_rule,
)

router = APIRouter()


def _rule_to_response(rule) -> RuleResponse:
    return RuleResponse.model_validate(rule)


@router.post("", response_model=APIResponse[RuleResponse], status_code=status.HTTP_201_CREATED)
async def create_rule_endpoint(
    request: Request,
    body: RuleCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    rule = await create_rule(
        db,
        {
            **body.model_dump(),
            "organization_id": create_org(current_user, body.organization_id),
        },
    )
    return APIResponse(data=_rule_to_response(rule))


@router.get("", response_model=APIResponse[RuleListResponse])
async def list_rules(
    request: Request,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    trigger_type: str | None = Query(None),
    is_active: bool | None = Query(None),
    organization_id: UUID | None = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    rules_items, total = await get_rules_paginated(
        db,
        page=page,
        per_page=per_page,
        trigger_type=trigger_type,
        is_active=is_active,
        organization_id=scope_org(current_user, organization_id),
    )
    total_pages = max((total + per_page - 1) // per_page, 1) if total > 0 else 0

    return APIResponse(
        data=RuleListResponse(
            rules=[_rule_to_response(r) for r in rules_items],
            total=total,
        ),
        meta={  # type: ignore[arg-type]
            "page": page,
            "per_page": per_page,
            "total": total,
            "total_pages": total_pages,
        },
    )


@router.get("/{rule_id}", response_model=APIResponse[RuleResponse])
async def get_rule(
    request: Request,
    rule_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    rule = await get_rule_by_id(db, rule_id, scope_org(current_user))
    if not rule:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "RULE_NOT_FOUND", "message": "ルールが見つかりません。"},
        )
    return APIResponse(data=_rule_to_response(rule))


@router.put("/{rule_id}", response_model=APIResponse[RuleResponse])
async def update_rule_endpoint(
    request: Request,
    rule_id: UUID,
    body: RuleUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    rule = await update_rule(
        db,
        rule_id,
        body.model_dump(exclude_unset=True),
        organization_id=scope_org(current_user),
    )
    if not rule:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "RULE_NOT_FOUND", "message": "ルールが見つかりません。"},
        )
    return APIResponse(data=_rule_to_response(rule))


@router.delete("/{rule_id}", response_model=APIResponse)
async def delete_rule_endpoint(
    request: Request,
    rule_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    deleted = await delete_rule(db, rule_id, scope_org(current_user))
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "RULE_NOT_FOUND", "message": "ルールが見つかりません。"},
        )
    return APIResponse(data={"message": "ルールを削除しました。"})


@router.post("/{rule_id}/enable", response_model=APIResponse[RuleResponse])
async def enable_rule_endpoint(
    request: Request,
    rule_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    rule = await enable_rule(db, rule_id, scope_org(current_user))
    if not rule:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "RULE_NOT_FOUND", "message": "ルールが見つかりません。"},
        )
    return APIResponse(data=_rule_to_response(rule))


@router.post("/{rule_id}/disable", response_model=APIResponse[RuleResponse])
async def disable_rule_endpoint(
    request: Request,
    rule_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    rule = await disable_rule(db, rule_id, scope_org(current_user))
    if not rule:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "RULE_NOT_FOUND", "message": "ルールが見つかりません。"},
        )
    return APIResponse(data=_rule_to_response(rule))


@router.post("/{rule_id}/test", response_model=APIResponse[RuleTestResponse])
async def test_rule_endpoint(
    request: Request,
    rule_id: UUID,
    body: RuleTestRequest,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    result = await test_rule_execution(
        db, rule_id, body.model_dump(), organization_id=scope_org(current_user)
    )
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "RULE_NOT_FOUND", "message": "ルールが見つかりません。"},
        )
    return APIResponse(data=result)
