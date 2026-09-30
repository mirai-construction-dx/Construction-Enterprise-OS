"""Organization (tenant) isolation tests for the document service (ADR-0004, Issue #114)."""

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
DOC_ID = uuid.uuid4()
BASE = "/api/v1/documents"


def _payload(org: str | None = str(ORG_A), roles: list[str] | None = None) -> dict:
    return {
        "sub": str(uuid.uuid4()),
        "type": "user",
        "org": org,
        "roles": roles if roles is not None else ["member"],
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

    def scalars(self):
        return self

    def all(self):
        return self._value or []


def _client(*values):
    app = create_app()
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=[_Result(v) for v in values])
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()

    async def _db():
        yield db

    app.dependency_overrides[get_db] = _db
    return TestClient(app), db


def _user(**kw) -> TokenData:
    p = _payload(**kw)
    return TokenData(sub=p["sub"], type=p["type"], org=p["org"], roles=p["roles"])


def _compiled(db, index: int):
    """Return (WHERE clause, bound params); the SELECT column list always names organization_id."""
    stmt = db.execute.await_args_list[index].args[0]
    sql = str(stmt)
    where = sql.split("WHERE", 1)[1] if "WHERE" in sql else ""
    return where, stmt.compile().params


def _assert_no_write(db):
    db.add.assert_not_called()
    db.flush.assert_not_awaited()
    db.commit.assert_not_awaited()


_FILE = {"file": ("a.pdf", b"%PDF-1.4 x", "application/pdf")}


# -- helper rules --------------------------------------------------------------


def test_scope_org_regular_user_is_pinned_to_token_org():
    assert scope_org(_user()) == ORG_A
    assert scope_org(_user(), ORG_A) == ORG_A


def test_scope_org_rejects_other_org_for_regular_user():
    with pytest.raises(HTTPException) as exc:
        scope_org(_user(), ORG_B)
    assert exc.value.status_code == 403
    assert exc.value.detail["code"] == "ORG_FORBIDDEN"


def test_roles_none_is_treated_as_regular_user():
    user = TokenData(sub=str(uuid.uuid4()), type="user", org=str(ORG_A), roles=None)
    assert scope_org(user) == ORG_A


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


# -- fail-closed (no zero-org fallback) ----------------------------------------


@patch("src.middleware.auth.jwt")
@pytest.mark.parametrize(
    ("org", "code"), [(None, "ORG_REQUIRED"), ("not-a-uuid", "ORG_INVALID")]
)
@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", BASE),
        ("get", f"{BASE}/{DOC_ID}"),
        ("get", f"{BASE}/{DOC_ID}/download"),
        ("get", f"{BASE}/{DOC_ID}/versions"),
        ("get", f"{BASE}/{DOC_ID}/versions/1"),
        ("delete", f"{BASE}/{DOC_ID}"),
    ],
)
def test_missing_or_invalid_org_is_rejected(mock_jwt, method, path, org, code):
    mock_jwt.decode.return_value = _payload(org=org)
    client, db = _client()

    resp = getattr(client, method)(path, headers=_auth_header())

    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == code
    db.execute.assert_not_awaited()


@patch("src.middleware.auth.jwt")
@pytest.mark.parametrize(
    ("org", "code"), [(None, "ORG_REQUIRED"), ("not-a-uuid", "ORG_INVALID")]
)
def test_update_without_valid_org_is_rejected(mock_jwt, org, code):
    mock_jwt.decode.return_value = _payload(org=org)
    client, db = _client()

    resp = client.put(f"{BASE}/{DOC_ID}", json={"name": "x"}, headers=_auth_header())

    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == code
    db.execute.assert_not_awaited()
    _assert_no_write(db)


@patch("src.services.document_service.upload_file")
@patch("src.middleware.auth.jwt")
@pytest.mark.parametrize(
    ("org", "code"), [(None, "ORG_REQUIRED"), ("not-a-uuid", "ORG_INVALID")]
)
def test_upload_without_valid_org_is_rejected(mock_jwt, mock_upload, org, code):
    """Previously an org-less token stored the document under UUID(int=0)."""
    mock_jwt.decode.return_value = _payload(org=org)
    client, db = _client()

    resp = client.post(
        f"{BASE}/upload", data={"name": "n"}, files=_FILE, headers=_auth_header()
    )

    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == code
    _assert_no_write(db)
    mock_upload.assert_not_called()


@patch("src.services.document_service.upload_file")
@patch("src.middleware.auth.jwt")
@pytest.mark.parametrize(
    ("org", "code"), [(None, "ORG_REQUIRED"), ("not-a-uuid", "ORG_INVALID")]
)
def test_new_version_without_valid_org_is_rejected(mock_jwt, mock_upload, org, code):
    mock_jwt.decode.return_value = _payload(org=org)
    client, db = _client()

    resp = client.post(f"{BASE}/{DOC_ID}/versions", files=_FILE, headers=_auth_header())

    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == code
    db.execute.assert_not_awaited()
    _assert_no_write(db)
    mock_upload.assert_not_called()


# -- list ----------------------------------------------------------------------


@patch("src.middleware.auth.jwt")
def test_list_is_scoped_to_token_org(mock_jwt):
    mock_jwt.decode.return_value = _payload()
    client, db = _client(0, [])

    resp = client.get(BASE, headers=_auth_header())

    assert resp.status_code == 200
    for i in range(2):
        sql, params = _compiled(db, i)
        assert "organization_id" in sql
        assert ORG_A in params.values()


@patch("src.middleware.auth.jwt")
def test_list_for_other_org_is_forbidden(mock_jwt):
    mock_jwt.decode.return_value = _payload()
    client, db = _client()

    resp = client.get(
        BASE, params={"organization_id": str(ORG_B)}, headers=_auth_header()
    )

    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "ORG_FORBIDDEN"
    db.execute.assert_not_awaited()


@patch("src.middleware.auth.jwt")
def test_admin_list_without_org_is_global(mock_jwt):
    mock_jwt.decode.return_value = _payload(roles=["admin"])
    client, db = _client(0, [])

    resp = client.get(BASE, headers=_auth_header())

    assert resp.status_code == 200
    for i in range(2):
        assert "organization_id" not in _compiled(db, i)[0]


@patch("src.middleware.auth.jwt")
def test_admin_list_with_other_org_filters_that_org(mock_jwt):
    mock_jwt.decode.return_value = _payload(roles=["admin"])
    client, db = _client(0, [])

    resp = client.get(
        BASE, params={"organization_id": str(ORG_B)}, headers=_auth_header()
    )

    assert resp.status_code == 200
    for i in range(2):
        sql, params = _compiled(db, i)
        assert "organization_id" in sql
        assert ORG_B in params.values()
        assert ORG_A not in params.values()


@patch("src.middleware.auth.jwt")
def test_admin_without_org_can_list_globally(mock_jwt):
    mock_jwt.decode.return_value = _payload(org=None, roles=["admin"])
    client, db = _client(0, [])

    resp = client.get(BASE, headers=_auth_header())

    assert resp.status_code == 200
    assert "organization_id" not in _compiled(db, 0)[0]


# -- by-id (other org = 404, no write) -----------------------------------------


@patch("src.middleware.auth.jwt")
@pytest.mark.parametrize(
    "path",
    [
        f"{BASE}/{DOC_ID}",
        f"{BASE}/{DOC_ID}/download",
        f"{BASE}/{DOC_ID}/versions",
        f"{BASE}/{DOC_ID}/versions/1",
    ],
)
def test_get_by_id_of_other_org_is_not_found(mock_jwt, path):
    """A document of another organization is 404 because the lookup is org-scoped."""
    mock_jwt.decode.return_value = _payload()
    client, db = _client(None)

    resp = client.get(path, headers=_auth_header())

    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "NOT_FOUND"
    assert db.execute.await_count == 1  # no child (version) query after the miss
    sql, params = _compiled(db, 0)
    assert "organization_id" in sql
    assert ORG_A in params.values()


@patch("src.middleware.auth.jwt")
def test_update_of_other_org_is_not_found_and_not_written(mock_jwt):
    mock_jwt.decode.return_value = _payload()
    client, db = _client(None)

    resp = client.put(
        f"{BASE}/{DOC_ID}", json={"name": "hijack"}, headers=_auth_header()
    )

    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "NOT_FOUND"
    sql, params = _compiled(db, 0)
    assert "organization_id" in sql
    assert ORG_A in params.values()
    _assert_no_write(db)


@patch("src.middleware.auth.jwt")
def test_delete_of_other_org_is_not_found_and_not_written(mock_jwt):
    mock_jwt.decode.return_value = _payload()
    client, db = _client(None)

    resp = client.delete(f"{BASE}/{DOC_ID}", headers=_auth_header())

    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "NOT_FOUND"
    sql, params = _compiled(db, 0)
    assert "organization_id" in sql
    assert ORG_A in params.values()
    _assert_no_write(db)


@patch("src.services.document_service.upload_file")
@patch("src.middleware.auth.jwt")
def test_new_version_of_other_org_is_not_found_and_not_written(mock_jwt, mock_upload):
    mock_jwt.decode.return_value = _payload()
    client, db = _client(None)

    resp = client.post(f"{BASE}/{DOC_ID}/versions", files=_FILE, headers=_auth_header())

    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "NOT_FOUND"
    sql, params = _compiled(db, 0)
    assert "organization_id" in sql
    assert ORG_A in params.values()
    _assert_no_write(db)
    mock_upload.assert_not_called()


@patch("src.middleware.auth.jwt")
def test_admin_get_by_id_is_cross_org(mock_jwt):
    mock_jwt.decode.return_value = _payload(roles=["admin"])
    client, db = _client(None)

    resp = client.get(f"{BASE}/{DOC_ID}", headers=_auth_header())

    assert resp.status_code == 404
    assert "organization_id" not in _compiled(db, 0)[0]


# -- create (upload) ------------------------------------------------------------


@patch("src.services.document_service.upload_file")
@patch("src.middleware.auth.jwt")
def test_upload_into_other_org_is_forbidden(mock_jwt, mock_upload):
    mock_jwt.decode.return_value = _payload()
    client, db = _client()

    resp = client.post(
        f"{BASE}/upload",
        data={"name": "n", "organization_id": str(ORG_B)},
        files=_FILE,
        headers=_auth_header(),
    )

    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "ORG_FORBIDDEN"
    _assert_no_write(db)
    mock_upload.assert_not_called()


@patch("src.services.document_service.create_document", new_callable=AsyncMock)
@patch("src.middleware.auth.jwt")
@pytest.mark.parametrize("body_org", [None, str(ORG_A)])
def test_upload_uses_token_org_for_regular_user(mock_jwt, mock_create, body_org):
    mock_jwt.decode.return_value = _payload()
    mock_create.side_effect = RuntimeError("stop after org resolution")
    client, _ = _client()
    data = {"name": "n"}
    if body_org:
        data["organization_id"] = body_org

    client.post(f"{BASE}/upload", data=data, files=_FILE, headers=_auth_header())

    assert mock_create.await_args.kwargs["organization_id"] == ORG_A


@patch("src.services.document_service.create_document", new_callable=AsyncMock)
@patch("src.middleware.auth.jwt")
def test_admin_upload_uses_body_org(mock_jwt, mock_create):
    mock_jwt.decode.return_value = _payload(roles=["admin"])
    mock_create.side_effect = RuntimeError("stop after org resolution")
    client, _ = _client()

    client.post(
        f"{BASE}/upload",
        data={"name": "n", "organization_id": str(ORG_B)},
        files=_FILE,
        headers=_auth_header(),
    )

    assert mock_create.await_args.kwargs["organization_id"] == ORG_B
