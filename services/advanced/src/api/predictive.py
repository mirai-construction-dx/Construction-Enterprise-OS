"""予知保全エンドポイント"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from ..middleware.auth import TokenData, get_current_user
from ..middleware.tenant import create_org, scope_org
from ..models.base import get_db
from ..schemas import (
    APIResponse,
    PredictiveModelCreateRequest,
    PredictiveModelResponse,
    PredictiveModelUpdateRequest,
    PredictionResultResponse,
)
from ..services.advanced_service import (
    create_predictive_model,
    get_predictive_model_by_id,
    list_predictive_models,
    update_predictive_model,
    delete_predictive_model,
    get_prediction_result,
)

router = APIRouter()


def _to_response(record) -> PredictiveModelResponse:
    return PredictiveModelResponse(
        id=record.id,
        organization_id=record.organization_id,
        asset_name=record.asset_name,
        asset_type=record.asset_type,
        model_type=record.model_type,
        status=record.status,
        training_data_count=record.training_data_count,
        accuracy=record.accuracy,
        last_trained_at=record.last_trained_at,
        next_maintenance_predicted=record.next_maintenance_predicted,
        failure_probability=record.failure_probability,
        remaining_life_days=record.remaining_life_days,
        recommendations=record.recommendations if record.recommendations else [],
        input_metrics=record.input_metrics if record.input_metrics else {},
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


@router.post("", response_model=APIResponse[PredictiveModelResponse], status_code=status.HTTP_201_CREATED)
async def create_model(
    request: Request,
    body: PredictiveModelCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    data = body.model_dump()
    data["organization_id"] = create_org(current_user, body.organization_id)
    record = await create_predictive_model(db, data)
    return APIResponse(data=_to_response(record))


@router.get("", response_model=APIResponse)
async def list_models(
    request: Request,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    model_type: str | None = Query(None),
    status: str | None = Query(None),
    asset_type: str | None = Query(None),
    organization_id: UUID | None = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    records, total = await list_predictive_models(
        db,
        page=page,
        per_page=per_page,
        model_type=model_type,
        status=status,
        asset_type=asset_type,
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


@router.get("/{model_id}", response_model=APIResponse[PredictiveModelResponse])
async def get_model(
    request: Request,
    model_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    record = await get_predictive_model_by_id(db, model_id, scope_org(current_user))
    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "NOT_FOUND", "message": "予知保全モデルが見つかりません。"},
        )
    return APIResponse(data=_to_response(record))


@router.put("/{model_id}", response_model=APIResponse[PredictiveModelResponse])
async def update_model(
    request: Request,
    model_id: UUID,
    body: PredictiveModelUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    record = await update_predictive_model(
        db, model_id, body.model_dump(exclude_unset=True), scope_org(current_user)
    )
    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "NOT_FOUND", "message": "予知保全モデルが見つかりません。"},
        )
    return APIResponse(data=_to_response(record))


@router.delete("/{model_id}", response_model=APIResponse)
async def delete_model(
    request: Request,
    model_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    deleted = await delete_predictive_model(db, model_id, scope_org(current_user))
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "NOT_FOUND", "message": "予知保全モデルが見つかりません。"},
        )
    return APIResponse(data={"message": "予知保全モデルを削除しました。"})


@router.get("/{model_id}/prediction", response_model=APIResponse[PredictionResultResponse])
async def get_prediction(
    request: Request,
    model_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    result = await get_prediction_result(db, model_id, scope_org(current_user))
    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "NOT_FOUND", "message": "予知保全モデルが見つかりません。"},
        )
    return APIResponse(data=result)
