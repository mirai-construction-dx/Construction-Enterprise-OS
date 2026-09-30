"""Organization (tenant) isolation tests for the partner service (Issue #114, ADR-0004)."""

import base64
import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from src.main import create_app
from src.middleware.tenant import create_org, scope_org
from src.models.base import get_db
from src.schemas import TokenData

from .conftest import (
    make_mock_contract,
    make_mock_evaluation,
    make_mock_partner,
    make_mock_assignment,
)

ORG_A = uuid.uuid4()
ORG_B = uuid.uuid4()
PARTNER_ID = uuid.uuid4()
CONTRACT_ID = uuid.uuid4()


def _payload(org: str | None = str(ORG_A), roles: list[str] | None = None) -> dict:
    return {
        "sub": str(uuid.uuid4()),
        "type": "user",
        "org": org,
        "roles": roles if roles is not None else ["partner_manager"],
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

    def one_or_none(self):
        return self._value

    def scalars(self):
        mock = MagicMock()
        mock.all.return_value = self._value or []
        return mock


def _client(*values):
    app = create_app()
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=[_Result(v) for v in values])
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock()

    async def _db():
        yield db

    app.dependency_overrides[get_db] = _db
    return TestClient(app), db


def _user(**kw) -> TokenData:
    p = _payload(**kw)
    return TokenData(sub=p["sub"], type=p["type"], org=p["org"], roles=p["roles"])


def _params(db, index: int) -> dict:
    """Bound parameters of the ``index``-th executed statement.

    Note: ``str(select(Model))`` always lists ``organization_id`` as a column, so assertions
    are made on bound parameters (the WHERE values), not on the SQL text.
    """
    stmt = db.execute.await_args_list[index].args[0]
    return stmt.compile().params


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


# ── lists ────────────────────────────────────────────────────

LIST_PATHS = [
    "/api/v1/partners",
    "/api/v1/partners/contracts",
    "/api/v1/partners/evaluations",
    "/api/v1/partners/assignments",
    f"/api/v1/projects/{uuid.uuid4()}/assignments",
]


@patch("src.middleware.auth.jwt")
@pytest.mark.parametrize("path", LIST_PATHS)
def test_list_is_scoped_to_token_org(mock_jwt, path):
    mock_jwt.decode.return_value = _payload()
    client, db = _client(0, [])

    resp = client.get(path, headers=_auth_header())

    assert resp.status_code == 200
    # Both the count query and the page query are filtered by the caller's org.
    assert ORG_A in _params(db, 0).values()
    assert ORG_A in _params(db, 1).values()


@patch("src.middleware.auth.jwt")
@pytest.mark.parametrize("path", LIST_PATHS[:4])
def test_list_for_other_org_is_forbidden(mock_jwt, path):
    mock_jwt.decode.return_value = _payload()
    client, db = _client()

    resp = client.get(
        path, params={"organization_id": str(ORG_B)}, headers=_auth_header()
    )

    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "ORG_FORBIDDEN"
    db.execute.assert_not_awaited()


@patch("src.middleware.auth.jwt")
@pytest.mark.parametrize("org", [None, "not-a-uuid"])
@pytest.mark.parametrize("path", LIST_PATHS)
def test_list_without_valid_org_is_rejected(mock_jwt, path, org):
    mock_jwt.decode.return_value = _payload(org=org)
    client, db = _client()

    resp = client.get(path, headers=_auth_header())

    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] in {"ORG_REQUIRED", "ORG_INVALID"}
    db.execute.assert_not_awaited()


@patch("src.middleware.auth.jwt")
@pytest.mark.parametrize("path", LIST_PATHS[:4])
def test_admin_list_without_org_is_global(mock_jwt, path):
    mock_jwt.decode.return_value = _payload(roles=["admin"])
    client, db = _client(0, [])

    resp = client.get(path, headers=_auth_header())

    assert resp.status_code == 200
    assert ORG_A not in _params(db, 0).values()


@patch("src.middleware.auth.jwt")
@pytest.mark.parametrize("path", LIST_PATHS[:4])
def test_admin_list_with_org_is_filtered(mock_jwt, path):
    mock_jwt.decode.return_value = _payload(roles=["admin"])
    client, db = _client(0, [])

    resp = client.get(
        path, params={"organization_id": str(ORG_B)}, headers=_auth_header()
    )

    assert resp.status_code == 200
    assert ORG_B in _params(db, 0).values()


# ── by-id reads / updates / state transitions ────────────────

BY_ID_REQUESTS = [
    ("GET", f"/api/v1/partners/{PARTNER_ID}", None, "PARTNER_NOT_FOUND"),
    ("GET", f"/api/v1/partner/{PARTNER_ID}", None, "PARTNER_NOT_FOUND"),
    ("PUT", f"/api/v1/partners/{PARTNER_ID}", {"name": "x"}, "PARTNER_NOT_FOUND"),
    ("GET", f"/api/v1/partners/{PARTNER_ID}/contacts", None, "PARTNER_NOT_FOUND"),
    (
        "POST",
        f"/api/v1/partners/{PARTNER_ID}/contacts",
        {"name": "x", "email": "x@example.com"},
        "PARTNER_NOT_FOUND",
    ),
    ("GET", f"/api/v1/partners/{PARTNER_ID}/contracts", None, "PARTNER_NOT_FOUND"),
    ("GET", f"/api/v1/partners/{PARTNER_ID}/evaluations", None, "PARTNER_NOT_FOUND"),
    ("GET", f"/api/v1/partners/{PARTNER_ID}/rating", None, "PARTNER_NOT_FOUND"),
    ("GET", f"/api/v1/partners/contracts/{CONTRACT_ID}", None, "CONTRACT_NOT_FOUND"),
    (
        "PUT",
        f"/api/v1/partners/contracts/{CONTRACT_ID}",
        {"title": "x"},
        "CONTRACT_NOT_FOUND",
    ),
    (
        "POST",
        f"/api/v1/partners/contracts/{CONTRACT_ID}/sign",
        {"signed_by_our": str(uuid.uuid4()), "signed_by_partner": "相手先代表者"},
        "CONTRACT_NOT_FOUND",
    ),
]


@patch("src.middleware.auth.jwt")
@pytest.mark.parametrize(("method", "path", "body", "code"), BY_ID_REQUESTS)
def test_by_id_lookup_is_org_scoped_and_other_org_is_404(
    mock_jwt, method, path, body, code
):
    """A record of another organization is not found (404) because the lookup is org-scoped."""
    mock_jwt.decode.return_value = _payload()
    client, db = _client(None)

    resp = client.request(method, path, json=body, headers=_auth_header())

    assert resp.status_code != 422, resp.text
    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == code
    assert ORG_A in _params(db, 0).values()
    assert db.execute.await_count == 1  # nothing else is read or written
    db.add.assert_not_called()


@patch("src.middleware.auth.jwt")
def test_admin_by_id_lookup_is_cross_org(mock_jwt):
    mock_jwt.decode.return_value = _payload(roles=["admin"])
    client, db = _client(make_mock_contract(organization_id=ORG_B))

    resp = client.get(
        f"/api/v1/partners/contracts/{CONTRACT_ID}", headers=_auth_header()
    )

    assert resp.status_code == 200
    params = _params(db, 0).values()
    assert ORG_A not in params and ORG_B not in params


@patch("src.middleware.auth.jwt")
def test_contract_update_to_other_org_partner_is_404(mock_jwt):
    """A regular user cannot re-point an own-org contract to another org's partner."""
    mock_jwt.decode.return_value = _payload()
    contract = make_mock_contract(organization_id=ORG_A, partner_id=PARTNER_ID)
    client, db = _client(contract, None)
    new_partner_id = uuid.uuid4()

    resp = client.put(
        f"/api/v1/partners/contracts/{CONTRACT_ID}",
        json={"partner_id": str(new_partner_id)},
        headers=_auth_header(),
    )

    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "PARTNER_NOT_FOUND"
    assert ORG_A in _params(db, 0).values()  # contract lookup is org-scoped
    partner_params = _params(db, 1).values()
    assert new_partner_id in partner_params and ORG_A in partner_params
    assert contract.partner_id == PARTNER_ID  # not re-pointed


@patch("src.middleware.auth.jwt")
def test_admin_contract_update_to_other_org_partner_is_400(mock_jwt):
    """Admin (cross-org) still cannot move a contract to a partner of another organization."""
    mock_jwt.decode.return_value = _payload(roles=["admin"])
    contract = make_mock_contract(organization_id=ORG_A, partner_id=PARTNER_ID)
    other = make_mock_partner(id=uuid.uuid4(), organization_id=ORG_B)
    client, db = _client(contract, other)

    resp = client.put(
        f"/api/v1/partners/contracts/{CONTRACT_ID}",
        json={"partner_id": str(other.id), "title": "changed"},
        headers=_auth_header(),
    )

    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "PARTNER_ORG_MISMATCH"
    assert contract.partner_id == PARTNER_ID  # not re-pointed
    assert contract.organization_id == ORG_A
    assert contract.title == "試験契約"  # nothing else updated either


@patch("src.middleware.auth.jwt")
@pytest.mark.parametrize("roles", [None, ["admin"]])
def test_contract_update_to_same_org_partner_succeeds(mock_jwt, roles):
    mock_jwt.decode.return_value = _payload(roles=roles)
    contract = make_mock_contract(organization_id=ORG_A, partner_id=PARTNER_ID)
    same = make_mock_partner(id=uuid.uuid4(), organization_id=ORG_A)
    client, db = _client(contract, same)

    resp = client.put(
        f"/api/v1/partners/contracts/{CONTRACT_ID}",
        json={"partner_id": str(same.id)},
        headers=_auth_header(),
    )

    assert resp.status_code == 200, resp.text
    assert contract.partner_id == same.id
    assert resp.json()["data"]["partner_id"] == str(same.id)
    assert resp.json()["data"]["organization_id"] == str(ORG_A)
    if roles is None:
        # Regular users: the partner lookup is restricted to the contract's organization.
        assert ORG_A in _params(db, 1).values()


# ── creates ──────────────────────────────────────────────────

PARTNER_BODY = {"name": "テスト建設株式会社", "company_type": "subcontractor"}
CONTRACT_BODY = {
    "partner_id": str(PARTNER_ID),
    "title": "試験契約",
    "contract_type": "subcontract",
    "amount": 1000000.0,
    "start_date": "2026-05-01",
}
EVALUATION_BODY = {"partner_id": str(PARTNER_ID), "overall_score": 4.0}
ASSIGNMENT_BODY = {
    "partner_id": str(PARTNER_ID),
    "project_id": str(uuid.uuid4()),
    "role": "元請け",
}

CREATE_REQUESTS = [
    ("/api/v1/partners", PARTNER_BODY),
    ("/api/v1/partners/contracts", CONTRACT_BODY),
    ("/api/v1/partners/evaluations", EVALUATION_BODY),
    ("/api/v1/partners/assignments", ASSIGNMENT_BODY),
]


# Regular users: every create. Admin: top-level partner create (no org in body -> token org).
# Admin child creates take the referenced partner's org (test_admin_child_create_uses_partner_org).
NO_ORG_CREATE_CASES = [(path, body, None) for path, body in CREATE_REQUESTS] + [
    ("/api/v1/partners", PARTNER_BODY, ["admin"])
]


@patch("src.middleware.auth.jwt")
@pytest.mark.parametrize("org", [None, "not-a-uuid"])
@pytest.mark.parametrize(("path", "body", "roles"), NO_ORG_CREATE_CASES)
def test_create_without_valid_org_is_rejected(mock_jwt, path, body, roles, org):
    """The fixed ``...0001`` organization fallback is gone: no valid org -> 403 (fail-closed)."""
    mock_jwt.decode.return_value = _payload(org=org, roles=roles)
    client, db = _client(make_mock_partner(organization_id=ORG_A))

    resp = client.post(path, json=body, headers=_auth_header())

    assert resp.status_code != 422, resp.text
    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] in {"ORG_REQUIRED", "ORG_INVALID"}
    db.add.assert_not_called()


@patch("src.middleware.auth.jwt")
@pytest.mark.parametrize("roles", [None, ["admin"]])
def test_create_partner_uses_token_org(mock_jwt, roles):
    mock_jwt.decode.return_value = _payload(roles=roles)
    client, _ = _client()

    with patch(
        "src.api.partners.partner_service.create_partner",
        new_callable=AsyncMock,
        return_value=make_mock_partner(organization_id=ORG_A),
    ) as mock_create:
        resp = client.post(
            "/api/v1/partners", json=PARTNER_BODY, headers=_auth_header()
        )

    assert resp.status_code == 201
    assert mock_create.await_args.args[1] == ORG_A


@patch("src.middleware.auth.jwt")
@pytest.mark.parametrize(("path", "body"), CREATE_REQUESTS[1:])
def test_child_create_for_other_org_partner_is_404(mock_jwt, path, body):
    """Contracts / evaluations / assignments cannot be attached to another org's partner."""
    mock_jwt.decode.return_value = _payload()
    client, db = _client(None)

    resp = client.post(path, json=body, headers=_auth_header())

    assert resp.status_code != 422, resp.text
    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "PARTNER_NOT_FOUND"
    assert ORG_A in _params(db, 0).values()
    assert db.execute.await_count == 1  # no rating update on another org's partner
    db.add.assert_not_called()


CHILD_CREATE_TARGETS = [
    (
        "/api/v1/partners/contracts",
        CONTRACT_BODY,
        "src.api.contracts.contract_service.create_contract",
        make_mock_contract,
    ),
    (
        "/api/v1/partners/evaluations",
        EVALUATION_BODY,
        "src.api.evaluations.evaluation_service.create_evaluation",
        make_mock_evaluation,
    ),
    (
        "/api/v1/partners/assignments",
        ASSIGNMENT_BODY,
        "src.api.assignments.assignment_service.create_assignment",
        make_mock_assignment,
    ),
]


@patch("src.middleware.auth.jwt")
@pytest.mark.parametrize(("path", "body", "target", "factory"), CHILD_CREATE_TARGETS)
def test_child_create_uses_token_org(mock_jwt, path, body, target, factory):
    mock_jwt.decode.return_value = _payload()
    client, db = _client(make_mock_partner(organization_id=ORG_A), None, None)

    with (
        patch(target, new_callable=AsyncMock, return_value=factory()) as mock_create,
        patch(
            "src.api.evaluations.evaluation_service.update_partner_rating",
            new_callable=AsyncMock,
        ) as mock_rating,
    ):
        resp = client.post(path, json=body, headers=_auth_header())

    assert resp.status_code == 201, resp.text
    assert ORG_A in _params(db, 0).values()
    assert mock_create.await_args.args[1] == ORG_A
    if "evaluations" in path:
        assert mock_rating.await_args.args[2] == ORG_A


@patch("src.middleware.auth.jwt")
@pytest.mark.parametrize(("path", "body", "target", "factory"), CHILD_CREATE_TARGETS)
def test_admin_child_create_uses_partner_org(mock_jwt, path, body, target, factory):
    """Admin (cross-org) child records follow the referenced partner's organization."""
    mock_jwt.decode.return_value = _payload(roles=["admin"])
    client, db = _client(make_mock_partner(organization_id=ORG_B))

    with (
        patch(target, new_callable=AsyncMock, return_value=factory()) as mock_create,
        patch(
            "src.api.evaluations.evaluation_service.update_partner_rating",
            new_callable=AsyncMock,
        ),
    ):
        resp = client.post(path, json=body, headers=_auth_header())

    assert resp.status_code == 201, resp.text
    assert ORG_A not in _params(db, 0).values()  # unscoped lookup for admin
    assert mock_create.await_args.args[1] == ORG_B


@patch("src.middleware.auth.jwt")
def test_assignment_with_other_org_contract_is_404(mock_jwt):
    mock_jwt.decode.return_value = _payload()
    client, db = _client(make_mock_partner(organization_id=ORG_A), None)

    resp = client.post(
        "/api/v1/partners/assignments",
        json={**ASSIGNMENT_BODY, "contract_id": str(CONTRACT_ID)},
        headers=_auth_header(),
    )

    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "CONTRACT_NOT_FOUND"
    assert ORG_A in _params(db, 1).values()
    db.add.assert_not_called()


@patch("src.middleware.auth.jwt")
def test_evaluation_rating_update_is_org_scoped(mock_jwt):
    """The rating recomputation after an evaluation only reads/writes the caller's org."""
    mock_jwt.decode.return_value = _payload()
    partner = make_mock_partner(organization_id=ORG_A)
    # partner lookup, rating aggregate, partner fetch for rating update
    client, db = _client(partner, (4.0, 1), partner)

    with patch(
        "src.api.evaluations.evaluation_service.create_evaluation",
        new_callable=AsyncMock,
        return_value=make_mock_evaluation(),
    ):
        resp = client.post(
            "/api/v1/partners/evaluations", json=EVALUATION_BODY, headers=_auth_header()
        )

    assert resp.status_code == 201, resp.text
    assert db.execute.await_count == 3
    for i in range(3):
        assert ORG_A in _params(db, i).values()
