"""港湾施工管理エンドポイント"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from ..middleware.auth import TokenData, get_current_user
from ..middleware.tenant import create_org, scope_org
from ..models.base import get_db
from ..schemas import (
    APIResponse,
    MarineConstructionCreateRequest,
    MarineConstructionResponse,
    MarineConstructionUpdateRequest,
    ProgressUpdateRequest,
)
from ..services.advanced_service import (
    create_marine_construction,
    get_marine_construction_by_id,
    list_marine_constructions,
    update_marine_construction,
    delete_marine_construction,
)

router = APIRouter()


def _to_response(record) -> MarineConstructionResponse:
    return MarineConstructionResponse(
        id=record.id,
        organization_id=record.organization_id,
        project_id=record.project_id,
        name=record.name,
        construction_type=record.construction_type,
        status=record.status,
        water_depth=record.water_depth,
        tide_info=record.tide_info,
        wave_condition=record.wave_condition,
        equipment_deployed=record.equipment_deployed,
        material_volume=float(record.material_volume)
        if record.material_volume
        else None,
        progress_percent=float(record.progress_percent)
        if record.progress_percent
        else None,
        location=record.location,
        start_date=record.start_date,
        end_date=record.end_date,
        supervisor_id=record.supervisor_id,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


@router.post(
    "",
    response_model=APIResponse[MarineConstructionResponse],
    status_code=status.HTTP_201_CREATED,
)
async def create_marine(
    request: Request,
    body: MarineConstructionCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    data = body.model_dump()
    data["organization_id"] = create_org(current_user, body.organization_id)
    record = await create_marine_construction(db, data)
    return APIResponse(data=_to_response(record))


@router.get("", response_model=APIResponse)
async def list_marine(
    request: Request,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    construction_type: str | None = Query(None),
    status: str | None = Query(None),
    project_id: UUID | None = Query(None),
    organization_id: UUID | None = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    records, total = await list_marine_constructions(
        db,
        page=page,
        per_page=per_page,
        construction_type=construction_type,
        status=status,
        project_id=project_id,
        organization_id=scope_org(current_user, organization_id),
    )
    total_pages = max((total + per_page - 1) // per_page, 1) if total > 0 else 0

    return APIResponse(
        data={"records": [_to_response(r) for r in records], "total": total},
        meta={  # type: ignore[arg-type]
            "page": page,
            "per_page": per_page,
            "total": total,
            "total_pages": total_pages,
        },
    )


@router.get("/{record_id}", response_model=APIResponse[MarineConstructionResponse])
async def get_marine(
    request: Request,
    record_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    record = await get_marine_construction_by_id(db, record_id, scope_org(current_user))
    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "NOT_FOUND", "message": "施工記録が見つかりません。"},
        )
    return APIResponse(data=_to_response(record))


@router.put("/{record_id}", response_model=APIResponse[MarineConstructionResponse])
async def update_marine(
    request: Request,
    record_id: UUID,
    body: MarineConstructionUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    record = await update_marine_construction(
        db, record_id, body.model_dump(exclude_unset=True), scope_org(current_user)
    )
    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "NOT_FOUND", "message": "施工記録が見つかりません。"},
        )
    return APIResponse(data=_to_response(record))


@router.delete("/{record_id}", response_model=APIResponse)
async def delete_marine(
    request: Request,
    record_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    deleted = await delete_marine_construction(db, record_id, scope_org(current_user))
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "NOT_FOUND", "message": "施工記録が見つかりません。"},
        )
    return APIResponse(data={"message": "施工記録を削除しました。"})


@router.patch(
    "/{record_id}/progress", response_model=APIResponse[MarineConstructionResponse]
)
async def update_progress(
    request: Request,
    record_id: UUID,
    body: ProgressUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    record = await update_marine_construction(
        db,
        record_id,
        {"progress_percent": body.progress_percent},
        scope_org(current_user),
    )
    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "NOT_FOUND", "message": "施工記録が見つかりません。"},
        )
    return APIResponse(data=_to_response(record))
