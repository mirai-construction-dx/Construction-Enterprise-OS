"""RAG (Retrieval Augmented Generation) パイプライン"""

import logging
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..models import PromptTemplate
from .embedding_service import EmbeddingService
from .llm_service import LLMProvider

logger = logging.getLogger(__name__)
settings = get_settings()

DEFAULT_RAG_SYSTEM_PROMPT = """あなたは建設業向けAIアシスタントです。
以下の参照情報に基づいて、ユーザーの質問に正確に回答してください。
参照情報に記載されていない内容については、「わかりません」と正直に答えてください。
参照情報のどの部分に基づいて回答したかを明示してください。"""

DEFAULT_RAG_USER_TEMPLATE = """参照情報:
{% for chunk in chunks %}
[出典 {{ loop.index }}] {{ chunk.content }}
{% endfor %}

質問: {{ query }}

上記の参照情報に基づいて回答してください。"""


class RAGService:
    def __init__(
        self,
        embedding_service: EmbeddingService,
        llm_provider: LLMProvider,
    ):
        self.embedding_service = embedding_service
        self.llm_provider = llm_provider

    async def semantic_search(
        self,
        db: AsyncSession,
        query: str,
        top_k: int = 5,
        organization_id: UUID | None = None,
        source_type: str | None = None,
        filters: dict | None = None,
        use_mock: bool = False,
    ) -> list[dict]:
        return await self.embedding_service.vector_search(
            db=db,
            query=query,
            top_k=top_k,
            organization_id=organization_id,
            source_type=source_type,
            filters=filters,
            use_mock=use_mock,
        )

    async def generate_with_context(
        self,
        db: AsyncSession,
        query: str,
        context_chunks: list[dict],
        prompt_template_id: UUID | None = None,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        organization_id: UUID | None = None,
    ) -> tuple[str, list[dict]]:
        if prompt_template_id:
            stmt = select(PromptTemplate).where(PromptTemplate.id == prompt_template_id)
            if organization_id is not None:
                stmt = stmt.where(PromptTemplate.organization_id == organization_id)
            result = await db.execute(stmt)
            template = result.scalar_one_or_none()
            if template:
                system_prompt = template.system_prompt
                user_template = template.user_prompt_template
                model = model or template.model
                temperature = temperature if temperature is not None else template.temperature
                max_tokens = max_tokens or template.max_tokens
            else:
                system_prompt = DEFAULT_RAG_SYSTEM_PROMPT
                user_template = DEFAULT_RAG_USER_TEMPLATE
        else:
            system_prompt = DEFAULT_RAG_SYSTEM_PROMPT
            user_template = DEFAULT_RAG_USER_TEMPLATE
            model = model or settings.LLM_DEFAULT_MODEL
            temperature = temperature if temperature is not None else 0.7
            max_tokens = max_tokens or 2000

        from jinja2 import Template
        user_prompt = Template(user_template).render(
            query=query, chunks=context_chunks
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        answer = await self.llm_provider.complete(
            messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
        )

        return answer, context_chunks
