"""ProxyService の耐障害性・ヘッダー処理・CORS のテスト (Issue #101 / #107)。

httpx.AsyncClient をフェイクに差し替え、外部へは一切接続しない。
公開パス（/api/v1/auth/login）経由で ProxyService.forward まで到達させる。
#101 で固定した挙動に加え、#107 で修正した CORS のミドルウェア順序、
X-Request-ID の正規化、hop-by-hop ヘッダー除去、content-encoding の扱いを検証する。
"""

import gzip
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


def _make_request(
    headers: list[tuple[bytes, bytes]],
    request_id: str | None = None,
    method: str = "GET",
) -> Request:
    scope: dict[str, Any] = {
        "type": "http",
        "method": method,
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


# ============================================
# Issue #107: CORS はミドルウェアの最外側で処理する
# ============================================
PROTECTED_PATH = "/api/v1/users"


def test_middleware_order_cors_is_outermost():
    app = create_app()
    # user_middleware は外側 -> 内側の順。Auth/RateLimit/Logging の相対順序は変えない
    names = [m.cls.__name__ for m in app.user_middleware]
    assert names == [
        "CORSMiddleware",
        "AuthMiddleware",
        "RateLimitMiddleware",
        "LoggingMiddleware",
    ]


def test_cors_preflight_on_protected_path_skips_auth(gw_client, fake_upstream):
    response = gw_client.options(
        PROTECTED_PATH,
        headers={
            "Origin": ALLOWED_ORIGIN,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == ALLOWED_ORIGIN
    assert response.headers["access-control-allow-credentials"] == "true"
    assert response.headers["access-control-allow-headers"] == "authorization"
    assert fake_upstream.calls == []


def test_cors_preflight_on_protected_path_disallowed_origin(gw_client, fake_upstream):
    response = gw_client.options(
        PROTECTED_PATH,
        headers={
            "Origin": "http://evil.example",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers
    assert fake_upstream.calls == []


def test_non_preflight_options_still_requires_auth(gw_client, fake_upstream):
    # Access-Control-Request-Method が無い OPTIONS は preflight ではない
    response = gw_client.options(PROTECTED_PATH, headers={"Origin": ALLOWED_ORIGIN})

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTH_REQUIRED"
    assert fake_upstream.calls == []


def test_options_without_origin_still_requires_auth(gw_client, fake_upstream):
    # Origin が無ければ Access-Control-Request-Method があっても preflight ではない
    response = gw_client.options(
        PROTECTED_PATH, headers={"Access-Control-Request-Method": "GET"}
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTH_REQUIRED"
    assert fake_upstream.calls == []


@pytest.mark.parametrize("method", ["GET", "POST", "DELETE"])
def test_request_with_origin_but_no_token_is_401_with_cors_headers(
    gw_client, fake_upstream, method
):
    response = gw_client.request(
        method, PROTECTED_PATH, headers={"Origin": ALLOWED_ORIGIN}
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTH_REQUIRED"
    assert response.headers["access-control-allow-origin"] == ALLOWED_ORIGIN
    assert response.headers["access-control-allow-credentials"] == "true"
    assert fake_upstream.calls == []


def test_invalid_token_401_has_cors_headers(gw_client, fake_upstream):
    response = gw_client.get(
        PROTECTED_PATH,
        headers={
            "Origin": ALLOWED_ORIGIN,
            "Authorization": "Bearer invalid.token.here",
        },
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_TOKEN"
    assert response.headers["access-control-allow-origin"] == ALLOWED_ORIGIN
    assert fake_upstream.calls == []


def test_401_for_disallowed_origin_has_no_cors_headers(gw_client, fake_upstream):
    response = gw_client.get(PROTECTED_PATH, headers={"Origin": "http://evil.example"})

    assert response.status_code == 401
    assert "access-control-allow-origin" not in response.headers


def test_rate_limited_429_has_cors_headers(gw_client, fake_upstream):
    settings = get_settings()
    original = settings.RATE_LIMIT_PER_MINUTE
    settings.RATE_LIMIT_PER_MINUTE = 1
    headers = {"Origin": ALLOWED_ORIGIN, "X-Forwarded-For": "10.0.107.1"}
    try:
        assert gw_client.get("/health", headers=headers).status_code == 200
        response = gw_client.get("/health", headers=headers)
    finally:
        settings.RATE_LIMIT_PER_MINUTE = original

    assert response.status_code == 429
    assert response.json()["error"]["code"] == "RATE_LIMIT_EXCEEDED"
    assert "retry-after" in response.headers
    assert response.headers["access-control-allow-origin"] == ALLOWED_ORIGIN
    assert response.headers["access-control-allow-credentials"] == "true"


# ============================================
# Issue #107: X-Request-ID を 1 本に正規化する
# ============================================
def _request_id_headers(headers: dict[str, str]) -> list[tuple[str, str]]:
    return [(k, v) for k, v in headers.items() if k.lower() == "x-request-id"]


def test_prepare_headers_request_id_is_not_duplicated():
    request = _make_request(
        [(b"x-request-id", b"incoming"), (b"x-keep", b"1")], request_id="rid-42"
    )

    headers = ProxyService._prepare_headers(request)

    assert _request_id_headers(headers) == [("X-Request-ID", "rid-42")]
    assert headers["x-keep"] == "1"


def test_prepare_headers_passes_incoming_request_id_without_state():
    request = _make_request([(b"x-request-id", b"incoming")])

    headers = ProxyService._prepare_headers(request)

    assert _request_id_headers(headers) == [("x-request-id", "incoming")]


def test_forwarded_request_id_is_single_end_to_end(gw_client, fake_upstream):
    gw_client.post(PUBLIC_UPSTREAM_PATH, json={}, headers={"X-Request-ID": "req-777"})

    sent = fake_upstream.calls[0]["headers"]
    assert _request_id_headers(sent) == [("X-Request-ID", "req-777")]


# ============================================
# Issue #107: hop-by-hop ヘッダー（RFC 9110 §7.6.1）
# ============================================
HOP_BY_HOP = [
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
]


def test_prepare_headers_strips_all_rfc9110_hop_by_hop_and_connection_tokens():
    request = _make_request(
        [
            (b"host", b"gateway.local"),
            (b"connection", b"keep-alive, X-Custom-Hop"),
            (b"connection", b"x-second-hop"),
            (b"keep-alive", b"timeout=5"),
            (b"proxy-authenticate", b"Basic"),
            (b"proxy-authorization", b"Basic Zm9vOmJhcg=="),
            (b"te", b"trailers"),
            (b"trailer", b"Expires"),
            (b"transfer-encoding", b"chunked"),
            (b"upgrade", b"websocket"),
            (b"x-custom-hop", b"secret"),
            (b"x-second-hop", b"secret"),
            (b"x-kept", b"1"),
        ]
    )

    headers = ProxyService._prepare_headers(request)

    assert headers == {"x-kept": "1"}


def test_request_rfc9110_hop_by_hop_headers_are_not_forwarded_end_to_end(
    gw_client, fake_upstream
):
    gw_client.post(
        PUBLIC_UPSTREAM_PATH,
        json={},
        headers={
            "Connection": "close, X-Custom-Hop",
            "X-Custom-Hop": "secret",
            "TE": "trailers",
            "Trailer": "Expires",
            "Upgrade": "websocket",
            "Proxy-Authorization": "Basic Zm9vOmJhcg==",
            "X-Kept": "1",
        },
    )

    sent = {k.lower() for k in fake_upstream.calls[0]["headers"]}
    for name in [*HOP_BY_HOP, "x-custom-hop", "host"]:
        assert name not in sent
    assert "x-kept" in sent


def test_response_rfc9110_hop_by_hop_and_connection_tokens_are_removed(
    gw_client, fake_upstream
):
    fake_upstream.behavior = httpx.Response(
        200,
        content=b"{}",
        headers=[
            ("connection", "keep-alive, X-Upstream-Hop"),
            ("keep-alive", "timeout=5"),
            ("proxy-authenticate", "Basic"),
            ("te", "trailers"),
            ("trailer", "Expires"),
            ("upgrade", "h2c"),
            ("x-upstream-hop", "secret"),
            ("x-kept", "1"),
        ],
    )

    response = gw_client.post(PUBLIC_UPSTREAM_PATH, json={})

    assert response.status_code == 200
    for name in [*HOP_BY_HOP, "x-upstream-hop"]:
        assert name not in response.headers
    assert response.headers["x-kept"] == "1"


# ============================================
# Issue #107: 展開済み本文に content-encoding / content-length を付けない
# ============================================
GZIP_PLAIN = b'{"message":"' + b"a" * 200 + b'"}'


def _gzip_upstream_response() -> httpx.Response:
    # httpx は content-length を圧縮後サイズで自動付与し、.content は展開済みを返す
    return httpx.Response(
        200,
        content=gzip.compress(GZIP_PLAIN),
        headers={"content-encoding": "gzip", "content-type": "application/json"},
    )


async def test_forward_drops_content_encoding_and_stale_content_length(fake_upstream):
    upstream = _gzip_upstream_response()
    # 前提: 上流の content-length は圧縮後サイズで、展開済み本文の長さと一致しない
    assert upstream.headers["content-length"] != str(len(GZIP_PLAIN))
    assert upstream.content == GZIP_PLAIN
    fake_upstream.behavior = upstream

    response = await ProxyService().forward(
        _make_request([]), AUTH_UPSTREAM_URL, "api-v1-auth"
    )

    assert response.body == GZIP_PLAIN
    assert "content-encoding" not in response.headers
    assert response.headers["content-length"] == str(len(GZIP_PLAIN))
    assert response.headers["content-type"] == "application/json"


def test_gzip_upstream_body_reaches_client_intact(gw_client, fake_upstream):
    fake_upstream.behavior = _gzip_upstream_response()

    response = gw_client.post(PUBLIC_UPSTREAM_PATH, json={})

    assert response.status_code == 200
    assert "content-encoding" not in response.headers
    assert response.headers["content-length"] == str(len(GZIP_PLAIN))
    assert response.content == GZIP_PLAIN


# ============================================
# HEAD: 本文が空なので上流の表現メタデータ（content-length / content-encoding）を保持する
# ============================================
HEAD_UPSTREAM_LENGTH = "4096"


def _head_upstream_response() -> httpx.Response:
    # 実際の HEAD 応答と同様に本文は空で、content-length は GET 時の本文長を示す
    return httpx.Response(
        200,
        headers={
            "content-length": HEAD_UPSTREAM_LENGTH,
            "content-encoding": "gzip",
            "content-type": "application/json",
        },
    )


async def test_forward_head_keeps_upstream_content_length_and_encoding(fake_upstream):
    upstream = _head_upstream_response()
    assert upstream.content == b""
    fake_upstream.behavior = upstream

    response = await ProxyService().forward(
        _make_request([], method="HEAD"), AUTH_UPSTREAM_URL, "api-v1-auth"
    )

    assert response.body == b""
    # Starlette must not replace the supplied content-length with len(b"") == 0
    assert response.headers.getlist("content-length") == [HEAD_UPSTREAM_LENGTH]
    assert response.headers["content-encoding"] == "gzip"


def test_head_upstream_content_length_reaches_client(gw_client, fake_upstream):
    fake_upstream.behavior = _head_upstream_response()

    response = gw_client.head(PUBLIC_UPSTREAM_PATH)

    assert response.status_code == 200
    assert fake_upstream.calls[-1]["method"] == "HEAD"
    assert response.headers.get_list("content-length") == [HEAD_UPSTREAM_LENGTH]
    assert response.headers["content-encoding"] == "gzip"
    assert response.content == b""


async def test_forward_get_still_drops_stale_entity_headers(fake_upstream):
    fake_upstream.behavior = _gzip_upstream_response()

    response = await ProxyService().forward(
        _make_request([], method="GET"), AUTH_UPSTREAM_URL, "api-v1-auth"
    )

    assert response.body == GZIP_PLAIN
    assert "content-encoding" not in response.headers
    assert response.headers.getlist("content-length") == [str(len(GZIP_PLAIN))]
