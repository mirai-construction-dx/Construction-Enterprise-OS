"""ADR-0008 是正: AI Provider への送信を監査する（Provider 名を残し、本文は残さない）。

外部送信は httpx.AsyncClient.send を差し替えて模擬する。実際の通信は一度も発生しない。
"""

import json
import logging
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from src.config import get_settings
from src.services import send_audit
from tests import test_ai
from tests.test_ai import _auth_headers

SECRET_MARKER = "BODY-MARKER-7f3a"  # 本文に埋め込む目印。監査に出てはいけない
KEY_VALUE = "sk-audit-test-key-should-not-appear"
BASE_URL = "https://user:pass@llm.example.test:8443/v1?token=q"

REQUIRED_FIELDS = {
    "ts",
    "event",
    "organization_id",
    "actor",
    "actor_type",
    "route",
    "api",
    "stream",
    "provider",
    "model",
    "request_bytes",
    "result",
    "http_status",
    "error_type",
}


@pytest.fixture
def client():
    # 送信失敗時のサーバー側例外を 5xx 応答として受け取る（例外の再送出をしない）
    return TestClient(test_ai.app.__wrapped__(), raise_server_exceptions=False)


@pytest.fixture
def direct_env(monkeypatch):
    """開発環境で直接呼び出しの経路に入れる（キーとエンドポイントを差し替える）。"""
    s = get_settings()
    monkeypatch.setattr(s, "ENVIRONMENT", "development")
    monkeypatch.setattr(s, "LLM_API_KEY", KEY_VALUE)
    monkeypatch.setattr(s, "ALLOW_DIRECT_LLM_IN_NONDEV", False)
    monkeypatch.setattr(s, "LLM_BASE_URL", BASE_URL)
    # サービスはモジュール読み込み時の settings を参照するため同じオブジェクトを使う
    return s


def _provider_ok(monkeypatch, status: int = 200, raise_exc: Exception | None = None):
    sent: list[httpx.Request] = []

    async def fake_send(self, request, **kwargs):
        sent.append(request)
        if raise_exc is not None:
            raise raise_exc
        if status >= 400:
            return httpx.Response(status, json={"error": "x"}, request=request)
        if str(request.url).endswith("/embeddings"):
            payload = json.loads(request.content or b"{}")
            inp = payload.get("input")
            n = len(inp) if isinstance(inp, list) else 1
            body = {"data": [{"embedding": [0.0] * 1536} for _ in range(n)]}
            return httpx.Response(200, json=body, request=request)
        if b'"stream":true' in request.content.replace(b" ", b""):
            text = 'data: {"choices":[{"delta":{"content":"x"}}]}\n\ndata: [DONE]\n\n'
            return httpx.Response(200, text=text, request=request)
        body = {"choices": [{"message": {"content": "direct"}}]}
        return httpx.Response(200, json=body, request=request)

    monkeypatch.setattr(httpx.AsyncClient, "send", fake_send)
    return sent


def _events(caplog) -> list[dict]:
    return [
        json.loads(r.getMessage()) for r in caplog.records if r.name == "ceos_ai.audit"
    ]


def _assert_no_secret(caplog):
    blob = "\n".join(
        r.getMessage() for r in caplog.records if r.name == "ceos_ai.audit"
    )
    for forbidden in (
        SECRET_MARKER,
        KEY_VALUE,
        "Bearer",
        "user:pass",
        "token=q",
        "/v1",
    ):
        assert forbidden not in blob, f"監査に含めてはいけない値が出ている: {forbidden}"


ROUTES = [
    (
        "chat",
        "/api/v1/ai/chat",
        {"messages": [{"role": "user", "content": SECRET_MARKER}]},
        "chat.completions",
    ),
    (
        "chat",
        "/api/v1/ai/chat/stream",
        {"messages": [{"role": "user", "content": SECRET_MARKER}]},
        "chat.completions",
    ),
    (
        "rag",
        "/api/v1/ai/rag/search",
        {"query": SECRET_MARKER, "top_k": 3},
        "embeddings",
    ),
    (
        "embeddings",
        "/api/v1/ai/embeddings/search",
        {"query": SECRET_MARKER, "top_k": 3},
        "embeddings",
    ),
    (
        "embeddings",
        "/api/v1/ai/embeddings",
        {
            "source_type": "document",
            "source_id": str(uuid4()),
            "content": SECRET_MARKER,
            "chunk_size": 500,
            "chunk_overlap": 50,
        },
        "embeddings",
    ),
]


# ---------------------------------------------------------------- 単体


class TestProviderHost:
    @pytest.mark.parametrize(
        "url,host",
        [
            ("https://api.openai.com/v1", "api.openai.com"),
            (BASE_URL, "llm.example.test"),
            ("http://LOCALHOST:11434/v1", "localhost"),
            ("not a url", None),
            ("", None),
        ],
    )
    def test_host_only(self, url, host):
        assert send_audit.provider_host(url) == host


# ---------------------------------------------------------------- 3 経路の送信監査


class TestAuditOnSend:
    @pytest.mark.parametrize("route,path,body,api", ROUTES)
    def test_one_event_per_send_with_required_fields(
        self, client, direct_env, monkeypatch, caplog, route, path, body, api
    ):
        sent = _provider_ok(monkeypatch)
        org = str(uuid4())
        user = str(uuid4())
        with caplog.at_level(logging.INFO, logger="ceos_ai.audit"):
            res = client.post(
                path, json=body, headers=_auth_headers(user_id=user, org_id=org)
            )
        assert res.status_code == 200
        events = _events(caplog)
        assert sent and len(events) == len(sent), "送信 1 回につき監査 1 件"
        for ev in events:
            assert set(ev) == REQUIRED_FIELDS
            assert ev["event"] == "ai.provider_send"
            assert ev["route"] == route
            assert ev["api"] == api
            assert ev["provider"] == "llm.example.test"
            assert ev["organization_id"] == org
            assert ev["actor"] == user
            assert ev["actor_type"] == "user"
            assert ev["result"] == "success"
            assert ev["http_status"] == 200
            assert ev["error_type"] is None
            assert ev["model"]
            assert isinstance(ev["request_bytes"], int) and ev["request_bytes"] > 0
            assert ev["stream"] is path.endswith("/stream")
        _assert_no_secret(caplog)

    def test_request_bytes_is_body_length(
        self, client, direct_env, monkeypatch, caplog
    ):
        sent = _provider_ok(monkeypatch)
        with caplog.at_level(logging.INFO, logger="ceos_ai.audit"):
            client.post(ROUTES[0][1], json=ROUTES[0][2], headers=_auth_headers())
        assert _events(caplog)[0]["request_bytes"] == len(sent[0].content)


class TestAuditOnFailure:
    def test_http_error_is_recorded(self, client, direct_env, monkeypatch, caplog):
        _provider_ok(monkeypatch, status=429)
        with caplog.at_level(logging.INFO, logger="ceos_ai.audit"):
            res = client.post(ROUTES[0][1], json=ROUTES[0][2], headers=_auth_headers())
        assert res.status_code >= 500
        (ev,) = _events(caplog)
        assert (ev["result"], ev["http_status"], ev["error_type"]) == (
            "error",
            429,
            "HTTPStatusError",
        )
        assert ev["provider"] == "llm.example.test"
        _assert_no_secret(caplog)

    @pytest.mark.parametrize("route,path,body,api", ROUTES)
    def test_transport_error_is_recorded(
        self, client, direct_env, monkeypatch, caplog, route, path, body, api
    ):
        _provider_ok(monkeypatch, raise_exc=httpx.ConnectError("boom"))
        with caplog.at_level(logging.INFO, logger="ceos_ai.audit"):
            res = client.post(path, json=body, headers=_auth_headers())
        if path.endswith("/stream"):
            # SSE は応答ヘッダを返した後に送信するため、失敗はストリームの途中で起きる（既存の挙動）
            assert res.status_code == 200
        else:
            assert res.status_code >= 500
        events = _events(caplog)
        assert len(events) == 1
        ev = events[0]
        assert (ev["result"], ev["http_status"], ev["error_type"]) == (
            "error",
            None,
            "ConnectError",
        )
        assert ev["route"] == route and ev["api"] == api
        _assert_no_secret(caplog)


class TestNoSendNoAudit:
    @pytest.mark.parametrize("route,path,body,api", ROUTES)
    def test_mock_path_records_nothing(
        self, client, monkeypatch, caplog, route, path, body, api
    ):
        s = get_settings()
        monkeypatch.setattr(s, "ENVIRONMENT", "development")
        monkeypatch.setattr(s, "LLM_API_KEY", "")
        sent = _provider_ok(monkeypatch)
        with caplog.at_level(logging.INFO, logger="ceos_ai.audit"):
            res = client.post(path, json=body, headers=_auth_headers())
        assert res.status_code == 200
        assert sent == []
        assert _events(caplog) == []

    @pytest.mark.parametrize("route,path,body,api", ROUTES)
    def test_refusal_is_recorded_without_send(
        self, client, monkeypatch, caplog, route, path, body, api
    ):
        s = get_settings()
        monkeypatch.setattr(s, "ENVIRONMENT", "production")
        monkeypatch.setattr(s, "LLM_API_KEY", KEY_VALUE)
        monkeypatch.setattr(s, "ALLOW_DIRECT_LLM_IN_NONDEV", False)
        monkeypatch.setattr(s, "LLM_BASE_URL", BASE_URL)
        sent = _provider_ok(monkeypatch)
        org = str(uuid4())
        with caplog.at_level(logging.INFO, logger="ceos_ai.audit"):
            res = client.post(path, json=body, headers=_auth_headers(org_id=org))
        assert res.status_code == 503
        assert sent == []
        (ev,) = _events(caplog)
        assert ev["result"] == "refused"
        assert ev["http_status"] == 503
        assert ev["request_bytes"] is None
        assert ev["route"] == route
        assert ev["organization_id"] == org
        _assert_no_secret(caplog)
