"""トークン交換（RFC 8693、ADR-0003）のテスト

- 既定（TOKEN_EXCHANGE_ENABLED=false）では拒否され、挙動は従来と同一
- ① aud 無しユーザートークン → MCP 用（aud=api://ceos-mcp）
- ② MCP 用 → 上流用（aud 無し・act 付き）はクライアント認証とスコープが必須
- 有効期限は subject を超えない。交換済み・別 audience・別発行者・非ユーザーは拒否
- MCP 用トークンは既存サービスの検証（audience 未指定）で拒否される
"""

import base64
import hashlib
import time
import uuid
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import jwt
import pytest
from fastapi.testclient import TestClient

from src.config import get_settings
from src.main import create_app
from src.models import AuditLog
from src.models.base import get_db
from src.services.token_exchange_service import (
    GRANT_TYPE_TOKEN_EXCHANGE,
    TOKEN_TYPE_ACCESS_TOKEN,
)
from src.services.token_service import TOKEN_ISSUER, decode_token

MCP_AUD = "api://ceos-mcp"
UPSTREAM_AUD = "urn:ceos:upstream"
USER_ID = str(uuid.UUID("11111111-1111-1111-1111-111111111111"))
CLIENT_ID = "ceo_mcp_client"
CLIENT_SECRET = "test-only-client-secret"
EXCHANGE_SCOPE = "token-exchange:ceos-upstream"


def _key() -> str:
    return get_settings().jwt_private_key


def make_user_token(*, expires_in: int = 3600, **overrides: Any) -> str:
    now = int(time.time())
    payload: dict[str, Any] = {
        "sub": USER_ID,
        "type": "user",
        "org": "org-1",
        "roles": ["project_manager"],
        "scopes": [],
        "iat": now,
        "exp": now + expires_in,
        "iss": TOKEN_ISSUER,
        "jti": str(uuid.uuid4()),
    }
    payload.update(overrides)
    payload = {k: v for k, v in payload.items() if v is not None}
    return jwt.encode(payload, _key(), algorithm=get_settings().JWT_ALGORITHM)


def decode_unverified(token: str) -> dict[str, Any]:
    return jwt.decode(token, options={"verify_signature": False})


class _Result:
    def __init__(self, value: Any) -> None:
        self._value = value

    def scalar_one_or_none(self) -> Any:
        return self._value


def _client_record(*, scopes: list[str] | None = None, status: str = "active") -> Any:
    return SimpleNamespace(
        client_id=CLIENT_ID,
        client_secret_hash=hashlib.sha256(CLIENT_SECRET.encode()).hexdigest(),
        scopes=[EXCHANGE_SCOPE] if scopes is None else scopes,
        status=status,
    )


@pytest.fixture
def enabled(monkeypatch):
    monkeypatch.setattr(get_settings(), "TOKEN_EXCHANGE_ENABLED", True)


@pytest.fixture
def db_state():
    return {"client": _client_record(), "audit": []}


@pytest.fixture
def client(db_state):
    app = create_app()
    db = MagicMock()

    async def execute(*args, **kwargs):
        return _Result(db_state["client"])

    db.execute = execute
    db.add = lambda obj: db_state["audit"].append(obj)
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    db.close = AsyncMock()

    async def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app)


def _form(subject_token: str, audience: str, **extra: str) -> dict[str, str]:
    data = {
        "grant_type": GRANT_TYPE_TOKEN_EXCHANGE,
        "subject_token": subject_token,
        "subject_token_type": TOKEN_TYPE_ACCESS_TOKEN,
        "audience": audience,
    }
    data.update(extra)
    return data


def _basic(client_id: str = CLIENT_ID, secret: str = CLIENT_SECRET) -> dict[str, str]:
    raw = base64.b64encode(f"{client_id}:{secret}".encode()).decode()
    return {"Authorization": f"Basic {raw}"}


def _mcp_token(client: TestClient) -> str:
    response = client.post("/api/v1/auth/token", data=_form(make_user_token(), MCP_AUD))
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


# --- キルスイッチ ---------------------------------------------------------


def test_disabled_by_default_returns_unsupported_grant_type(client):
    response = client.post("/api/v1/auth/token", data=_form(make_user_token(), MCP_AUD))
    assert response.status_code == 400
    assert response.json()["error"] == "unsupported_grant_type"
    assert response.headers["cache-control"] == "no-store"


def test_other_grant_type_is_rejected(client, enabled):
    data = _form(make_user_token(), MCP_AUD, grant_type="client_credentials")
    response = client.post("/api/v1/auth/token", data=data)
    assert response.json()["error"] == "unsupported_grant_type"


# --- ① 通常ユーザートークン → MCP 用 ---------------------------------------


def test_user_token_exchanges_to_mcp_audience(client, enabled, db_state):
    subject = make_user_token()
    response = client.post("/api/v1/auth/token", data=_form(subject, MCP_AUD))
    assert response.status_code == 200
    body = response.json()
    assert body["issued_token_type"] == TOKEN_TYPE_ACCESS_TOKEN
    assert body["token_type"] == "Bearer"
    assert 0 < body["expires_in"] <= 10 * 60
    assert response.headers["cache-control"] == "no-store"

    claims = jwt.decode(
        body["access_token"], _key(), algorithms=[get_settings().JWT_ALGORITHM], audience=MCP_AUD
    )
    assert claims["aud"] == MCP_AUD
    assert claims["sub"] == USER_ID
    assert claims["roles"] == ["project_manager"]
    assert "act" not in claims

    # 監査ログ（トークン本体は含めない）
    logs = [a for a in db_state["audit"] if isinstance(a, AuditLog)]
    assert logs and logs[-1].event_type == "auth.token.exchange" and logs[-1].success
    assert body["access_token"] not in str(logs[-1].event_data)


def test_mcp_token_is_rejected_by_existing_service_verification(client, enabled):
    """既存サービスの検証（audience 未指定）では aud 付きトークンは無効になる。"""
    assert decode_token(_mcp_token(client)) is None


def test_exchanged_token_never_outlives_subject(client, enabled):
    subject = make_user_token(expires_in=90)
    response = client.post("/api/v1/auth/token", data=_form(subject, MCP_AUD))
    assert response.status_code == 200
    assert decode_unverified(response.json()["access_token"])["exp"] == decode_unverified(subject)["exp"]


@pytest.mark.parametrize(
    "overrides",
    [
        {"type": "client"},
        {"iss": "someone-else"},
        {"act": {"sub": "x"}},
        {"aud": "api://other"},
    ],
    ids=["non-user", "foreign-issuer", "already-exchanged", "has-audience"],
)
def test_invalid_subject_tokens_are_rejected_for_mcp(client, enabled, overrides):
    response = client.post("/api/v1/auth/token", data=_form(make_user_token(**overrides), MCP_AUD))
    assert response.status_code == 400
    assert response.json()["error"] == "invalid_grant"


def test_expired_or_forged_subject_is_rejected(client, enabled):
    expired = make_user_token(expires_in=-10)
    forged = jwt.encode(
        decode_unverified(make_user_token()), "wrong-key-0123456789abcdef-long-enough", algorithm="HS256"
    )
    for token in (expired, forged, "not-a-jwt"):
        response = client.post("/api/v1/auth/token", data=_form(token, MCP_AUD))
        assert response.json()["error"] == "invalid_grant"


def test_unknown_audience_is_invalid_target(client, enabled):
    response = client.post("/api/v1/auth/token", data=_form(make_user_token(), "api://mcip-tool-api"))
    assert response.json()["error"] == "invalid_target"


def test_missing_parameters_and_bad_types(client, enabled):
    assert client.post("/api/v1/auth/token", data=_form("", MCP_AUD)).json()["error"] == "invalid_request"
    bad_type = _form(make_user_token(), MCP_AUD, subject_token_type="urn:x")
    assert client.post("/api/v1/auth/token", data=bad_type).json()["error"] == "invalid_request"
    bad_req = _form(make_user_token(), MCP_AUD, requested_token_type="urn:ietf:params:oauth:token-type:id_token")
    assert client.post("/api/v1/auth/token", data=bad_req).json()["error"] == "invalid_request"


# --- ② MCP 用 → 上流用 ------------------------------------------------------


def test_mcp_token_exchanges_to_upstream_with_client_auth(client, enabled):
    mcp_token = _mcp_token(client)
    response = client.post(
        "/api/v1/auth/token", data=_form(mcp_token, UPSTREAM_AUD), headers=_basic()
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert 0 < body["expires_in"] <= 5 * 60

    claims = decode_unverified(body["access_token"])
    assert "aud" not in claims
    assert claims["act"] == {"sub": CLIENT_ID}
    assert claims["sub"] == USER_ID
    assert claims["exp"] <= decode_unverified(mcp_token)["exp"]
    # 既存サービスの検証で有効（上流と互換）
    assert decode_token(body["access_token"]) is not None


def test_client_secret_post_is_supported(client, enabled):
    data = _form(_mcp_token(client), UPSTREAM_AUD, client_id=CLIENT_ID, client_secret=CLIENT_SECRET)
    assert client.post("/api/v1/auth/token", data=data).status_code == 200


def test_upstream_exchange_requires_client_auth(client, enabled):
    response = client.post("/api/v1/auth/token", data=_form(_mcp_token(client), UPSTREAM_AUD))
    assert response.status_code == 401
    assert response.json()["error"] == "invalid_client"
    assert "www-authenticate" in response.headers


@pytest.mark.parametrize(
    "record, headers",
    [
        (None, _basic()),
        (_client_record(status="revoked"), _basic()),
        (_client_record(), _basic(secret="wrong-secret")),
    ],
    ids=["unknown-client", "revoked-client", "wrong-secret"],
)
def test_bad_client_credentials_are_rejected(client, enabled, db_state, record, headers):
    mcp_token = _mcp_token(client)
    db_state["client"] = record
    response = client.post("/api/v1/auth/token", data=_form(mcp_token, UPSTREAM_AUD), headers=headers)
    assert response.status_code == 401
    assert response.json()["error"] == "invalid_client"
    assert CLIENT_SECRET not in response.text


def test_client_without_exchange_scope_is_unauthorized(client, enabled, db_state):
    mcp_token = _mcp_token(client)
    db_state["client"] = _client_record(scopes=["erp:read"])
    response = client.post("/api/v1/auth/token", data=_form(mcp_token, UPSTREAM_AUD), headers=_basic())
    assert response.json()["error"] == "unauthorized_client"


def test_plain_user_token_cannot_be_exchanged_to_upstream(client, enabled):
    """② の subject は MCP 用トークンに限る（通常トークンの act 付与・短命化の迂回を防ぐ）。"""
    response = client.post(
        "/api/v1/auth/token", data=_form(make_user_token(), UPSTREAM_AUD), headers=_basic()
    )
    assert response.json()["error"] == "invalid_grant"


def test_upstream_token_cannot_be_re_exchanged(client, enabled):
    upstream = client.post(
        "/api/v1/auth/token", data=_form(_mcp_token(client), UPSTREAM_AUD), headers=_basic()
    ).json()["access_token"]
    response = client.post("/api/v1/auth/token", data=_form(upstream, MCP_AUD))
    assert response.json()["error"] == "invalid_grant"


def test_mixed_client_auth_methods_are_rejected(client, enabled):
    data = _form(_mcp_token(client), UPSTREAM_AUD, client_id=CLIENT_ID, client_secret=CLIENT_SECRET)
    response = client.post("/api/v1/auth/token", data=data, headers=_basic())
    assert response.json()["error"] == "invalid_request"


def test_failed_exchange_is_audited_without_secrets(client, enabled, db_state):
    mcp_token = _mcp_token(client)
    db_state["client"] = None
    client.post("/api/v1/auth/token", data=_form(mcp_token, UPSTREAM_AUD), headers=_basic())
    failed = [a for a in db_state["audit"] if isinstance(a, AuditLog) and not a.success]
    assert failed and failed[-1].event_data["error"] == "invalid_client"
    assert CLIENT_SECRET not in str(failed[-1].event_data)
    assert mcp_token not in str(failed[-1].event_data)
