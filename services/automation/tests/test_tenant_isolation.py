"""Organization (tenant) isolation tests for the automation service (Issue #114, ADR-0004)."""

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import src.api.rules as rules_api
import src.api.tasks as tasks_api
import src.api.triggers as triggers_api
import src.services.automation_service as svc
from src.main import create_app
from src.middleware.auth import TokenData, get_current_user
from src.middleware.tenant import create_org, scope_org
from src.models.base import get_db

ORG_A = uuid.uuid4()
ORG_B = uuid.uuid4()
BASE = "/api/v1/automation"
NOW = datetime.now(timezone.utc)


@pytest.fixture(autouse=True)
def _real_service_functions(monkeypatch):
    """test_automation.py replaces router-level service functions without restoring them.

    Re-point every router name to the real service function so these tests exercise the
    actual org-scoped queries regardless of test order.
    """
    for module in (rules_api, tasks_api, triggers_api):
        for name in dir(module):
            real = getattr(svc, name, None)
            if callable(real) and name in module.__dict__:
                monkeypatch.setattr(module, name, real)


def _user(org: str | None = str(ORG_A), roles: list[str] | None = None) -> TokenData:
    return TokenData(
        sub=str(uuid.uuid4()),
        type="user",
        org=org,
        roles=roles if roles is not None else ["member"],
    )


ADMIN = _user(roles=["admin"])


class _Result:
    """Minimal stand-in for a SQLAlchemy result."""

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


def _compiled(db, index: int):
    stmt = db.execute.await_args_list[index].args[0]
    return str(stmt), stmt.compile().params


def _assert_scoped_to(db, index: int, org: uuid.UUID) -> None:
    sql, params = _compiled(db, index)
    assert ":organization_id" in sql
    assert org in params.values()


def _assert_unscoped(db, index: int) -> None:
    sql, _ = _compiled(db, index)
    assert "organization_id =" not in sql


def _assert_no_write(db) -> None:
    db.add.assert_not_called()
    db.delete.assert_not_awaited()
    db.flush.assert_not_awaited()
    db.commit.assert_not_awaited()


def _rule(org=ORG_A):
    return SimpleNamespace(
        id=uuid.uuid4(),
        organization_id=org,
        name="rule",
        description=None,
        trigger_type="event",
        condition={},
        action={"type": "notify", "config": {}},
        is_active=True,
        created_by=None,
        last_triggered=None,
        created_at=NOW,
        updated_at=NOW,
    )


def _task(org=ORG_A):
    return SimpleNamespace(
        id=uuid.uuid4(),
        organization_id=org,
        name="task",
        description=None,
        cron_expression="0 * * * *",
        action_type="execute",
        action_config={},
        is_active=True,
        created_by=None,
        last_run=None,
        next_run=None,
        last_status=None,
        created_at=NOW,
        updated_at=NOW,
    )


def _trigger(org=ORG_A):
    return SimpleNamespace(
        id=uuid.uuid4(),
        organization_id=org,
        name="trigger",
        description=None,
        event_type="iot.alert",
        filter_conditions={},
        action_config={},
        is_active=True,
        created_by=None,
        last_triggered=None,
        created_at=NOW,
        updated_at=NOW,
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


def test_admin_is_cross_org():
    assert scope_org(ADMIN) is None
    assert scope_org(ADMIN, ORG_B) == ORG_B
    assert create_org(ADMIN, ORG_B) == ORG_B


def test_create_org_rejects_other_org_for_regular_user():
    assert create_org(_user(), ORG_A) == ORG_A
    with pytest.raises(HTTPException) as exc:
        create_org(_user(), ORG_B)
    assert exc.value.status_code == 403
    assert exc.value.detail["code"] == "ORG_FORBIDDEN"


# ── list ─────────────────────────────────────────────────────

LIST_PATHS = ["rules", "tasks", "triggers"]


@pytest.mark.parametrize("resource", LIST_PATHS)
def test_list_other_org_is_forbidden(resource):
    client, db = _client(_user())
    resp = client.get(f"{BASE}/{resource}", params={"organization_id": str(ORG_B)})
    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "ORG_FORBIDDEN"
    db.execute.assert_not_awaited()


@pytest.mark.parametrize("resource", LIST_PATHS)
def test_list_is_scoped_to_token_org(resource):
    client, db = _client(_user(), 0, [])
    resp = client.get(f"{BASE}/{resource}")
    assert resp.status_code == 200
    _assert_scoped_to(db, 0, ORG_A)  # count query
    _assert_scoped_to(db, 1, ORG_A)  # page query


@pytest.mark.parametrize(
    ("org", "code"), [(None, "ORG_REQUIRED"), ("not-a-uuid", "ORG_INVALID")]
)
@pytest.mark.parametrize("resource", LIST_PATHS)
def test_list_fails_closed_without_valid_org(resource, org, code):
    client, db = _client(_user(org=org))
    resp = client.get(f"{BASE}/{resource}")
    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == code
    db.execute.assert_not_awaited()


@pytest.mark.parametrize("resource", LIST_PATHS)
def test_admin_list_without_org_is_unfiltered(resource):
    client, db = _client(ADMIN, 0, [])
    resp = client.get(f"{BASE}/{resource}")
    assert resp.status_code == 200
    _assert_unscoped(db, 0)
    _assert_unscoped(db, 1)


@pytest.mark.parametrize("resource", LIST_PATHS)
def test_admin_list_can_select_other_org(resource):
    client, db = _client(ADMIN, 0, [])
    resp = client.get(f"{BASE}/{resource}", params={"organization_id": str(ORG_B)})
    assert resp.status_code == 200
    _assert_scoped_to(db, 0, ORG_B)
    _assert_scoped_to(db, 1, ORG_B)


# ── by-id: other org is 404 and nothing is written ──────────

# (method, path template, json body, expected error code)
BY_ID_CASES = [
    ("get", "rules/{id}", None, "RULE_NOT_FOUND"),
    ("put", "rules/{id}", {"name": "x"}, "RULE_NOT_FOUND"),
    ("delete", "rules/{id}", None, "RULE_NOT_FOUND"),
    ("post", "rules/{id}/enable", None, "RULE_NOT_FOUND"),
    ("post", "rules/{id}/disable", None, "RULE_NOT_FOUND"),
    ("post", "rules/{id}/test", {"input_data": {}}, "RULE_NOT_FOUND"),
    ("get", "tasks/{id}", None, "TASK_NOT_FOUND"),
    ("put", "tasks/{id}", {"name": "x"}, "TASK_NOT_FOUND"),
    ("delete", "tasks/{id}", None, "TASK_NOT_FOUND"),
    ("post", "tasks/{id}/trigger", None, "TASK_NOT_FOUND"),
    ("get", "tasks/{id}/history", None, "TASK_NOT_FOUND"),
    ("get", "triggers/{id}", None, "TRIGGER_NOT_FOUND"),
    ("put", "triggers/{id}", {"name": "x"}, "TRIGGER_NOT_FOUND"),
    ("delete", "triggers/{id}", None, "TRIGGER_NOT_FOUND"),
    ("post", "triggers/{id}/enable", None, "TRIGGER_NOT_FOUND"),
    ("post", "triggers/{id}/disable", None, "TRIGGER_NOT_FOUND"),
]


def _call(client, method, path, body):
    url = f"{BASE}/{path.format(id=uuid.uuid4())}"
    if body is None:
        return client.request(method.upper(), url)
    return client.request(method.upper(), url, json=body)


@pytest.mark.parametrize(("method", "path", "body", "code"), BY_ID_CASES)
def test_by_id_other_org_is_not_found_and_not_written(method, path, body, code):
    # The org-scoped lookup finds nothing for a record owned by ORG_B.
    # 削除（DELETE）は admin/site_manager ロールを要求するため、ロール検査を
    # 通過しつつ組織スコープ（非横断）を維持する site_manager を使う。
    roles = ["site_manager"] if method == "delete" else None
    client, db = _client(_user(roles=roles), None)
    resp = _call(client, method, path, body)
    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == code
    assert db.execute.await_count == 1
    _assert_scoped_to(db, 0, ORG_A)
    _assert_no_write(db)


@pytest.mark.parametrize(
    ("org", "code"), [(None, "ORG_REQUIRED"), ("not-a-uuid", "ORG_INVALID")]
)
@pytest.mark.parametrize(("method", "path", "body", "_nf"), BY_ID_CASES)
def test_by_id_fails_closed_without_valid_org(method, path, body, _nf, org, code):
    client, db = _client(_user(org=org))
    resp = _call(client, method, path, body)
    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == code
    db.execute.assert_not_awaited()
    _assert_no_write(db)


# ── delete requires management role ─────────────────────────

DELETE_PATHS = ["rules", "tasks", "triggers"]


@pytest.mark.parametrize("resource", DELETE_PATHS)
def test_delete_requires_management_role(resource):
    """削除（DELETE）は admin/site_manager ロールを要求する（fail-closed）。"""
    client, db = _client(_user())  # roles=["member"]（非管理ロール）
    resp = client.delete(f"{BASE}/{resource}/{uuid.uuid4()}")
    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "FORBIDDEN"
    db.execute.assert_not_awaited()
    _assert_no_write(db)


def test_admin_get_rule_of_other_org_is_unscoped():
    rule = _rule(org=ORG_B)
    client, db = _client(ADMIN, rule)
    resp = client.get(f"{BASE}/rules/{rule.id}")
    assert resp.status_code == 200
    assert resp.json()["data"]["organization_id"] == str(ORG_B)
    _assert_unscoped(db, 0)


def test_admin_disable_trigger_of_other_org():
    trigger = _trigger(org=ORG_B)
    client, db = _client(ADMIN, trigger)
    resp = client.post(f"{BASE}/triggers/{trigger.id}/disable")
    assert resp.status_code == 200
    assert trigger.is_active is False
    _assert_unscoped(db, 0)
    db.flush.assert_awaited_once()


def test_same_org_rule_update_is_applied():
    rule = _rule()
    client, db = _client(_user(), rule)
    resp = client.put(f"{BASE}/rules/{rule.id}", json={"name": "renamed"})
    assert resp.status_code == 200
    assert rule.name == "renamed"
    _assert_scoped_to(db, 0, ORG_A)


# ── execution paths (rule test / task trigger) ──────────────


def test_rule_test_execution_same_org_only():
    rule = _rule()
    client, db = _client(_user(), rule)
    resp = client.post(f"{BASE}/rules/{rule.id}/test", json={"input_data": {}})
    assert resp.status_code == 200
    assert resp.json()["data"]["matched"] is True
    _assert_scoped_to(db, 0, ORG_A)


def test_trigger_task_now_records_run_in_task_org():
    task = _task()
    client, db = _client(_user(), task)

    async def _flush():
        # Emulate the DB populating primary key / server defaults on flush.
        added = db.add.call_args.args[0]
        added.id = uuid.uuid4()
        added.created_at = NOW

    db.flush.side_effect = _flush
    resp = client.post(f"{BASE}/tasks/{task.id}/trigger")
    assert resp.status_code == 200
    _assert_scoped_to(db, 0, ORG_A)
    run = db.add.call_args.args[0]
    assert run.organization_id == ORG_A
    assert run.task_id == task.id


def test_task_history_child_query_is_scoped():
    task = _task()
    client, db = _client(_user(), task, [])
    resp = client.get(f"{BASE}/tasks/{task.id}/history")
    assert resp.status_code == 200
    _assert_scoped_to(db, 0, ORG_A)  # parent task lookup
    _assert_scoped_to(db, 1, ORG_A)  # run history


# ── create ───────────────────────────────────────────────────

CREATE_CASES = [
    (
        "rules",
        {
            "name": "r",
            "trigger_type": "event",
            "action": {"type": "notify", "config": {}},
        },
        "create_rule",
        rules_api,
        _rule,
    ),
    (
        "tasks",
        {"name": "t", "cron_expression": "0 * * * *", "action_type": "execute"},
        "create_task",
        tasks_api,
        _task,
    ),
    (
        "triggers",
        {"name": "g", "event_type": "iot.alert"},
        "create_trigger",
        triggers_api,
        _trigger,
    ),
]


@pytest.mark.parametrize(("resource", "body", "_fn", "_mod", "_obj"), CREATE_CASES)
def test_create_in_other_org_is_forbidden(resource, body, _fn, _mod, _obj):
    client, db = _client(_user())
    resp = client.post(
        f"{BASE}/{resource}", json={**body, "organization_id": str(ORG_B)}
    )
    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "ORG_FORBIDDEN"
    _assert_no_write(db)


@pytest.mark.parametrize(
    ("org", "code"), [(None, "ORG_REQUIRED"), ("not-a-uuid", "ORG_INVALID")]
)
@pytest.mark.parametrize(("resource", "body", "_fn", "_mod", "_obj"), CREATE_CASES)
def test_create_fails_closed_without_valid_org(
    resource, body, _fn, _mod, _obj, org, code
):
    client, db = _client(_user(org=org))
    resp = client.post(
        f"{BASE}/{resource}", json={**body, "organization_id": str(ORG_A)}
    )
    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == code
    _assert_no_write(db)


@pytest.mark.parametrize(("resource", "body", "fn", "mod", "obj"), CREATE_CASES)
def test_create_in_own_org_stores_token_org(monkeypatch, resource, body, fn, mod, obj):
    create = AsyncMock(return_value=obj(org=ORG_A))
    monkeypatch.setattr(mod, fn, create)
    client, _ = _client(_user())
    resp = client.post(
        f"{BASE}/{resource}", json={**body, "organization_id": str(ORG_A)}
    )
    assert resp.status_code == 201
    assert create.await_args.args[1]["organization_id"] == ORG_A


@pytest.mark.parametrize(("resource", "body", "fn", "mod", "obj"), CREATE_CASES)
def test_admin_create_uses_body_org(monkeypatch, resource, body, fn, mod, obj):
    create = AsyncMock(return_value=obj(org=ORG_B))
    monkeypatch.setattr(mod, fn, create)
    client, _ = _client(ADMIN)
    resp = client.post(
        f"{BASE}/{resource}", json={**body, "organization_id": str(ORG_B)}
    )
    assert resp.status_code == 201
    assert create.await_args.args[1]["organization_id"] == ORG_B
