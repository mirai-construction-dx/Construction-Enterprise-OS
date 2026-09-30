"""OCR service — CRUD operations for OCRResult model."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import OCRResult


async def create_ocr_result(
    db: AsyncSession,
    organization_id: UUID,
    extracted_text: str,
    document_id: UUID | None = None,
    file_key: str | None = None,
    language: str = "ja",
    confidence: float | None = None,
    page_count: int | None = None,
    processing_time_ms: int | None = None,
    entities: dict | None = None,
    status: str = "completed",
    error_message: str | None = None,
    processed_by: str | None = None,
) -> OCRResult:
    ocr = OCRResult(
        organization_id=organization_id,
        document_id=document_id,
        file_key=file_key,
        language=language,
        extracted_text=extracted_text,
        confidence=confidence,
        page_count=page_count,
        processing_time_ms=processing_time_ms,
        entities=entities or {},
        status=status,
        error_message=error_message,
        processed_by=processed_by,
    )
    db.add(ocr)
    await db.flush()
    return ocr


async def get_ocr_results(
    db: AsyncSession,
    organization_id: UUID | None = None,
    status: str | None = None,
    document_id: UUID | None = None,
    skip: int = 0,
    limit: int = 50,
) -> list[OCRResult]:
    stmt = select(OCRResult)
    if organization_id is not None:
        stmt = stmt.where(OCRResult.organization_id == organization_id)
    if status:
        stmt = stmt.where(OCRResult.status == status)
    if document_id:
        stmt = stmt.where(OCRResult.document_id == document_id)
    stmt = stmt.order_by(OCRResult.created_at.desc()).offset(skip).limit(limit)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_ocr_result_by_id(
    db: AsyncSession, result_id: UUID, organization_id: UUID | None = None
) -> OCRResult | None:
    stmt = select(OCRResult).where(OCRResult.id == result_id)
    if organization_id is not None:
        stmt = stmt.where(OCRResult.organization_id == organization_id)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()
