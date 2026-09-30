"""RAG 検索 + 生成エンドポイント"""

import logging

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ..middleware.auth import TokenData, get_current_user
from ..middleware.tenant import scope_org
from ..models.base import get_db
from ..schemas import (
    EmbeddingSearchResult,
    RAGGenerateRequest,
    RAGSearchRequest,
)
from ..services.embedding_service import EmbeddingService
from ..services.llm_service import (
    LLMProvider,
    MockLLMProvider,
    OpenAICompatibleProvider,
)
from ..services.rag_service import RAGService

logger = logging.getLogger(__name__)
router = APIRouter()


def _get_rag_service() -> RAGService:
    from ..config import get_settings

    s = get_settings()
    embedding_service = EmbeddingService()
    llm_provider: LLMProvider
    if s.LLM_API_KEY:
        llm_provider = OpenAICompatibleProvider()
    else:
        llm_provider = MockLLMProvider()
    return RAGService(embedding_service, llm_provider)


@router.post("/rag/search")
async def rag_search(
    body: RAGSearchRequest,
    token_data: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = scope_org(token_data)
    service = _get_rag_service()

    from ..config import get_settings

    use_mock = not get_settings().LLM_API_KEY

    try:
        results = await service.semantic_search(
            db=db,
            query=body.query,
            top_k=body.top_k,
            organization_id=org_id,
            source_type=body.source_type,
            filters=body.filters,
            use_mock=use_mock,
        )
    finally:
        await service.llm_provider.close()
        await service.embedding_service.close()

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


@router.post("/rag/generate")
async def rag_generate(
    body: RAGGenerateRequest,
    token_data: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = scope_org(token_data)
    service = _get_rag_service()

    from ..config import get_settings

    use_mock = not get_settings().LLM_API_KEY

    try:
        chunks = await service.semantic_search(
            db=db,
            query=body.query,
            top_k=body.top_k,
            organization_id=org_id,
            source_type=body.source_type,
            filters=body.filters,
            use_mock=use_mock,
        )

        answer, sources = await service.generate_with_context(
            db=db,
            query=body.query,
            context_chunks=chunks,
            prompt_template_id=body.prompt_template_id,
            model=body.model,
            temperature=body.temperature,
            max_tokens=body.max_tokens,
            organization_id=org_id,
        )
    finally:
        await service.llm_provider.close()
        await service.embedding_service.close()

    source_results = [
        EmbeddingSearchResult(
            id=s["id"],
            source_type=s["source_type"],
            source_id=s["source_id"],
            chunk_index=s["chunk_index"],
            content=s["content"],
            similarity=s["similarity"],
            metadata=s["metadata"],
        )
        for s in sources
    ]

    return {
        "success": True,
        "data": {
            "answer": answer,
            "sources": [r.model_dump() for r in source_results],
            "usage": None,
        },
    }
