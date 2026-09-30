"""Embedding 生成サービス"""

import logging
from uuid import UUID

import httpx
from sqlalchemy import delete, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..models import Embedding

logger = logging.getLogger(__name__)
settings = get_settings()


class EmbeddingService:
    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        embedding_model: str | None = None,
    ):
        self.base_url = (base_url or settings.LLM_BASE_URL).rstrip("/")
        self.api_key = api_key or settings.LLM_API_KEY
        self.embedding_model = embedding_model or settings.LLM_EMBEDDING_MODEL
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                timeout=httpx.Timeout(60.0),
            )
        return self._client

    def chunk_text(self, text: str, chunk_size: int = 500, overlap: int = 50) -> list[str]:
        if not text.strip():
            return []
        if len(text) <= chunk_size:
            return [text]

        chunks = []
        start = 0
        while start < len(text):
            end = min(start + chunk_size, len(text))
            chunks.append(text[start:end])
            start += chunk_size - overlap
        return chunks

    async def generate_embedding(self, text: str) -> list[float]:
        client = await self._get_client()
        resp = await client.post(
            f"{self.base_url}/embeddings",
            json={"model": self.embedding_model, "input": text},
        )
        resp.raise_for_status()
        data = resp.json()
        return data["data"][0]["embedding"]

    async def mock_embedding(self, text: str) -> list[float]:
        import hashlib
        dims = 1536
        h = hashlib.sha256(text.encode()).digest()
        vec = []
        for i in range(dims):
            byte_idx = i % len(h)
            val = (h[byte_idx] / 255.0) * 2 - 1
            vec.append(val)
        return vec

    async def batch_embed(self, texts: list[str]) -> list[list[float]]:
        client = await self._get_client()
        resp = await client.post(
            f"{self.base_url}/embeddings",
            json={"model": self.embedding_model, "input": texts},
        )
        resp.raise_for_status()
        data = resp.json()
        return [item["embedding"] for item in data["data"]]

    async def mock_batch_embed(self, texts: list[str]) -> list[list[float]]:
        results = []
        for t in texts:
            results.append(await self.mock_embedding(t))
        return results

    async def store_embedding(
        self,
        db: AsyncSession,
        organization_id: UUID,
        source_type: str,
        source_id: UUID,
        content: str,
        metadata: dict | None = None,
        chunk_size: int = 500,
        chunk_overlap: int = 50,
        use_mock: bool = False,
    ) -> list[Embedding]:
        chunks = self.chunk_text(content, chunk_size, chunk_overlap)
        texts = [c for c in chunks]

        if use_mock:
            vectors = await self.mock_batch_embed(texts)
        else:
            vectors = await self.batch_embed(texts)

        embeddings = []
        for idx, (chunk_text, vector) in enumerate(zip(texts, vectors)):
            embedding = Embedding(
                organization_id=organization_id,
                source_type=source_type,
                source_id=source_id,
                chunk_index=idx,
                content=chunk_text,
                embedding=vector,
                metadata_=metadata or {},
            )
            db.add(embedding)
            embeddings.append(embedding)

        await db.flush()
        return embeddings

    async def vector_search(
        self,
        db: AsyncSession,
        query: str,
        top_k: int = 5,
        organization_id: UUID | None = None,
        source_type: str | None = None,
        filters: dict | None = None,
        use_mock: bool = False,
    ) -> list[dict]:
        if use_mock:
            query_embedding = await self.mock_embedding(query)
        else:
            query_embedding = await self.generate_embedding(query)

        embedding_str = "[" + ",".join(str(v) for v in query_embedding) + "]"

        query_sql = """
            SELECT
                id, source_type, source_id, chunk_index, content, metadata,
                1 - (embedding <=> :embedding) AS similarity
            FROM ai.embeddings
            WHERE embedding IS NOT NULL
        """
        params = {"embedding": embedding_str, "top_k": top_k}

        if organization_id is not None:
            query_sql += " AND organization_id = :org_id"
            params["org_id"] = organization_id
        if source_type is not None:
            query_sql += " AND source_type = :source_type"
            params["source_type"] = source_type

        query_sql += " ORDER BY embedding <=> :embedding LIMIT :top_k"

        result = await db.execute(text(query_sql), params)
        rows = result.fetchall()

        return [
            {
                "id": row[0],
                "source_type": row[1],
                "source_id": row[2],
                "chunk_index": row[3],
                "content": row[4],
                "similarity": float(row[6]) if row[6] is not None else 0.0,
                "metadata": row[5],
            }
            for row in rows
        ]

    async def delete_embeddings(
        self,
        db: AsyncSession,
        source_type: str,
        source_id: UUID,
        organization_id: UUID | None = None,
    ) -> int:
        stmt = delete(Embedding).where(
            Embedding.source_type == source_type,
            Embedding.source_id == source_id,
        )
        if organization_id is not None:
            stmt = stmt.where(Embedding.organization_id == organization_id)
        result = await db.execute(stmt)
        return result.rowcount

    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None
