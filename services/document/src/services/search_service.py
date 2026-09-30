"""検索サービスラッパー（Elasticsearch プレースホルダー）"""

import logging
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Document

logger = logging.getLogger(__name__)


async def search_documents(
    db: AsyncSession,
    organization_id: UUID | None,
    query: str | None = None,
    document_type: str | None = None,
    status: str | None = None,
    project_id: UUID | None = None,
    tags: list[str] | None = None,
) -> list[Document]:
    # None means no org filter; only allowed for a cross-org admin (ADR-0004).
    stmt = select(Document)
    if organization_id is not None:
        stmt = stmt.where(Document.organization_id == organization_id)

    if query:
        search_term = f"%{query}%"
        stmt = stmt.where(
            or_(
                Document.name.ilike(search_term),
                Document.description.ilike(search_term),
            )
        )

    if document_type:
        stmt = stmt.where(Document.document_type == document_type)

    if status:
        stmt = stmt.where(Document.status == status)

    if project_id:
        stmt = stmt.where(Document.project_id == project_id)

    if tags:
        stmt = stmt.where(Document.tags.overlap(tags))

    stmt = stmt.order_by(Document.created_at.desc())

    result = await db.execute(stmt)
    return list(result.scalars().all())


async def count_search_documents(
    db: AsyncSession,
    organization_id: UUID | None,
    query: str | None = None,
    document_type: str | None = None,
    status: str | None = None,
    project_id: UUID | None = None,
    tags: list[str] | None = None,
) -> int:
    stmt = select(func.count(Document.id))
    if organization_id is not None:
        stmt = stmt.where(Document.organization_id == organization_id)

    if query:
        search_term = f"%{query}%"
        stmt = stmt.where(
            or_(
                Document.name.ilike(search_term),
                Document.description.ilike(search_term),
            )
        )

    if document_type:
        stmt = stmt.where(Document.document_type == document_type)

    if status:
        stmt = stmt.where(Document.status == status)

    if project_id:
        stmt = stmt.where(Document.project_id == project_id)

    if tags:
        stmt = stmt.where(Document.tags.overlap(tags))

    result = await db.execute(stmt)
    return result.scalar() or 0
