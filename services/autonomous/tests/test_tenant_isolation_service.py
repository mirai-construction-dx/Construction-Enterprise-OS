"""Organization (tenant) isolation at the service layer (ADR-0004, #114).

Every by-id function (including the ones that actuate agents, machines, operations and robots)
queries with the organization condition; when another org's record is not found nothing is
written, deleted or flushed.
"""

import uuid

import pytest

from src.services import autonomous_service as svc

from .tenant_support import (
    ORG_A,
    assert_not_scoped,
    assert_scoped_to,
    compiled,
    make_db,
    record,
)

RID = uuid.uuid4()

# (service function, extra positional args after the id, value returned when not found)
BY_ID_FUNCS = [
    (svc.get_agent_by_id, (), None),
    (svc.update_agent, ({"name": "x"},), None),
    (svc.delete_agent, (), False),
    (svc.start_agent, (), None),
    (svc.stop_agent, (), None),
    (svc.pause_agent, (), None),
    (svc.get_twin_by_id, (), None),
    (svc.update_twin, ({"name": "x"},), None),
    (svc.delete_twin, (), False),
    (svc.sync_twin, ({"x": 1},), None),
    (svc.get_twin_current_state, (), None),
    (svc.get_task_by_id, (), None),
    (svc.get_simulation_by_id, (), None),
    (svc.update_simulation, ({"name": "x"},), None),
    (svc.delete_simulation, (), False),
    (svc.run_simulation, (), None),
    (svc.get_operation_by_id, (), None),
    (svc.update_operation, ({"name": "x"},), None),
    (svc.delete_operation, (), False),
    (svc.start_operation, (), None),
    (svc.pause_operation, (), None),
    (svc.resume_operation, (), None),
    (svc.abort_operation, (), None),
    (svc.emergency_stop_operation, (), None),
    (svc.get_operation_progress, (), None),
    (svc.get_marine_robot_by_id, (), None),
    (svc.update_marine_robot, ({"robot_name": "x"},), None),
    (svc.delete_marine_robot, (), False),
    (svc.deploy_marine_robot, (), None),
    (svc.recover_marine_robot, (), None),
    (svc.get_marine_robot_telemetry, (), None),
    (svc.set_marine_robot_mission, ({"route": []},), None),
    (svc.get_control_by_id, (), None),
]


def _ids(params):
    return [getattr(f[0], "__name__", str(f[0])) for f in params]


@pytest.mark.parametrize(("fn", "extra", "missing"), BY_ID_FUNCS, ids=_ids(BY_ID_FUNCS))
async def test_other_org_record_is_not_found_and_not_written(fn, extra, missing):
    db = make_db(None)  # the org-scoped query does not match another org's record

    result = await fn(db, RID, *extra, organization_id=ORG_A)

    assert result is missing
    assert_scoped_to(db, ORG_A)
    _, params = compiled(db)
    assert params["id_1"] == RID
    db.flush.assert_not_awaited()
    db.delete.assert_not_awaited()
    db.add.assert_not_called()


@pytest.mark.parametrize(("fn", "extra", "missing"), BY_ID_FUNCS, ids=_ids(BY_ID_FUNCS))
async def test_admin_lookup_has_no_org_condition(fn, extra, missing):
    db = make_db(None)

    await fn(db, RID, *extra, organization_id=None)

    assert_not_scoped(db)


# Actuating functions act only on the record returned by the org-scoped query.
ACTIONS = [
    (svc.start_agent, "agent", "status", "active"),
    (svc.stop_agent, "agent", "status", "idle"),
    (svc.pause_agent, "agent", "status", "paused"),
    (svc.run_simulation, "simulation", "status", "completed"),
    (svc.start_operation, "operation", "status", "in_progress"),
    (svc.pause_operation, "operation", "status", "paused"),
    (svc.resume_operation, "operation", "status", "in_progress"),
    (svc.abort_operation, "operation", "status", "aborted"),
    (svc.emergency_stop_operation, "operation", "status", "emergency_stop"),
    (svc.deploy_marine_robot, "robot", "status", "deploying"),
    (svc.recover_marine_robot, "robot", "status", "docked"),
]


@pytest.mark.parametrize(("fn", "kind", "attr", "value"), ACTIONS, ids=_ids(ACTIONS))
async def test_actions_apply_to_own_org_record(fn, kind, attr, value):
    row = record(kind, org=ORG_A, status="x")
    db = make_db(row)

    result = await fn(db, row.id, organization_id=ORG_A)

    assert result is row
    assert getattr(row, attr) == value
    assert_scoped_to(db, ORG_A)
    db.flush.assert_awaited_once()


async def test_set_mission_applies_to_own_org_robot():
    row = record("robot", org=ORG_A)
    db = make_db(row)

    await svc.set_marine_robot_mission(
        db, row.id, {"route": [1]}, organization_id=ORG_A
    )

    assert row.mission_plan == {"route": [1]}
    assert_scoped_to(db, ORG_A)


# ── list / child queries ─────────────────────────────────────

LISTS = [
    svc.get_agents_paginated,
    svc.get_twins_paginated,
    svc.get_tasks_paginated,
    svc.get_simulations_paginated,
    svc.get_operations_paginated,
    svc.get_marine_robots_paginated,
    svc.get_pending_controls,
]


@pytest.mark.parametrize("fn", LISTS, ids=_ids([(f,) for f in LISTS]))
async def test_list_count_and_rows_are_scoped(fn):
    db = make_db(0, [])

    await fn(db, organization_id=ORG_A)

    assert_scoped_to(db, ORG_A, index=0)  # count
    assert_scoped_to(db, ORG_A, index=1)  # rows


async def test_target_command_history_is_scoped():
    db = make_db(0, [])

    await svc.get_controls_for_target(
        db, target_id=RID, target_type="operation", organization_id=ORG_A
    )

    assert_scoped_to(db, ORG_A, index=0)
    assert_scoped_to(db, ORG_A, index=1)


async def test_admin_target_command_history_is_global():
    db = make_db(0, [])

    await svc.get_controls_for_target(
        db, target_id=RID, target_type="operation", organization_id=None
    )

    assert_not_scoped(db, index=0)
    assert_not_scoped(db, index=1)


def test_control_targets_are_org_owned_models():
    for model in svc.CONTROL_TARGET_MODELS.values():
        assert "organization_id" in model.__table__.c


async def test_control_target_lookup_rejects_unknown_type():
    with pytest.raises(KeyError):
        await svc.get_control_target(make_db(), "machine", RID, organization_id=ORG_A)
