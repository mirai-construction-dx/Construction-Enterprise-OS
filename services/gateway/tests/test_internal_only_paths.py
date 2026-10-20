"""内部専用パス（トークン交換、ADR-0003）を gateway が遮断することの回帰テスト

`^/api/v1/auth` は auth へ転送されるため、明示的に遮断しないと有効な JWT を持つ
外部の呼び出し元がトークン交換へ到達できる。認証の有無に関わらず 404 とする。
"""

import time

import jwt
import pytest
from fastapi.testclient import TestClient

from src.config import get_settings
from src.main import app
from src.middleware.auth import AuthMiddleware


def _token() -> str:
    settings = get_settings()
    payload = {"sub": "user-1", "type": "user", "exp": int(time.time()) + 600}
    return jwt.encode(payload, settings.jwt_public_key, algorithm=settings.JWT_ALGORITHM)


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.mark.parametrize(
    "path", ["/api/v1/auth/token", "/api/v1/auth/token/", "//api/v1/auth/token"]
)
@pytest.mark.parametrize("authorized", [False, True])
def test_token_exchange_is_not_reachable_through_gateway(client, path, authorized):
    headers = {"Authorization": f"Bearer {_token()}"} if authorized else {}
    response = client.post(
        path,
        data={"grant_type": "urn:ietf:params:oauth:grant-type:token-exchange"},
        headers=headers,
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


@pytest.mark.parametrize(
    "path, expected",
    [
        ("/api/v1/auth/token", True),
        ("/api/v1/auth/tokens", False),
        ("/api/v1/auth/login", False),
        ("/api/v1/auth/refresh", False),
    ],
)
def test_internal_only_boundary(path, expected):
    assert AuthMiddleware._is_internal_only_path(path) is expected


def test_login_remains_public():
    assert AuthMiddleware(app=None)._is_public_path("/api/v1/auth/login") is True


# --- Issue #103: workflow の内部ジョブ API を gateway 経由で到達不能にする ---
# `/api/v1/workflow` は UPSTREAM_SERVICES で workflow へ転送されるため、
# 明示的に遮断しないと gateway を経由して内部ジョブ API に到達できてしまう
# （内部 API キーを知る呼び出し元なら、外部からでも実行できる）。
# 内部専用パスは認証の有無を問わず 404 とし、存在も明かさない。


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/workflow/internal",
        "/api/v1/workflow/internal/",
        "/api/v1/workflow/internal/jobs/deadline-notifications",
        "/api/v1/workflow/internal/jobs/workload-notifications",
        # 注: "//api/..." は ASGI 到達前に正規化され、この統合テストでは
        # 内部専用パス遮断を検証できない。先頭スラッシュの境界は下の
        # ユニットテスト（_is_internal_only_path へ生文字列を渡す）で担保する。
    ],
)
@pytest.mark.parametrize("authorized", [False, True])
def test_workflow_internal_api_is_not_reachable_through_gateway(
    client, path, authorized
):
    headers = {"Authorization": f"Bearer {_token()}"} if authorized else {}
    response = client.post(path, headers=headers)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


@pytest.mark.parametrize(
    "path, expected",
    [
        ("/api/v1/workflow/internal", True),
        ("/api/v1/workflow/internal/", True),
        ("/api/v1/workflow/internal/jobs/deadline-notifications", True),
        ("//api/v1/workflow/internal/jobs/deadline-notifications", True),
        # 境界: 前方一致するだけの近接パスは遮断しない
        ("/api/v1/workflow/internals", False),
        ("/api/v1/workflow/internal-jobs", False),
        ("/api/v1/workflow/definitions", False),
    ],
)
def test_workflow_internal_boundary(path, expected):
    assert AuthMiddleware._is_internal_only_path(path) is expected
