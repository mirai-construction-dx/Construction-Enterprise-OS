"""自律施工オペレーション管理エンドポイント"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from ..middleware.auth import MANAGEMENT_ROLES, TokenData, get_current_user, require_any_role
from ..middleware.tenant import create_org, scope_org
from ..models.base import get_db
from ..schemas import (
    APIResponse,
    OperationCreateRequest,
    OperationListResponse,
    OperationProgressResponse,
    OperationResponse,
    OperationUpdateRequest,
)
from ..services.autonomous_service import (
    get_twin_by_id,
    abort_operation,
    create_operation,
    delete_operation,
    emergency_stop_operation,
    get_operation_by_id,
    get_operation_progress,
    get_operations_paginated,
    pause_operation,
    resume_operation,
    start_operation,
    update_operation,
)
from ._parents import ensure_parent_in_org

router = APIRouter()


def _op_to_response(op) -> OperationResponse:
    return OperationResponse.model_validate(op)


@router.post("", response_model=APIResponse[OperationResponse], status_code=status.HTTP_201_CREATED)
async def create_operation_endpoint(
    request: Request,
    body: OperationCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    org = create_org(current_user, body.organization_id)
    await ensure_parent_in_org(
        db, get_twin_by_id, body.digital_twin_id, org, current_user, code="TWIN", label="デジタルツイン"
    )
    data = body.model_dump()
    data["organization_id"] = org
    op = await create_operation(db, data)
    return APIResponse(data=_op_to_response(op))


@router.get("", response_model=APIResponse[OperationListResponse])
async def list_operations(
    request: Request,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    operation_type: str | None = Query(None),
    status: str | None = Query(None),
    project_id: UUID | None = Query(None),
    organization_id: UUID | None = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    ops, total = await get_operations_paginated(
        db,
        page=page,
        per_page=per_page,
        operation_type=operation_type,
        status=status,
        project_id=project_id,
        organization_id=scope_org(current_user, organization_id),
    )
    total_pages = max((total + per_page - 1) // per_page, 1) if total > 0 else 0

    return APIResponse(
        data=OperationListResponse(
            operations=[_op_to_response(o) for o in ops],
            total=total,
        ),
        meta={  # type: ignore[arg-type]
            "page": page,
            "per_page": per_page,
            "total": total,
            "total_pages": total_pages,
        },
    )


@router.get("/{op_id}", response_model=APIResponse[OperationResponse])
async def get_operation(
    request: Request,
    op_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    op = await get_operation_by_id(db, op_id, organization_id=scope_org(current_user))
    if not op:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "OPERATION_NOT_FOUND", "message": "施工オペレーションが見つかりません。"},
        )
    return APIResponse(data=_op_to_response(op))


@router.put("/{op_id}", response_model=APIResponse[OperationResponse])
async def update_operation_endpoint(
    request: Request,
    op_id: UUID,
    body: OperationUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    op = await update_operation(db, op_id, body.model_dump(exclude_unset=True), organization_id=scope_org(current_user))
    if not op:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "OPERATION_NOT_FOUND", "message": "施工オペレーションが見つかりません。"},
        )
    return APIResponse(data=_op_to_response(op))


@router.delete("/{op_id}", response_model=APIResponse)
async def delete_operation_endpoint(
    request: Request,
    op_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    org = scope_org(current_user)
    require_any_role(current_user, MANAGEMENT_ROLES)
    deleted = await delete_operation(db, op_id, organization_id=org)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "OPERATION_NOT_FOUND", "message": "施工オペレーションが見つかりません。"},
        )
    return APIResponse(data={"message": "施工オペレーションを削除しました。"})


@router.post("/{op_id}/start", response_model=APIResponse[OperationResponse])
async def start_operation_endpoint(
    request: Request,
    op_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    op = await start_operation(db, op_id, organization_id=scope_org(current_user))
    if not op:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "OPERATION_NOT_FOUND", "message": "施工オペレーションが見つかりません。"},
        )
    return APIResponse(data=_op_to_response(op))


@router.post("/{op_id}/pause", response_model=APIResponse[OperationResponse])
async def pause_operation_endpoint(
    request: Request,
    op_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    op = await pause_operation(db, op_id, organization_id=scope_org(current_user))
    if not op:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "OPERATION_NOT_FOUND", "message": "施工オペレーションが見つかりません。"},
        )
    return APIResponse(data=_op_to_response(op))


@router.post("/{op_id}/resume", response_model=APIResponse[OperationResponse])
async def resume_operation_endpoint(
    request: Request,
    op_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    op = await resume_operation(db, op_id, organization_id=scope_org(current_user))
    if not op:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "OPERATION_NOT_FOUND", "message": "施工オペレーションが見つかりません。"},
        )
    return APIResponse(data=_op_to_response(op))


@router.post("/{op_id}/abort", response_model=APIResponse[OperationResponse])
async def abort_operation_endpoint(
    request: Request,
    op_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    op = await abort_operation(db, op_id, organization_id=scope_org(current_user))
    if not op:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "OPERATION_NOT_FOUND", "message": "施工オペレーションが見つかりません。"},
        )
    return APIResponse(data=_op_to_response(op))


@router.post("/{op_id}/emergency-stop", response_model=APIResponse[OperationResponse])
async def emergency_stop_operation_endpoint(
    request: Request,
    op_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    op = await emergency_stop_operation(db, op_id, organization_id=scope_org(current_user))
    if not op:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "OPERATION_NOT_FOUND", "message": "施工オペレーションが見つかりません。"},
        )
    return APIResponse(data=_op_to_response(op))


@router.get("/{op_id}/progress", response_model=APIResponse[OperationProgressResponse])
async def get_operation_progress_endpoint(
    request: Request,
    op_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    progress = await get_operation_progress(db, op_id, organization_id=scope_org(current_user))
    if not progress:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "OPERATION_NOT_FOUND", "message": "施工オペレーションが見つかりません。"},
        )
    return APIResponse(data=OperationProgressResponse(**progress))
