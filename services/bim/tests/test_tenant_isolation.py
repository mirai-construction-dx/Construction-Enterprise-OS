"""Organization (tenant) isolation tests for the BIM service (Issue #114, ADR-0004)."""

import base64
import json
import re
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from src.api.elements import search_elements
from src.main import create_app
from src.middleware.auth import TokenData
from src.middleware.tenant import create_org, scope_org
from src.models import BIMElement, BIMModel, PointCloud
from src.models.base import get_db

ORG_A = uuid.uuid4()
ORG_B = uuid.uuid4()
NOW = datetime(2026, 9, 30, tzinfo=timezone.utc)


def _payload(org: str | None = str(ORG_A), roles: list[str] | None = None) -> dict:
    return {
        "sub": str(uuid.uuid4()),
        "type": "user",
        "org": org,
        "roles": roles if roles is not None else ["bim_manager"],
        "scopes": [],
    }


def _b64(data: dict) -> str:
    return base64.urlsafe_b64encode(json.dumps(data).encode()).decode().rstrip("=")


def _auth_header() -> dict:
    # Signature is not verified in tests: jwt.decode is patched per test.
    return {"Authorization": f"Bearer {_b64({'alg': 'HS256'})}.{_b64({})}.sig"}


class _Result:
    """Result stub usable for scalar(), scalar_one_or_none() and scalars().all()."""

    def __init__(self, value=None):
        self._value = value

    def scalar(self):
        return self._value

    def scalar_one_or_none(self):
        return self._value

    def scalars(self):
        return self

    def all(self):
        return self._value if isinstance(self._value, list) else []


async def _refresh(obj):
    if getattr(obj, "id", None) is None:
        obj.id = uuid.uuid4()
    obj.created_at = NOW
    if hasattr(type(obj), "updated_at"):
        obj.updated_at = NOW
    if isinstance(obj, BIMModel) and obj.status is None:
        obj.status = "draft"


def _client(*values):
    app = create_app()
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=[_Result(v) for v in values])
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock(side_effect=_refresh)
    db.delete = AsyncMock()
    db.commit = AsyncMock()

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


def _where(sql: str) -> str:
    # Only the filter part matters: the SELECT list always contains organization_id.
    parts = re.split(r"\sWHERE\s", sql, maxsplit=1)
    return parts[1] if len(parts) == 2 else ""


def _assert_org_filtered(db, index: int, org: uuid.UUID) -> None:
    sql, params = _compiled(db, index)
    assert "organization_id" in _where(sql)
    assert org in params.values()


def _assert_not_org_filtered(db, index: int) -> None:
    sql, _ = _compiled(db, index)
    assert "organization_id" not in _where(sql)


def _assert_no_write(db) -> None:
    db.add.assert_not_called()
    db.flush.assert_not_awaited()
    db.delete.assert_not_awaited()
    db.commit.assert_not_awaited()


def _model(org: uuid.UUID = ORG_A) -> BIMModel:
    return BIMModel(
        id=uuid.uuid4(),
        organization_id=org,
        name="Model",
        model_type="architectural",
        file_format="ifc",
        status="draft",
        tags=[],
        metadata_={},
        created_at=NOW,
        updated_at=NOW,
    )


def _element(model_id: uuid.UUID) -> BIMElement:
    return BIMElement(
        id=uuid.uuid4(),
        model_id=model_id,
        name="Wall-01",
        category="walls",
        created_at=NOW,
    )


def _pointcloud(org: uuid.UUID = ORG_A) -> PointCloud:
    return PointCloud(
        id=uuid.uuid4(),
        organization_id=org,
        name="Scan",
        is_colorized=False,
        is_classified=False,
        metadata_={},
        created_at=NOW,
    )


MODEL_BODY = {"name": "M", "model_type": "architectural", "file_format": "ifc"}
PC_BODY = {"name": "Scan", "capture_method": "lidar"}


# ── helper rules ─────────────────────────────────────────────


def test_scope_org_regular_user_is_pinned_to_token_org():
    assert scope_org(_user()) == ORG_A
    assert scope_org(_user(), ORG_A) == ORG_A


def test_scope_org_rejects_other_org_for_regular_user():
    with pytest.raises(HTTPException) as exc:
        scope_org(_user(), ORG_B)
    assert exc.value.status_code == 403
    assert exc.value.detail["code"] == "ORG_FORBIDDEN"


def test_missing_roles_claim_is_not_admin():
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


# ── fail-closed on every org-owned endpoint ──────────────────

ENDPOINTS = [
    ("get", "/api/v1/bim/models", None),
    ("post", "/api/v1/bim/models", {**MODEL_BODY, "organization_id": str(ORG_A)}),
    ("get", f"/api/v1/bim/models/{uuid.uuid4()}", None),
    ("put", f"/api/v1/bim/models/{uuid.uuid4()}", {"name": "x"}),
    ("delete", f"/api/v1/bim/models/{uuid.uuid4()}", None),
    ("get", f"/api/v1/bim/{uuid.uuid4()}/elements", None),
    ("get", f"/api/v1/bim/{uuid.uuid4()}/elements/by-category", None),
    ("get", f"/api/v1/bim/{uuid.uuid4()}/elements/by-level", None),
    ("get", f"/api/v1/bim/elements/{uuid.uuid4()}", None),
    ("get", "/api/v1/bim/pointclouds", None),
    ("post", "/api/v1/bim/pointclouds", {**PC_BODY, "organization_id": str(ORG_A)}),
    ("get", f"/api/v1/bim/pointclouds/{uuid.uuid4()}", None),
    ("put", f"/api/v1/bim/pointclouds/{uuid.uuid4()}", {"name": "x"}),
    ("delete", f"/api/v1/bim/pointclouds/{uuid.uuid4()}", None),
]


@pytest.mark.parametrize(("method", "path", "body"), ENDPOINTS)
@pytest.mark.parametrize(
    ("org", "code"), [(None, "ORG_REQUIRED"), ("not-a-uuid", "ORG_INVALID")]
)
@patch("src.middleware.auth.jwt")
def test_endpoints_fail_closed_without_valid_org(
    mock_jwt, org, code, method, path, body
):
    mock_jwt.decode.return_value = _payload(org=org)
    client, db = _client()

    kwargs = {"headers": _auth_header()}
    if body is not None:
        kwargs["json"] = body
    resp = getattr(client, method)(path, **kwargs)

    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == code
    db.execute.assert_not_awaited()
    _assert_no_write(db)


# ── models ───────────────────────────────────────────────────


@patch("src.middleware.auth.jwt")
def test_list_models_is_scoped_to_token_org(mock_jwt):
    mock_jwt.decode.return_value = _payload()
    client, db = _client(0, [])

    resp = client.get("/api/v1/bim/models", headers=_auth_header())

    assert resp.status_code == 200
    _assert_org_filtered(db, 0, ORG_A)  # count
    _assert_org_filtered(db, 1, ORG_A)  # page


@patch("src.middleware.auth.jwt")
def test_list_models_for_other_org_is_forbidden(mock_jwt):
    mock_jwt.decode.return_value = _payload()
    client, db = _client()

    resp = client.get(
        "/api/v1/bim/models",
        params={"organization_id": str(ORG_B)},
        headers=_auth_header(),
    )

    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "ORG_FORBIDDEN"
    db.execute.assert_not_awaited()


@patch("src.middleware.auth.jwt")
def test_admin_list_models_without_org_is_global(mock_jwt):
    mock_jwt.decode.return_value = _payload(roles=["admin"])
    client, db = _client(0, [])

    resp = client.get("/api/v1/bim/models", headers=_auth_header())

    assert resp.status_code == 200
    _assert_not_org_filtered(db, 0)
    _assert_not_org_filtered(db, 1)


@patch("src.middleware.auth.jwt")
def test_admin_list_models_with_org_filters_that_org(mock_jwt):
    mock_jwt.decode.return_value = _payload(roles=["admin"])
    client, db = _client(0, [])

    resp = client.get(
        "/api/v1/bim/models",
        params={"organization_id": str(ORG_B)},
        headers=_auth_header(),
    )

    assert resp.status_code == 200
    _assert_org_filtered(db, 0, ORG_B)
    _assert_org_filtered(db, 1, ORG_B)


@patch("src.middleware.auth.jwt")
def test_get_model_of_other_org_is_404(mock_jwt):
    mock_jwt.decode.return_value = _payload()
    client, db = _client(None)  # org-scoped lookup finds nothing

    resp = client.get(f"/api/v1/bim/models/{uuid.uuid4()}", headers=_auth_header())

    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "NOT_FOUND"
    _assert_org_filtered(db, 0, ORG_A)


@patch("src.middleware.auth.jwt")
def test_update_model_of_other_org_is_404_without_write(mock_jwt):
    mock_jwt.decode.return_value = _payload()
    client, db = _client(None)

    resp = client.put(
        f"/api/v1/bim/models/{uuid.uuid4()}",
        json={"name": "hijack"},
        headers=_auth_header(),
    )

    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "NOT_FOUND"
    _assert_org_filtered(db, 0, ORG_A)
    _assert_no_write(db)


@patch("src.middleware.auth.jwt")
def test_delete_model_of_other_org_is_404_without_write(mock_jwt):
    mock_jwt.decode.return_value = _payload()
    client, db = _client(None)

    resp = client.delete(f"/api/v1/bim/models/{uuid.uuid4()}", headers=_auth_header())

    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "NOT_FOUND"
    _assert_org_filtered(db, 0, ORG_A)
    _assert_no_write(db)


@patch("src.middleware.auth.jwt")
def test_update_own_model_succeeds(mock_jwt):
    mock_jwt.decode.return_value = _payload()
    model = _model()
    client, db = _client(model)

    resp = client.put(
        f"/api/v1/bim/models/{model.id}",
        json={"name": "renamed"},
        headers=_auth_header(),
    )

    assert resp.status_code == 200
    assert model.name == "renamed"
    _assert_org_filtered(db, 0, ORG_A)
    db.flush.assert_awaited_once()


@patch("src.middleware.auth.jwt")
def test_admin_get_model_is_not_org_filtered(mock_jwt):
    mock_jwt.decode.return_value = _payload(roles=["admin"])
    model = _model(ORG_B)
    client, db = _client(model)

    resp = client.get(f"/api/v1/bim/models/{model.id}", headers=_auth_header())

    assert resp.status_code == 200
    assert resp.json()["data"]["organization_id"] == str(ORG_B)
    _assert_not_org_filtered(db, 0)


@patch("src.middleware.auth.jwt")
def test_create_model_in_other_org_is_forbidden(mock_jwt):
    mock_jwt.decode.return_value = _payload()
    client, db = _client()

    resp = client.post(
        "/api/v1/bim/models",
        json={**MODEL_BODY, "organization_id": str(ORG_B)},
        headers=_auth_header(),
    )

    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "ORG_FORBIDDEN"
    _assert_no_write(db)


@patch("src.middleware.auth.jwt")
def test_create_model_in_own_org_succeeds(mock_jwt):
    mock_jwt.decode.return_value = _payload()
    client, db = _client()

    resp = client.post(
        "/api/v1/bim/models",
        json={**MODEL_BODY, "organization_id": str(ORG_A)},
        headers=_auth_header(),
    )

    assert resp.status_code == 200
    added = db.add.call_args.args[0]
    assert added.organization_id == ORG_A
    assert resp.json()["data"]["organization_id"] == str(ORG_A)


@patch("src.middleware.auth.jwt")
def test_admin_creates_model_in_any_org(mock_jwt):
    mock_jwt.decode.return_value = _payload(roles=["admin"])
    client, db = _client()

    resp = client.post(
        "/api/v1/bim/models",
        json={**MODEL_BODY, "organization_id": str(ORG_B)},
        headers=_auth_header(),
    )

    assert resp.status_code == 200
    assert db.add.call_args.args[0].organization_id == ORG_B


# ── elements (scoped through the parent model) ───────────────

MODEL_CHILD_PATHS = ["elements", "elements/by-category", "elements/by-level"]


@pytest.mark.parametrize("suffix", MODEL_CHILD_PATHS)
@patch("src.middleware.auth.jwt")
def test_elements_of_other_org_model_are_404(mock_jwt, suffix):
    mock_jwt.decode.return_value = _payload()
    client, db = _client(None)  # parent model not found within ORG_A

    resp = client.get(f"/api/v1/bim/{uuid.uuid4()}/{suffix}", headers=_auth_header())

    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "NOT_FOUND"
    # Only the org-scoped parent lookup ran; element rows were never queried.
    assert db.execute.await_count == 1
    sql, params = _compiled(db, 0)
    assert "bim_models" in sql
    assert ORG_A in params.values()


@pytest.mark.parametrize("suffix", MODEL_CHILD_PATHS)
@patch("src.middleware.auth.jwt")
def test_elements_of_own_model_are_listed(mock_jwt, suffix):
    mock_jwt.decode.return_value = _payload()
    model = _model()
    element = _element(model.id)
    values = (model, 1, [element]) if suffix == "elements" else (model, [element])
    client, db = _client(*values)

    resp = client.get(f"/api/v1/bim/{model.id}/{suffix}", headers=_auth_header())

    assert resp.status_code == 200
    assert resp.json()["success"] is True
    _assert_org_filtered(db, 0, ORG_A)


@pytest.mark.parametrize("suffix", MODEL_CHILD_PATHS)
@patch("src.middleware.auth.jwt")
def test_admin_elements_cross_org(mock_jwt, suffix):
    mock_jwt.decode.return_value = _payload(roles=["admin"])
    model = _model(ORG_B)
    values = (model, 0, []) if suffix == "elements" else (model, [])
    client, db = _client(*values)

    resp = client.get(f"/api/v1/bim/{model.id}/{suffix}", headers=_auth_header())

    assert resp.status_code == 200
    _assert_not_org_filtered(db, 0)


@patch("src.middleware.auth.jwt")
def test_get_element_of_other_org_is_404(mock_jwt):
    mock_jwt.decode.return_value = _payload()
    client, db = _client(None)

    resp = client.get(f"/api/v1/bim/elements/{uuid.uuid4()}", headers=_auth_header())

    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "NOT_FOUND"
    sql, params = _compiled(db, 0)
    assert "JOIN bim.bim_models" in sql
    assert "bim_models.organization_id" in sql
    assert ORG_A in params.values()


@patch("src.middleware.auth.jwt")
def test_admin_get_element_is_not_org_filtered(mock_jwt):
    mock_jwt.decode.return_value = _payload(roles=["admin"])
    element = _element(uuid.uuid4())
    client, db = _client(element)

    resp = client.get(f"/api/v1/bim/elements/{element.id}", headers=_auth_header())

    assert resp.status_code == 200
    sql, _ = _compiled(db, 0)
    assert "bim_models" not in sql


def _search_db(*values):
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=[_Result(v) for v in values])
    return db


async def _search(user: TokenData, db, organization_id=None, model_id=None):
    return await search_elements(
        q="wall",
        model_id=model_id,
        organization_id=organization_id,
        page=1,
        per_page=20,
        token_data=user,
        db=db,
    )


@pytest.mark.anyio
async def test_search_elements_is_scoped_to_token_org():
    db = _search_db(0, [])

    await _search(_user(), db)

    for i in range(2):
        sql, params = _compiled(db, i)
        assert "JOIN bim.bim_models" in sql
        assert "bim_models.organization_id" in sql
        assert ORG_A in params.values()


@pytest.mark.anyio
async def test_search_elements_with_other_org_model_stays_org_scoped():
    db = _search_db(0, [])

    await _search(_user(), db, model_id=uuid.uuid4())

    sql, params = _compiled(db, 1)
    assert "bim_models.organization_id" in sql
    assert ORG_A in params.values()


@pytest.mark.anyio
async def test_search_elements_for_other_org_is_forbidden():
    db = _search_db()

    with pytest.raises(HTTPException) as exc:
        await _search(_user(), db, organization_id=ORG_B)

    assert exc.value.status_code == 403
    assert exc.value.detail["code"] == "ORG_FORBIDDEN"
    db.execute.assert_not_awaited()


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("org", "code"), [(None, "ORG_REQUIRED"), ("not-a-uuid", "ORG_INVALID")]
)
async def test_search_elements_fails_closed_without_valid_org(org, code):
    db = _search_db()

    with pytest.raises(HTTPException) as exc:
        await _search(_user(org=org), db)

    assert exc.value.status_code == 403
    assert exc.value.detail["code"] == code
    db.execute.assert_not_awaited()


@pytest.mark.anyio
async def test_admin_search_elements_is_global():
    db = _search_db(0, [])

    await _search(_user(roles=["admin"]), db)

    for i in range(2):
        sql, _ = _compiled(db, i)
        assert "bim_models" not in sql


# ── point clouds ─────────────────────────────────────────────


@patch("src.middleware.auth.jwt")
def test_list_pointclouds_is_scoped_to_token_org(mock_jwt):
    mock_jwt.decode.return_value = _payload()
    client, db = _client(0, [])

    resp = client.get("/api/v1/bim/pointclouds", headers=_auth_header())

    assert resp.status_code == 200
    _assert_org_filtered(db, 0, ORG_A)
    _assert_org_filtered(db, 1, ORG_A)


@patch("src.middleware.auth.jwt")
def test_list_pointclouds_for_other_org_is_forbidden(mock_jwt):
    mock_jwt.decode.return_value = _payload()
    client, db = _client()

    resp = client.get(
        "/api/v1/bim/pointclouds",
        params={"organization_id": str(ORG_B)},
        headers=_auth_header(),
    )

    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "ORG_FORBIDDEN"
    db.execute.assert_not_awaited()


@patch("src.middleware.auth.jwt")
def test_admin_list_pointclouds_without_org_is_global(mock_jwt):
    mock_jwt.decode.return_value = _payload(roles=["admin"])
    client, db = _client(0, [])

    resp = client.get("/api/v1/bim/pointclouds", headers=_auth_header())

    assert resp.status_code == 200
    _assert_not_org_filtered(db, 0)
    _assert_not_org_filtered(db, 1)


@pytest.mark.parametrize(
    ("method", "body"), [("get", None), ("put", {"name": "hijack"}), ("delete", None)]
)
@patch("src.middleware.auth.jwt")
def test_pointcloud_by_id_of_other_org_is_404_without_write(mock_jwt, method, body):
    mock_jwt.decode.return_value = _payload()
    client, db = _client(None)

    kwargs = {"headers": _auth_header()}
    if body is not None:
        kwargs["json"] = body
    resp = getattr(client, method)(f"/api/v1/bim/pointclouds/{uuid.uuid4()}", **kwargs)

    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "NOT_FOUND"
    _assert_org_filtered(db, 0, ORG_A)
    _assert_no_write(db)


@patch("src.middleware.auth.jwt")
def test_delete_own_pointcloud_succeeds(mock_jwt):
    mock_jwt.decode.return_value = _payload()
    pc = _pointcloud()
    client, db = _client(pc)

    resp = client.delete(f"/api/v1/bim/pointclouds/{pc.id}", headers=_auth_header())

    assert resp.status_code == 200
    _assert_org_filtered(db, 0, ORG_A)
    db.delete.assert_awaited_once_with(pc)


@patch("src.middleware.auth.jwt")
def test_admin_get_pointcloud_is_not_org_filtered(mock_jwt):
    mock_jwt.decode.return_value = _payload(roles=["admin"])
    pc = _pointcloud(ORG_B)
    client, db = _client(pc)

    resp = client.get(f"/api/v1/bim/pointclouds/{pc.id}", headers=_auth_header())

    assert resp.status_code == 200
    assert resp.json()["data"]["organization_id"] == str(ORG_B)
    _assert_not_org_filtered(db, 0)


@patch("src.middleware.auth.jwt")
def test_create_pointcloud_in_other_org_is_forbidden(mock_jwt):
    mock_jwt.decode.return_value = _payload()
    client, db = _client()

    resp = client.post(
        "/api/v1/bim/pointclouds",
        json={**PC_BODY, "organization_id": str(ORG_B)},
        headers=_auth_header(),
    )

    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "ORG_FORBIDDEN"
    _assert_no_write(db)


@patch("src.middleware.auth.jwt")
def test_create_pointcloud_in_own_org_succeeds(mock_jwt):
    mock_jwt.decode.return_value = _payload()
    client, db = _client()

    resp = client.post(
        "/api/v1/bim/pointclouds",
        json={**PC_BODY, "organization_id": str(ORG_A)},
        headers=_auth_header(),
    )

    assert resp.status_code == 200
    assert db.add.call_args.args[0].organization_id == ORG_A


@patch("src.middleware.auth.jwt")
def test_admin_creates_pointcloud_in_any_org(mock_jwt):
    mock_jwt.decode.return_value = _payload(roles=["admin"])
    client, db = _client()

    resp = client.post(
        "/api/v1/bim/pointclouds",
        json={**PC_BODY, "organization_id": str(ORG_B)},
        headers=_auth_header(),
    )

    assert resp.status_code == 200
    assert db.add.call_args.args[0].organization_id == ORG_B
