"""Embedding エンドポイント"""

import logging
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ..middleware.auth import TokenData, get_current_user
from ..models.base import get_db
from ..schemas import (
    EmbeddingRequest,
    EmbeddingSearchRequest,
    EmbeddingSearchResult,
)
from ..services.embedding_service import EmbeddingService

logger = logging.getLogger(__name__)
router = APIRouter()


def _get_embedding_service() -> EmbeddingService:
    return EmbeddingService()


@router.post("/embeddings")
async def create_embeddings(
    body: EmbeddingRequest,
    token_data: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = UUID(token_data.org) if token_data.org else UUID(int=0)
    service = _get_embedding_service()

    from ..config import get_settings
    use_mock = not get_settings().LLM_API_KEY

    try:
        embeddings = await service.store_embedding(
            db=db,
            organization_id=org_id,
            source_type=body.source_type,
            source_id=body.source_id,
            content=body.content,
            metadata=body.metadata,
            chunk_size=body.chunk_size,
            chunk_overlap=body.chunk_overlap,
            use_mock=use_mock,
        )
    finally:
        await service.close()

    return {
        "success": True,
        "data": {
            "embeddings_created": len(embeddings),
            "source_type": body.source_type,
            "source_id": str(body.source_id),
        },
    }


@router.post("/embeddings/search")
async def search_embeddings(
    body: EmbeddingSearchRequest,
    token_data: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = UUID(token_data.org) if token_data.org else UUID(int=0)
    service = _get_embedding_service()

    from ..config import get_settings
    use_mock = not get_settings().LLM_API_KEY

    try:
        results = await service.vector_search(
            db=db,
            query=body.query,
            top_k=body.top_k,
            organization_id=org_id,
            source_type=body.source_type,
            filters=body.filters,
            use_mock=use_mock,
        )
    finally:
        await service.close()

    search_results = [
        EmbeddingSearchResult(
            id=r["id"],
            source_type=r["source_type"],
            source_id=r["source_id"],
            chunk_index=r["chunk_index"],
            content=r["content"],
            similarity=r["similarity"],
            metadata=r["metadata"],
        )
        for r in results
    ]

    return {
        "success": True,
        "data": {"results": [r.model_dump() for r in search_results]},
    }


@router.delete("/embeddings/{source_type}/{source_id}")
async def delete_embeddings(
    source_type: str,
    source_id: UUID,
    token_data: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = UUID(token_data.org) if token_data.org else UUID(int=0)
    service = _get_embedding_service()
    try:
        count = await service.delete_embeddings(db, org_id, source_type, source_id)
    finally:
        await service.close()

    return {"success": True, "data": {"deleted": count}}
