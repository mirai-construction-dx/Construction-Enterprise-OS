"""デジタルツイン管理エンドポイント"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from ..middleware.auth import TokenData, get_current_user
from ..middleware.tenant import create_org, scope_org
from ..models.base import get_db
from ..schemas import (
    APIResponse,
    TwinCreateRequest,
    TwinCurrentStateResponse,
    TwinListResponse,
    TwinResponse,
    TwinSyncRequest,
    TwinUpdateRequest,
)
from ..services.autonomous_service import (
    create_twin,
    delete_twin,
    get_twin_by_id,
    get_twin_current_state,
    get_twins_paginated,
    sync_twin,
    update_twin,
)

router = APIRouter()


def _twin_to_response(twin) -> TwinResponse:
    return TwinResponse.model_validate(twin)


@router.post("", response_model=APIResponse[TwinResponse], status_code=status.HTTP_201_CREATED)
async def create_twin_endpoint(
    request: Request,
    body: TwinCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    data = body.model_dump()
    data["organization_id"] = create_org(current_user, body.organization_id)
    twin = await create_twin(db, data)
    return APIResponse(data=_twin_to_response(twin))


@router.get("", response_model=APIResponse[TwinListResponse])
async def list_twins(
    request: Request,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    twin_type: str | None = Query(None),
    status: str | None = Query(None),
    project_id: UUID | None = Query(None),
    organization_id: UUID | None = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    twins, total = await get_twins_paginated(
        db,
        page=page,
        per_page=per_page,
        twin_type=twin_type,
        status=status,
        project_id=project_id,
        organization_id=scope_org(current_user, organization_id),
    )
    total_pages = max((total + per_page - 1) // per_page, 1) if total > 0 else 0

    return APIResponse(
        data=TwinListResponse(
            twins=[_twin_to_response(t) for t in twins],
            total=total,
        ),
        meta={  # type: ignore[arg-type]
            "page": page,
            "per_page": per_page,
            "total": total,
            "total_pages": total_pages,
        },
    )


@router.get("/{twin_id}", response_model=APIResponse[TwinResponse])
async def get_twin(
    request: Request,
    twin_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    twin = await get_twin_by_id(db, twin_id, organization_id=scope_org(current_user))
    if not twin:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "TWIN_NOT_FOUND", "message": "デジタルツインが見つかりません。"},
        )
    return APIResponse(data=_twin_to_response(twin))


@router.put("/{twin_id}", response_model=APIResponse[TwinResponse])
async def update_twin_endpoint(
    request: Request,
    twin_id: UUID,
    body: TwinUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    twin = await update_twin(db, twin_id, body.model_dump(exclude_unset=True), organization_id=scope_org(current_user))
    if not twin:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "TWIN_NOT_FOUND", "message": "デジタルツインが見つかりません。"},
        )
    return APIResponse(data=_twin_to_response(twin))


@router.delete("/{twin_id}", response_model=APIResponse)
async def delete_twin_endpoint(
    request: Request,
    twin_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    deleted = await delete_twin(db, twin_id, organization_id=scope_org(current_user))
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "TWIN_NOT_FOUND", "message": "デジタルツインが見つかりません。"},
        )
    return APIResponse(data={"message": "デジタルツインを削除しました。"})


@router.post("/{twin_id}/sync", response_model=APIResponse[TwinResponse])
async def sync_twin_endpoint(
    request: Request,
    twin_id: UUID,
    body: TwinSyncRequest,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    twin = await sync_twin(db, twin_id, body.current_state, organization_id=scope_org(current_user))
    if not twin:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "TWIN_NOT_FOUND", "message": "デジタルツインが見つかりません。"},
        )
    return APIResponse(data=_twin_to_response(twin))


@router.get("/{twin_id}/state", response_model=APIResponse[TwinCurrentStateResponse])
async def get_twin_state_endpoint(
    request: Request,
    twin_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    state = await get_twin_current_state(db, twin_id, organization_id=scope_org(current_user))
    if not state:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "TWIN_NOT_FOUND", "message": "デジタルツインが見つかりません。"},
        )
    return APIResponse(data=TwinCurrentStateResponse(**state))
