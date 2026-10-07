"""Organization (tenant) isolation tests for the vision service (Issue #114, ADR-0004)."""

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

from .test_vision import MockImageAnalysis, MockOCRResult, MockVectorIndex

ORG_A = uuid.uuid4()
ORG_B = uuid.uuid4()
RECORD_ID = uuid.uuid4()


def _payload(org: str | None = str(ORG_A), roles: list[str] | None = None) -> dict:
    return {
        "sub": str(uuid.uuid4()),
        "type": "user",
        "org": org,
        "roles": roles if roles is not None else ["vision_user"],
        "scopes": [],
    }


def _b64(data: dict) -> str:
    return base64.urlsafe_b64encode(json.dumps(data).encode()).decode().rstrip("=")


def _auth_header() -> dict:
    # Signature is not verified in tests: jwt.decode is patched per test.
    return {"Authorization": f"Bearer {_b64({'alg': 'HS256'})}.{_b64({})}.sig"}


class _Result:
    def __init__(self, value=None, rowcount: int = 0):
        self._value = value
        self.rowcount = rowcount

    def scalar_one_or_none(self):
        return self._value

    def scalars(self):
        mock = MagicMock()
        mock.all.return_value = self._value or []
        return mock


def _client(*results):
    app = create_app()
    db = AsyncMock()
    db.execute = AsyncMock(
        side_effect=[r if isinstance(r, _Result) else _Result(r) for r in results]
    )
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()

    async def _db():
        yield db

    app.dependency_overrides[get_db] = _db
    return TestClient(app), db


def _user(**kw) -> TokenData:
    p = _payload(**kw)
    return TokenData(sub=p["sub"], type=p["type"], org=p["org"], roles=p["roles"])


def _params(db, index: int) -> dict:
    """Bound parameters of the ``index``-th executed statement.

    ``str(select(Model))`` always lists ``organization_id`` as a column, so assertions are made
    on the bound WHERE values, not on the SQL text.
    """
    stmt = db.execute.await_args_list[index].args[0]
    return stmt.compile().params


def _assert_error(response, status_code: int, code: str) -> None:
    assert response.status_code == status_code, response.text
    assert response.json()["detail"]["code"] == code


def _assert_no_write(db) -> None:
    db.add.assert_not_called()
    db.flush.assert_not_awaited()
    db.commit.assert_not_awaited()


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
    "/api/v1/ocr/results",
    "/api/v1/vision/analyses",
    "/api/v1/vectors/indices",
]


@pytest.mark.parametrize("path", LIST_PATHS)
@patch("src.middleware.auth.jwt")
def test_list_other_org_is_forbidden(mock_jwt, path):
    mock_jwt.decode.return_value = _payload()
    client, db = _client()
    r = client.get(path, params={"organization_id": str(ORG_B)}, headers=_auth_header())
    _assert_error(r, 403, "ORG_FORBIDDEN")
    db.execute.assert_not_awaited()


@pytest.mark.parametrize("path", LIST_PATHS + ["/api/v1/vision/ocr/tasks"])
@patch("src.middleware.auth.jwt")
def test_list_is_filtered_by_token_org(mock_jwt, path):
    mock_jwt.decode.return_value = _payload()
    client, db = _client([])
    r = client.get(path, headers=_auth_header())
    assert r.status_code == 200, r.text
    assert ORG_A in _params(db, 0).values()


@pytest.mark.parametrize(
    ("org", "code"), [(None, "ORG_REQUIRED"), ("not-a-uuid", "ORG_INVALID")]
)
@pytest.mark.parametrize("path", LIST_PATHS + ["/api/v1/vision/ocr/tasks"])
@patch("src.middleware.auth.jwt")
def test_list_without_valid_org_fails_closed(mock_jwt, path, org, code):
    mock_jwt.decode.return_value = _payload(org=org)
    client, db = _client()
    r = client.get(path, headers=_auth_header())
    _assert_error(r, 403, code)
    db.execute.assert_not_awaited()


@pytest.mark.parametrize("path", LIST_PATHS + ["/api/v1/vision/ocr/tasks"])
@patch("src.middleware.auth.jwt")
def test_admin_list_without_org_is_unfiltered(mock_jwt, path):
    mock_jwt.decode.return_value = _payload(org=None, roles=["admin"])
    client, db = _client([])
    r = client.get(path, headers=_auth_header())
    assert r.status_code == 200, r.text
    params = _params(db, 0)
    assert ORG_A not in params.values()
    assert ORG_B not in params.values()


@pytest.mark.parametrize("path", LIST_PATHS)
@patch("src.middleware.auth.jwt")
def test_admin_list_other_org(mock_jwt, path):
    mock_jwt.decode.return_value = _payload(roles=["admin"])
    client, db = _client([])
    r = client.get(path, params={"organization_id": str(ORG_B)}, headers=_auth_header())
    assert r.status_code == 200, r.text
    assert ORG_B in _params(db, 0).values()


# ── by-id reads ──────────────────────────────────────────────

GET_PATHS = [
    f"/api/v1/ocr/results/{RECORD_ID}",
    f"/api/v1/vision/analyses/{RECORD_ID}",
    f"/api/v1/vectors/indices/{RECORD_ID}",
]


@pytest.mark.parametrize("path", GET_PATHS)
@patch("src.middleware.auth.jwt")
def test_get_other_org_record_is_not_found(mock_jwt, path):
    mock_jwt.decode.return_value = _payload()
    # The org-scoped query finds nothing for another organization's record.
    client, db = _client(None)
    r = client.get(path, headers=_auth_header())
    _assert_error(r, 404, "NOT_FOUND")
    params = _params(db, 0)
    assert RECORD_ID in params.values()
    assert ORG_A in params.values()


@pytest.mark.parametrize(
    ("path", "record"),
    [
        (GET_PATHS[0], MockOCRResult(id=RECORD_ID, organization_id=ORG_B)),
        (GET_PATHS[1], MockImageAnalysis(id=RECORD_ID, organization_id=ORG_B)),
        (GET_PATHS[2], MockVectorIndex(id=RECORD_ID, organization_id=ORG_B)),
    ],
)
@patch("src.middleware.auth.jwt")
def test_admin_get_other_org_record(mock_jwt, path, record):
    mock_jwt.decode.return_value = _payload(roles=["admin"])
    client, db = _client(record)
    r = client.get(path, headers=_auth_header())
    assert r.status_code == 200, r.text
    assert r.json()["data"]["organization_id"] == str(ORG_B)
    assert ORG_A not in _params(db, 0).values()


@pytest.mark.parametrize("path", GET_PATHS)
@patch("src.middleware.auth.jwt")
def test_get_without_org_fails_closed(mock_jwt, path):
    mock_jwt.decode.return_value = _payload(org=None)
    client, db = _client()
    r = client.get(path, headers=_auth_header())
    _assert_error(r, 403, "ORG_REQUIRED")
    db.execute.assert_not_awaited()


# ── by-id writes / actions ───────────────────────────────────


@patch("src.middleware.auth.jwt")
def test_update_other_org_index_is_not_found_and_not_written(mock_jwt):
    mock_jwt.decode.return_value = _payload()
    client, db = _client(None)
    r = client.patch(
        f"/api/v1/vectors/indices/{RECORD_ID}",
        json={"is_active": False},
        headers=_auth_header(),
    )
    _assert_error(r, 404, "NOT_FOUND")
    assert db.execute.await_count == 1
    assert ORG_A in _params(db, 0).values()
    _assert_no_write(db)


@patch("src.middleware.auth.jwt")
def test_delete_other_org_index_is_not_found_and_not_deleted(mock_jwt):
    mock_jwt.decode.return_value = _payload()
    client, db = _client(None)
    r = client.delete(f"/api/v1/vectors/indices/{RECORD_ID}", headers=_auth_header())
    _assert_error(r, 404, "NOT_FOUND")
    # Only the scoped SELECT ran; no DELETE statement was issued.
    assert db.execute.await_count == 1
    assert ORG_A in _params(db, 0).values()
    _assert_no_write(db)


@patch("src.middleware.auth.jwt")
def test_delete_own_org_index_is_scoped(mock_jwt):
    mock_jwt.decode.return_value = _payload(roles=["site_manager"])
    vi = MockVectorIndex(id=RECORD_ID, organization_id=ORG_A)
    client, db = _client(vi, _Result(rowcount=1))
    r = client.delete(f"/api/v1/vectors/indices/{RECORD_ID}", headers=_auth_header())
    assert r.status_code == 200, r.text
    assert r.json()["data"]["deleted"] is True
    assert ORG_A in _params(db, 0).values()
    assert ORG_A in _params(db, 1).values()  # DELETE also carries the org predicate


@patch("src.middleware.auth.jwt")
def test_delete_requires_management_role(mock_jwt):
    """削除は admin / site_manager のみ。非管理ロールは対象が見つかっても 403。"""
    mock_jwt.decode.return_value = _payload(roles=["vision_user"])
    vi = MockVectorIndex(id=RECORD_ID, organization_id=ORG_A)
    client, db = _client(vi, _Result(rowcount=1))
    r = client.delete(f"/api/v1/vectors/indices/{RECORD_ID}", headers=_auth_header())
    _assert_error(r, 403, "FORBIDDEN")
    # Scoped SELECT ran, but the role gate stopped the DELETE from being issued.
    assert db.execute.await_count == 1
    _assert_no_write(db)


@patch("src.middleware.auth.jwt")
def test_search_other_org_index_is_not_found(mock_jwt):
    mock_jwt.decode.return_value = _payload()
    client, db = _client(None)
    r = client.post(
        "/api/v1/vectors/search",
        json={"index_id": str(RECORD_ID), "query_text": "見積書", "top_k": 3},
        headers=_auth_header(),
    )
    _assert_error(r, 404, "NOT_FOUND")
    assert ORG_A in _params(db, 0).values()


@patch("src.middleware.auth.jwt")
def test_index_documents_into_other_org_index_is_not_found_and_not_written(mock_jwt):
    mock_jwt.decode.return_value = _payload()
    client, db = _client(None)
    r = client.post(
        "/api/v1/vectors/index",
        json={
            "index_id": str(RECORD_ID),
            "documents": [
                {
                    "source_id": str(uuid.uuid4()),
                    "source_type": "document",
                    "content": "x",
                }
            ],
        },
        headers=_auth_header(),
    )
    _assert_error(r, 404, "NOT_FOUND")
    assert db.execute.await_count == 1
    assert ORG_A in _params(db, 0).values()
    _assert_no_write(db)


@patch("src.middleware.auth.jwt")
def test_index_documents_own_org_is_scoped(mock_jwt):
    mock_jwt.decode.return_value = _payload()
    vi = MockVectorIndex(id=RECORD_ID, organization_id=ORG_A)
    client, db = _client(vi, vi)
    r = client.post(
        "/api/v1/vectors/index",
        json={
            "index_id": str(RECORD_ID),
            "documents": [
                {
                    "source_id": str(uuid.uuid4()),
                    "source_type": "document",
                    "content": "x",
                }
            ],
        },
        headers=_auth_header(),
    )
    assert r.status_code == 201, r.text
    assert ORG_A in _params(db, 0).values()
    assert ORG_A in _params(db, 1).values()  # counter update lookup is scoped too


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("patch", f"/api/v1/vectors/indices/{RECORD_ID}", {"is_active": False}),
        ("delete", f"/api/v1/vectors/indices/{RECORD_ID}", None),
        (
            "post",
            "/api/v1/vectors/search",
            {"index_id": str(RECORD_ID), "query_text": "q"},
        ),
        (
            "post",
            "/api/v1/vectors/index",
            {"index_id": str(RECORD_ID), "documents": []},
        ),
    ],
)
@patch("src.middleware.auth.jwt")
def test_actions_without_valid_org_fail_closed(mock_jwt, method, path, body):
    mock_jwt.decode.return_value = _payload(org="not-a-uuid")
    client, db = _client()
    kwargs = {"headers": _auth_header()}
    if body is not None:
        kwargs["json"] = body
    r = getattr(client, method)(path, **kwargs)
    _assert_error(r, 403, "ORG_INVALID")
    db.execute.assert_not_awaited()
    _assert_no_write(db)


@patch("src.middleware.auth.jwt")
def test_admin_update_other_org_index(mock_jwt):
    mock_jwt.decode.return_value = _payload(roles=["admin"])
    vi = MockVectorIndex(id=RECORD_ID, organization_id=ORG_B)
    client, db = _client(vi)
    r = client.patch(
        f"/api/v1/vectors/indices/{RECORD_ID}",
        json={"is_active": False},
        headers=_auth_header(),
    )
    assert r.status_code == 200, r.text
    assert vi.is_active is False
    assert ORG_A not in _params(db, 0).values()


# ── creates ──────────────────────────────────────────────────

CREATE_CASES = [
    ("/api/v1/ocr/process", {"file_key": "docs/a.pdf"}),
    (
        "/api/v1/vision/analyze",
        {"file_key": "img/a.jpg", "analysis_type": "object_detection"},
    ),
    ("/api/v1/vectors/indices", {"collection_name": "docs", "dimension": 8}),
]


@pytest.mark.parametrize(("path", "body"), CREATE_CASES)
@patch("src.middleware.auth.jwt")
def test_create_in_other_org_is_forbidden(mock_jwt, path, body):
    mock_jwt.decode.return_value = _payload()
    client, db = _client()
    r = client.post(
        path, json={**body, "organization_id": str(ORG_B)}, headers=_auth_header()
    )
    _assert_error(r, 403, "ORG_FORBIDDEN")
    _assert_no_write(db)


@pytest.mark.parametrize(("path", "body"), CREATE_CASES)
@patch("src.middleware.auth.jwt")
def test_create_without_org_fails_closed(mock_jwt, path, body):
    mock_jwt.decode.return_value = _payload(org=None)
    client, db = _client()
    r = client.post(
        path, json={**body, "organization_id": str(ORG_A)}, headers=_auth_header()
    )
    _assert_error(r, 403, "ORG_REQUIRED")
    _assert_no_write(db)


@pytest.mark.parametrize(("path", "body"), CREATE_CASES)
@patch("src.middleware.auth.jwt")
def test_create_in_own_org(mock_jwt, path, body):
    mock_jwt.decode.return_value = _payload()
    client, db = _client()
    r = client.post(
        path, json={**body, "organization_id": str(ORG_A)}, headers=_auth_header()
    )
    assert r.status_code == 201, r.text
    assert db.add.call_args.args[0].organization_id == ORG_A


@pytest.mark.parametrize(("path", "body"), CREATE_CASES)
@patch("src.middleware.auth.jwt")
def test_admin_creates_in_body_org(mock_jwt, path, body):
    mock_jwt.decode.return_value = _payload(roles=["admin"])
    client, db = _client()
    r = client.post(
        path, json={**body, "organization_id": str(ORG_B)}, headers=_auth_header()
    )
    assert r.status_code == 201, r.text
    assert db.add.call_args.args[0].organization_id == ORG_B
