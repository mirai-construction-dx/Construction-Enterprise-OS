"""AI設計照査エンドポイント"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from ..middleware.auth import TokenData, get_current_user
from ..middleware.tenant import create_org, scope_org
from ..models.base import get_db
from ..schemas import (
    APIResponse,
    ComplianceReportResponse,
    DesignReviewCreateRequest,
    DesignReviewResponse,
    DesignReviewUpdateRequest,
)
from ..services.advanced_service import (
    create_design_review,
    get_design_review_by_id,
    list_design_reviews,
    update_design_review,
    delete_design_review,
    get_compliance_report,
)

router = APIRouter()


def _to_response(record) -> DesignReviewResponse:
    return DesignReviewResponse(
        id=record.id,
        organization_id=record.organization_id,
        project_id=record.project_id,
        design_document_id=record.design_document_id,
        review_type=record.review_type,
        status=record.status,
        ai_suggestions=record.ai_suggestions if record.ai_suggestions else [],
        compliance_checks=record.compliance_checks if record.compliance_checks else {},
        reviewer_id=record.reviewer_id,
        reviewed_at=record.reviewed_at,
        created_at=record.created_at,
    )


@router.post("", response_model=APIResponse[DesignReviewResponse], status_code=status.HTTP_201_CREATED)
async def create_review(
    request: Request,
    body: DesignReviewCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    data = body.model_dump()
    data["organization_id"] = create_org(current_user, body.organization_id)
    record = await create_design_review(db, data)
    return APIResponse(data=_to_response(record))


@router.get("", response_model=APIResponse)
async def list_reviews(
    request: Request,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    review_type: str | None = Query(None),
    status: str | None = Query(None),
    project_id: UUID | None = Query(None),
    organization_id: UUID | None = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    records, total = await list_design_reviews(
        db,
        page=page,
        per_page=per_page,
        review_type=review_type,
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


@router.get("/{review_id}", response_model=APIResponse[DesignReviewResponse])
async def get_review(
    request: Request,
    review_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    record = await get_design_review_by_id(db, review_id, scope_org(current_user))
    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "NOT_FOUND", "message": "設計照査が見つかりません。"},
        )
    return APIResponse(data=_to_response(record))


@router.put("/{review_id}", response_model=APIResponse[DesignReviewResponse])
async def update_review(
    request: Request,
    review_id: UUID,
    body: DesignReviewUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    record = await update_design_review(
        db, review_id, body.model_dump(exclude_unset=True), scope_org(current_user)
    )
    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "NOT_FOUND", "message": "設計照査が見つかりません。"},
        )
    return APIResponse(data=_to_response(record))


@router.delete("/{review_id}", response_model=APIResponse)
async def delete_review(
    request: Request,
    review_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    deleted = await delete_design_review(db, review_id, scope_org(current_user))
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "NOT_FOUND", "message": "設計照査が見つかりません。"},
        )
    return APIResponse(data={"message": "設計照査を削除しました。"})


@router.get("/{review_id}/compliance-report", response_model=APIResponse[ComplianceReportResponse])
async def compliance_report_endpoint(
    request: Request,
    review_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    report = await get_compliance_report(db, review_id, scope_org(current_user))
    if not report:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "NOT_FOUND", "message": "設計照査が見つかりません。"},
        )
    return APIResponse(data=report)
