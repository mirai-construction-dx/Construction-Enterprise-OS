"""スケジュールタスク管理エンドポイント"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from ..middleware.auth import TokenData, get_current_user
from ..middleware.tenant import create_org, scope_org
from ..models.base import get_db
from ..schemas import (
    APIResponse,
    TaskCreateRequest,
    TaskListResponse,
    TaskResponse,
    TaskRunResponse,
    TaskUpdateRequest,
)
from ..services.automation_service import (
    create_task,
    delete_task,
    get_task_by_id,
    get_task_run_history,
    get_tasks_paginated,
    trigger_task_now,
    update_task,
)

router = APIRouter()


def _task_to_response(task) -> TaskResponse:
    return TaskResponse.model_validate(task)


def _run_to_response(run) -> TaskRunResponse:
    return TaskRunResponse.model_validate(run)


@router.post("", response_model=APIResponse[TaskResponse], status_code=status.HTTP_201_CREATED)
async def create_task_endpoint(
    request: Request,
    body: TaskCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    task = await create_task(
        db,
        {
            **body.model_dump(),
            "organization_id": create_org(current_user, body.organization_id),
        },
    )
    return APIResponse(data=_task_to_response(task))


@router.get("", response_model=APIResponse[TaskListResponse])
async def list_tasks(
    request: Request,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    action_type: str | None = Query(None),
    is_active: bool | None = Query(None),
    organization_id: UUID | None = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    tasks_items, total = await get_tasks_paginated(
        db,
        page=page,
        per_page=per_page,
        action_type=action_type,
        is_active=is_active,
        organization_id=scope_org(current_user, organization_id),
    )
    total_pages = max((total + per_page - 1) // per_page, 1) if total > 0 else 0

    return APIResponse(
        data=TaskListResponse(
            tasks=[_task_to_response(t) for t in tasks_items],
            total=total,
        ),
        meta={  # type: ignore[arg-type]
            "page": page,
            "per_page": per_page,
            "total": total,
            "total_pages": total_pages,
        },
    )


@router.get("/{task_id}", response_model=APIResponse[TaskResponse])
async def get_task(
    request: Request,
    task_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    task = await get_task_by_id(db, task_id, scope_org(current_user))
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "TASK_NOT_FOUND", "message": "タスクが見つかりません。"},
        )
    return APIResponse(data=_task_to_response(task))


@router.put("/{task_id}", response_model=APIResponse[TaskResponse])
async def update_task_endpoint(
    request: Request,
    task_id: UUID,
    body: TaskUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    task = await update_task(
        db,
        task_id,
        body.model_dump(exclude_unset=True),
        organization_id=scope_org(current_user),
    )
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "TASK_NOT_FOUND", "message": "タスクが見つかりません。"},
        )
    return APIResponse(data=_task_to_response(task))


@router.delete("/{task_id}", response_model=APIResponse)
async def delete_task_endpoint(
    request: Request,
    task_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    deleted = await delete_task(db, task_id, scope_org(current_user))
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "TASK_NOT_FOUND", "message": "タスクが見つかりません。"},
        )
    return APIResponse(data={"message": "タスクを削除しました。"})


@router.post("/{task_id}/trigger", response_model=APIResponse[TaskRunResponse])
async def trigger_task_now_endpoint(
    request: Request,
    task_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    run = await trigger_task_now(db, task_id, scope_org(current_user))
    if not run:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "TASK_NOT_FOUND", "message": "タスクが見つかりません。"},
        )
    return APIResponse(data=_run_to_response(run))


@router.get("/{task_id}/history", response_model=APIResponse[list[TaskRunResponse]])
async def get_task_run_history_endpoint(
    request: Request,
    task_id: UUID,
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    org = scope_org(current_user)
    task = await get_task_by_id(db, task_id, org)
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "TASK_NOT_FOUND", "message": "タスクが見つかりません。"},
        )
    runs = await get_task_run_history(db, task_id, limit=limit, organization_id=org)
    return APIResponse(data=[_run_to_response(r) for r in runs])
