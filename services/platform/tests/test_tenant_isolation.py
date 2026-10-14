"""Organization (tenant) isolation tests for the platform service (Issue #114, ADR-0004)."""

import base64
import json
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
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
DASHBOARD_ID = uuid.uuid4()
GROUP_ID = uuid.uuid4()
PARENT_ID = uuid.uuid4()
CONFIG_ID = uuid.uuid4()
SCENE_ID = uuid.uuid4()
NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _payload(org: str | None = str(ORG_A), roles: list[str] | None = None) -> dict:
    return {
        "sub": str(uuid.uuid4()),
        "type": "user",
        "org": org,
        "roles": roles if roles is not None else ["viewer"],
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
        mock = MagicMock()
        mock.all.return_value = self._value or []
        return mock


def _client(*values):
    """TestClient whose DB returns ``values`` in order and commits like ``get_db`` does."""
    app = create_app()
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=[_Result(v) for v in values])
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock()
    db.delete = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()

    async def _db():
        try:
            yield db
            await db.commit()
        except Exception:
            await db.rollback()
            raise

    app.dependency_overrides[get_db] = _db
    return TestClient(app), db


def _user(**kw) -> TokenData:
    p = _payload(**kw)
    return TokenData(sub=p["sub"], type=p["type"], org=p["org"], roles=p["roles"])


def _params(db, index: int) -> dict:
    """Bound parameters of the ``index``-th executed statement (the WHERE values)."""
    stmt = db.execute.await_args_list[index].args[0]
    return stmt.compile().params


def _assert_no_write(db) -> None:
    db.add.assert_not_called()
    db.flush.assert_not_awaited()
    db.delete.assert_not_awaited()
    db.commit.assert_not_awaited()


def _group(org: uuid.UUID, group_id: uuid.UUID = GROUP_ID) -> SimpleNamespace:
    return SimpleNamespace(
        id=group_id,
        organization_id=org,
        name="Site Sensors",
        description=None,
        device_ids=[],
        group_type="site",
        parent_group_id=None,
        created_at=NOW,
    )


def _dashboard(org: uuid.UUID) -> SimpleNamespace:
    return SimpleNamespace(
        id=DASHBOARD_ID,
        organization_id=org,
        project_id=None,
        name="Dashboard",
        description=None,
        layout={"widgets": []},
        refresh_interval_seconds=10,
        is_public=False,
        created_by=None,
        created_at=NOW,
        updated_at=NOW,
    )


def _config(org: uuid.UUID) -> SimpleNamespace:
    return SimpleNamespace(
        id=CONFIG_ID,
        organization_id=org,
        project_id=None,
        name="Viewer",
        viewer_type="bim_3d",
        model_ids=[],
        layer_ids=[],
        camera_state={},
        visible_categories=[],
        clipping_planes={},
        theme="light",
        created_by=None,
        created_at=NOW,
        updated_at=NOW,
        scenes=[],
    )


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


def test_token_without_roles_is_not_admin():
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


# ── lists ────────────────────────────────────────────────────

LIST_PATHS = [
    "/platform/iot/dashboards",
    "/platform/iot/device-groups",
    "/platform/viewer/configs",
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
@pytest.mark.parametrize("path", LIST_PATHS)
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
@pytest.mark.parametrize(
    ("org", "code"), [(None, "ORG_REQUIRED"), ("not-a-uuid", "ORG_INVALID")]
)
@pytest.mark.parametrize("path", LIST_PATHS)
def test_list_without_valid_org_is_rejected(mock_jwt, path, org, code):
    mock_jwt.decode.return_value = _payload(org=org)
    client, db = _client()

    resp = client.get(path, headers=_auth_header())

    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == code
    db.execute.assert_not_awaited()


@patch("src.middleware.auth.jwt")
@pytest.mark.parametrize("path", LIST_PATHS)
def test_admin_list_without_org_is_global(mock_jwt, path):
    mock_jwt.decode.return_value = _payload(roles=["admin"])
    client, db = _client(0, [])

    resp = client.get(path, headers=_auth_header())

    assert resp.status_code == 200
    assert ORG_A not in _params(db, 0).values()
    assert ORG_A not in _params(db, 1).values()


@patch("src.middleware.auth.jwt")
@pytest.mark.parametrize("path", LIST_PATHS)
def test_admin_list_with_org_is_filtered(mock_jwt, path):
    mock_jwt.decode.return_value = _payload(roles=["admin"])
    client, db = _client(0, [])

    resp = client.get(
        path, params={"organization_id": str(ORG_B)}, headers=_auth_header()
    )

    assert resp.status_code == 200
    assert ORG_B in _params(db, 0).values()
    assert ORG_B in _params(db, 1).values()


# ── by-id reads / updates / deletes / child records ─────────

BY_ID_REQUESTS = [
    ("PUT", f"/platform/iot/dashboards/{DASHBOARD_ID}", {"name": "x"}),
    ("GET", f"/platform/iot/device-groups/{GROUP_ID}", None),
    ("PUT", f"/platform/iot/device-groups/{GROUP_ID}/devices", {"device_ids": []}),
    ("GET", f"/platform/viewer/configs/{CONFIG_ID}", None),
    ("DELETE", f"/platform/viewer/configs/{CONFIG_ID}", None),
    (
        "POST",
        f"/platform/viewer/configs/{CONFIG_ID}/scenes",
        {"name": "Scene", "camera_state": {"position": {"x": 0}}},
    ),
    ("GET", f"/platform/viewer/scenes/{SCENE_ID}", None),
]


@patch("src.middleware.auth.jwt")
@pytest.mark.parametrize(("method", "path", "body"), BY_ID_REQUESTS)
def test_by_id_other_org_is_404_without_write(mock_jwt, method, path, body):
    """A record of another organization is not found because the lookup is org-scoped."""
    mock_jwt.decode.return_value = _payload()
    client, db = _client(None)

    resp = client.request(method, path, json=body, headers=_auth_header())

    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "NOT_FOUND"
    assert db.execute.await_count == 1
    assert ORG_A in _params(db, 0).values()
    _assert_no_write(db)
    db.rollback.assert_awaited()


@patch("src.middleware.auth.jwt")
@pytest.mark.parametrize(
    ("org", "code"), [(None, "ORG_REQUIRED"), ("not-a-uuid", "ORG_INVALID")]
)
@pytest.mark.parametrize(("method", "path", "body"), BY_ID_REQUESTS)
def test_by_id_without_valid_org_is_rejected(mock_jwt, method, path, body, org, code):
    mock_jwt.decode.return_value = _payload(org=org)
    client, db = _client()

    resp = client.request(method, path, json=body, headers=_auth_header())

    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == code
    db.execute.assert_not_awaited()
    _assert_no_write(db)


@patch("src.middleware.auth.jwt")
@pytest.mark.parametrize(("method", "path", "body"), BY_ID_REQUESTS)
def test_admin_by_id_lookup_is_not_org_filtered(mock_jwt, method, path, body):
    mock_jwt.decode.return_value = _payload(roles=["admin"])
    client, db = _client(None)

    resp = client.request(method, path, json=body, headers=_auth_header())

    assert resp.status_code == 404
    assert ORG_A not in _params(db, 0).values()


@patch("src.middleware.auth.jwt")
def test_scene_lookup_is_scoped_through_parent_config(mock_jwt):
    mock_jwt.decode.return_value = _payload()
    client, db = _client(None)

    client.get(f"/platform/viewer/scenes/{SCENE_ID}", headers=_auth_header())

    sql = str(db.execute.await_args_list[0].args[0])
    assert "JOIN platform.viewer_configs" in sql
    assert ORG_A in _params(db, 0).values()


@patch("src.middleware.auth.jwt")
def test_admin_can_update_other_org_dashboard(mock_jwt):
    mock_jwt.decode.return_value = _payload(roles=["admin"])
    client, db = _client(_dashboard(ORG_B))

    resp = client.put(
        f"/platform/iot/dashboards/{DASHBOARD_ID}",
        json={"name": "x"},
        headers=_auth_header(),
    )

    assert resp.status_code == 200
    assert resp.json()["data"]["organization_id"] == str(ORG_B)
    db.commit.assert_awaited()


@patch("src.middleware.auth.jwt")
def test_admin_can_delete_other_org_config(mock_jwt):
    mock_jwt.decode.return_value = _payload(roles=["admin"])
    config = _config(ORG_B)
    client, db = _client(config)

    resp = client.delete(
        f"/platform/viewer/configs/{CONFIG_ID}", headers=_auth_header()
    )

    assert resp.status_code == 200
    db.delete.assert_awaited_once_with(config)


@patch("src.middleware.auth.jwt")
def test_delete_config_requires_management_role(mock_jwt):
    mock_jwt.decode.return_value = _payload(roles=["viewer"])  # non-management
    config = _config(ORG_A)  # same org -> passes the org-scoped 404 check
    client, db = _client(config)

    resp = client.delete(
        f"/platform/viewer/configs/{CONFIG_ID}", headers=_auth_header()
    )

    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "FORBIDDEN"
    db.delete.assert_not_awaited()


# ── create ───────────────────────────────────────────────────

CREATE_REQUESTS = [
    ("/platform/iot/dashboards", {"name": "d", "layout": {"widgets": []}}),
    ("/platform/iot/device-groups", {"name": "g"}),
    ("/platform/viewer/configs", {"name": "v", "viewer_type": "bim_3d"}),
]


@patch("src.middleware.auth.jwt")
@pytest.mark.parametrize(("path", "body"), CREATE_REQUESTS)
def test_create_in_other_org_is_forbidden(mock_jwt, path, body):
    mock_jwt.decode.return_value = _payload()
    client, db = _client()

    resp = client.post(
        path, json={**body, "organization_id": str(ORG_B)}, headers=_auth_header()
    )

    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "ORG_FORBIDDEN"
    db.execute.assert_not_awaited()
    _assert_no_write(db)


@patch("src.middleware.auth.jwt")
@pytest.mark.parametrize(
    ("org", "code"), [(None, "ORG_REQUIRED"), ("not-a-uuid", "ORG_INVALID")]
)
@pytest.mark.parametrize(("path", "body"), CREATE_REQUESTS)
def test_create_without_valid_org_is_rejected(mock_jwt, path, body, org, code):
    mock_jwt.decode.return_value = _payload(org=org)
    client, db = _client()

    resp = client.post(
        path, json={**body, "organization_id": str(ORG_A)}, headers=_auth_header()
    )

    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == code
    _assert_no_write(db)


@patch("src.middleware.auth.jwt")
@pytest.mark.parametrize("roles", [["viewer"], ["admin"]])
@pytest.mark.parametrize(("path", "body"), CREATE_REQUESTS)
def test_create_stores_the_resolved_org(mock_jwt, path, body, roles):
    """Regular users create in their own org; admins may create in any org (body org)."""
    mock_jwt.decode.return_value = _payload(roles=roles)
    target = ORG_A if roles == ["viewer"] else ORG_B
    client, db = _client()
    # refresh() is mocked, so fill the server-side defaults the response schema needs.
    db.refresh = AsyncMock(
        side_effect=lambda obj: obj.__dict__.update(
            id=uuid.uuid4(), created_at=NOW, updated_at=NOW
        )
    )

    resp = client.post(
        path, json={**body, "organization_id": str(target)}, headers=_auth_header()
    )

    assert resp.status_code == 200
    stored = db.add.call_args.args[0]
    assert stored.organization_id == target


# ── device group parent references ──────────────────────────


@patch("src.middleware.auth.jwt")
def test_create_group_with_other_org_parent_is_404(mock_jwt):
    mock_jwt.decode.return_value = _payload()
    client, db = _client(None)

    resp = client.post(
        "/platform/iot/device-groups",
        json={
            "organization_id": str(ORG_A),
            "name": "g",
            "parent_group_id": str(PARENT_ID),
        },
        headers=_auth_header(),
    )

    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "PARENT_GROUP_NOT_FOUND"
    assert ORG_A in _params(db, 0).values()
    assert PARENT_ID in _params(db, 0).values()
    _assert_no_write(db)


@patch("src.middleware.auth.jwt")
def test_admin_create_group_with_parent_of_different_org_is_400(mock_jwt):
    mock_jwt.decode.return_value = _payload(roles=["admin"])
    client, db = _client(_group(ORG_B, PARENT_ID))

    resp = client.post(
        "/platform/iot/device-groups",
        json={
            "organization_id": str(ORG_A),
            "name": "g",
            "parent_group_id": str(PARENT_ID),
        },
        headers=_auth_header(),
    )

    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "PARENT_GROUP_ORG_MISMATCH"
    _assert_no_write(db)


@patch("src.middleware.auth.jwt")
def test_update_group_with_other_org_parent_is_404(mock_jwt):
    mock_jwt.decode.return_value = _payload()
    group = _group(ORG_A)
    client, db = _client(group, None)

    resp = client.put(
        f"/platform/iot/device-groups/{GROUP_ID}/devices",
        json={"parent_group_id": str(PARENT_ID)},
        headers=_auth_header(),
    )

    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "PARENT_GROUP_NOT_FOUND"
    assert ORG_A in _params(db, 1).values()
    assert group.parent_group_id is None
    _assert_no_write(db)


@patch("src.middleware.auth.jwt")
def test_admin_update_group_with_parent_of_different_org_is_400(mock_jwt):
    mock_jwt.decode.return_value = _payload(roles=["admin"])
    group = _group(ORG_A)
    client, db = _client(group, _group(ORG_B, PARENT_ID))

    resp = client.put(
        f"/platform/iot/device-groups/{GROUP_ID}/devices",
        json={"parent_group_id": str(PARENT_ID)},
        headers=_auth_header(),
    )

    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "PARENT_GROUP_ORG_MISMATCH"
    assert group.parent_group_id is None
    _assert_no_write(db)


@patch("src.middleware.auth.jwt")
def test_update_group_with_same_org_parent_succeeds(mock_jwt):
    mock_jwt.decode.return_value = _payload()
    group = _group(ORG_A)
    client, db = _client(group, _group(ORG_A, PARENT_ID))

    resp = client.put(
        f"/platform/iot/device-groups/{GROUP_ID}/devices",
        json={"parent_group_id": str(PARENT_ID)},
        headers=_auth_header(),
    )

    assert resp.status_code == 200
    assert group.parent_group_id == PARENT_ID
    db.commit.assert_awaited()
