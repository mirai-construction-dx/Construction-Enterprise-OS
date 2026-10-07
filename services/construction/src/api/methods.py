"""施工計画書/施工方法書 API"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from ..middleware.auth import TokenData, get_current_user
from ..models.base import get_db
from ..schemas import (
    MethodApprovalRequest,
    MethodCreateRequest,
    MethodListResponse,
    MethodResponse,
    MethodUpdateRequest,
)
from ..services import construction_service

router = APIRouter()


def _actor_id(user: TokenData) -> UUID:
    """トークンの sub から操作者を同定する（ボディ由来の値は信用しない）。"""
    try:
        return UUID(user.sub)
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "INVALID_IDENTITY",
                "message": "トークンの利用者IDが不正です。",
            },
        )


@router.post("/methods", response_model=MethodResponse, status_code=status.HTTP_201_CREATED)
async def create_method(
    body: MethodCreateRequest,
    db: AsyncSession = Depends(get_db),
    _user: TokenData = Depends(get_current_user),
):
    return await construction_service.create_method(db, body.model_dump())


@router.get("/methods", response_model=MethodListResponse)
async def list_methods(
    organization_id: UUID | None = Query(None),
    project_id: UUID | None = Query(None),
    document_type: str | None = Query(None),
    status: str | None = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    _user: TokenData = Depends(get_current_user),
):
    items, total = await construction_service.list_methods(
        db,
        organization_id=organization_id,
        project_id=project_id,
        document_type=document_type,
        status=status,
        page=page,
        per_page=per_page,
    )
    return MethodListResponse(items=items, total=total, page=page, per_page=per_page)  # type: ignore[arg-type]


@router.get("/methods/{method_id}", response_model=MethodResponse)
async def get_method(
    method_id: UUID,
    db: AsyncSession = Depends(get_db),
    _user: TokenData = Depends(get_current_user),
):
    method = await construction_service.get_method(db, method_id)
    if not method:
        raise HTTPException(status_code=404, detail="施工計画書が見つかりません")
    return method


@router.put("/methods/{method_id}", response_model=MethodResponse)
async def update_method(
    method_id: UUID,
    body: MethodUpdateRequest,
    db: AsyncSession = Depends(get_db),
    _user: TokenData = Depends(get_current_user),
):
    method = await construction_service.get_method(db, method_id)
    if not method:
        raise HTTPException(status_code=404, detail="施工計画書が見つかりません")
    return await construction_service.update_method(db, method, body.model_dump(exclude_none=True))


@router.delete("/methods/{method_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_method(
    method_id: UUID,
    db: AsyncSession = Depends(get_db),
    _user: TokenData = Depends(get_current_user),
):
    method = await construction_service.get_method(db, method_id)
    if not method:
        raise HTTPException(status_code=404, detail="施工計画書が見つかりません")
    await db.delete(method)


@router.post("/methods/{method_id}/submit", response_model=MethodResponse)
async def submit_method(
    method_id: UUID,
    db: AsyncSession = Depends(get_db),
    _user: TokenData = Depends(get_current_user),
):
    method = await construction_service.get_method(db, method_id)
    if not method:
        raise HTTPException(status_code=404, detail="施工計画書が見つかりません")
    try:
        return await construction_service.submit_for_approval(db, method)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/methods/{method_id}/approve", response_model=MethodResponse)
async def approve_method(
    method_id: UUID,
    _body: MethodApprovalRequest | None = None,
    db: AsyncSession = Depends(get_db),
    user: TokenData = Depends(get_current_user),
):
    method = await construction_service.get_method(db, method_id)
    if not method:
        raise HTTPException(status_code=404, detail="施工計画書が見つかりません")
    try:
        # 承認者同定はトークン由来（_body.approved_by は後方互換のため受理のみ）。
        return await construction_service.approve_method(db, method, _actor_id(user))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/methods/{method_id}/reject", response_model=MethodResponse)
async def reject_method(
    method_id: UUID,
    db: AsyncSession = Depends(get_db),
    _user: TokenData = Depends(get_current_user),
):
    method = await construction_service.get_method(db, method_id)
    if not method:
        raise HTTPException(status_code=404, detail="施工計画書が見つかりません")
    try:
        return await construction_service.reject_method(db, method)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
