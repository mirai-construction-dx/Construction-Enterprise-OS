"""Shared helpers for the organization (tenant) isolation tests (ADR-0004, Issue #114).

Router-level tests replace the service functions bound in each router module with spies via
``monkeypatch`` (restored after every test), so they do not depend on the module-level patches
that ``test_autonomous.py`` leaves behind. SQL-level scoping is verified by calling
``src.services.autonomous_service`` directly.
"""

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from fastapi.testclient import TestClient

from src.main import create_app
from src.middleware.auth import TokenData, get_current_user
from src.models.base import get_db

ORG_A = uuid.uuid4()
ORG_B = uuid.uuid4()
BASE = "/api/v1/autonomous"
AUTH = {"Authorization": "Bearer test-token"}


def make_user(
    org: str | None = str(ORG_A), roles: list[str] | None = None
) -> TokenData:
    return TokenData(
        sub=str(uuid.uuid4()),
        type="user",
        org=org,
        roles=roles if roles is not None else ["site_manager"],
    )


def admin() -> TokenData:
    return make_user(roles=["admin"])


class Result:
    """Minimal stand-in for a SQLAlchemy result."""

    def __init__(self, value: Any = None):
        self._value = value

    def scalar(self):
        return self._value

    def scalar_one_or_none(self):
        return self._value

    def scalars(self):
        return self

    def all(self):
        return self._value if isinstance(self._value, list) else []


def make_db(*values: Any) -> MagicMock:
    db = MagicMock()
    if values:
        db.execute = AsyncMock(side_effect=[Result(v) for v in values])
    else:
        db.execute = AsyncMock(return_value=Result(None))
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    db.close = AsyncMock()
    db.add = MagicMock()
    db.delete = AsyncMock()
    return db


def make_client(
    user: TokenData, db: MagicMock | None = None
) -> tuple[TestClient, MagicMock]:
    app = create_app()
    db = db if db is not None else make_db()

    async def _db():
        yield db

    async def _user():
        return user

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[get_current_user] = _user
    return TestClient(app), db


def compiled(db: MagicMock, index: int = 0) -> tuple[str, dict]:
    stmt = db.execute.await_args_list[index].args[0]
    return str(stmt), stmt.compile().params


def assert_scoped_to(db: MagicMock, org: uuid.UUID, index: int = 0) -> None:
    sql, params = compiled(db, index)
    assert ".organization_id = :organization_id" in sql, sql
    assert params["organization_id_1"] == org


def assert_not_scoped(db: MagicMock, index: int = 0) -> None:
    sql, params = compiled(db, index)
    assert ":organization_id" not in sql, sql
    assert "organization_id_1" not in params


def detail_code(resp) -> str:
    return resp.json()["detail"]["code"]


_NOW = datetime.now(timezone.utc)


def record(kind: str, org: uuid.UUID = ORG_A, **overrides: Any) -> SimpleNamespace:
    """Build a row object that validates against the corresponding response schema."""
    common = {"id": uuid.uuid4(), "organization_id": org, "created_at": _NOW}
    fields: dict[str, dict[str, Any]] = {
        "agent": {
            "name": "agent",
            "agent_type": "scheduler",
            "status": "idle",
            "target_resource": None,
            "config": {},
            "last_run_at": None,
            "run_count": 0,
            "error_count": 0,
            "is_enabled": True,
        },
        "twin": {
            "project_id": None,
            "name": "twin",
            "twin_type": "site",
            "status": "active",
            "bim_model_id": None,
            "iot_device_ids": [],
            "last_sync_at": None,
            "sync_interval_seconds": 60,
            "data_sources": {},
            "current_state": {},
            "metadata_": {},
            "metadata": {},
            "updated_at": _NOW,
        },
        "task": {
            "agent_id": None,
            "digital_twin_id": None,
            "title": "task",
            "task_type": "optimize",
            "priority": "normal",
            "status": "pending",
            "input_data": None,
            "output_data": None,
            "error_message": None,
            "started_at": None,
            "completed_at": None,
            "duration_ms": None,
        },
        "simulation": {
            "project_id": None,
            "digital_twin_id": None,
            "name": "sim",
            "simulation_type": "schedule",
            "status": "draft",
            "parameters": {},
            "results": {},
            "progress_percent": 0,
            "started_at": None,
            "completed_at": None,
            "created_by": None,
        },
        "operation": {
            "project_id": None,
            "digital_twin_id": None,
            "name": "op",
            "operation_type": "excavation",
            "equipment_id": None,
            "status": "planned",
            "plan_data": {},
            "execution_log": [],
            "progress_percent": 0,
            "safety_status": "normal",
            "area": None,
            "start_time": None,
            "end_time": None,
            "operator_id": None,
        },
        "robot": {
            "project_id": None,
            "robot_name": "auv",
            "robot_type": "auv",
            "status": "docked",
            "mission_type": None,
            "location": None,
            "depth_meters": None,
            "battery_level": 90,
            "mission_plan": {},
            "telemetry": {},
            "last_contact": None,
            "deployed_at": None,
            "recovered_at": None,
        },
        "control": {
            "target_id": uuid.uuid4(),
            "target_type": "operation",
            "command_type": "start",
            "parameters": {},
            "status": "pending",
            "issued_by": uuid.uuid4(),
            "executed_at": None,
            "result": None,
            "error_message": None,
        },
    }
    return SimpleNamespace(**{**common, **fields[kind], **overrides})
