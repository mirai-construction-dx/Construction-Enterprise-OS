"""Organization (tenant) isolation tests for the security service (Issue #114, ADR-0004)."""

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
BASE = "/api/v1/security"


def _payload(org: str | None = str(ORG_A), roles: list[str] | None = None) -> dict:
    return {
        "sub": str(uuid.uuid4()),
        "type": "user",
        "org": org,
        "roles": roles if roles is not None else ["security_manager"],
        "scopes": [],
    }


def _b64(data: dict) -> str:
    return base64.urlsafe_b64encode(json.dumps(data).encode()).decode().rstrip("=")


def _auth_header() -> dict:
    # Signature is not verified in tests: jwt.decode is patched per test.
    return {"Authorization": f"Bearer {_b64({'alg': 'HS256'})}.{_b64({})}.sig"}


class _Result:
    """Minimal stand-in for a SQLAlchemy result (scalar / rows / scalars)."""

    def __init__(self, value=None):
        self._value = value

    def scalar(self):
        return self._value

    def scalar_one_or_none(self):
        return self._value

    def all(self):
        return self._value if isinstance(self._value, list) else []

    def scalars(self):
        return self


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


def _assert_scoped_to(db, index: int, org: uuid.UUID) -> None:
    sql, params = _compiled(db, index)
    assert ":organization_id" in sql
    assert org in params.values()


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
    assert exc.value.detail["code"] == "ORG_FORBIDDEN"


# ── dashboard ────────────────────────────────────────────────

# Query order in get_dashboard: incident severity, vulnerability severity,
# policies due review, recent incidents, latest audit.
_DASHBOARD_RESULTS = ([], [], 0, [], None)


@patch("src.middleware.auth.jwt")
def test_dashboard_is_scoped_to_token_org(mock_jwt):
    mock_jwt.decode.return_value = _payload()
    client, db = _client(*_DASHBOARD_RESULTS)

    resp = client.get(f"{BASE}/dashboard", headers=_auth_header())

    assert resp.status_code == 200
    assert db.execute.await_count == 5
    for i in range(5):
        _assert_scoped_to(db, i, ORG_A)


@patch("src.middleware.auth.jwt")
def test_dashboard_for_other_org_is_forbidden(mock_jwt):
    mock_jwt.decode.return_value = _payload()
    client, db = _client()

    resp = client.get(
        f"{BASE}/dashboard",
        params={"organization_id": str(ORG_B)},
        headers=_auth_header(),
    )

    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "ORG_FORBIDDEN"
    db.execute.assert_not_awaited()


@pytest.mark.parametrize(
    ("org", "code"), [(None, "ORG_REQUIRED"), ("bad", "ORG_INVALID")]
)
@patch("src.middleware.auth.jwt")
def test_dashboard_without_valid_org_fails_closed(mock_jwt, org, code):
    mock_jwt.decode.return_value = _payload(org=org)
    client, db = _client()

    resp = client.get(f"{BASE}/dashboard", headers=_auth_header())

    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == code
    db.execute.assert_not_awaited()


@patch("src.middleware.auth.jwt")
def test_admin_dashboard_without_org_is_global(mock_jwt):
    mock_jwt.decode.return_value = _payload(roles=["admin"])
    client, db = _client(*_DASHBOARD_RESULTS)

    resp = client.get(f"{BASE}/dashboard", headers=_auth_header())

    assert resp.status_code == 200
    for i in range(5):
        assert ":organization_id" not in _compiled(db, i)[0]


@patch("src.middleware.auth.jwt")
def test_admin_dashboard_with_org_is_scoped(mock_jwt):
    mock_jwt.decode.return_value = _payload(roles=["admin"])
    client, db = _client(*_DASHBOARD_RESULTS)

    resp = client.get(
        f"{BASE}/dashboard",
        params={"organization_id": str(ORG_B)},
        headers=_auth_header(),
    )

    assert resp.status_code == 200
    for i in range(5):
        _assert_scoped_to(db, i, ORG_B)


# ── lists / aggregates ───────────────────────────────────────


@patch("src.middleware.auth.jwt")
@pytest.mark.parametrize(
    ("path", "result"),
    [
        ("/incidents", []),
        ("/vulnerabilities", []),
        ("/policies", []),
        ("/incidents/active", 0),
        ("/vulnerabilities/open", []),
    ],
)
def test_list_and_aggregate_default_to_token_org(mock_jwt, path, result):
    mock_jwt.decode.return_value = _payload()
    client, db = _client(result)

    resp = client.get(f"{BASE}{path}", headers=_auth_header())

    assert resp.status_code == 200
    _assert_scoped_to(db, 0, ORG_A)


@patch("src.middleware.auth.jwt")
@pytest.mark.parametrize(
    "path",
    [
        "/incidents",
        "/vulnerabilities",
        "/policies",
        "/incidents/active",
        "/vulnerabilities/open",
    ],
)
def test_list_and_aggregate_other_org_is_forbidden(mock_jwt, path):
    mock_jwt.decode.return_value = _payload()
    client, db = _client()

    resp = client.get(
        f"{BASE}{path}",
        params={"organization_id": str(ORG_B)},
        headers=_auth_header(),
    )

    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "ORG_FORBIDDEN"
    db.execute.assert_not_awaited()


@patch("src.middleware.auth.jwt")
def test_admin_list_without_org_is_global(mock_jwt):
    mock_jwt.decode.return_value = _payload(roles=["admin"])
    client, db = _client([])

    resp = client.get(f"{BASE}/incidents", headers=_auth_header())

    assert resp.status_code == 200
    assert ":organization_id" not in _compiled(db, 0)[0]


# ── by-id: get / update / state transition ───────────────────


@patch("src.middleware.auth.jwt")
@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("get", f"/incidents/{uuid.uuid4()}", None),
        ("put", f"/incidents/{uuid.uuid4()}", {"status": "investigating"}),
        (
            "post",
            f"/incidents/{uuid.uuid4()}/updates",
            {"update_type": "note", "content": "c"},
        ),
        ("put", f"/vulnerabilities/{uuid.uuid4()}", {"status": "fixed"}),
        ("get", f"/policies/{uuid.uuid4()}", None),
        ("put", f"/policies/{uuid.uuid4()}", {"name": "n"}),
        ("post", f"/policies/{uuid.uuid4()}/review", None),
    ],
)
def test_by_id_lookup_is_org_scoped_and_other_org_is_404(mock_jwt, method, path, body):
    """A record of another organization is not found (404) because the lookup is org-scoped."""
    mock_jwt.decode.return_value = _payload()
    client, db = _client(None)

    kwargs: dict = {"headers": _auth_header()}
    if body is not None:
        kwargs["json"] = body
    resp = getattr(client, method)(f"{BASE}{path}", **kwargs)

    assert resp.status_code == 404
    _assert_scoped_to(db, 0, ORG_A)
    db.add.assert_not_called()


@patch("src.middleware.auth.jwt")
def test_admin_by_id_lookup_is_not_org_filtered(mock_jwt):
    mock_jwt.decode.return_value = _payload(roles=["admin"])
    client, db = _client(None)

    resp = client.get(f"{BASE}/policies/{uuid.uuid4()}", headers=_auth_header())

    assert resp.status_code == 404
    assert ":organization_id" not in _compiled(db, 0)[0]


# ── create ───────────────────────────────────────────────────

_CREATE_CASES = [
    ("/incidents", {"title": "t", "severity": "high", "incident_type": "malware"}),
    ("/vulnerabilities", {"title": "t", "severity": "high"}),
    ("/policies", {"name": "n", "category": "access_control", "content": "c"}),
]


@patch("src.middleware.auth.jwt")
@pytest.mark.parametrize(("path", "body"), _CREATE_CASES)
def test_create_in_other_org_is_forbidden(mock_jwt, path, body):
    mock_jwt.decode.return_value = _payload()
    client, db = _client()

    resp = client.post(
        f"{BASE}{path}",
        json={**body, "organization_id": str(ORG_B)},
        headers=_auth_header(),
    )

    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "ORG_FORBIDDEN"
    db.add.assert_not_called()


@patch("src.middleware.auth.jwt")
@pytest.mark.parametrize(("path", "body"), _CREATE_CASES)
def test_create_in_own_org_succeeds(mock_jwt, path, body):
    mock_jwt.decode.return_value = _payload()
    client, db = _client()

    resp = client.post(
        f"{BASE}{path}",
        json={**body, "organization_id": str(ORG_A)},
        headers=_auth_header(),
    )

    assert resp.status_code == 201
    assert db.add.call_args.args[0].organization_id == ORG_A


@patch("src.middleware.auth.jwt")
@pytest.mark.parametrize(("path", "body"), _CREATE_CASES)
def test_admin_can_create_in_any_org(mock_jwt, path, body):
    mock_jwt.decode.return_value = _payload(roles=["admin"])
    client, db = _client()

    resp = client.post(
        f"{BASE}{path}",
        json={**body, "organization_id": str(ORG_B)},
        headers=_auth_header(),
    )

    assert resp.status_code == 201
    assert db.add.call_args.args[0].organization_id == ORG_B
