"""Image analysis API endpoints."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from ..middleware.auth import TokenData, get_current_user
from ..middleware.tenant import create_org, scope_org
from ..models.base import get_db
from ..schemas import APIResponse, ImageAnalyzeRequest
from ..services import vision_service

router = APIRouter()


def _analysis_to_response(analysis) -> dict:
    return {
        "id": str(analysis.id),
        "organization_id": str(analysis.organization_id),
        "file_key": analysis.file_key,
        "analysis_type": analysis.analysis_type,
        "results": analysis.results,
        "confidence": analysis.confidence,
        "processing_time_ms": analysis.processing_time_ms,
        "model_used": analysis.model_used,
        "status": analysis.status,
        "created_at": analysis.created_at.isoformat() if analysis.created_at else None,
    }


@router.post("/vision/analyze", status_code=status.HTTP_201_CREATED)
async def analyze_image(
    body: ImageAnalyzeRequest,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    analysis = await vision_service.create_image_analysis(
        db,
        organization_id=create_org(current_user, body.organization_id),
        file_key=body.file_key,
        analysis_type=body.analysis_type,
        results={},
        status="processing",
    )
    return APIResponse(data=_analysis_to_response(analysis))


@router.get("/vision/analyses")
async def list_analyses(
    organization_id: UUID | None = Query(None),
    analysis_type: str | None = Query(None),
    status_filter: str | None = Query(None, alias="status"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    analyses = await vision_service.get_image_analyses(
        db,
        organization_id=scope_org(current_user, organization_id),
        analysis_type=analysis_type,
        status=status_filter,
        skip=skip,
        limit=limit,
    )
    return APIResponse(data=[_analysis_to_response(a) for a in analyses])


@router.get("/vision/analyses/{analysis_id}")
async def get_analysis(
    analysis_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    analysis = await vision_service.get_image_analysis_by_id(
        db, analysis_id, scope_org(current_user)
    )
    if not analysis:
        raise HTTPException(
            status_code=404,
            detail={"code": "NOT_FOUND", "message": "Image analysis not found."},
        )
    return APIResponse(data=_analysis_to_response(analysis))
