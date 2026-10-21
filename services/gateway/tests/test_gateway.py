"""API Gateway テスト"""

import pytest
from fastapi.testclient import TestClient

from src.config import get_settings
from src.main import app


@pytest.fixture
def client():
    """テストクライアント"""
    return TestClient(app)


def test_health_check(client):
    """ヘルスチェックが 200 を返す"""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["service"] == "api-gateway"


def test_unknown_route_returns_404(client):
    """不明なルートは 404 を返す"""
    response = client.get("/some/random/unknown/path")
    assert response.status_code == 404
    data = response.json()
    assert data["success"] is False
    assert data["error"]["code"] == "NOT_FOUND"


def test_auth_required_without_token_returns_401(client):
    """トークンなしで認証必須エンドポイントにアクセスすると 401"""
    response = client.get("/api/v1/users")
    assert response.status_code == 401
    data = response.json()
    assert data["success"] is False
    assert data["error"]["code"] == "AUTH_REQUIRED"


def test_auth_with_invalid_token_returns_401(client):
    """不正なトークンでアクセスすると 401"""
    response = client.get(
        "/api/v1/users",
        headers={"Authorization": "Bearer invalid.token.here"},
    )
    assert response.status_code == 401
    data = response.json()
    assert data["success"] is False
    assert data["error"]["code"] == "INVALID_TOKEN"


def test_public_paths_no_auth_required(client):
    """公開パスは認証なしでアクセス可能"""
    response = client.get("/health")
    assert response.status_code == 200

    response = client.post("/api/v1/auth/login", json={})
    assert response.status_code != 401  # 認証で弾かれないこと


def test_rate_limiting(client):
    """レート制限を超えると 429 を返す"""
    settings = get_settings()
    original = settings.RATE_LIMIT_PER_MINUTE
    settings.RATE_LIMIT_PER_MINUTE = 2

    headers = {"X-Forwarded-For": "10.0.0.99"}

    try:
        for _ in range(2):
            response = client.get("/health", headers=headers)
            assert response.status_code == 200

        # 3回目で制限超過
        response = client.get("/health", headers=headers)
        assert response.status_code == 429
        data = response.json()
        assert data["success"] is False
        assert data["error"]["code"] == "RATE_LIMIT_EXCEEDED"
        assert "Retry-After" in response.headers
    finally:
        settings.RATE_LIMIT_PER_MINUTE = original


def test_x_request_id_header(client):
    """X-Request-ID ヘッダーが付与される"""
    response = client.get("/health")
    assert "X-Request-ID" in response.headers
    assert response.headers["X-Request-ID"] != ""


def test_request_id_forwarded(client):
    """クライアント指定の X-Request-ID が転送される"""
    response = client.get(
        "/health",
        headers={"X-Request-ID": "test-id-12345"},
    )
    assert response.headers["X-Request-ID"] == "test-id-12345"


def test_proxy_request_with_valid_token_format(client, monkeypatch):
    """有効なJWTは転送され、模擬した接続失敗は502になる（実上流へ接続しない）。"""
    import httpx

    calls = []

    async def unavailable(_client, **kwargs):
        calls.append(kwargs)
        raise httpx.ConnectError("synthetic upstream unavailable")

    monkeypatch.setattr(httpx.AsyncClient, "request", unavailable)
    import jwt as jose_jwt
    from src.config import get_settings

    settings = get_settings()
    token = jose_jwt.encode(
        {
            "sub": "test-user",
            "type": "user",
            "roles": [],
            "scopes": [],
            "exp": 9999999999,
        },
        # ミドルウェアと同じ解決済み鍵で署名する(既定値ではなく)
        settings.jwt_public_key,
        algorithm=settings.JWT_ALGORITHM,
    )

    response = client.get(
        "/api/v1/construction/test",
        headers={"Authorization": f"Bearer {token}"},
    )
    # Assertions stay outside the proxy's broad exception handler.
    assert len(calls) == 1
    assert calls[0]["method"] == "GET"
    assert calls[0]["url"].endswith("/api/v1/construction/test")
    assert calls[0]["headers"]["authorization"] == f"Bearer {token}"
    # Synthetic ConnectError, independent of real upstream availability.
    assert response.status_code == 502
    data = response.json()
    assert data["success"] is False
    assert data["error"]["code"] == "BAD_GATEWAY"
