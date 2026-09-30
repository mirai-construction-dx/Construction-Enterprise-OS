"""Organization (tenant) isolation tests for the maintenance service (Issue #114, ADR-0004).

Regular users are pinned to the token ``org`` claim; the ``admin`` role crosses organizations.
Recovery plans are children of disaster reports: the parent lookup is org-scoped and the child
query is also filtered by the plan's own organization (defense in depth).
"""

import uuid
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from src.main import create_app
from src.middleware.auth import TokenData, get_current_user
from src.middleware.tenant import create_org, scope_org
from src.models.base import get_db

ORG_A = uuid.uuid4()
ORG_B = uuid.uuid4()
DISASTER_ID = uuid.uuid4()
PLAN_ID = uuid.uuid4()
RECORD_ID = uuid.uuid4()
INSPECTION_ID = uuid.uuid4()
USER_ID = uuid.uuid4()
BASE = "/api/v1/maintenance"


class _Result:
    def __init__(self, value=None):
        self._value = value

    def scalar_one_or_none(self):
        return self._value

    def scalars(self):
        mock = MagicMock()
        mock.all.return_value = self._value or []
        return mock


def _user(org: str | None = str(ORG_A), roles: list[str] | None = None) -> TokenData:
    return TokenData(
        sub=str(USER_ID),
        type="user",
        org=org,
        roles=roles if roles is not None else ["site_manager"],
    )


def _admin() -> TokenData:
    return _user(roles=["admin"])


def _client(user: TokenData, *values):
    app = create_app()
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=[_Result(v) for v in values])
    db.add = MagicMock()
    db.delete = AsyncMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()

    async def _db():
        yield db

    async def _current_user():
        return user

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[get_current_user] = _current_user
    return TestClient(app), db


def _params(db, index: int) -> dict:
    """Bound parameters of the ``index``-th executed statement."""
    stmt = db.execute.await_args_list[index].args[0]
    return stmt.compile().params


def _org_bound(db, index: int) -> list:
    """Values bound against an ``organization_id`` column in the ``index``-th statement."""
    return [v for k, v in _params(db, index).items() if k.startswith("organization_id")]


def _assert_no_write(db) -> None:
    db.add.assert_not_called()
    db.delete.assert_not_awaited()
    db.flush.assert_not_awaited()
    db.commit.assert_not_awaited()


def _assert_error(resp, status_code: int, code: str) -> None:
    assert resp.status_code == status_code, resp.text
    assert resp.json()["detail"]["code"] == code


def _now():
    return datetime.now(timezone.utc)


def _disaster(org: uuid.UUID = ORG_A):
    d = MagicMock()
    d.id = DISASTER_ID
    d.organization_id = org
    d.project_id = None
    d.title = "Flood"
    d.disaster_type = "flood"
    d.severity = "moderate"
    d.status = "reported"
    d.occurred_at = _now()
    d.location = None
    d.description = "desc"
    d.damage_assessment = None
    d.estimated_cost = None
    d.casualties = 0
    d.evacuation_required = False
    d.reported_by = USER_ID
    d.created_at = _now()
    d.updated_at = _now()
    return d


def _plan(org: uuid.UUID = ORG_A):
    p = MagicMock()
    p.id = PLAN_ID
    p.organization_id = org
    p.disaster_report_id = DISASTER_ID
    p.title = "Plan"
    p.description = None
    p.priority = "high"
    p.status = "planned"
    p.estimated_duration_days = None
    p.estimated_cost = None
    p.actual_cost = None
    p.start_date = None
    p.completed_date = None
    p.contractor = None
    p.resources_needed = None
    p.progress_percent = None
    p.created_by = USER_ID
    p.created_at = _now()
    p.updated_at = _now()
    return p


def _record(org: uuid.UUID = ORG_A):
    r = MagicMock()
    r.id = RECORD_ID
    r.organization_id = org
    r.project_id = None
    r.asset_name = "Bridge"
    r.asset_type = "bridge"
    r.maintenance_type = "preventive"
    r.status = "scheduled"
    r.description = "desc"
    r.work_performed = None
    r.cost = None
    r.contractor = None
    r.scheduled_date = None
    r.completed_date = None
    r.next_maintenance_date = None
    r.location = None
    r.performed_by = None
    r.notes = None
    r.created_at = _now()
    r.updated_at = _now()
    return r


def _inspection(org: uuid.UUID = ORG_A):
    i = MagicMock()
    i.id = INSPECTION_ID
    i.organization_id = org
    i.asset_name = "Tunnel"
    i.asset_type = "tunnel"
    i.inspection_type = "visual"
    i.frequency = "monthly"
    i.last_inspection_date = None
    i.next_inspection_date = date.today()
    i.status = "scheduled"
    i.inspector = None
    i.checklist = None
    i.notes = None
    i.created_at = _now()
    i.updated_at = _now()
    return i


def _disaster_body(org: uuid.UUID) -> dict:
    return {
        "organization_id": str(org),
        "title": "Quake",
        "disaster_type": "earthquake",
        "severity": "severe",
        "occurred_at": _now().isoformat(),
        "description": "desc",
        "reported_by": str(USER_ID),
    }


def _plan_body(org: uuid.UUID) -> dict:
    return {"organization_id": str(org), "title": "Plan", "created_by": str(USER_ID)}


def _record_body(org: uuid.UUID) -> dict:
    return {
        "organization_id": str(org),
        "asset_name": "Bridge",
        "asset_type": "bridge",
        "maintenance_type": "preventive",
        "description": "desc",
    }


def _inspection_body(org: uuid.UUID) -> dict:
    return {
        "organization_id": str(org),
        "asset_name": "Tunnel",
        "asset_type": "tunnel",
        "inspection_type": "visual",
        "frequency": "monthly",
        "next_inspection_date": date.today().isoformat(),
    }


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
    assert scope_org(_admin()) is None
    assert scope_org(_admin(), ORG_B) == ORG_B
    assert create_org(_admin(), ORG_B) == ORG_B


def test_create_org_rejects_other_org_for_regular_user():
    assert create_org(_user(), ORG_A) == ORG_A
    with pytest.raises(HTTPException) as exc:
        create_org(_user(), ORG_B)
    assert exc.value.status_code == 403
    assert exc.value.detail["code"] == "ORG_FORBIDDEN"


# ── list / aggregate endpoints ───────────────────────────────

LIST_PATHS = [
    "/disasters",
    "/records",
    "/records/overdue",
    "/inspections",
    "/inspections/upcoming",
    "/inspections/overdue",
]


@pytest.mark.parametrize("path", LIST_PATHS)
def test_list_other_org_is_forbidden(path):
    client, db = _client(_user())
    resp = client.get(f"{BASE}{path}", params={"organization_id": str(ORG_B)})
    _assert_error(resp, 403, "ORG_FORBIDDEN")
    db.execute.assert_not_awaited()


@pytest.mark.parametrize("path", LIST_PATHS)
def test_list_is_filtered_by_token_org(path):
    client, db = _client(_user(), [])
    resp = client.get(f"{BASE}{path}")
    assert resp.status_code == 200, resp.text
    assert _org_bound(db, 0) == [ORG_A]


@pytest.mark.parametrize("path", LIST_PATHS)
@pytest.mark.parametrize(
    ("org", "code"), [(None, "ORG_REQUIRED"), ("not-a-uuid", "ORG_INVALID")]
)
def test_list_fails_closed_without_valid_org(path, org, code):
    client, db = _client(_user(org=org))
    resp = client.get(f"{BASE}{path}")
    _assert_error(resp, 403, code)
    db.execute.assert_not_awaited()


@pytest.mark.parametrize("path", LIST_PATHS)
def test_admin_list_is_unfiltered_or_requested_org(path):
    client, db = _client(_admin(), [], [])
    assert client.get(f"{BASE}{path}").status_code == 200
    assert _org_bound(db, 0) == []
    assert (
        client.get(f"{BASE}{path}", params={"organization_id": str(ORG_B)}).status_code
        == 200
    )
    assert _org_bound(db, 1) == [ORG_B]


# ── by-id reads: other org -> 404 ────────────────────────────

GET_PATHS = [
    f"/disasters/{DISASTER_ID}",
    f"/recovery-plans/{PLAN_ID}",
    f"/records/{RECORD_ID}",
    f"/inspections/{INSPECTION_ID}",
]


@pytest.mark.parametrize("path", GET_PATHS)
def test_get_other_org_is_not_found(path):
    # The org-scoped lookup finds nothing for another organization's id.
    client, db = _client(_user(), None)
    resp = client.get(f"{BASE}{path}")
    _assert_error(resp, 404, "NOT_FOUND")
    assert _org_bound(db, 0) == [ORG_A]
    assert db.execute.await_count == 1
    _assert_no_write(db)


@pytest.mark.parametrize("path", GET_PATHS)
def test_get_without_org_fails_closed(path):
    client, db = _client(_user(org=None))
    _assert_error(client.get(f"{BASE}{path}"), 403, "ORG_REQUIRED")
    db.execute.assert_not_awaited()


def test_get_disaster_child_plans_are_org_scoped():
    client, db = _client(_user(), _disaster(), [_plan()])
    resp = client.get(f"{BASE}/disasters/{DISASTER_ID}")
    assert resp.status_code == 200, resp.text
    assert len(resp.json()["data"]["recovery_plans"]) == 1
    assert _org_bound(db, 0) == [ORG_A]
    # Child query: filtered by parent id AND the plan's own organization.
    params = _params(db, 1)
    assert DISASTER_ID in params.values()
    assert _org_bound(db, 1) == [ORG_A]


def test_admin_get_disaster_child_plans_unfiltered():
    client, db = _client(_admin(), _disaster(ORG_B), [_plan(ORG_B)])
    resp = client.get(f"{BASE}/disasters/{DISASTER_ID}")
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["report"]["organization_id"] == str(ORG_B)
    assert _org_bound(db, 0) == []
    assert _org_bound(db, 1) == []


# ── by-id writes: other org -> 404 and nothing written ───────

UPDATE_CASES = [
    (f"/disasters/{DISASTER_ID}", {"status": "assessing"}),
    (f"/recovery-plans/{PLAN_ID}", {"status": "completed"}),
    (f"/records/{RECORD_ID}", {"status": "completed"}),
    (f"/inspections/{INSPECTION_ID}", {"notes": "done"}),
]


@pytest.mark.parametrize(("path", "body"), UPDATE_CASES)
def test_update_other_org_is_not_found_and_not_written(path, body):
    client, db = _client(_user(), None)
    resp = client.put(f"{BASE}{path}", json=body)
    _assert_error(resp, 404, "NOT_FOUND")
    assert _org_bound(db, 0) == [ORG_A]
    _assert_no_write(db)


@pytest.mark.parametrize(("path", "body"), UPDATE_CASES)
def test_update_without_org_fails_closed(path, body):
    client, db = _client(_user(org="not-a-uuid"))
    _assert_error(client.put(f"{BASE}{path}", json=body), 403, "ORG_INVALID")
    db.execute.assert_not_awaited()
    _assert_no_write(db)


def test_update_own_org_record_succeeds():
    record = _record()
    client, db = _client(_user(), record)
    resp = client.put(f"{BASE}/records/{RECORD_ID}", json={"status": "in_progress"})
    assert resp.status_code == 200, resp.text
    assert record.status == "in_progress"
    assert _org_bound(db, 0) == [ORG_A]


def test_admin_updates_other_org_inspection():
    inspection = _inspection(ORG_B)
    client, db = _client(_admin(), inspection)
    resp = client.put(f"{BASE}/inspections/{INSPECTION_ID}", json={"notes": "ok"})
    assert resp.status_code == 200, resp.text
    assert inspection.status == "completed"
    assert _org_bound(db, 0) == []


# ── create ───────────────────────────────────────────────────

CREATE_CASES = [
    ("/disasters", _disaster_body),
    ("/records", _record_body),
    ("/inspections", _inspection_body),
]


@pytest.mark.parametrize(("path", "make_body"), CREATE_CASES)
def test_create_other_org_is_forbidden(path, make_body):
    client, db = _client(_user())
    resp = client.post(f"{BASE}{path}", json=make_body(ORG_B))
    _assert_error(resp, 403, "ORG_FORBIDDEN")
    _assert_no_write(db)


@pytest.mark.parametrize(("path", "make_body"), CREATE_CASES)
def test_create_without_org_fails_closed(path, make_body):
    client, db = _client(_user(org=None))
    resp = client.post(f"{BASE}{path}", json=make_body(ORG_A))
    _assert_error(resp, 403, "ORG_REQUIRED")
    _assert_no_write(db)


@pytest.mark.parametrize(("path", "make_body"), CREATE_CASES)
def test_create_own_org_succeeds(path, make_body):
    client, db = _client(_user())
    resp = client.post(f"{BASE}{path}", json=make_body(ORG_A))
    assert resp.status_code == 201, resp.text
    assert resp.json()["data"]["organization_id"] == str(ORG_A)
    db.add.assert_called_once()


@pytest.mark.parametrize(("path", "make_body"), CREATE_CASES)
def test_admin_creates_in_body_org(path, make_body):
    client, db = _client(_admin())
    resp = client.post(f"{BASE}{path}", json=make_body(ORG_B))
    assert resp.status_code == 201, resp.text
    assert resp.json()["data"]["organization_id"] == str(ORG_B)


# ── recovery plan create (child of a disaster report) ────────

PLAN_CREATE = f"{BASE}/disasters/{DISASTER_ID}/recovery-plans"


def test_create_plan_body_other_org_is_forbidden():
    client, db = _client(_user())
    _assert_error(
        client.post(PLAN_CREATE, json=_plan_body(ORG_B)), 403, "ORG_FORBIDDEN"
    )
    db.execute.assert_not_awaited()
    _assert_no_write(db)


def test_create_plan_under_other_org_disaster_is_not_found():
    # Body org is the caller's own, but the parent disaster belongs to another org.
    client, db = _client(_user(), None)
    resp = client.post(PLAN_CREATE, json=_plan_body(ORG_A))
    _assert_error(resp, 404, "NOT_FOUND")
    assert _org_bound(db, 0) == [ORG_A]
    _assert_no_write(db)


def test_create_plan_without_org_fails_closed():
    client, db = _client(_user(org=None))
    _assert_error(client.post(PLAN_CREATE, json=_plan_body(ORG_A)), 403, "ORG_REQUIRED")
    db.execute.assert_not_awaited()
    _assert_no_write(db)


def test_create_plan_own_org_succeeds():
    client, db = _client(_user(), _disaster())
    resp = client.post(PLAN_CREATE, json=_plan_body(ORG_A))
    assert resp.status_code == 201, resp.text
    assert resp.json()["data"]["organization_id"] == str(ORG_A)
    db.add.assert_called_once()


def test_admin_create_plan_org_mismatch_is_rejected():
    client, db = _client(_admin(), _disaster(ORG_A))
    resp = client.post(PLAN_CREATE, json=_plan_body(ORG_B))
    _assert_error(resp, 400, "RECOVERY_PLAN_ORG_MISMATCH")
    assert _org_bound(db, 0) == []
    _assert_no_write(db)


def test_admin_create_plan_in_disaster_org_succeeds():
    client, db = _client(_admin(), _disaster(ORG_B))
    resp = client.post(PLAN_CREATE, json=_plan_body(ORG_B))
    assert resp.status_code == 201, resp.text
    assert resp.json()["data"]["organization_id"] == str(ORG_B)
