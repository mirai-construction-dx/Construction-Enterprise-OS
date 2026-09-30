"""施工シミュレーション管理エンドポイント"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from ..middleware.auth import TokenData, get_current_user
from ..middleware.tenant import create_org, scope_org
from ..models.base import get_db
from ..schemas import (
    APIResponse,
    SimulationCreateRequest,
    SimulationListResponse,
    SimulationResponse,
)
from ..services.autonomous_service import (
    get_twin_by_id,
    create_simulation,
    delete_simulation,
    get_simulation_by_id,
    get_simulations_paginated,
    run_simulation,
)
from ._parents import ensure_parent_in_org

router = APIRouter()


def _sim_to_response(sim) -> SimulationResponse:
    return SimulationResponse.model_validate(sim)


@router.post("", response_model=APIResponse[SimulationResponse], status_code=status.HTTP_201_CREATED)
async def create_simulation_endpoint(
    request: Request,
    body: SimulationCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    org = create_org(current_user, body.organization_id)
    await ensure_parent_in_org(
        db, get_twin_by_id, body.digital_twin_id, org, current_user, code="TWIN", label="デジタルツイン"
    )
    data = body.model_dump()
    data["organization_id"] = org
    sim = await create_simulation(db, data)
    return APIResponse(data=_sim_to_response(sim))


@router.get("", response_model=APIResponse[SimulationListResponse])
async def list_simulations(
    request: Request,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    simulation_type: str | None = Query(None),
    status: str | None = Query(None),
    project_id: UUID | None = Query(None),
    organization_id: UUID | None = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    sims, total = await get_simulations_paginated(
        db,
        page=page,
        per_page=per_page,
        simulation_type=simulation_type,
        status=status,
        project_id=project_id,
        organization_id=scope_org(current_user, organization_id),
    )
    total_pages = max((total + per_page - 1) // per_page, 1) if total > 0 else 0

    return APIResponse(
        data=SimulationListResponse(
            simulations=[_sim_to_response(s) for s in sims],
            total=total,
        ),
        meta={  # type: ignore[arg-type]
            "page": page,
            "per_page": per_page,
            "total": total,
            "total_pages": total_pages,
        },
    )


@router.get("/{sim_id}", response_model=APIResponse[SimulationResponse])
async def get_simulation(
    request: Request,
    sim_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    sim = await get_simulation_by_id(db, sim_id, organization_id=scope_org(current_user))
    if not sim:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "SIMULATION_NOT_FOUND", "message": "シミュレーションが見つかりません。"},
        )
    return APIResponse(data=_sim_to_response(sim))


@router.delete("/{sim_id}", response_model=APIResponse)
async def delete_simulation_endpoint(
    request: Request,
    sim_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    deleted = await delete_simulation(db, sim_id, organization_id=scope_org(current_user))
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "SIMULATION_NOT_FOUND", "message": "シミュレーションが見つかりません。"},
        )
    return APIResponse(data={"message": "シミュレーションを削除しました。"})


@router.post("/{sim_id}/run", response_model=APIResponse[SimulationResponse])
async def run_simulation_endpoint(
    request: Request,
    sim_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    sim = await run_simulation(db, sim_id, organization_id=scope_org(current_user))
    if not sim:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "SIMULATION_NOT_FOUND", "message": "シミュレーションが見つかりません。"},
        )
    return APIResponse(data=_sim_to_response(sim))
