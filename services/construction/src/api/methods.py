"""施工計画書/施工方法書 API"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from ..middleware.auth import (
    TokenData,
    get_current_user,
    require_actor_id,
    require_organization_id,
)
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

# 施工計画書の承認ができるロール。admin は常に許可（auth サービスと同一規約）。
_APPROVAL_ROLES = {"approver", "management"}


def _require_approver(user: TokenData) -> None:
    roles = set(user.roles or [])
    if "admin" in roles:
        return
    if not (_APPROVAL_ROLES & roles):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "INSUFFICIENT_ROLE",
                "message": "施工計画書の承認には承認ロールが必要です。",
            },
        )


@router.post("/methods", response_model=MethodResponse, status_code=status.HTTP_201_CREATED)
async def create_method(
    body: MethodCreateRequest,
    db: AsyncSession = Depends(get_db),
    user: TokenData = Depends(get_current_user),
):
    data = body.model_dump()
    data["organization_id"] = require_organization_id(user)
    data["created_by"] = require_actor_id(user)
    return await construction_service.create_method(db, data)


@router.get("/methods", response_model=MethodListResponse)
async def list_methods(
    project_id: UUID | None = Query(None),
    document_type: str | None = Query(None),
    status: str | None = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    user: TokenData = Depends(get_current_user),
):
    items, total = await construction_service.list_methods(
        db,
        organization_id=require_organization_id(user),
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
    user: TokenData = Depends(get_current_user),
):
    method = await construction_service.get_method(
        db, method_id, require_organization_id(user)
    )
    if not method:
        raise HTTPException(status_code=404, detail="施工計画書が見つかりません")
    return method


@router.put("/methods/{method_id}", response_model=MethodResponse)
async def update_method(
    method_id: UUID,
    body: MethodUpdateRequest,
    db: AsyncSession = Depends(get_db),
    user: TokenData = Depends(get_current_user),
):
    method = await construction_service.get_method(
        db, method_id, require_organization_id(user)
    )
    if not method:
        raise HTTPException(status_code=404, detail="施工計画書が見つかりません")
    return await construction_service.update_method(db, method, body.model_dump(exclude_none=True))


@router.delete("/methods/{method_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_method(
    method_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: TokenData = Depends(get_current_user),
):
    method = await construction_service.get_method(
        db, method_id, require_organization_id(user)
    )
    if not method:
        raise HTTPException(status_code=404, detail="施工計画書が見つかりません")
    await db.delete(method)


@router.post("/methods/{method_id}/submit", response_model=MethodResponse)
async def submit_method(
    method_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: TokenData = Depends(get_current_user),
):
    method = await construction_service.get_method(
        db, method_id, require_organization_id(user)
    )
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
    _require_approver(user)
    method = await construction_service.get_method(
        db, method_id, require_organization_id(user)
    )
    if not method:
        raise HTTPException(status_code=404, detail="施工計画書が見つかりません")
    try:
        # 承認者同定はトークン由来（_body.approved_by は後方互換のため受理のみ）。
        return await construction_service.approve_method(db, method, require_actor_id(user))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/methods/{method_id}/reject", response_model=MethodResponse)
async def reject_method(
    method_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: TokenData = Depends(get_current_user),
):
    method = await construction_service.get_method(
        db, method_id, require_organization_id(user)
    )
    if not method:
        raise HTTPException(status_code=404, detail="施工計画書が見つかりません")
    try:
        return await construction_service.reject_method(db, method)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
