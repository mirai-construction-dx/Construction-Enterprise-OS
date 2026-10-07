"""評価管理エンドポイント"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from ..middleware.auth import get_current_user
from ..middleware.tenant import create_org, scope_org
from ..models.base import get_db
from ..schemas import (
    APIResponse,
    EvaluationCreate,
    EvaluationResponse,
    TokenData,
)
from ..services import evaluation_service, partner_service

eval_router = APIRouter()


def _partner_not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={"code": "PARTNER_NOT_FOUND", "message": "協力会社が見つかりません。"},
    )


def _evaluation_to_response(eval_) -> EvaluationResponse:
    return EvaluationResponse(
        id=eval_.id,
        organization_id=eval_.organization_id,
        partner_id=eval_.partner_id,
        project_id=eval_.project_id,
        evaluator_id=eval_.evaluator_id,
        overall_score=float(eval_.overall_score),
        quality_score=float(eval_.quality_score) if eval_.quality_score is not None else None,
        safety_score=float(eval_.safety_score) if eval_.safety_score is not None else None,
        schedule_score=float(eval_.schedule_score) if eval_.schedule_score is not None else None,
        cost_score=float(eval_.cost_score) if eval_.cost_score is not None else None,
        communication_score=float(eval_.communication_score) if eval_.communication_score is not None else None,
        comment=eval_.comment,
        evaluation_period_start=eval_.evaluation_period_start,
        evaluation_period_end=eval_.evaluation_period_end,
        created_at=eval_.created_at,
    )


@eval_router.post("", response_model=APIResponse[EvaluationResponse], status_code=status.HTTP_201_CREATED)
async def create_evaluation(
    request: Request,
    body: EvaluationCreate,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    # EvaluationCreate has no organization_id: the evaluation belongs to the referenced partner's
    # organization, which must be visible to the caller (regular users: their token org).
    partner = await partner_service.get_partner_by_id(db, body.partner_id, scope_org(current_user))
    if not partner:
        raise _partner_not_found()
    org_id = create_org(current_user, partner.organization_id)
    evaluator_id = UUID(current_user.sub)
    data = body.model_dump()
    existing = await evaluation_service.find_existing_evaluation(
        db,
        organization_id=org_id,
        partner_id=data.get("partner_id"),
        project_id=data.get("project_id"),
        evaluator_id=evaluator_id,
    )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "DUPLICATE_EVALUATION",
                "message": "同一評価者・同一対象・同一案件の評価は既に登録されています。",
            },
        )
    evaluation = await evaluation_service.create_evaluation(db, org_id, evaluator_id, data)
    await db.flush()
    await evaluation_service.update_partner_rating(db, body.partner_id, org_id)
    await db.refresh(evaluation)
    return APIResponse(data=_evaluation_to_response(evaluation))


@eval_router.get("", response_model=APIResponse[list[EvaluationResponse]])
async def list_evaluations(
    request: Request,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    partner_id: UUID | None = Query(None),
    project_id: UUID | None = Query(None),
    organization_id: UUID | None = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    evaluations, total = await evaluation_service.list_evaluations(
        db,
        organization_id=scope_org(current_user, organization_id),
        page=page,
        per_page=per_page,
        partner_id=partner_id,
        project_id=project_id,
    )
    total_pages = max((total + per_page - 1) // per_page, 1) if total > 0 else 0
    return APIResponse(
        data=[_evaluation_to_response(e) for e in evaluations],
        meta={
            "page": page,
            "per_page": per_page,
            "total": total,
            "total_pages": total_pages,
        },
    )
