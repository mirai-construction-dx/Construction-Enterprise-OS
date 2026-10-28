"""LLM Provider 抽象化レイヤー"""

import logging
from abc import ABC, abstractmethod
from typing import AsyncGenerator

import httpx

from ..config import get_settings
from . import send_audit

logger = logging.getLogger(__name__)
settings = get_settings()


class LLMProvider(ABC):
    @abstractmethod
    async def complete(self, messages: list[dict], **kwargs) -> str:
        pass

    @abstractmethod
    def stream_complete(
        self, messages: list[dict], **kwargs
    ) -> AsyncGenerator[str, None]: ...

    @abstractmethod
    async def close(self): ...


class OpenAICompatibleProvider(LLMProvider):
    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        default_model: str | None = None,
    ):
        self.base_url = (base_url or settings.LLM_BASE_URL).rstrip("/")
        self.api_key = api_key or settings.LLM_API_KEY
        self.default_model = default_model or settings.LLM_DEFAULT_MODEL
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                timeout=httpx.Timeout(120.0),
            )
        return self._client

    async def complete(self, messages: list[dict], **kwargs) -> str:
        model = kwargs.get("model", self.default_model)
        temperature = kwargs.get("temperature", 0.7)
        max_tokens = kwargs.get("max_tokens", 2000)

        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        client = await self._get_client()
        request = client.build_request(
            "POST", f"{self.base_url}/chat/completions", json=payload
        )
        resp = await send_audit.audited_send(
            client,
            request,
            api="chat.completions",
            provider=send_audit.provider_host(self.base_url),
            model=model,
        )
        data = resp.json()
        return data["choices"][0]["message"]["content"]

    async def stream_complete(
        self, messages: list[dict], **kwargs
    ) -> AsyncGenerator[str, None]:
        model = kwargs.get("model", self.default_model)
        temperature = kwargs.get("temperature", 0.7)
        max_tokens = kwargs.get("max_tokens", 2000)

        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
        }

        client = await self._get_client()
        request = client.build_request(
            "POST", f"{self.base_url}/chat/completions", json=payload
        )
        resp = await send_audit.audited_send(
            client,
            request,
            api="chat.completions",
            provider=send_audit.provider_host(self.base_url),
            model=model,
            stream=True,
        )
        try:
            async for line in resp.aiter_lines():
                if line.startswith("data: ") and line != "data: [DONE]":
                    import json

                    try:
                        chunk = json.loads(line[6:])
                        delta = (
                            chunk.get("choices", [{}])[0]
                            .get("delta", {})
                            .get("content", "")
                        )
                        if delta:
                            yield delta
                    except json.JSONDecodeError:
                        continue
        finally:
            await resp.aclose()

    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None


class MockLLMProvider(LLMProvider):
    async def complete(self, messages: list[dict], **kwargs) -> str:
        last_message = messages[-1]["content"] if messages else ""
        return f"Mock response to: {last_message[:100]}..."

    async def stream_complete(
        self, messages: list[dict], **kwargs
    ) -> AsyncGenerator[str, None]:
        last_message = messages[-1]["content"] if messages else ""
        text = f"Mock response to: {last_message[:100]}..."
        for word in text.split():
            yield word + " "

    async def close(self):
        pass
