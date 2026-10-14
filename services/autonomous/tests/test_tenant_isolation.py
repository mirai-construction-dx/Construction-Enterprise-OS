"""Organization (tenant) isolation: helper rules, list endpoints and by-id endpoints (ADR-0004, #114).

Create endpoints / parent references / control targets: ``test_tenant_isolation_create.py``.
SQL scoping and "no write on another org" at the service layer: ``test_tenant_isolation_service.py``.
"""

import importlib
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from src.middleware.tenant import create_org, scope_org

from .tenant_support import (
    AUTH,
    BASE,
    ORG_A,
    ORG_B,
    admin,
    detail_code,
    make_client,
    make_user,
)

# ── helper rules ─────────────────────────────────────────────


def test_scope_org_pins_regular_user_to_token_org():
    assert scope_org(make_user()) == ORG_A
    assert scope_org(make_user(), ORG_A) == ORG_A


def test_scope_org_rejects_other_org_for_regular_user():
    with pytest.raises(HTTPException) as exc:
        scope_org(make_user(), ORG_B)
    assert exc.value.status_code == 403
    assert exc.value.detail["code"] == "ORG_FORBIDDEN"


@pytest.mark.parametrize(
    ("org", "code"), [(None, "ORG_REQUIRED"), ("not-a-uuid", "ORG_INVALID")]
)
def test_scope_org_fails_closed_without_valid_org(org, code):
    with pytest.raises(HTTPException) as exc:
        scope_org(make_user(org=org))
    assert exc.value.status_code == 403
    assert exc.value.detail["code"] == code


def test_admin_is_cross_org():
    assert scope_org(admin()) is None
    assert scope_org(admin(), ORG_B) == ORG_B
    assert create_org(admin(), ORG_B) == ORG_B


def test_create_org_rejects_other_org_for_regular_user():
    assert create_org(make_user(), ORG_A) == ORG_A
    with pytest.raises(HTTPException) as exc:
        create_org(make_user(), ORG_B)
    assert exc.value.status_code == 403
    assert exc.value.detail["code"] == "ORG_FORBIDDEN"


# ── list endpoints ───────────────────────────────────────────

# (path, router module, service function bound in that module)
LISTS = [
    ("/agents", "agents", "get_agents_paginated"),
    ("/digital-twins", "digital_twins", "get_twins_paginated"),
    ("/tasks", "tasks", "get_tasks_paginated"),
    ("/simulations", "simulations", "get_simulations_paginated"),
    ("/operations", "operations", "get_operations_paginated"),
    ("/marine-robots", "marine_robots", "get_marine_robots_paginated"),
    ("/controls", "controls", "get_pending_controls"),
]
TARGET_HISTORY = (
    f"/controls/target/operation/{ORG_B}",  # any uuid as target id
    "controls",
    "get_controls_for_target",
)


def _spy(monkeypatch, module: str, fn: str, result) -> AsyncMock:
    spy = AsyncMock(return_value=result)
    monkeypatch.setattr(importlib.import_module(f"src.api.{module}"), fn, spy)
    return spy


@pytest.mark.parametrize(("path", "module", "fn"), [*LISTS, TARGET_HISTORY])
def test_list_is_scoped_to_token_org(monkeypatch, path, module, fn):
    spy = _spy(monkeypatch, module, fn, ([], 0))
    client, _ = make_client(make_user())

    resp = client.get(f"{BASE}{path}", headers=AUTH)

    assert resp.status_code == 200, resp.text
    assert spy.await_args.kwargs["organization_id"] == ORG_A


@pytest.mark.parametrize(("path", "module", "fn"), LISTS)
def test_list_for_other_org_is_forbidden(monkeypatch, path, module, fn):
    spy = _spy(monkeypatch, module, fn, ([], 0))
    client, db = make_client(make_user())

    resp = client.get(
        f"{BASE}{path}", params={"organization_id": str(ORG_B)}, headers=AUTH
    )

    assert resp.status_code == 403
    assert detail_code(resp) == "ORG_FORBIDDEN"
    spy.assert_not_awaited()
    db.execute.assert_not_awaited()


@pytest.mark.parametrize(
    ("org", "code"), [(None, "ORG_REQUIRED"), ("bad", "ORG_INVALID")]
)
@pytest.mark.parametrize(("path", "module", "fn"), [*LISTS, TARGET_HISTORY])
def test_list_without_valid_org_fails_closed(monkeypatch, path, module, fn, org, code):
    spy = _spy(monkeypatch, module, fn, ([], 0))
    client, db = make_client(make_user(org=org))

    resp = client.get(f"{BASE}{path}", headers=AUTH)

    assert resp.status_code == 403
    assert detail_code(resp) == code
    spy.assert_not_awaited()
    db.execute.assert_not_awaited()


@pytest.mark.parametrize(("path", "module", "fn"), [*LISTS, TARGET_HISTORY])
def test_admin_list_without_org_is_global(monkeypatch, path, module, fn):
    spy = _spy(monkeypatch, module, fn, ([], 0))
    client, _ = make_client(admin())

    resp = client.get(f"{BASE}{path}", headers=AUTH)

    assert resp.status_code == 200, resp.text
    assert spy.await_args.kwargs["organization_id"] is None


@pytest.mark.parametrize(("path", "module", "fn"), LISTS)
def test_admin_list_with_org_is_scoped(monkeypatch, path, module, fn):
    spy = _spy(monkeypatch, module, fn, ([], 0))
    client, _ = make_client(admin())

    resp = client.get(
        f"{BASE}{path}", params={"organization_id": str(ORG_B)}, headers=AUTH
    )

    assert resp.status_code == 200, resp.text
    assert spy.await_args.kwargs["organization_id"] == ORG_B


# ── by-id endpoints (get / update / delete / actions) ───────

RID = "11111111-1111-1111-1111-111111111111"

# (method, path, json body, router module, service function, not-found code)
BY_ID = [
    ("get", f"/agents/{RID}", None, "agents", "get_agent_by_id", "AGENT_NOT_FOUND"),
    (
        "put",
        f"/agents/{RID}",
        {"name": "x"},
        "agents",
        "update_agent",
        "AGENT_NOT_FOUND",
    ),
    ("delete", f"/agents/{RID}", None, "agents", "delete_agent", "AGENT_NOT_FOUND"),
    ("post", f"/agents/{RID}/start", None, "agents", "start_agent", "AGENT_NOT_FOUND"),
    ("post", f"/agents/{RID}/stop", None, "agents", "stop_agent", "AGENT_NOT_FOUND"),
    ("post", f"/agents/{RID}/pause", None, "agents", "pause_agent", "AGENT_NOT_FOUND"),
    (
        "get",
        f"/digital-twins/{RID}",
        None,
        "digital_twins",
        "get_twin_by_id",
        "TWIN_NOT_FOUND",
    ),
    (
        "put",
        f"/digital-twins/{RID}",
        {"name": "x"},
        "digital_twins",
        "update_twin",
        "TWIN_NOT_FOUND",
    ),
    (
        "delete",
        f"/digital-twins/{RID}",
        None,
        "digital_twins",
        "delete_twin",
        "TWIN_NOT_FOUND",
    ),
    (
        "post",
        f"/digital-twins/{RID}/sync",
        {"current_state": {"x": 1}},
        "digital_twins",
        "sync_twin",
        "TWIN_NOT_FOUND",
    ),
    (
        "get",
        f"/digital-twins/{RID}/state",
        None,
        "digital_twins",
        "get_twin_current_state",
        "TWIN_NOT_FOUND",
    ),
    ("get", f"/tasks/{RID}", None, "tasks", "get_task_by_id", "TASK_NOT_FOUND"),
    (
        "get",
        f"/simulations/{RID}",
        None,
        "simulations",
        "get_simulation_by_id",
        "SIMULATION_NOT_FOUND",
    ),
    (
        "delete",
        f"/simulations/{RID}",
        None,
        "simulations",
        "delete_simulation",
        "SIMULATION_NOT_FOUND",
    ),
    (
        "post",
        f"/simulations/{RID}/run",
        None,
        "simulations",
        "run_simulation",
        "SIMULATION_NOT_FOUND",
    ),
    (
        "get",
        f"/operations/{RID}",
        None,
        "operations",
        "get_operation_by_id",
        "OPERATION_NOT_FOUND",
    ),
    (
        "put",
        f"/operations/{RID}",
        {"name": "x"},
        "operations",
        "update_operation",
        "OPERATION_NOT_FOUND",
    ),
    (
        "delete",
        f"/operations/{RID}",
        None,
        "operations",
        "delete_operation",
        "OPERATION_NOT_FOUND",
    ),
    (
        "post",
        f"/operations/{RID}/start",
        None,
        "operations",
        "start_operation",
        "OPERATION_NOT_FOUND",
    ),
    (
        "post",
        f"/operations/{RID}/pause",
        None,
        "operations",
        "pause_operation",
        "OPERATION_NOT_FOUND",
    ),
    (
        "post",
        f"/operations/{RID}/resume",
        None,
        "operations",
        "resume_operation",
        "OPERATION_NOT_FOUND",
    ),
    (
        "post",
        f"/operations/{RID}/abort",
        None,
        "operations",
        "abort_operation",
        "OPERATION_NOT_FOUND",
    ),
    (
        "post",
        f"/operations/{RID}/emergency-stop",
        None,
        "operations",
        "emergency_stop_operation",
        "OPERATION_NOT_FOUND",
    ),
    (
        "get",
        f"/operations/{RID}/progress",
        None,
        "operations",
        "get_operation_progress",
        "OPERATION_NOT_FOUND",
    ),
    (
        "get",
        f"/marine-robots/{RID}",
        None,
        "marine_robots",
        "get_marine_robot_by_id",
        "ROBOT_NOT_FOUND",
    ),
    (
        "put",
        f"/marine-robots/{RID}",
        {"robot_name": "x"},
        "marine_robots",
        "update_marine_robot",
        "ROBOT_NOT_FOUND",
    ),
    (
        "delete",
        f"/marine-robots/{RID}",
        None,
        "marine_robots",
        "delete_marine_robot",
        "ROBOT_NOT_FOUND",
    ),
    (
        "post",
        f"/marine-robots/{RID}/deploy",
        None,
        "marine_robots",
        "deploy_marine_robot",
        "ROBOT_NOT_FOUND",
    ),
    (
        "post",
        f"/marine-robots/{RID}/recover",
        None,
        "marine_robots",
        "recover_marine_robot",
        "ROBOT_NOT_FOUND",
    ),
    (
        "get",
        f"/marine-robots/{RID}/telemetry",
        None,
        "marine_robots",
        "get_marine_robot_telemetry",
        "ROBOT_NOT_FOUND",
    ),
    (
        "post",
        f"/marine-robots/{RID}/mission",
        {"mission_plan": {"route": []}},
        "marine_robots",
        "set_marine_robot_mission",
        "ROBOT_NOT_FOUND",
    ),
    (
        "get",
        f"/controls/{RID}",
        None,
        "controls",
        "get_control_by_id",
        "CONTROL_NOT_FOUND",
    ),
]


def _call(client, method: str, path: str, body):
    kwargs = {"headers": AUTH}
    if body is not None:
        kwargs["json"] = body
    return getattr(client, method)(f"{BASE}{path}", **kwargs)


@pytest.mark.parametrize(("method", "path", "body", "module", "fn", "code"), BY_ID)
def test_by_id_of_other_org_is_404(monkeypatch, method, path, body, module, fn, code):
    # The org-scoped lookup finds nothing for another org's record -> 404 without existence leak.
    spy = _spy(monkeypatch, module, fn, None)
    client, db = make_client(make_user())

    resp = _call(client, method, path, body)

    assert resp.status_code == 404
    assert detail_code(resp) == code
    assert spy.await_args.kwargs["organization_id"] == ORG_A
    db.add.assert_not_called()


@pytest.mark.parametrize(
    ("org", "code"), [(None, "ORG_REQUIRED"), ("bad", "ORG_INVALID")]
)
@pytest.mark.parametrize(("method", "path", "body", "module", "fn", "_nf"), BY_ID)
def test_by_id_without_valid_org_fails_closed(
    monkeypatch, method, path, body, module, fn, _nf, org, code
):
    spy = _spy(monkeypatch, module, fn, None)
    client, db = make_client(make_user(org=org))

    resp = _call(client, method, path, body)

    assert resp.status_code == 403
    assert detail_code(resp) == code
    spy.assert_not_awaited()
    db.execute.assert_not_awaited()


@pytest.mark.parametrize(("method", "path", "body", "module", "fn", "code"), BY_ID)
def test_admin_by_id_is_not_org_filtered(
    monkeypatch, method, path, body, module, fn, code
):
    spy = _spy(monkeypatch, module, fn, None)
    client, _ = make_client(admin())

    resp = _call(client, method, path, body)

    assert resp.status_code == 404
    assert detail_code(resp) == code
    assert spy.await_args.kwargs["organization_id"] is None


# ── delete role enforcement (RBAC) ───────────────────────────

# (method, path, router module, service function)
DELETE_PATHS = [
    ("delete", f"/agents/{RID}", "agents", "delete_agent"),
    ("delete", f"/digital-twins/{RID}", "digital_twins", "delete_twin"),
    ("delete", f"/simulations/{RID}", "simulations", "delete_simulation"),
    ("delete", f"/operations/{RID}", "operations", "delete_operation"),
    ("delete", f"/marine-robots/{RID}", "marine_robots", "delete_marine_robot"),
]


@pytest.mark.parametrize(("method", "path", "module", "fn"), DELETE_PATHS)
def test_delete_requires_management_role(monkeypatch, method, path, module, fn):
    """削除は admin / site_manager のみ（RBAC ロールモデル）。非管理ロールは 403。"""
    spy = _spy(monkeypatch, module, fn, True)
    client, db = make_client(make_user(roles=["site_supervisor"]))

    resp = _call(client, method, path, None)

    assert resp.status_code == 403
    assert detail_code(resp) == "FORBIDDEN"
    spy.assert_not_awaited()
    db.execute.assert_not_awaited()


def test_same_org_emergency_stop_still_works(monkeypatch):
    from .tenant_support import record

    op = record("operation", status="emergency_stop", safety_status="emergency")
    spy = _spy(monkeypatch, "operations", "emergency_stop_operation", op)
    client, _ = make_client(make_user())

    resp = client.post(f"{BASE}/operations/{RID}/emergency-stop", headers=AUTH)

    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["status"] == "emergency_stop"
    assert spy.await_args.kwargs["organization_id"] == ORG_A
