"""AIエージェント管理エンドポイント"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from ..middleware.auth import TokenData, get_current_user
from ..middleware.tenant import create_org, scope_org
from ..models.base import get_db
from ..schemas import (
    APIResponse,
    AgentCreateRequest,
    AgentListResponse,
    AgentResponse,
    AgentUpdateRequest,
)
from ..services.autonomous_service import (
    create_agent,
    delete_agent,
    get_agent_by_id,
    get_agents_paginated,
    pause_agent,
    start_agent,
    stop_agent,
    update_agent,
)

router = APIRouter()


def _agent_to_response(agent) -> AgentResponse:
    return AgentResponse.model_validate(agent)


@router.post("", response_model=APIResponse[AgentResponse], status_code=status.HTTP_201_CREATED)
async def create_agent_endpoint(
    request: Request,
    body: AgentCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    data = body.model_dump()
    data["organization_id"] = create_org(current_user, body.organization_id)
    agent = await create_agent(db, data)
    return APIResponse(data=_agent_to_response(agent))


@router.get("", response_model=APIResponse[AgentListResponse])
async def list_agents(
    request: Request,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    agent_type: str | None = Query(None),
    status: str | None = Query(None),
    organization_id: UUID | None = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    agents, total = await get_agents_paginated(
        db,
        page=page,
        per_page=per_page,
        agent_type=agent_type,
        status=status,
        organization_id=scope_org(current_user, organization_id),
    )
    total_pages = max((total + per_page - 1) // per_page, 1) if total > 0 else 0

    return APIResponse(
        data=AgentListResponse(
            agents=[_agent_to_response(a) for a in agents],
            total=total,
        ),
        meta={  # type: ignore[arg-type]
            "page": page,
            "per_page": per_page,
            "total": total,
            "total_pages": total_pages,
        },
    )


@router.get("/{agent_id}", response_model=APIResponse[AgentResponse])
async def get_agent(
    request: Request,
    agent_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    agent = await get_agent_by_id(db, agent_id, organization_id=scope_org(current_user))
    if not agent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "AGENT_NOT_FOUND", "message": "エージェントが見つかりません。"},
        )
    return APIResponse(data=_agent_to_response(agent))


@router.put("/{agent_id}", response_model=APIResponse[AgentResponse])
async def update_agent_endpoint(
    request: Request,
    agent_id: UUID,
    body: AgentUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    agent = await update_agent(db, agent_id, body.model_dump(exclude_unset=True), organization_id=scope_org(current_user))
    if not agent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "AGENT_NOT_FOUND", "message": "エージェントが見つかりません。"},
        )
    return APIResponse(data=_agent_to_response(agent))


@router.delete("/{agent_id}", response_model=APIResponse)
async def delete_agent_endpoint(
    request: Request,
    agent_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    deleted = await delete_agent(db, agent_id, organization_id=scope_org(current_user))
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "AGENT_NOT_FOUND", "message": "エージェントが見つかりません。"},
        )
    return APIResponse(data={"message": "エージェントを削除しました。"})


@router.post("/{agent_id}/start", response_model=APIResponse[AgentResponse])
async def start_agent_endpoint(
    request: Request,
    agent_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    agent = await start_agent(db, agent_id, organization_id=scope_org(current_user))
    if not agent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "AGENT_NOT_FOUND", "message": "エージェントが見つかりません。"},
        )
    return APIResponse(data=_agent_to_response(agent))


@router.post("/{agent_id}/stop", response_model=APIResponse[AgentResponse])
async def stop_agent_endpoint(
    request: Request,
    agent_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    agent = await stop_agent(db, agent_id, organization_id=scope_org(current_user))
    if not agent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "AGENT_NOT_FOUND", "message": "エージェントが見つかりません。"},
        )
    return APIResponse(data=_agent_to_response(agent))


@router.post("/{agent_id}/pause", response_model=APIResponse[AgentResponse])
async def pause_agent_endpoint(
    request: Request,
    agent_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    agent = await pause_agent(db, agent_id, organization_id=scope_org(current_user))
    if not agent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "AGENT_NOT_FOUND", "message": "エージェントが見つかりません。"},
        )
    return APIResponse(data=_agent_to_response(agent))
