"""Organization isolation of device heartbeat / telemetry ingest (Issue #132, ADR-0004).

Both endpoints accept user and client tokens (``get_current_client``). The caller is pinned to
its token ``org`` claim; the ``admin`` role crosses organizations. Another organization's device
and an unknown device are both 404 and nothing is written (no status update, no telemetry row,
no alert rule evaluation).
"""

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.sql import Select

from src.main import create_app
from src.middleware.auth import TokenData, get_current_client
from src.models.base import get_db

ORG_A = uuid.uuid4()
ORG_B = uuid.uuid4()
DEVICE_ID = uuid.uuid4()
OTHER_DEVICE_ID = uuid.uuid4()
AUTH = {"Authorization": "Bearer mock-token"}
HEARTBEAT = f"/api/v1/iot/devices/{DEVICE_ID}/heartbeat"
INGEST = "/api/v1/iot/telemetry/ingest"


class _Result:
    def __init__(self, value=None):
        self._value = value

    def scalar_one_or_none(self):
        return self._value

    def scalars(self):
        mock = MagicMock()
        mock.all.return_value = self._value or []
        return mock


def _principal(
    token_type: str = "user",
    org: str | None = str(ORG_A),
    roles: list[str] | None = None,
) -> TokenData:
    default_roles = ["site_manager"] if token_type == "user" else []
    return TokenData(
        sub=str(uuid.uuid4()),
        type=token_type,
        org=org,
        roles=roles if roles is not None else default_roles,
        scopes=["iot:ingest"] if token_type == "client" else [],
    )


def _admin() -> TokenData:
    return _principal(roles=["admin"])


# Non-admin principals: regular user token and client (M2M) token, both carry ``org``.
PRINCIPAL_TYPES = ["user", "client"]


def _client(principal: TokenData, *values):
    app = create_app()
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=[_Result(v) for v in values])
    db.add = MagicMock()
    db.delete = AsyncMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()

    async def _db():
        yield db

    async def _current_client():
        return principal

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[get_current_client] = _current_client
    return TestClient(app), db


def _params(db, index: int) -> dict:
    stmt = db.execute.await_args_list[index].args[0]
    return stmt.compile().params


def _param_values(db, index: int) -> list:
    """Flattened bound values (``IN`` lists are expanded)."""
    flat: list = []
    for value in _params(db, index).values():
        flat.extend(value if isinstance(value, (list, tuple)) else [value])
    return flat


def _assert_no_write(db) -> None:
    db.add.assert_not_called()
    db.delete.assert_not_awaited()
    db.flush.assert_not_awaited()
    db.commit.assert_not_awaited()


def _device(org: uuid.UUID = ORG_A):
    d = MagicMock()
    d.id = DEVICE_ID
    d.organization_id = org
    d.project_id = None
    d.site_id = None
    d.name = "Device"
    d.device_type = "gps_tracker"
    d.serial_number = None
    d.firmware_version = None
    d.status = "offline"
    d.battery_level = None
    d.location = None
    d.metadata_ = {}
    d.last_seen_at = None
    d.registered_at = datetime.now(timezone.utc)
    d.updated_at = datetime.now(timezone.utc)
    d.sensors = []
    return d


def _ingest_body(*device_ids: uuid.UUID) -> dict:
    return {
        "data": [
            {"device_id": str(d), "metric_name": "temperature", "value": 99.0}
            for d in device_ids
        ]
    }


@pytest.fixture
def ingest_spies(monkeypatch):
    """Spy on the write / alert steps of ingest so their absence can be asserted."""
    ingest = AsyncMock(return_value=1)
    alerts = AsyncMock(return_value=[])
    monkeypatch.setattr("src.api.telemetry.ingest_telemetry", ingest)
    monkeypatch.setattr("src.api.telemetry.check_alert_rules", alerts)
    return ingest, alerts


# ── heartbeat ────────────────────────────────────────────────


@pytest.mark.parametrize("token_type", PRINCIPAL_TYPES)
def test_heartbeat_of_other_org_device_is_not_found_and_not_written(token_type):
    # The org-scoped lookup finds nothing (the device belongs to another organization).
    client, db = _client(_principal(token_type), None)

    resp = client.post(HEARTBEAT, json={"battery_level": 50}, headers=AUTH)

    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "DEVICE_NOT_FOUND"
    assert db.execute.await_count == 1
    params = _params(db, 0)
    assert ORG_A in params.values()
    assert DEVICE_ID in params.values()
    _assert_no_write(db)


def test_heartbeat_of_unknown_device_is_not_found_for_admin():
    client, db = _client(_admin(), None)

    resp = client.post(HEARTBEAT, json={}, headers=AUTH)

    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "DEVICE_NOT_FOUND"
    assert ORG_A not in _params(db, 0).values()
    _assert_no_write(db)


@pytest.mark.parametrize(
    ("org", "code"), [(None, "ORG_REQUIRED"), ("not-a-uuid", "ORG_INVALID")]
)
@pytest.mark.parametrize("token_type", PRINCIPAL_TYPES)
def test_heartbeat_without_valid_org_is_rejected(token_type, org, code):
    client, db = _client(_principal(token_type, org=org))

    resp = client.post(HEARTBEAT, json={}, headers=AUTH)

    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == code
    db.execute.assert_not_awaited()
    _assert_no_write(db)


@pytest.mark.parametrize("token_type", PRINCIPAL_TYPES)
def test_heartbeat_of_own_org_device_is_recorded(token_type):
    device = _device(ORG_A)
    client, db = _client(_principal(token_type), device)

    resp = client.post(HEARTBEAT, json={"battery_level": 50}, headers=AUTH)

    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "online"
    assert resp.json()["data"]["battery_level"] == 50
    assert ORG_A in _params(db, 0).values()
    db.flush.assert_awaited_once()


def test_admin_heartbeat_of_other_org_device_is_recorded():
    client, db = _client(_admin(), _device(ORG_B))

    resp = client.post(HEARTBEAT, json={}, headers=AUTH)

    assert resp.status_code == 200
    assert resp.json()["data"]["organization_id"] == str(ORG_B)
    assert ORG_A not in _params(db, 0).values()
    db.flush.assert_awaited_once()


# ── telemetry ingest ─────────────────────────────────────────


def _assert_lookup_only(db) -> None:
    """Only the device lookup ran: no telemetry INSERT reached the database."""
    assert db.execute.await_count == 1
    assert isinstance(db.execute.await_args_list[0].args[0], Select)


@pytest.mark.parametrize("token_type", PRINCIPAL_TYPES)
def test_ingest_for_other_org_device_is_not_found_and_not_written(
    ingest_spies, token_type
):
    ingest, alerts = ingest_spies
    client, db = _client(_principal(token_type), [])  # org-scoped lookup finds nothing

    resp = client.post(INGEST, json=_ingest_body(DEVICE_ID), headers=AUTH)

    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "DEVICE_NOT_FOUND"
    _assert_lookup_only(db)
    values = _param_values(db, 0)
    assert ORG_A in values
    assert DEVICE_ID in values
    ingest.assert_not_awaited()
    alerts.assert_not_awaited()
    _assert_no_write(db)


def test_ingest_batch_with_one_other_org_device_is_rejected_entirely(ingest_spies):
    ingest, alerts = ingest_spies
    # Only the own-org device is visible; the batch also references another org's device.
    client, db = _client(_principal(), [DEVICE_ID])

    resp = client.post(
        INGEST, json=_ingest_body(DEVICE_ID, OTHER_DEVICE_ID), headers=AUTH
    )

    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "DEVICE_NOT_FOUND"
    _assert_lookup_only(db)
    assert ORG_A in _param_values(db, 0)
    ingest.assert_not_awaited()
    alerts.assert_not_awaited()


def test_ingest_for_unknown_device_is_not_found_for_admin(ingest_spies):
    ingest, alerts = ingest_spies
    client, db = _client(_admin(), [])

    resp = client.post(INGEST, json=_ingest_body(DEVICE_ID), headers=AUTH)

    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "DEVICE_NOT_FOUND"
    _assert_lookup_only(db)
    assert ORG_A not in _param_values(db, 0)
    ingest.assert_not_awaited()
    alerts.assert_not_awaited()


@pytest.mark.parametrize(
    ("org", "code"), [(None, "ORG_REQUIRED"), ("not-a-uuid", "ORG_INVALID")]
)
@pytest.mark.parametrize("token_type", PRINCIPAL_TYPES)
def test_ingest_without_valid_org_is_rejected(ingest_spies, token_type, org, code):
    ingest, alerts = ingest_spies
    client, db = _client(_principal(token_type, org=org))

    resp = client.post(INGEST, json=_ingest_body(DEVICE_ID), headers=AUTH)

    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == code
    db.execute.assert_not_awaited()
    ingest.assert_not_awaited()
    alerts.assert_not_awaited()


@pytest.mark.parametrize("token_type", PRINCIPAL_TYPES)
def test_ingest_for_own_org_device_is_accepted(ingest_spies, token_type):
    ingest, alerts = ingest_spies
    client, db = _client(_principal(token_type), [DEVICE_ID])

    resp = client.post(INGEST, json=_ingest_body(DEVICE_ID), headers=AUTH)

    assert resp.status_code == 202
    assert resp.json()["data"]["ingested"] == 1
    assert ORG_A in _param_values(db, 0)
    ingest.assert_awaited_once()
    alerts.assert_awaited_once()
    assert alerts.await_args.kwargs["device_id"] == DEVICE_ID


def test_admin_ingest_for_other_org_device_is_accepted(ingest_spies):
    ingest, alerts = ingest_spies
    client, db = _client(_admin(), [DEVICE_ID])

    resp = client.post(INGEST, json=_ingest_body(DEVICE_ID), headers=AUTH)

    assert resp.status_code == 202
    assert ORG_A not in _param_values(db, 0)
    ingest.assert_awaited_once()
    alerts.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_visible_device_ids_skips_query_for_empty_input():
    from src.services.device_service import get_visible_device_ids

    db = MagicMock()
    db.execute = AsyncMock()

    assert await get_visible_device_ids(db, set(), ORG_A) == set()
    db.execute.assert_not_awaited()
