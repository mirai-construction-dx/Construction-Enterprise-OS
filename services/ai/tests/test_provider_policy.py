"""ADR-0008 是正: 本番相当の環境では LLM Provider を直接呼ばない（fail closed）。

外部送信は httpx.AsyncClient.send を差し替えて数える。実際の通信は一度も発生しない。
"""

import json
from uuid import uuid4

import httpx
import pytest
from fastapi import HTTPException

from src.config import Settings, get_settings
from src.services.provider_policy import (
    DIRECT_LLM_ALLOWED_ENVIRONMENTS,
    LLMMode,
    resolve_llm_mode,
)
from fastapi.testclient import TestClient

from tests import test_ai
from tests.test_ai import _auth_headers

DEV_ENVS = ["development", "test", "docker"]
NONDEV_ENVS = ["production", "staging", "Production", "STAGING", "prod", "stg", ""]


def _settings(env: str, key: str, flag: bool) -> Settings:
    return Settings(
        ENVIRONMENT=env,
        LLM_API_KEY=key,
        ALLOW_DIRECT_LLM_IN_NONDEV=flag,
        JWT_PUBLIC_KEY="unit-test-key",
    )


# ---------------------------------------------------------------- 判定関数（環境 × キー × フラグ）


class TestResolveLLMMode:
    def test_allowed_environments_are_dev_only(self):
        assert DIRECT_LLM_ALLOWED_ENVIRONMENTS == {"development", "test", "docker"}

    def test_flag_defaults_to_false(self):
        assert (
            Settings(JWT_PUBLIC_KEY="unit-test-key").ALLOW_DIRECT_LLM_IN_NONDEV is False
        )

    @pytest.mark.parametrize("env", DEV_ENVS + NONDEV_ENVS)
    @pytest.mark.parametrize("flag", [False, True])
    def test_no_key_is_always_mock(self, env, flag):
        assert resolve_llm_mode(_settings(env, "", flag)) is LLMMode.MOCK

    @pytest.mark.parametrize("env", DEV_ENVS)
    @pytest.mark.parametrize("flag", [False, True])
    def test_dev_with_key_is_direct(self, env, flag):
        assert resolve_llm_mode(_settings(env, "k", flag)) is LLMMode.DIRECT

    @pytest.mark.parametrize("env", NONDEV_ENVS)
    def test_nondev_with_key_without_flag_fails_closed(self, env):
        with pytest.raises(HTTPException) as exc:
            resolve_llm_mode(_settings(env, "k", False))
        assert exc.value.status_code == 503
        assert exc.value.detail["code"] == "AI_PROVIDER_DISABLED"

    @pytest.mark.parametrize("env", NONDEV_ENVS)
    def test_nondev_with_key_and_explicit_flag_is_direct(self, env):
        assert resolve_llm_mode(_settings(env, "k", True)) is LLMMode.DIRECT


@pytest.fixture
def client():
    # test_ai.py と同じ DB モックのアプリ（fixture 本体を再利用する）
    return TestClient(test_ai.app.__wrapped__())


# ---------------------------------------------------------------- 3 経路すべて（/chat・/rag・/embeddings）


class _Sends:
    def __init__(self):
        self.urls: list[str] = []


@pytest.fixture
def sends(monkeypatch):
    """httpx.AsyncClient.send を差し替え、外部送信を数える（実通信はしない）。"""
    rec = _Sends()

    async def fake_send(self, request, **kwargs):
        rec.urls.append(str(request.url))
        path = request.url.path
        if path.endswith("/embeddings"):
            payload = json.loads(request.content or b"{}")
            n = (
                len(payload.get("input", []))
                if isinstance(payload.get("input"), list)
                else 1
            )
            body = {"data": [{"embedding": [0.0] * 1536} for _ in range(max(n, 1))]}
            return httpx.Response(200, json=body, request=request)
        if kwargs.get("stream") or b'"stream": true' in (request.content or b""):
            text = 'data: {"choices":[{"delta":{"content":"x"}}]}\n\ndata: [DONE]\n\n'
            return httpx.Response(200, text=text, request=request)
        body = {"choices": [{"message": {"content": "direct"}}]}
        return httpx.Response(200, json=body, request=request)

    monkeypatch.setattr(httpx.AsyncClient, "send", fake_send)
    return rec


@pytest.fixture
def env(monkeypatch):
    """キャッシュ済み Settings の値を一時的に書き換える。"""
    s = get_settings()

    def set_env(environment: str, key: str, flag: bool) -> None:
        monkeypatch.setattr(s, "ENVIRONMENT", environment)
        monkeypatch.setattr(s, "LLM_API_KEY", key)
        monkeypatch.setattr(s, "ALLOW_DIRECT_LLM_IN_NONDEV", flag)

    return set_env


ROUTES = [
    ("/api/v1/ai/chat", {"messages": [{"role": "user", "content": "hello"}]}),
    ("/api/v1/ai/chat/stream", {"messages": [{"role": "user", "content": "hello"}]}),
    ("/api/v1/ai/rag/search", {"query": "safety", "top_k": 3}),
    ("/api/v1/ai/rag/generate", {"query": "safety", "top_k": 3}),
    (
        "/api/v1/ai/embeddings",
        {
            "source_type": "document",
            "source_id": str(uuid4()),
            "content": "construction safety",
            "chunk_size": 500,
            "chunk_overlap": 50,
        },
    ),
    ("/api/v1/ai/embeddings/search", {"query": "safety", "top_k": 5}),
]


class TestRoutesNeverSendInNonDev:
    @pytest.mark.parametrize("path,body", ROUTES)
    @pytest.mark.parametrize("environment", ["production", "staging"])
    def test_key_without_flag_returns_503_and_sends_nothing(
        self, client, sends, env, path, body, environment
    ):
        env(environment, "configured-key", False)
        res = client.post(path, json=body, headers=_auth_headers())
        assert res.status_code == 503
        assert res.json()["detail"]["code"] == "AI_PROVIDER_DISABLED"
        assert sends.urls == []

    @pytest.mark.parametrize("path,body", ROUTES)
    @pytest.mark.parametrize("environment", ["production", "staging"])
    def test_no_key_uses_mock_and_sends_nothing(
        self, client, sends, env, path, body, environment
    ):
        env(environment, "", False)
        res = client.post(path, json=body, headers=_auth_headers())
        assert res.status_code == 200
        assert sends.urls == []

    @pytest.mark.parametrize("path,body", ROUTES)
    def test_explicit_flag_allows_direct(self, client, sends, env, path, body):
        env("production", "configured-key", True)
        res = client.post(path, json=body, headers=_auth_headers())
        assert res.status_code == 200
        assert sends.urls, "明示フラグがあるときだけ直接呼び出しが行われる"


class TestRoutesDirectInDev:
    """対照: 開発系の環境でキーがあれば直接呼び出しの経路に入る（上の 0 件が空振りでないことの確認）。"""

    @pytest.mark.parametrize("path,body", ROUTES)
    def test_dev_with_key_sends(self, client, sends, env, path, body):
        env("development", "configured-key", False)
        res = client.post(path, json=body, headers=_auth_headers())
        assert res.status_code == 200
        assert sends.urls

    @pytest.mark.parametrize("path,body", ROUTES)
    def test_dev_without_key_sends_nothing(self, client, sends, env, path, body):
        env("development", "", False)
        res = client.post(path, json=body, headers=_auth_headers())
        assert res.status_code == 200
        assert sends.urls == []
