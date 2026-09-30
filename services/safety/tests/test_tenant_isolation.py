"""Organization (tenant) isolation tests for the safety service (Issue #106, ADR-0004)."""

import base64
import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from src.main import create_app
from src.middleware.auth import TokenData
from src.middleware.tenant import create_org, scope_org
from src.models.base import get_db

ORG_A = uuid.uuid4()
ORG_B = uuid.uuid4()


def _payload(org: str | None = str(ORG_A), roles: list[str] | None = None) -> dict:
    return {
        "sub": str(uuid.uuid4()),
        "type": "user",
        "org": org,
        "roles": roles if roles is not None else ["safety_manager"],
        "scopes": [],
    }


def _b64(data: dict) -> str:
    return base64.urlsafe_b64encode(json.dumps(data).encode()).decode().rstrip("=")


def _auth_header() -> dict:
    # Signature is not verified in tests: jwt.decode is patched per test.
    return {"Authorization": f"Bearer {_b64({'alg': 'HS256'})}.{_b64({})}.sig"}


class _Result:
    def __init__(self, value=None):
        self._value = value

    def scalar(self):
        return self._value

    def scalar_one_or_none(self):
        return self._value


def _client(*values):
    app = create_app()
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=[_Result(v) for v in values])
    db.add = MagicMock()
    db.flush = AsyncMock()

    async def _db():
        yield db

    app.dependency_overrides[get_db] = _db
    return TestClient(app), db


def _user(**kw) -> TokenData:
    p = _payload(**kw)
    return TokenData(sub=p["sub"], type=p["type"], org=p["org"], roles=p["roles"])


def _compiled(db, index: int):
    stmt = db.execute.await_args_list[index].args[0]
    return str(stmt), stmt.compile().params


# ── helper rules ─────────────────────────────────────────────


def test_scope_org_regular_user_is_pinned_to_token_org():
    assert scope_org(_user()) == ORG_A
    assert scope_org(_user(), ORG_A) == ORG_A


def test_scope_org_rejects_other_org_for_regular_user():
    with pytest.raises(HTTPException) as exc:
        scope_org(_user(), ORG_B)
    assert exc.value.status_code == 403
    assert exc.value.detail["code"] == "ORG_FORBIDDEN"


@pytest.mark.parametrize(
    ("org", "code"), [(None, "ORG_REQUIRED"), ("not-a-uuid", "ORG_INVALID")]
)
def test_scope_org_fails_closed_without_valid_org(org, code):
    with pytest.raises(HTTPException) as exc:
        scope_org(_user(org=org))
    assert exc.value.status_code == 403
    assert exc.value.detail["code"] == code


def test_admin_is_cross_org():
    admin = _user(roles=["admin"])
    assert scope_org(admin) is None  # no filter
    assert scope_org(admin, ORG_B) == ORG_B
    assert create_org(admin, ORG_B) == ORG_B


def test_create_org_rejects_other_org_for_regular_user():
    assert create_org(_user(), ORG_A) == ORG_A
    with pytest.raises(HTTPException) as exc:
        create_org(_user(), ORG_B)
    assert exc.value.status_code == 403


# ── API behaviour ────────────────────────────────────────────


@patch("src.middleware.auth.jwt")
def test_stats_are_scoped_to_token_org(mock_jwt):
    mock_jwt.decode.return_value = _payload()
    client, db = _client(3, 1, 1, 50.0)

    resp = client.get("/api/v1/safety/inspections/stats", headers=_auth_header())

    assert resp.status_code == 200
    for i in range(4):
        sql, params = _compiled(db, i)
        assert "organization_id" in sql
        assert ORG_A in params.values()


@patch("src.middleware.auth.jwt")
def test_stats_for_other_org_is_forbidden(mock_jwt):
    mock_jwt.decode.return_value = _payload()
    client, db = _client()

    resp = client.get(
        "/api/v1/safety/inspections/stats",
        params={"organization_id": str(ORG_B)},
        headers=_auth_header(),
    )

    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "ORG_FORBIDDEN"
    db.execute.assert_not_awaited()


@patch("src.middleware.auth.jwt")
def test_admin_stats_without_org_are_global(mock_jwt):
    mock_jwt.decode.return_value = _payload(roles=["admin"])
    client, db = _client(3, 1, 1, 50.0)

    resp = client.get("/api/v1/safety/inspections/stats", headers=_auth_header())

    assert resp.status_code == 200
    assert "organization_id" not in _compiled(db, 0)[0]


@patch("src.middleware.auth.jwt")
def test_stats_average_zero_is_not_none(mock_jwt):
    mock_jwt.decode.return_value = _payload()
    client, _ = _client(2, 0, 2, 0.0)

    resp = client.get("/api/v1/safety/inspections/stats", headers=_auth_header())

    assert resp.json()["data"]["average_score"] == 0.0


@patch("src.middleware.auth.jwt")
@pytest.mark.parametrize(
    "path",
    [
        f"/api/v1/safety/inspections/{uuid.uuid4()}",
        f"/api/v1/safety/incidents/{uuid.uuid4()}",
    ],
)
def test_get_by_id_filters_by_token_org(mock_jwt, path):
    """A record of another organization is not found (404) because the lookup is org-scoped."""
    mock_jwt.decode.return_value = _payload()
    client, db = _client(None)

    resp = client.get(path, headers=_auth_header())

    assert resp.status_code == 404
    sql, params = _compiled(db, 0)
    assert "organization_id" in sql
    assert ORG_A in params.values()


@patch("src.middleware.auth.jwt")
def test_update_filters_by_token_org(mock_jwt):
    mock_jwt.decode.return_value = _payload()
    client, db = _client(None)

    resp = client.put(
        f"/api/v1/safety/hazards/{uuid.uuid4()}",
        json={"title": "x"},
        headers=_auth_header(),
    )

    assert resp.status_code == 404
    sql, params = _compiled(db, 0)
    assert "organization_id" in sql
    assert ORG_A in params.values()


@patch("src.middleware.auth.jwt")
@pytest.mark.parametrize(
    ("path", "body"),
    [
        (
            "/api/v1/safety/inspections",
            {
                "title": "t",
                "inspection_type": "daily",
                "inspector_id": str(uuid.uuid4()),
            },
        ),
        (
            "/api/v1/safety/hazards",
            {
                "title": "t",
                "description": "d",
                "hazard_type": "fall",
                "risk_level": "high",
                "severity": "high",
                "reported_by": str(uuid.uuid4()),
            },
        ),
    ],
)
def test_create_in_other_org_is_forbidden(mock_jwt, path, body):
    mock_jwt.decode.return_value = _payload()
    client, db = _client()

    resp = client.post(
        path, json={**body, "organization_id": str(ORG_B)}, headers=_auth_header()
    )

    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "ORG_FORBIDDEN"
    db.add.assert_not_called()


@patch("src.middleware.auth.jwt")
def test_list_other_org_is_forbidden(mock_jwt):
    mock_jwt.decode.return_value = _payload()
    client, db = _client()

    resp = client.get(
        "/api/v1/safety/hazards",
        params={"organization_id": str(ORG_B)},
        headers=_auth_header(),
    )

    assert resp.status_code == 403
    db.execute.assert_not_awaited()
