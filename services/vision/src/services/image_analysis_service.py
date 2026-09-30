"""Image analysis service — CRUD operations for ImageAnalysis model."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import ImageAnalysis


async def create_image_analysis(
    db: AsyncSession,
    organization_id: UUID,
    file_key: str,
    analysis_type: str,
    results: dict,
    confidence: float | None = None,
    processing_time_ms: int | None = None,
    model_used: str | None = None,
    status: str = "completed",
) -> ImageAnalysis:
    analysis = ImageAnalysis(
        organization_id=organization_id,
        file_key=file_key,
        analysis_type=analysis_type,
        results=results,
        confidence=confidence,
        processing_time_ms=processing_time_ms,
        model_used=model_used,
        status=status,
    )
    db.add(analysis)
    await db.flush()
    return analysis


async def get_image_analyses(
    db: AsyncSession,
    organization_id: UUID | None = None,
    analysis_type: str | None = None,
    status: str | None = None,
    skip: int = 0,
    limit: int = 50,
) -> list[ImageAnalysis]:
    stmt = select(ImageAnalysis)
    if organization_id is not None:
        stmt = stmt.where(ImageAnalysis.organization_id == organization_id)
    if analysis_type:
        stmt = stmt.where(ImageAnalysis.analysis_type == analysis_type)
    if status:
        stmt = stmt.where(ImageAnalysis.status == status)
    stmt = stmt.order_by(ImageAnalysis.created_at.desc()).offset(skip).limit(limit)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_image_analysis_by_id(
    db: AsyncSession, analysis_id: UUID, organization_id: UUID | None = None
) -> ImageAnalysis | None:
    stmt = select(ImageAnalysis).where(ImageAnalysis.id == analysis_id)
    if organization_id is not None:
        stmt = stmt.where(ImageAnalysis.organization_id == organization_id)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()
