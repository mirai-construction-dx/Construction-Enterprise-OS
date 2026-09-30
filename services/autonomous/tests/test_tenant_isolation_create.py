"""Organization (tenant) isolation: create endpoints, parent references and control targets (ADR-0004, #114)."""

import importlib
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from .tenant_support import (
    AUTH,
    BASE,
    ORG_A,
    ORG_B,
    admin,
    assert_not_scoped,
    assert_scoped_to,
    compiled,
    detail_code,
    make_client,
    make_db,
    make_user,
    record,
)

TARGET = "22222222-2222-2222-2222-222222222222"


def _spy(monkeypatch, module: str, fn: str, result=None, side_effect=None) -> AsyncMock:
    spy = AsyncMock(return_value=result, side_effect=side_effect)
    monkeypatch.setattr(importlib.import_module(f"src.api.{module}"), fn, spy)
    return spy


def _stored(kind: str):
    """Create-function side effect that echoes the organization it was asked to store."""

    async def _create(db, data):
        return record(kind, org=data["organization_id"])

    return _create


# (path, body without organization_id, router module, create function, record kind)
CREATES = [
    (
        "/agents",
        {"name": "a", "agent_type": "scheduler"},
        "agents",
        "create_agent",
        "agent",
    ),
    (
        "/digital-twins",
        {"name": "t", "twin_type": "site"},
        "digital_twins",
        "create_twin",
        "twin",
    ),
    ("/tasks", {"title": "t", "task_type": "optimize"}, "tasks", "create_task", "task"),
    (
        "/simulations",
        {"name": "s", "simulation_type": "schedule"},
        "simulations",
        "create_simulation",
        "simulation",
    ),
    (
        "/operations",
        {"name": "o", "operation_type": "excavation"},
        "operations",
        "create_operation",
        "operation",
    ),
    (
        "/marine-robots",
        {"robot_name": "r", "robot_type": "auv"},
        "marine_robots",
        "create_marine_robot",
        "robot",
    ),
]


@pytest.mark.parametrize(("path", "body", "module", "fn", "kind"), CREATES)
def test_create_in_own_org(monkeypatch, path, body, module, fn, kind):
    spy = _spy(monkeypatch, module, fn, side_effect=_stored(kind))
    client, _ = make_client(make_user())

    resp = client.post(
        f"{BASE}{path}", json={**body, "organization_id": str(ORG_A)}, headers=AUTH
    )

    assert resp.status_code == 201, resp.text
    assert spy.await_args.args[1]["organization_id"] == ORG_A
    assert resp.json()["data"]["organization_id"] == str(ORG_A)


@pytest.mark.parametrize(("path", "body", "module", "fn", "kind"), CREATES)
def test_create_in_other_org_is_forbidden(monkeypatch, path, body, module, fn, kind):
    spy = _spy(monkeypatch, module, fn, side_effect=_stored(kind))
    client, db = make_client(make_user())

    resp = client.post(
        f"{BASE}{path}", json={**body, "organization_id": str(ORG_B)}, headers=AUTH
    )

    assert resp.status_code == 403
    assert detail_code(resp) == "ORG_FORBIDDEN"
    spy.assert_not_awaited()
    db.add.assert_not_called()
    db.execute.assert_not_awaited()


@pytest.mark.parametrize(
    ("org", "code"), [(None, "ORG_REQUIRED"), ("bad", "ORG_INVALID")]
)
@pytest.mark.parametrize(("path", "body", "module", "fn", "kind"), CREATES)
def test_create_without_valid_org_fails_closed(
    monkeypatch, path, body, module, fn, kind, org, code
):
    spy = _spy(monkeypatch, module, fn, side_effect=_stored(kind))
    client, db = make_client(make_user(org=org))

    resp = client.post(
        f"{BASE}{path}", json={**body, "organization_id": str(ORG_A)}, headers=AUTH
    )

    assert resp.status_code == 403
    assert detail_code(resp) == code
    spy.assert_not_awaited()
    db.add.assert_not_called()


@pytest.mark.parametrize(("path", "body", "module", "fn", "kind"), CREATES)
def test_admin_creates_in_body_org(monkeypatch, path, body, module, fn, kind):
    spy = _spy(monkeypatch, module, fn, side_effect=_stored(kind))
    client, _ = make_client(admin())

    resp = client.post(
        f"{BASE}{path}", json={**body, "organization_id": str(ORG_B)}, headers=AUTH
    )

    assert resp.status_code == 201, resp.text
    assert spy.await_args.args[1]["organization_id"] == ORG_B


# ── parent references (task -> agent / twin, simulation / operation -> twin) ──

# (path, body, router module, create function, parent lookup, parent field, code)
PARENT_REFS = [
    (
        "/tasks",
        {"title": "t", "task_type": "x"},
        "tasks",
        "create_task",
        "get_agent_by_id",
        "agent_id",
        "AGENT",
    ),
    (
        "/tasks",
        {"title": "t", "task_type": "x"},
        "tasks",
        "create_task",
        "get_twin_by_id",
        "digital_twin_id",
        "TWIN",
    ),
    (
        "/simulations",
        {"name": "s", "simulation_type": "x"},
        "simulations",
        "create_simulation",
        "get_twin_by_id",
        "digital_twin_id",
        "TWIN",
    ),
    (
        "/operations",
        {"name": "o", "operation_type": "x"},
        "operations",
        "create_operation",
        "get_twin_by_id",
        "digital_twin_id",
        "TWIN",
    ),
]


@pytest.mark.parametrize(
    ("path", "body", "module", "create_fn", "lookup", "field", "code"), PARENT_REFS
)
def test_parent_of_other_org_is_404(
    monkeypatch, path, body, module, create_fn, lookup, field, code
):
    # Org-scoped parent lookup finds nothing for another org's agent / twin.
    create_spy = _spy(monkeypatch, module, create_fn)
    lookup_spy = _spy(monkeypatch, module, lookup, None)
    client, db = make_client(make_user())

    resp = client.post(
        f"{BASE}{path}",
        json={**body, "organization_id": str(ORG_A), field: TARGET},
        headers=AUTH,
    )

    assert resp.status_code == 404
    assert detail_code(resp) == f"{code}_NOT_FOUND"
    assert lookup_spy.await_args.kwargs["organization_id"] == ORG_A
    create_spy.assert_not_awaited()
    db.add.assert_not_called()


@pytest.mark.parametrize(
    ("path", "body", "module", "create_fn", "lookup", "field", "code"), PARENT_REFS
)
def test_admin_parent_org_mismatch_is_400(
    monkeypatch, path, body, module, create_fn, lookup, field, code
):
    create_spy = _spy(monkeypatch, module, create_fn)
    lookup_spy = _spy(
        monkeypatch, module, lookup, SimpleNamespace(organization_id=ORG_B)
    )
    client, _ = make_client(admin())

    resp = client.post(
        f"{BASE}{path}",
        json={**body, "organization_id": str(ORG_A), field: TARGET},
        headers=AUTH,
    )

    assert resp.status_code == 400
    assert detail_code(resp) == f"{code}_ORG_MISMATCH"
    assert lookup_spy.await_args.kwargs["organization_id"] is None
    create_spy.assert_not_awaited()


@pytest.mark.parametrize(
    ("path", "body", "module", "create_fn", "lookup", "field", "code"), PARENT_REFS
)
def test_parent_in_same_org_is_accepted(
    monkeypatch, path, body, module, create_fn, lookup, field, code
):
    kind = {
        "create_task": "task",
        "create_simulation": "simulation",
        "create_operation": "operation",
    }[create_fn]
    create_spy = _spy(monkeypatch, module, create_fn, side_effect=_stored(kind))
    _spy(monkeypatch, module, lookup, SimpleNamespace(organization_id=ORG_A))
    client, _ = make_client(make_user())

    resp = client.post(
        f"{BASE}{path}",
        json={**body, "organization_id": str(ORG_A), field: TARGET},
        headers=AUTH,
    )

    assert resp.status_code == 201, resp.text
    assert create_spy.await_args.args[1]["organization_id"] == ORG_A


# ── controls: commands must never target another org's equipment ──

TARGET_TABLES = [
    ("operation", "autonomous_operations"),
    ("marine_robot", "marine_robotics"),
    ("agent", "autonomous_agents"),
    ("digital_twin", "digital_twins"),
    ("simulation", "construction_simulations"),
]


def _command(target_type: str, org=ORG_A) -> dict:
    return {
        "organization_id": str(org),
        "target_id": TARGET,
        "target_type": target_type,
        "command_type": "start",
        "parameters": {},
        "issued_by": "33333333-3333-3333-3333-333333333333",
    }


@pytest.mark.parametrize(("target_type", "table"), TARGET_TABLES)
def test_command_to_other_org_target_is_404_and_not_issued(
    monkeypatch, target_type, table
):
    # The real org-scoped target lookup runs; another org's equipment is not found.
    send_spy = _spy(monkeypatch, "controls", "send_control_command")
    client, db = make_client(make_user(), make_db(None))

    resp = client.post(f"{BASE}/controls", json=_command(target_type), headers=AUTH)

    assert resp.status_code == 404
    assert detail_code(resp) == "CONTROL_TARGET_NOT_FOUND"
    sql, params = compiled(db)
    assert f"autonomous.{table}" in sql
    assert str(params["id_1"]) == TARGET
    assert_scoped_to(db, ORG_A)
    send_spy.assert_not_awaited()
    db.add.assert_not_called()
    db.flush.assert_not_awaited()


@pytest.mark.parametrize("target_type", ["machine", "drone", "OPERATION", "operations"])
def test_command_to_unsupported_target_type_fails_closed(monkeypatch, target_type):
    send_spy = _spy(monkeypatch, "controls", "send_control_command")
    client, db = make_client(make_user())

    resp = client.post(f"{BASE}/controls", json=_command(target_type), headers=AUTH)

    assert resp.status_code == 400
    assert detail_code(resp) == "CONTROL_TARGET_UNSUPPORTED"
    send_spy.assert_not_awaited()
    db.execute.assert_not_awaited()
    db.add.assert_not_called()


def test_command_in_other_org_is_forbidden_before_target_lookup(monkeypatch):
    send_spy = _spy(monkeypatch, "controls", "send_control_command")
    client, db = make_client(make_user())

    resp = client.post(
        f"{BASE}/controls", json=_command("operation", org=ORG_B), headers=AUTH
    )

    assert resp.status_code == 403
    assert detail_code(resp) == "ORG_FORBIDDEN"
    send_spy.assert_not_awaited()
    db.execute.assert_not_awaited()


@pytest.mark.parametrize(
    ("org", "code"), [(None, "ORG_REQUIRED"), ("bad", "ORG_INVALID")]
)
def test_command_without_valid_org_fails_closed(monkeypatch, org, code):
    send_spy = _spy(monkeypatch, "controls", "send_control_command")
    client, db = make_client(make_user(org=org))

    resp = client.post(f"{BASE}/controls", json=_command("operation"), headers=AUTH)

    assert resp.status_code == 403
    assert detail_code(resp) == code
    send_spy.assert_not_awaited()
    db.execute.assert_not_awaited()


def test_admin_command_to_target_of_different_org_is_400(monkeypatch):
    send_spy = _spy(monkeypatch, "controls", "send_control_command")
    client, db = make_client(admin(), make_db(record("operation", org=ORG_B)))

    resp = client.post(
        f"{BASE}/controls", json=_command("operation", org=ORG_A), headers=AUTH
    )

    assert resp.status_code == 400
    assert detail_code(resp) == "CONTROL_TARGET_ORG_MISMATCH"
    assert_not_scoped(db)
    send_spy.assert_not_awaited()


def test_admin_command_in_target_org_is_issued(monkeypatch):
    send_spy = _spy(
        monkeypatch, "controls", "send_control_command", side_effect=_stored("control")
    )
    client, _ = make_client(
        admin(), make_db(record("robot", org=ORG_B))
    )

    resp = client.post(
        f"{BASE}/controls", json=_command("marine_robot", org=ORG_B), headers=AUTH
    )

    assert resp.status_code == 201, resp.text
    assert send_spy.await_args.args[1]["organization_id"] == ORG_B


def test_command_to_own_org_target_is_issued(monkeypatch):
    send_spy = _spy(
        monkeypatch, "controls", "send_control_command", side_effect=_stored("control")
    )
    client, db = make_client(make_user(), make_db(record("operation", org=ORG_A)))

    resp = client.post(f"{BASE}/controls", json=_command("operation"), headers=AUTH)

    assert resp.status_code == 201, resp.text
    assert_scoped_to(db, ORG_A)
    assert send_spy.await_args.args[1]["organization_id"] == ORG_A
