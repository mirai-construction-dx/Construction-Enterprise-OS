"""Vector index service — CRUD operations and search stub for VectorIndex model."""

from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import VectorIndex


async def create_vector_index(
    db: AsyncSession,
    organization_id: UUID,
    collection_name: str,
    dimension: int,
    index_type: str = "ivfflat",
    metric: str = "cosine",
) -> VectorIndex:
    vi = VectorIndex(
        organization_id=organization_id,
        collection_name=collection_name,
        dimension=dimension,
        index_type=index_type,
        metric=metric,
    )
    db.add(vi)
    await db.flush()
    return vi


async def get_vector_indices(
    db: AsyncSession,
    organization_id: UUID | None = None,
    is_active: bool | None = None,
    skip: int = 0,
    limit: int = 50,
) -> list[VectorIndex]:
    stmt = select(VectorIndex)
    if organization_id is not None:
        stmt = stmt.where(VectorIndex.organization_id == organization_id)
    if is_active is not None:
        stmt = stmt.where(VectorIndex.is_active == is_active)
    stmt = stmt.order_by(VectorIndex.created_at.desc()).offset(skip).limit(limit)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_vector_index_by_id(
    db: AsyncSession, index_id: UUID, organization_id: UUID | None = None
) -> VectorIndex | None:
    stmt = select(VectorIndex).where(VectorIndex.id == index_id)
    if organization_id is not None:
        stmt = stmt.where(VectorIndex.organization_id == organization_id)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def update_vector_index(
    db: AsyncSession,
    index_id: UUID,
    is_active: bool | None = None,
    document_count: int | None = None,
    total_vectors: int | None = None,
    organization_id: UUID | None = None,
) -> VectorIndex | None:
    vi = await get_vector_index_by_id(db, index_id, organization_id)
    if not vi:
        return None
    if is_active is not None:
        vi.is_active = is_active
    if document_count is not None:
        vi.document_count = document_count
    if total_vectors is not None:
        vi.total_vectors = total_vectors
    await db.flush()
    return vi


async def delete_vector_index(
    db: AsyncSession, index_id: UUID, organization_id: UUID | None = None
) -> bool:
    stmt = delete(VectorIndex).where(VectorIndex.id == index_id)
    if organization_id is not None:
        stmt = stmt.where(VectorIndex.organization_id == organization_id)
    result = await db.execute(stmt)
    await db.flush()
    return result.rowcount > 0


async def increment_vector_counts(
    db: AsyncSession,
    index_id: UUID,
    added_docs: int,
    added_vectors: int,
    organization_id: UUID | None = None,
) -> VectorIndex | None:
    vi = await get_vector_index_by_id(db, index_id, organization_id)
    if not vi:
        return None
    vi.document_count += added_docs
    vi.total_vectors += added_vectors
    await db.flush()
    return vi


def build_search_results(query_text: str, top_k: int) -> list[dict]:
    """Return stub search results until a real embedding backend is wired up."""
    return [
        {
            "source_id": str(UUID("00000000-0000-0000-0000-000000000001")),
            "source_type": "document",
            "chunk_index": i,
            "content": f"Mock result {i + 1} for query: {query_text[:30]}",
            "similarity": round(0.95 - (i * 0.1), 2),
            "metadata": {"score": 0.95 - i * 0.1},
        }
        for i in range(min(top_k, 5))
    ]
