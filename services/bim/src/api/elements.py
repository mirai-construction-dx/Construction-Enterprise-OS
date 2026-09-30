"""BIM要素管理 API"""

from math import ceil
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..middleware.auth import TokenData, get_current_user
from ..middleware.tenant import scope_org
from ..models import BIMElement, BIMModel
from ..models.base import get_db
from ..schemas import (
    APIResponse,
    BIMElementResponse,
    MetaInfo,
)
from ..services.bim_service import get_bim_model

router = APIRouter()


def _api_response(data=None, meta=None, error=None, success=True):
    return APIResponse(success=success, data=data, error=error, meta=meta)


def _element_to_response(e: BIMElement) -> dict:
    return BIMElementResponse.model_validate(e).model_dump(mode="json")


async def _require_model(
    db: AsyncSession, model_id: UUID, organization_id: UUID | None
) -> None:
    """Ensure the parent model exists within the caller's organization (else 404).

    Elements have no organization_id of their own; they inherit the parent model's organization.
    ``organization_id=None`` is only passed for cross-org admins.
    """
    if await get_bim_model(db, model_id, organization_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "NOT_FOUND", "message": "BIMモデルが見つかりません。"},
        )


def _scope_elements(stmt, organization_id: UUID | None):
    """Restrict an element query to elements whose parent model belongs to the organization."""
    if organization_id is None:
        return stmt
    return stmt.join(BIMModel, BIMElement.model_id == BIMModel.id).where(
        BIMModel.organization_id == organization_id
    )


@router.get("/{model_id}/elements")
async def list_elements(
    model_id: UUID,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    category: str | None = Query(None),
    element_type: str | None = Query(None),
    token_data: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_model(db, model_id, scope_org(token_data))

    query = select(BIMElement).where(BIMElement.model_id == model_id)
    count_query = select(func.count(BIMElement.id)).where(
        BIMElement.model_id == model_id
    )

    if category:
        query = query.where(BIMElement.category == category)
        count_query = count_query.where(BIMElement.category == category)
    if element_type:
        query = query.where(BIMElement.element_type == element_type)
        count_query = count_query.where(BIMElement.element_type == element_type)

    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0
    total_pages = ceil(total / per_page) if total > 0 else 0

    query = query.order_by(BIMElement.created_at.desc())
    query = query.offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(query)
    elements = result.scalars().all()

    meta = MetaInfo(page=page, per_page=per_page, total=total, total_pages=total_pages)
    return _api_response(
        data=[_element_to_response(e) for e in elements], meta=meta
    )


@router.get("/elements/{element_id}")
async def get_element(
    element_id: UUID,
    token_data: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    stmt = _scope_elements(
        select(BIMElement).where(BIMElement.id == element_id), scope_org(token_data)
    )
    result = await db.execute(stmt)
    element = result.scalar_one_or_none()
    if not element:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "NOT_FOUND", "message": "BIM要素が見つかりません。"},
        )
    return _api_response(data=_element_to_response(element))


@router.get("/{model_id}/elements/by-category")
async def elements_by_category(
    model_id: UUID,
    token_data: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_model(db, model_id, scope_org(token_data))

    result = await db.execute(
        select(BIMElement).where(BIMElement.model_id == model_id)
        .order_by(BIMElement.category, BIMElement.name)
    )
    elements = result.scalars().all()

    grouped: dict[str, list] = {}
    for e in elements:
        cat = e.category or "uncategorized"
        grouped.setdefault(cat, []).append(_element_to_response(e))

    data = [
        {"category": cat, "count": len(items), "elements": items}
        for cat, items in grouped.items()
    ]
    return _api_response(data=data)


@router.get("/{model_id}/elements/by-level")
async def elements_by_level(
    model_id: UUID,
    token_data: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_model(db, model_id, scope_org(token_data))

    result = await db.execute(
        select(BIMElement).where(BIMElement.model_id == model_id)
        .order_by(BIMElement.level_name, BIMElement.name)
    )
    elements = result.scalars().all()

    grouped: dict[str, list] = {}
    for e in elements:
        lvl = e.level_name or "unknown"
        grouped.setdefault(lvl, []).append(_element_to_response(e))

    data = [
        {"level_name": lvl, "count": len(items), "elements": items}
        for lvl, items in grouped.items()
    ]
    return _api_response(data=data)


@router.get("/elements/search")
async def search_elements(
    q: str = Query(..., min_length=1),
    model_id: UUID | None = Query(None),
    organization_id: UUID | None = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    token_data: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org = scope_org(token_data, organization_id)
    query = _scope_elements(select(BIMElement), org)
    count_query = _scope_elements(select(func.count(BIMElement.id)), org)

    search_term = f"%{q}%"
    name_filter = BIMElement.name.ilike(search_term)
    type_filter = BIMElement.element_type.ilike(search_term)
    combined = name_filter | type_filter

    query = query.where(combined)
    count_query = count_query.where(combined)

    if model_id:
        query = query.where(BIMElement.model_id == model_id)
        count_query = count_query.where(BIMElement.model_id == model_id)

    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0
    total_pages = ceil(total / per_page) if total > 0 else 0

    query = query.order_by(BIMElement.name)
    query = query.offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(query)
    elements = result.scalars().all()

    meta = MetaInfo(page=page, per_page=per_page, total=total, total_pages=total_pages)
    return _api_response(
        data=[_element_to_response(e) for e in elements], meta=meta
    )
