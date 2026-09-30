"""ProxyService の耐障害性・ヘッダー処理・CORS preflight のテスト (Issue #101)。

httpx.AsyncClient をフェイクに差し替え、外部へは一切接続しない。
公開パス（/api/v1/auth/login）経由で ProxyService.forward まで到達させ、
現在の実装の挙動を固定する。
"""

from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request

from src.config import get_settings
from src.main import create_app
from src.services.proxy_service import ProxyService

PUBLIC_UPSTREAM_PATH = "/api/v1/auth/login"
AUTH_UPSTREAM_URL = get_settings().UPSTREAM_SERVICES["^/api/v1/auth"]
ALLOWED_ORIGIN = get_settings().CORS_ORIGINS[0]


class FakeAsyncClient:
    """httpx.AsyncClient の最小フェイク。呼び出し内容を記録する。"""

    calls: list[dict[str, Any]] = []
    init_kwargs: list[dict[str, Any]] = []
    behavior: Any = None

    def __init__(self, **kwargs: Any) -> None:
        FakeAsyncClient.init_kwargs.append(kwargs)

    async def __aenter__(self) -> "FakeAsyncClient":
        return self

    async def __aexit__(self, *exc: Any) -> None:
        return None

    async def request(self, **kwargs: Any) -> httpx.Response:
        FakeAsyncClient.calls.append(kwargs)
        behavior = FakeAsyncClient.behavior
        if isinstance(behavior, BaseException):
            raise behavior
        assert isinstance(behavior, httpx.Response)
        return behavior


@pytest.fixture
def fake_upstream(monkeypatch):
    FakeAsyncClient.calls = []
    FakeAsyncClient.init_kwargs = []
    FakeAsyncClient.behavior = httpx.Response(200, content=b"{}")
    # TestClient 自体は同期の httpx.Client を使うため、AsyncClient の差し替えは影響しない
    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)
    return FakeAsyncClient


@pytest.fixture
def gw_client():
    return TestClient(create_app())


# ============================================
# 上流エラー分岐
# ============================================
@pytest.mark.parametrize(
    "exc",
    [
        httpx.ReadTimeout("read timed out"),
        httpx.ConnectTimeout("connect timed out"),
        httpx.PoolTimeout("pool timed out"),
    ],
)
def test_upstream_timeout_returns_504(gw_client, fake_upstream, exc):
    fake_upstream.behavior = exc

    response = gw_client.post(PUBLIC_UPSTREAM_PATH, json={})

    assert response.status_code == 504
    assert response.json() == {
        "success": False,
        "error": {
            "code": "GATEWAY_TIMEOUT",
            "message": "上流サービスがタイムアウトしました。",
        },
    }
    assert len(fake_upstream.calls) == 1


def test_upstream_connect_error_returns_502(gw_client, fake_upstream):
    fake_upstream.behavior = httpx.ConnectError("refused")

    response = gw_client.post(PUBLIC_UPSTREAM_PATH, json={})

    assert response.status_code == 502
    assert response.json()["error"] == {
        "code": "BAD_GATEWAY",
        "message": "上流サービスに接続できません。",
    }


def test_upstream_unexpected_error_returns_502(gw_client, fake_upstream):
    fake_upstream.behavior = RuntimeError("boom")

    response = gw_client.post(PUBLIC_UPSTREAM_PATH, json={})

    assert response.status_code == 502
    body = response.json()
    assert body["success"] is False
    assert body["error"] == {
        "code": "BAD_GATEWAY",
        "message": "上流サービスでエラーが発生しました。",
    }
    # 例外メッセージをクライアントへ漏らさない
    assert "boom" not in response.text


def test_proxy_service_uses_configured_timeout(gw_client, fake_upstream):
    gw_client.post(PUBLIC_UPSTREAM_PATH, json={})

    assert fake_upstream.init_kwargs == [{"timeout": 30.0}]


# ============================================
# 転送内容
# ============================================
def test_forward_builds_target_url_and_passes_body(gw_client, fake_upstream):
    response = gw_client.post(f"{PUBLIC_UPSTREAM_PATH}?next=%2Fhome", content=b"payload")

    assert response.status_code == 200
    call = fake_upstream.calls[0]
    assert call["method"] == "POST"
    assert call["url"] == f"{AUTH_UPSTREAM_URL.rstrip('/')}/api/v1/auth/login?next=%2Fhome"
    assert call["content"] == b"payload"
    assert call["follow_redirects"] is False


def test_upstream_status_and_body_are_passed_through(gw_client, fake_upstream):
    fake_upstream.behavior = httpx.Response(
        401, content=b'{"detail":"bad credentials"}', headers={"content-type": "application/json"}
    )

    response = gw_client.post(PUBLIC_UPSTREAM_PATH, json={})

    assert response.status_code == 401
    assert response.json() == {"detail": "bad credentials"}
    assert response.headers["x-upstream-service"] == "api-v1-auth"


# ============================================
# hop-by-hop ヘッダー
# ============================================
def test_response_hop_by_hop_headers_are_removed(gw_client, fake_upstream):
    fake_upstream.behavior = httpx.Response(
        200,
        content=b"{}",
        headers={
            "transfer-encoding": "chunked",
            "connection": "keep-alive",
            "keep-alive": "timeout=5",
            "x-custom": "kept",
        },
    )

    response = gw_client.post(PUBLIC_UPSTREAM_PATH, json={})

    assert response.status_code == 200
    assert "transfer-encoding" not in response.headers
    assert "connection" not in response.headers
    assert "keep-alive" not in response.headers
    assert response.headers["x-custom"] == "kept"
    assert response.headers["x-upstream-service"] == "api-v1-auth"


def test_request_hop_by_hop_headers_are_not_forwarded(gw_client, fake_upstream):
    gw_client.post(
        PUBLIC_UPSTREAM_PATH,
        json={},
        headers={
            "Connection": "keep-alive",
            "Keep-Alive": "timeout=5",
            "X-Custom-Header": "forwarded",
            "X-Request-ID": "req-123",
        },
    )

    sent = {k.lower(): v for k, v in fake_upstream.calls[0]["headers"].items()}
    assert "host" not in sent
    assert "connection" not in sent
    assert "keep-alive" not in sent
    assert "transfer-encoding" not in sent
    assert sent["x-custom-header"] == "forwarded"
    assert sent["x-request-id"] == "req-123"


def _make_request(headers: list[tuple[bytes, bytes]], request_id: str | None = None) -> Request:
    scope: dict[str, Any] = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "query_string": b"",
        "headers": headers,
        "state": {},
    }
    request = Request(scope)
    if request_id is not None:
        request.state.request_id = request_id
    return request


def test_prepare_headers_excludes_hop_by_hop_case_insensitively():
    request = _make_request(
        [
            (b"host", b"gateway.local"),
            (b"connection", b"keep-alive"),
            (b"keep-alive", b"timeout=5"),
            (b"transfer-encoding", b"chunked"),
            (b"authorization", b"Bearer abc"),
            (b"x-keep", b"1"),
        ]
    )

    headers = ProxyService._prepare_headers(request)

    assert headers == {"authorization": "Bearer abc", "x-keep": "1"}


def test_prepare_headers_injects_request_id_from_state():
    request = _make_request([(b"x-keep", b"1")], request_id="rid-42")

    headers = ProxyService._prepare_headers(request)

    assert headers["X-Request-ID"] == "rid-42"
    assert headers["x-keep"] == "1"


# ============================================
# CORS preflight
# ============================================
def test_cors_preflight_allowed_origin(gw_client, fake_upstream):
    response = gw_client.options(
        PUBLIC_UPSTREAM_PATH,
        headers={
            "Origin": ALLOWED_ORIGIN,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,content-type",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == ALLOWED_ORIGIN
    assert response.headers["access-control-allow-credentials"] == "true"
    assert "POST" in response.headers["access-control-allow-methods"]
    assert response.headers["access-control-allow-headers"] == "authorization,content-type"
    # preflight は CORSMiddleware が応答し、上流へは転送されない
    assert fake_upstream.calls == []


def test_cors_preflight_disallowed_origin(gw_client, fake_upstream):
    response = gw_client.options(
        PUBLIC_UPSTREAM_PATH,
        headers={
            "Origin": "http://evil.example",
            "Access-Control-Request-Method": "POST",
        },
    )

    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers
    assert fake_upstream.calls == []


def test_cors_simple_request_echoes_allowed_origin(gw_client):
    response = gw_client.get("/health", headers={"Origin": ALLOWED_ORIGIN})

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == ALLOWED_ORIGIN
    assert response.headers["access-control-allow-credentials"] == "true"
