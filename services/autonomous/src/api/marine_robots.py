"""海洋ロボティクス管理エンドポイント"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from ..middleware.auth import TokenData, get_current_user
from ..middleware.tenant import create_org, scope_org
from ..models.base import get_db
from ..schemas import (
    APIResponse,
    MarineRobotCreateRequest,
    MarineRobotListResponse,
    MarineRobotResponse,
    MarineRobotTelemetryResponse,
    MarineRobotUpdateRequest,
    MissionPlanRequest,
)
from ..services.autonomous_service import (
    create_marine_robot,
    delete_marine_robot,
    deploy_marine_robot,
    get_marine_robot_by_id,
    get_marine_robot_telemetry,
    get_marine_robots_paginated,
    recover_marine_robot,
    set_marine_robot_mission,
    update_marine_robot,
)

router = APIRouter()


def _robot_to_response(robot) -> MarineRobotResponse:
    return MarineRobotResponse.model_validate(robot)


@router.post("", response_model=APIResponse[MarineRobotResponse], status_code=status.HTTP_201_CREATED)
async def create_marine_robot_endpoint(
    request: Request,
    body: MarineRobotCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    data = body.model_dump()
    data["organization_id"] = create_org(current_user, body.organization_id)
    robot = await create_marine_robot(db, data)
    return APIResponse(data=_robot_to_response(robot))


@router.get("", response_model=APIResponse[MarineRobotListResponse])
async def list_marine_robots(
    request: Request,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    robot_type: str | None = Query(None),
    status: str | None = Query(None),
    mission_type: str | None = Query(None),
    organization_id: UUID | None = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    robots, total = await get_marine_robots_paginated(
        db,
        page=page,
        per_page=per_page,
        robot_type=robot_type,
        status=status,
        mission_type=mission_type,
        organization_id=scope_org(current_user, organization_id),
    )
    total_pages = max((total + per_page - 1) // per_page, 1) if total > 0 else 0

    return APIResponse(
        data=MarineRobotListResponse(
            robots=[_robot_to_response(r) for r in robots],
            total=total,
        ),
        meta={  # type: ignore[arg-type]
            "page": page,
            "per_page": per_page,
            "total": total,
            "total_pages": total_pages,
        },
    )


@router.get("/{robot_id}", response_model=APIResponse[MarineRobotResponse])
async def get_marine_robot(
    request: Request,
    robot_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    robot = await get_marine_robot_by_id(db, robot_id, organization_id=scope_org(current_user))
    if not robot:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "ROBOT_NOT_FOUND", "message": "海洋ロボットが見つかりません。"},
        )
    return APIResponse(data=_robot_to_response(robot))


@router.put("/{robot_id}", response_model=APIResponse[MarineRobotResponse])
async def update_marine_robot_endpoint(
    request: Request,
    robot_id: UUID,
    body: MarineRobotUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    robot = await update_marine_robot(db, robot_id, body.model_dump(exclude_unset=True), organization_id=scope_org(current_user))
    if not robot:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "ROBOT_NOT_FOUND", "message": "海洋ロボットが見つかりません。"},
        )
    return APIResponse(data=_robot_to_response(robot))


@router.delete("/{robot_id}", response_model=APIResponse)
async def delete_marine_robot_endpoint(
    request: Request,
    robot_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    deleted = await delete_marine_robot(db, robot_id, organization_id=scope_org(current_user))
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "ROBOT_NOT_FOUND", "message": "海洋ロボットが見つかりません。"},
        )
    return APIResponse(data={"message": "海洋ロボットを削除しました。"})


@router.post("/{robot_id}/deploy", response_model=APIResponse[MarineRobotResponse])
async def deploy_marine_robot_endpoint(
    request: Request,
    robot_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    robot = await deploy_marine_robot(db, robot_id, organization_id=scope_org(current_user))
    if not robot:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "ROBOT_NOT_FOUND", "message": "海洋ロボットが見つかりません。"},
        )
    return APIResponse(data=_robot_to_response(robot))


@router.post("/{robot_id}/recover", response_model=APIResponse[MarineRobotResponse])
async def recover_marine_robot_endpoint(
    request: Request,
    robot_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    robot = await recover_marine_robot(db, robot_id, organization_id=scope_org(current_user))
    if not robot:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "ROBOT_NOT_FOUND", "message": "海洋ロボットが見つかりません。"},
        )
    return APIResponse(data=_robot_to_response(robot))


@router.get("/{robot_id}/telemetry", response_model=APIResponse[MarineRobotTelemetryResponse])
async def get_marine_robot_telemetry_endpoint(
    request: Request,
    robot_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    telemetry = await get_marine_robot_telemetry(db, robot_id, organization_id=scope_org(current_user))
    if not telemetry:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "ROBOT_NOT_FOUND", "message": "海洋ロボットが見つかりません。"},
        )
    return APIResponse(data=MarineRobotTelemetryResponse(**telemetry))


@router.post("/{robot_id}/mission", response_model=APIResponse[MarineRobotResponse])
async def set_mission_plan_endpoint(
    request: Request,
    robot_id: UUID,
    body: MissionPlanRequest,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    robot = await set_marine_robot_mission(db, robot_id, body.mission_plan, organization_id=scope_org(current_user))
    if not robot:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "ROBOT_NOT_FOUND", "message": "海洋ロボットが見つかりません。"},
        )
    return APIResponse(data=_robot_to_response(robot))
