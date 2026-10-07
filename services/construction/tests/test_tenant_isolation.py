"""Organization (tenant) isolation tests (ADR-0004).

Regular users are restricted to the token ``org``; ``admin`` crosses organizations.
"""

import uuid
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from src.main import create_app
from src.middleware.auth import TokenData, get_current_user
from src.models import MethodStatement, Resource, Schedule, WBSItem
from src.models.base import get_db

BASE = "/api/v1/construction"
ORG_A = uuid.UUID("00000000-0000-0000-0000-00000000000a")
ORG_B = uuid.UUID("00000000-0000-0000-0000-00000000000b")
PROJECT = uuid.UUID("00000000-0000-0000-0000-0000000000f1")

USER_A = TokenData(
    sub=str(uuid.UUID("00000000-0000-0000-0000-0000000000c1")),
    type="user",
    org=str(ORG_A),
    roles=["user"],
)
USER_A_NO_ROLES = TokenData(
    sub=str(uuid.UUID("00000000-0000-0000-0000-0000000000c1")),
    type="user",
    org=str(ORG_A),
    roles=None,
)
ADMIN_A = TokenData(
    sub=str(uuid.UUID("00000000-0000-0000-0000-0000000000c2")),
    type="user",
    org=str(ORG_A),
    roles=["admin"],
)
NO_ORG = TokenData(sub="no-org", type="user", org=None, roles=["user"])
BAD_ORG = TokenData(sub="bad-org", type="user", org="not-a-uuid", roles=["user"])


class _Result:
    def __init__(self, items=None, total=0):
        self._items = items or []
        self._total = total

    def scalar(self):
        return self._total

    def scalars(self):
        return self

    def all(self):
        return self._items


def _now():
    return datetime.now(timezone.utc)


def _wbs(org, **kw):
    return WBSItem(
        id=kw.pop("id", uuid.uuid4()),
        organization_id=org,
        project_id=PROJECT,
        wbs_code="1",
        name="WBS",
        level=1,
        progress_percent=0,
        status="pending",
        created_at=_now(),
        updated_at=_now(),
        **kw,
    )


def _resource(org):
    return Resource(
        id=uuid.uuid4(),
        organization_id=org,
        project_id=PROJECT,
        resource_type="labor",
        name="作業員",
        status="planned",
        created_at=_now(),
    )


def _schedule(org):
    return Schedule(
        id=uuid.uuid4(),
        organization_id=org,
        project_id=PROJECT,
        name="工程",
        schedule_type="task",
        planned_start=date(2026, 10, 1),
        planned_end=date(2026, 10, 31),
        predecessor_ids=[],
        successor_ids=[],
        critical_path=True,
        status="planned",
        progress_percent=0,
        created_at=_now(),
        updated_at=_now(),
    )


def _method(org, status="review"):
    return MethodStatement(
        id=uuid.uuid4(),
        organization_id=org,
        project_id=PROJECT,
        title="施工計画書",
        document_type="method",
        attachments=[],
        status=status,
        created_at=_now(),
        updated_at=_now(),
    )


FACTORIES = {
    "wbs": _wbs,
    "resources": _resource,
    "schedules": _schedule,
    "methods": _method,
}


def _record(kind, org, suffix=""):
    """Record in a state where the operation is valid (submit requires draft)."""
    if kind == "methods" and suffix == "/submit":
        return _method(org, status="draft")
    return FACTORIES[kind](org)


@pytest.fixture
def mock_db():
    db = AsyncMock()
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.flush = AsyncMock()
    db.delete = AsyncMock()
    db.execute = AsyncMock(return_value=_Result())
    db.get = AsyncMock(return_value=None)

    async def refresh(obj):
        if getattr(obj, "id", None) is None:
            obj.id = uuid.uuid4()
        for attr in ("created_at", "updated_at"):
            if hasattr(obj, attr) and getattr(obj, attr) is None:
                setattr(obj, attr, _now())
        if getattr(obj, "status", None) is None:
            obj.status = "planned"
        if isinstance(obj, (WBSItem, Schedule)) and obj.progress_percent is None:
            obj.progress_percent = 0
        if isinstance(obj, MethodStatement) and obj.attachments is None:
            obj.attachments = []

    db.refresh = refresh
    return db


def _client(mock_db, user):
    app = create_app()

    async def _db():
        yield mock_db

    async def _user():
        return user

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[get_current_user] = _user
    return TestClient(app)


@pytest.fixture
def as_user(mock_db):
    return _client(mock_db, USER_A)


@pytest.fixture
def as_admin(mock_db):
    return _client(mock_db, ADMIN_A)


def _assert_error(resp, status_code, code):
    assert resp.status_code == status_code, resp.text
    assert resp.json()["detail"]["code"] == code


def _assert_no_write(mock_db):
    mock_db.add.assert_not_called()
    mock_db.flush.assert_not_called()
    mock_db.delete.assert_not_called()
    mock_db.commit.assert_not_called()


def _org_params(mock_db):
    """Organization UUIDs bound in every statement passed to db.execute."""
    orgs = []
    for call in mock_db.execute.call_args_list:
        params = call.args[0].compile().params
        orgs.append({v for k, v in params.items() if k.startswith("organization_id")})
    return orgs


def _create_body(kind, org, **extra):
    common = {"organization_id": str(org), "project_id": str(PROJECT)}
    bodies = {
        "wbs": {"wbs_code": "1", "name": "WBS", "level": 1},
        "resources": {"resource_type": "labor", "name": "作業員"},
        "schedules": {
            "name": "工程",
            "schedule_type": "task",
            "planned_start": "2026-10-01",
            "planned_end": "2026-10-31",
        },
        "methods": {"title": "施工計画書", "document_type": "method"},
    }
    return {**common, **bodies[kind], **extra}


KINDS = ["wbs", "resources", "schedules", "methods"]

# (method, path suffix, json body) for by-id operations; {id} is replaced per record
BY_ID_OPS = [
    ("wbs", "get", "", None),
    ("wbs", "put", "", {"name": "改ざん"}),
    ("wbs", "delete", "", None),
    ("wbs", "get", "/children", None),
    ("wbs", "patch", "/progress", {"progress_percent": "50"}),
    ("resources", "get", "", None),
    ("resources", "put", "", {"unit": "人"}),
    ("resources", "delete", "", None),
    ("resources", "patch", "/allocation", {"status": "allocated"}),
    ("schedules", "get", "", None),
    ("schedules", "put", "", {"name": "改ざん"}),
    ("schedules", "delete", "", None),
    ("methods", "get", "", None),
    ("methods", "put", "", {"title": "改ざん"}),
    ("methods", "delete", "", None),
    ("methods", "post", "/submit", None),
    ("methods", "post", "/approve", {"approved_by": str(uuid.uuid4())}),
    ("methods", "post", "/reject", None),
]

PROJECT_AGGREGATES = [
    f"/projects/{PROJECT}/resource-cost-summary",
    f"/projects/{PROJECT}/critical-path",
    f"/projects/{PROJECT}/gantt",
]


def _request(client, method, url, body):
    if body is None:
        return getattr(client, method)(url)
    return client.request(method.upper(), url, json=body)


# ============================================
# Fail-closed: token without / with invalid org
# ============================================
@pytest.mark.parametrize(
    "user,code", [(NO_ORG, "ORG_REQUIRED"), (BAD_ORG, "ORG_INVALID")]
)
@pytest.mark.parametrize("kind", KINDS)
def test_list_rejects_token_without_valid_org(mock_db, user, code, kind):
    resp = _client(mock_db, user).get(f"{BASE}/{kind}")
    _assert_error(resp, 403, code)
    mock_db.execute.assert_not_called()


@pytest.mark.parametrize(
    "user,code", [(NO_ORG, "ORG_REQUIRED"), (BAD_ORG, "ORG_INVALID")]
)
@pytest.mark.parametrize("kind", KINDS)
def test_create_rejects_token_without_valid_org(mock_db, user, code, kind):
    resp = _client(mock_db, user).post(f"{BASE}/{kind}", json=_create_body(kind, ORG_A))
    _assert_error(resp, 403, code)
    _assert_no_write(mock_db)


@pytest.mark.parametrize(
    "user,code", [(NO_ORG, "ORG_REQUIRED"), (BAD_ORG, "ORG_INVALID")]
)
@pytest.mark.parametrize("kind,method,suffix,body", BY_ID_OPS)
def test_by_id_rejects_token_without_valid_org(
    mock_db, user, code, kind, method, suffix, body
):
    mock_db.get = AsyncMock(return_value=FACTORIES[kind](ORG_A))
    resp = _request(
        _client(mock_db, user), method, f"{BASE}/{kind}/{uuid.uuid4()}{suffix}", body
    )
    _assert_error(resp, 403, code)
    _assert_no_write(mock_db)


@pytest.mark.parametrize(
    "user,code", [(NO_ORG, "ORG_REQUIRED"), (BAD_ORG, "ORG_INVALID")]
)
@pytest.mark.parametrize(
    "path", PROJECT_AGGREGATES + ["/wbs/tree?project_id=" + str(PROJECT)]
)
def test_aggregates_reject_token_without_valid_org(mock_db, user, code, path):
    resp = _client(mock_db, user).get(f"{BASE}{path}")
    _assert_error(resp, 403, code)
    mock_db.execute.assert_not_called()


# ============================================
# List: filtered by token org, other org -> 403
# ============================================
@pytest.mark.parametrize("kind", KINDS)
def test_list_other_org_forbidden(as_user, mock_db, kind):
    resp = as_user.get(f"{BASE}/{kind}?organization_id={ORG_B}")
    _assert_error(resp, 403, "ORG_FORBIDDEN")
    mock_db.execute.assert_not_called()


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("query", ["", f"?organization_id={ORG_A}"])
def test_list_is_filtered_by_token_org(as_user, mock_db, kind, query):
    resp = as_user.get(f"{BASE}/{kind}{query}")
    assert resp.status_code == 200, resp.text
    # count query and page query both filter by the token org
    assert _org_params(mock_db) == [{ORG_A}, {ORG_A}]


def test_list_works_for_token_without_roles_claim(mock_db):
    resp = _client(mock_db, USER_A_NO_ROLES).get(f"{BASE}/wbs")
    assert resp.status_code == 200, resp.text
    assert _org_params(mock_db) == [{ORG_A}, {ORG_A}]


# ============================================
# By-id: other org -> 404 and nothing is written
# ============================================
@pytest.mark.parametrize("kind,method,suffix,body", BY_ID_OPS)
def test_by_id_other_org_not_found_and_not_written(
    as_user, mock_db, kind, method, suffix, body
):
    record = _record(kind, ORG_B, suffix)
    mock_db.get = AsyncMock(return_value=record)
    before = {c.name: getattr(record, c.name) for c in record.__table__.columns}

    resp = _request(as_user, method, f"{BASE}/{kind}/{record.id}{suffix}", body)

    assert resp.status_code == 404, resp.text
    _assert_no_write(mock_db)
    mock_db.execute.assert_not_called()
    assert {c.name: getattr(record, c.name) for c in record.__table__.columns} == before


@pytest.mark.parametrize("kind,method,suffix,body", BY_ID_OPS)
def test_by_id_same_org_allowed(as_user, mock_db, kind, method, suffix, body):
    record = _record(kind, ORG_A, suffix)
    mock_db.get = AsyncMock(return_value=record)
    resp = _request(as_user, method, f"{BASE}/{kind}/{record.id}{suffix}", body)
    assert resp.status_code in (200, 204), resp.text


def test_wbs_children_query_scoped_to_parent_org(as_user, mock_db):
    parent = _wbs(ORG_A)
    mock_db.get = AsyncMock(return_value=parent)
    resp = as_user.get(f"{BASE}/wbs/{parent.id}/children")
    assert resp.status_code == 200, resp.text
    assert _org_params(mock_db) == [{ORG_A}]


def test_wbs_tree_scoped_to_token_org_including_children(as_user, mock_db):
    root = _wbs(ORG_A)
    mock_db.execute = AsyncMock(side_effect=[_Result(items=[root]), _Result(items=[])])
    resp = as_user.get(f"{BASE}/wbs/tree?project_id={PROJECT}")
    assert resp.status_code == 200, resp.text
    assert _org_params(mock_db) == [{ORG_A}, {ORG_A}]


# ============================================
# Create: body org must equal token org
# ============================================
@pytest.mark.parametrize("kind", KINDS)
def test_create_other_org_forbidden(as_user, mock_db, kind):
    resp = as_user.post(f"{BASE}/{kind}", json=_create_body(kind, ORG_B))
    _assert_error(resp, 403, "ORG_FORBIDDEN")
    _assert_no_write(mock_db)


@pytest.mark.parametrize("kind", KINDS)
def test_create_own_org_allowed(as_user, mock_db, kind):
    resp = as_user.post(f"{BASE}/{kind}", json=_create_body(kind, ORG_A))
    assert resp.status_code == 201, resp.text
    assert mock_db.add.call_args[0][0].organization_id == ORG_A


@pytest.mark.parametrize(
    "kind,field",
    [
        ("wbs", "parent_id"),
        ("resources", "wbs_item_id"),
        ("schedules", "wbs_item_id"),
        ("methods", "wbs_item_id"),
    ],
)
def test_create_referencing_other_org_wbs_not_found(as_user, mock_db, kind, field):
    other = _wbs(ORG_B)
    mock_db.get = AsyncMock(return_value=other)
    body = _create_body(kind, ORG_A, **{field: str(other.id)})
    resp = as_user.post(f"{BASE}/{kind}", json=body)
    _assert_error(resp, 404, "WBS_NOT_FOUND")
    _assert_no_write(mock_db)


@pytest.mark.parametrize(
    "kind,field",
    [
        ("wbs", "parent_id"),
        ("resources", "wbs_item_id"),
        ("schedules", "wbs_item_id"),
        ("methods", "wbs_item_id"),
    ],
)
def test_create_referencing_same_org_wbs_allowed(as_user, mock_db, kind, field):
    parent = _wbs(ORG_A)
    mock_db.get = AsyncMock(return_value=parent)
    resp = as_user.post(
        f"{BASE}/{kind}", json=_create_body(kind, ORG_A, **{field: str(parent.id)})
    )
    assert resp.status_code == 201, resp.text


# ============================================
# Project aggregates: filtered by token org
# ============================================
@pytest.mark.parametrize("path", PROJECT_AGGREGATES)
def test_project_aggregates_filtered_by_token_org(as_user, mock_db, path):
    resp = as_user.get(f"{BASE}{path}")
    assert resp.status_code == 200, resp.text
    assert _org_params(mock_db) == [{ORG_A}]


@pytest.mark.parametrize("path", PROJECT_AGGREGATES)
def test_project_aggregates_admin_not_filtered(as_admin, mock_db, path):
    resp = as_admin.get(f"{BASE}{path}")
    assert resp.status_code == 200, resp.text
    assert _org_params(mock_db) == [set()]


# ============================================
# Admin crosses organizations
# ============================================
@pytest.mark.parametrize("kind", KINDS)
def test_admin_list_without_org_is_unfiltered(as_admin, mock_db, kind):
    resp = as_admin.get(f"{BASE}/{kind}")
    assert resp.status_code == 200, resp.text
    assert _org_params(mock_db) == [set(), set()]


@pytest.mark.parametrize("kind", KINDS)
def test_admin_list_other_org(as_admin, mock_db, kind):
    resp = as_admin.get(f"{BASE}/{kind}?organization_id={ORG_B}")
    assert resp.status_code == 200, resp.text
    assert _org_params(mock_db) == [{ORG_B}, {ORG_B}]


@pytest.mark.parametrize("kind,method,suffix,body", BY_ID_OPS)
def test_admin_by_id_other_org_allowed(as_admin, mock_db, kind, method, suffix, body):
    record = _record(kind, ORG_B, suffix)
    mock_db.get = AsyncMock(return_value=record)
    resp = _request(as_admin, method, f"{BASE}/{kind}/{record.id}{suffix}", body)
    assert resp.status_code in (200, 204), resp.text


@pytest.mark.parametrize("kind", KINDS)
def test_admin_create_in_other_org_uses_body_org(as_admin, mock_db, kind):
    resp = as_admin.post(f"{BASE}/{kind}", json=_create_body(kind, ORG_B))
    assert resp.status_code == 201, resp.text
    assert mock_db.add.call_args[0][0].organization_id == ORG_B


@pytest.mark.parametrize(
    "kind,field",
    [
        ("wbs", "parent_id"),
        ("resources", "wbs_item_id"),
        ("schedules", "wbs_item_id"),
        ("methods", "wbs_item_id"),
    ],
)
def test_admin_create_with_wbs_of_different_org_mismatch(
    as_admin, mock_db, kind, field
):
    parent = _wbs(ORG_A)
    mock_db.get = AsyncMock(return_value=parent)
    resp = as_admin.post(
        f"{BASE}/{kind}", json=_create_body(kind, ORG_B, **{field: str(parent.id)})
    )
    _assert_error(resp, 400, "WBS_ORG_MISMATCH")
    _assert_no_write(mock_db)


@pytest.mark.parametrize("kind", ["resources", "schedules", "methods"])
def test_admin_create_with_missing_wbs_not_found(as_admin, mock_db, kind):
    resp = as_admin.post(
        f"{BASE}/{kind}", json=_create_body(kind, ORG_B, wbs_item_id=str(uuid.uuid4()))
    )
    _assert_error(resp, 404, "WBS_NOT_FOUND")
    _assert_no_write(mock_db)
