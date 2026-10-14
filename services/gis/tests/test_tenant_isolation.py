"""Organization (tenant) isolation tests for the GIS service (Issue #114, ADR-0004)."""

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
from src.models import ConstructionSite, HazardZone, Infrastructure
from src.models.base import get_db

ORG_A = uuid.uuid4()
ORG_B = uuid.uuid4()
RECORD_ID = uuid.uuid4()

POINT = {"type": "Point", "coordinates": [139.6917, 35.6895]}
POLYGON = {
    "type": "Polygon",
    "coordinates": [
        [[139.0, 35.0], [140.0, 35.0], [140.0, 36.0], [139.0, 36.0], [139.0, 35.0]]
    ],
}


def _payload(org: str | None = str(ORG_A), roles: list[str] | None = None) -> dict:
    return {
        "sub": str(uuid.uuid4()),
        "type": "user",
        "org": org,
        "roles": roles if roles is not None else ["site_manager"],
        "scopes": [],
    }


def _b64(data: dict) -> str:
    return base64.urlsafe_b64encode(json.dumps(data).encode()).decode().rstrip("=")


AUTH = {"Authorization": f"Bearer {_b64({'alg': 'HS256'})}.{_b64({})}.sig"}


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
    app = create_app()
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=[_Result(v) for v in values])
    db.add = MagicMock()
    db.delete = AsyncMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock()
    db.commit = AsyncMock()

    async def _db():
        yield db

    app.dependency_overrides[get_db] = _db
    return TestClient(app), db


def _user(**kw) -> TokenData:
    p = _payload(**kw)
    return TokenData(sub=p["sub"], type=p["type"], org=p["org"], roles=p["roles"])


def _params(db, index: int) -> list:
    """Bound parameter values of the ``index``-th executed statement.

    ``str(select(Model))`` always lists ``organization_id`` as a column, so assertions are made
    on bound parameters (the WHERE values), not on the SQL text.
    """
    stmt = db.execute.await_args_list[index].args[0]
    return list(stmt.compile().params.values())


def _site(org=ORG_A, work_area=None) -> ConstructionSite:
    return ConstructionSite(
        id=RECORD_ID,
        organization_id=org,
        name="Site",
        location="SRID=4326;POINT(139.6917 35.6895)",
        work_area=work_area,
        status="active",
        metadata_={},
    )


def _infra(org=ORG_A) -> Infrastructure:
    return Infrastructure(
        id=RECORD_ID,
        organization_id=org,
        name="Bridge",
        infra_type="bridge",
        location="SRID=4326;POINT(139.6917 35.6895)",
        status="active",
        metadata_={},
    )


def _zone(org=ORG_A) -> HazardZone:
    return HazardZone(
        id=RECORD_ID,
        organization_id=org,
        name="Flood",
        hazard_type="flood",
        zone_area="SRID=4326;POLYGON((139 35, 140 35, 140 36, 139 36, 139 35))",
        risk_level="high",
        metadata_={},
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


def test_roles_none_is_not_admin():
    user = TokenData(sub="u", type="user", org=str(ORG_A), roles=None)
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


# ── lists / spatial searches ─────────────────────────────────

PAGED_LISTS = [
    "/api/v1/gis/sites",
    "/api/v1/gis/infrastructure",
    "/api/v1/gis/hazard-zones",
]
SPATIAL_SEARCHES = [
    "/api/v1/gis/sites/nearby?lat=35.0&lng=139.0&radius_m=1000",
    "/api/v1/gis/sites/in-area?min_lat=35.0&min_lng=139.0&max_lat=36.0&max_lng=140.0",
]
SITE_CHILD_QUERIES = [
    f"/api/v1/gis/infrastructure/near-site/{RECORD_ID}",
    f"/api/v1/gis/hazard-zones/intersecting/{RECORD_ID}",
]
ALL_READS = PAGED_LISTS + SPATIAL_SEARCHES + SITE_CHILD_QUERIES


def _with(path: str, query: str) -> str:
    return f"{path}{'&' if '?' in path else '?'}{query}"


@patch("src.middleware.auth.jwt")
@pytest.mark.parametrize("path", ALL_READS)
def test_read_other_org_is_forbidden(mock_jwt, path):
    mock_jwt.decode.return_value = _payload()
    client, db = _client()
    resp = client.get(_with(path, f"organization_id={ORG_B}"), headers=AUTH)
    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "ORG_FORBIDDEN"
    db.execute.assert_not_awaited()


@patch("src.middleware.auth.jwt")
@pytest.mark.parametrize("path", PAGED_LISTS)
def test_paged_list_and_count_are_scoped_to_token_org(mock_jwt, path):
    mock_jwt.decode.return_value = _payload()
    client, db = _client(0, [])
    resp = client.get(path, headers=AUTH)
    assert resp.status_code == 200
    assert ORG_A in _params(db, 0)  # count
    assert ORG_A in _params(db, 1)  # page


@patch("src.middleware.auth.jwt")
@pytest.mark.parametrize("path", SPATIAL_SEARCHES)
def test_spatial_search_is_scoped_to_token_org(mock_jwt, path):
    mock_jwt.decode.return_value = _payload()
    client, db = _client([])
    resp = client.get(path, headers=AUTH)
    assert resp.status_code == 200
    assert ORG_A in _params(db, 0)


@patch("src.middleware.auth.jwt")
@pytest.mark.parametrize("path", SITE_CHILD_QUERIES)
def test_site_child_query_other_org_site_is_404(mock_jwt, path):
    mock_jwt.decode.return_value = _payload()
    client, db = _client(None)  # site of another org is not visible
    resp = client.get(path, headers=AUTH)
    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "NOT_FOUND"
    assert db.execute.await_count == 1
    assert ORG_A in _params(db, 0)


@patch("src.middleware.auth.jwt")
def test_near_site_child_query_is_scoped_to_token_org(mock_jwt):
    mock_jwt.decode.return_value = _payload()
    client, db = _client(_site(), [])
    resp = client.get(f"/api/v1/gis/infrastructure/near-site/{RECORD_ID}", headers=AUTH)
    assert resp.status_code == 200
    assert ORG_A in _params(db, 0)  # site lookup
    assert ORG_A in _params(db, 1)  # infrastructure search


@patch("src.middleware.auth.jwt")
def test_intersecting_child_query_is_scoped_to_token_org(mock_jwt):
    mock_jwt.decode.return_value = _payload()
    site = _site(
        work_area="SRID=4326;POLYGON((139 35, 140 35, 140 36, 139 36, 139 35))"
    )
    client, db = _client(site, [])
    resp = client.get(
        f"/api/v1/gis/hazard-zones/intersecting/{RECORD_ID}", headers=AUTH
    )
    assert resp.status_code == 200
    assert ORG_A in _params(db, 0)  # site lookup
    assert ORG_A in _params(db, 1)  # hazard zone search


# ── by-id ────────────────────────────────────────────────────

BY_ID = [
    ("get", f"/api/v1/gis/sites/{RECORD_ID}", None),
    ("put", f"/api/v1/gis/sites/{RECORD_ID}", {"name": "x"}),
    ("delete", f"/api/v1/gis/sites/{RECORD_ID}", None),
    ("get", f"/api/v1/gis/infrastructure/{RECORD_ID}", None),
    ("put", f"/api/v1/gis/infrastructure/{RECORD_ID}", {"name": "x"}),
    ("delete", f"/api/v1/gis/infrastructure/{RECORD_ID}", None),
    ("get", f"/api/v1/gis/hazard-zones/{RECORD_ID}", None),
    ("put", f"/api/v1/gis/hazard-zones/{RECORD_ID}", {"name": "x"}),
    ("delete", f"/api/v1/gis/hazard-zones/{RECORD_ID}", None),
]


def _call(client, method, path, body):
    if body is None:
        return getattr(client, method)(path, headers=AUTH)
    return getattr(client, method)(path, json=body, headers=AUTH)


@patch("src.middleware.auth.jwt")
@pytest.mark.parametrize(("method", "path", "body"), BY_ID)
def test_by_id_other_org_is_404_without_write(mock_jwt, method, path, body):
    mock_jwt.decode.return_value = _payload()
    client, db = _client(
        None
    )  # org-scoped lookup finds nothing for another org's record
    resp = _call(client, method, path, body)
    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "NOT_FOUND"
    assert ORG_A in _params(db, 0)
    db.delete.assert_not_awaited()
    db.flush.assert_not_awaited()
    db.commit.assert_not_awaited()


# ── delete requires management role ──────────────────────────

DELETE_ENDPOINTS = [
    (f"/api/v1/gis/sites/{RECORD_ID}", _site()),
    (f"/api/v1/gis/infrastructure/{RECORD_ID}", _infra()),
    (f"/api/v1/gis/hazard-zones/{RECORD_ID}", _zone()),
]


@patch("src.middleware.auth.jwt")
@pytest.mark.parametrize(("path", "record"), DELETE_ENDPOINTS)
def test_delete_requires_management_role(mock_jwt, path, record):
    """削除は admin / site_manager のみ。非管理ロールは対象が見つかっても 403。"""
    mock_jwt.decode.return_value = _payload(roles=["site_worker"])
    client, db = _client(record)
    resp = client.delete(path, headers=AUTH)
    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "FORBIDDEN"
    db.delete.assert_not_awaited()
    db.flush.assert_not_awaited()


# ── create ───────────────────────────────────────────────────

CREATES = [
    ("/api/v1/gis/sites", {"name": "Site", "location": POINT}),
    (
        "/api/v1/gis/infrastructure",
        {"name": "Bridge", "infra_type": "bridge", "location": POINT},
    ),
    (
        "/api/v1/gis/hazard-zones",
        {"name": "Flood", "hazard_type": "flood", "zone_area": POLYGON},
    ),
]


@patch("src.middleware.auth.jwt")
@pytest.mark.parametrize(("path", "body"), CREATES)
def test_create_in_other_org_is_forbidden(mock_jwt, path, body):
    mock_jwt.decode.return_value = _payload()
    client, db = _client()
    resp = client.post(path, json={**body, "organization_id": str(ORG_B)}, headers=AUTH)
    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "ORG_FORBIDDEN"
    db.add.assert_not_called()
    db.flush.assert_not_awaited()


@patch("src.middleware.auth.jwt")
@pytest.mark.parametrize(("path", "body"), CREATES)
def test_create_in_own_org_is_allowed(mock_jwt, path, body):
    mock_jwt.decode.return_value = _payload()
    client, db = _client()
    resp = client.post(path, json={**body, "organization_id": str(ORG_A)}, headers=AUTH)
    assert resp.status_code == 200
    assert db.add.call_args.args[0].organization_id == ORG_A


# ── fail-closed on missing / invalid org ─────────────────────

ALL_ENDPOINTS = (
    [("get", p, None) for p in ALL_READS]
    + BY_ID
    + [("post", p, {**b, "organization_id": str(ORG_A)}) for p, b in CREATES]
)


@patch("src.middleware.auth.jwt")
@pytest.mark.parametrize(
    ("org", "code"), [(None, "ORG_REQUIRED"), ("not-a-uuid", "ORG_INVALID")]
)
@pytest.mark.parametrize(("method", "path", "body"), ALL_ENDPOINTS)
def test_token_without_valid_org_is_rejected(mock_jwt, org, code, method, path, body):
    mock_jwt.decode.return_value = _payload(org=org)
    client, db = _client()
    resp = _call(client, method, path, body)
    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == code
    db.execute.assert_not_awaited()
    db.add.assert_not_called()


# ── admin crosses organizations ──────────────────────────────


@patch("src.middleware.auth.jwt")
@pytest.mark.parametrize("path", PAGED_LISTS)
def test_admin_list_without_filter_is_cross_org(mock_jwt, path):
    mock_jwt.decode.return_value = _payload(roles=["admin"])
    client, db = _client(0, [])
    resp = client.get(path, headers=AUTH)
    assert resp.status_code == 200
    assert ORG_A not in _params(db, 0)
    assert ORG_A not in _params(db, 1)


@patch("src.middleware.auth.jwt")
@pytest.mark.parametrize("path", PAGED_LISTS + SPATIAL_SEARCHES)
def test_admin_may_filter_by_other_org(mock_jwt, path):
    mock_jwt.decode.return_value = _payload(roles=["admin"])
    client, db = _client(0, []) if path in PAGED_LISTS else _client([])
    resp = client.get(_with(path, f"organization_id={ORG_B}"), headers=AUTH)
    assert resp.status_code == 200
    assert ORG_B in _params(db, 0)


@patch("src.middleware.auth.jwt")
@pytest.mark.parametrize(
    ("path", "record"),
    [
        (f"/api/v1/gis/sites/{RECORD_ID}", _site(org=ORG_B)),
        (f"/api/v1/gis/infrastructure/{RECORD_ID}", _infra(org=ORG_B)),
        (f"/api/v1/gis/hazard-zones/{RECORD_ID}", _zone(org=ORG_B)),
    ],
)
def test_admin_can_read_other_org_record(mock_jwt, path, record):
    mock_jwt.decode.return_value = _payload(roles=["admin"])
    client, db = _client(record)
    resp = client.get(path, headers=AUTH)
    assert resp.status_code == 200
    assert resp.json()["data"]["properties"]["organization_id"] == str(ORG_B)
    assert ORG_A not in _params(db, 0)


@patch("src.middleware.auth.jwt")
def test_admin_intersecting_other_org_site(mock_jwt):
    mock_jwt.decode.return_value = _payload(roles=["admin"])
    client, db = _client(_site(org=ORG_B, work_area=None))
    resp = client.get(
        f"/api/v1/gis/hazard-zones/intersecting/{RECORD_ID}", headers=AUTH
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["features"] == []
    assert _params(db, 0) == [RECORD_ID]  # unscoped site lookup (id only)


@patch("src.middleware.auth.jwt")
@pytest.mark.parametrize(("path", "body"), CREATES)
def test_admin_can_create_in_other_org(mock_jwt, path, body):
    mock_jwt.decode.return_value = _payload(roles=["admin"])
    client, db = _client()
    resp = client.post(path, json={**body, "organization_id": str(ORG_B)}, headers=AUTH)
    assert resp.status_code == 200
    assert db.add.call_args.args[0].organization_id == ORG_B


# ── unchanged stub ───────────────────────────────────────────


@patch("src.middleware.auth.jwt")
def test_routes_stub_is_unchanged(mock_jwt):
    """/routes serves fixed mock data (no org-owned stored data), so no org scoping applies."""
    mock_jwt.decode.return_value = _payload()
    client, db = _client()
    resp = client.get("/api/v1/gis/routes", headers=AUTH)
    assert resp.status_code == 200
    assert resp.json()["data"]["total"] == 5
    db.execute.assert_not_awaited()
