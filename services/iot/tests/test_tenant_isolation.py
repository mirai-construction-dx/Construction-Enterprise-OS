"""Organization (tenant) isolation tests for the iot service (Issue #114, ADR-0004).

Regular users are pinned to the token ``org`` claim; the ``admin`` role crosses organizations.
Telemetry / sensors / alert history have no organization column, so they are scoped through
the parent device's organization.
"""

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from src.main import create_app
from src.middleware.auth import TokenData, get_current_user
from src.middleware.tenant import create_org, scope_org
from src.models.base import get_db
from src.services import alert_service

ORG_A = uuid.uuid4()
ORG_B = uuid.uuid4()
DEVICE_ID = uuid.uuid4()
SENSOR_ID = uuid.uuid4()
AUTH = {"Authorization": "Bearer mock-user-token"}


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

    def fetchall(self):
        return self._value or []


def _user(org: str | None = str(ORG_A), roles: list[str] | None = None) -> TokenData:
    return TokenData(
        sub=str(uuid.uuid4()),
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
    """Bound parameters (incl. sub-queries) of the ``index``-th executed statement."""
    stmt = db.execute.await_args_list[index].args[0]
    return stmt.compile().params


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
    d.status = "online"
    d.battery_level = None
    d.location = None
    d.metadata_ = {}
    d.last_seen_at = None
    d.registered_at = datetime.now(timezone.utc)
    d.updated_at = datetime.now(timezone.utc)
    d.sensors = []
    return d


def _sensor(org: uuid.UUID = ORG_A):
    s = MagicMock()
    s.id = SENSOR_ID
    s.device_id = DEVICE_ID
    s.device = _device(org)
    return s


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


# ── lists ────────────────────────────────────────────────────

# (path, DB results in execution order)
LISTS = [
    ("/api/v1/iot/devices", (0, [])),  # count, page
    ("/api/v1/iot/alert-rules", ([],)),
    ("/api/v1/iot/alerts", (0, [])),  # count, page
]


@pytest.mark.parametrize(("path", "values"), LISTS)
def test_list_is_scoped_to_token_org(path, values):
    client, db = _client(_user(), *values)

    resp = client.get(path, headers=AUTH)

    assert resp.status_code == 200
    assert db.execute.await_count == len(values)
    for i in range(len(values)):
        assert ORG_A in _params(db, i).values()


@pytest.mark.parametrize(("path", "values"), LISTS)
def test_list_for_other_org_is_forbidden(path, values):
    client, db = _client(_user())

    resp = client.get(path, params={"organization_id": str(ORG_B)}, headers=AUTH)

    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "ORG_FORBIDDEN"
    db.execute.assert_not_awaited()


@pytest.mark.parametrize(
    ("org", "code"), [(None, "ORG_REQUIRED"), ("not-a-uuid", "ORG_INVALID")]
)
@pytest.mark.parametrize(("path", "values"), LISTS)
def test_list_without_valid_org_is_rejected(path, values, org, code):
    client, db = _client(_user(org=org))

    resp = client.get(path, headers=AUTH)

    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == code
    db.execute.assert_not_awaited()


@pytest.mark.parametrize(("path", "values"), LISTS)
def test_admin_list_without_org_is_global(path, values):
    client, db = _client(_admin(), *values)

    resp = client.get(path, headers=AUTH)

    assert resp.status_code == 200
    for i in range(len(values)):
        assert ORG_A not in _params(db, i).values()


@pytest.mark.parametrize(("path", "values"), LISTS)
def test_admin_list_with_org_is_filtered(path, values):
    client, db = _client(_admin(), *values)

    resp = client.get(path, params={"organization_id": str(ORG_B)}, headers=AUTH)

    assert resp.status_code == 200
    for i in range(len(values)):
        assert ORG_B in _params(db, i).values()


# ── by-id reads / updates / deletes / actions (other org → 404, no write) ──

_TELEMETRY_RANGE = "start_time=2026-01-01T00:00:00Z&end_time=2026-01-02T00:00:00Z"

BY_ID_REQUESTS = [
    ("GET", f"/api/v1/iot/devices/{DEVICE_ID}", None, "DEVICE_NOT_FOUND"),
    ("PUT", f"/api/v1/iot/devices/{DEVICE_ID}", {"name": "x"}, "DEVICE_NOT_FOUND"),
    ("DELETE", f"/api/v1/iot/devices/{DEVICE_ID}", None, "DEVICE_NOT_FOUND"),
    ("GET", f"/api/v1/iot/devices/{DEVICE_ID}/sensors", None, "DEVICE_NOT_FOUND"),
    (
        "POST",
        f"/api/v1/iot/devices/{DEVICE_ID}/sensors",
        {"name": "t", "sensor_type": "temperature"},
        "DEVICE_NOT_FOUND",
    ),
    (
        "GET",
        f"/api/v1/iot/telemetry/{DEVICE_ID}?{_TELEMETRY_RANGE}",
        None,
        "DEVICE_NOT_FOUND",
    ),
    ("GET", f"/api/v1/iot/telemetry/{DEVICE_ID}/latest", None, "DEVICE_NOT_FOUND"),
    ("POST", "/api/v1/iot/alerts/1/acknowledge", None, "ALERT_NOT_FOUND"),
    ("POST", "/api/v1/iot/alerts/1/resolve", None, "ALERT_NOT_FOUND"),
]


@pytest.mark.parametrize(("method", "path", "body", "code"), BY_ID_REQUESTS)
def test_by_id_of_other_org_is_not_found_and_not_written(method, path, body, code):
    # The org-scoped lookup finds nothing (the record belongs to another organization).
    client, db = _client(_user(), None)

    resp = client.request(method, path, json=body, headers=AUTH)

    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == code
    assert db.execute.await_count == 1
    assert ORG_A in _params(db, 0).values()
    _assert_no_write(db)


@pytest.mark.parametrize(
    ("org", "code"), [(None, "ORG_REQUIRED"), ("not-a-uuid", "ORG_INVALID")]
)
@pytest.mark.parametrize(("method", "path", "body", "_code"), BY_ID_REQUESTS)
def test_by_id_without_valid_org_is_rejected(method, path, body, _code, org, code):
    client, db = _client(_user(org=org))

    resp = client.request(method, path, json=body, headers=AUTH)

    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == code
    db.execute.assert_not_awaited()
    _assert_no_write(db)


@pytest.mark.parametrize(("method", "path", "body", "code"), BY_ID_REQUESTS)
def test_admin_by_id_lookup_is_not_org_filtered(method, path, body, code):
    client, db = _client(_admin(), None)

    resp = client.request(method, path, json=body, headers=AUTH)

    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == code
    assert ORG_A not in _params(db, 0).values()


def test_get_device_of_own_org_is_returned():
    client, db = _client(_user(), _device())

    resp = client.get(f"/api/v1/iot/devices/{DEVICE_ID}", headers=AUTH)

    assert resp.status_code == 200
    assert resp.json()["data"]["organization_id"] == str(ORG_A)
    assert ORG_A in _params(db, 0).values()


def test_admin_reads_device_of_other_org():
    client, _ = _client(_admin(), _device(ORG_B))

    resp = client.get(f"/api/v1/iot/devices/{DEVICE_ID}", headers=AUTH)

    assert resp.status_code == 200
    assert resp.json()["data"]["organization_id"] == str(ORG_B)


def test_sensor_list_is_scoped_through_device_org():
    client, db = _client(_user(), _device(), [])

    resp = client.get(f"/api/v1/iot/devices/{DEVICE_ID}/sensors", headers=AUTH)

    assert resp.status_code == 200
    assert resp.json()["data"] == []
    assert ORG_A in _params(db, 0).values()  # parent device lookup
    assert ORG_A in _params(db, 1).values()  # sensors via device sub-query


def test_telemetry_latest_of_own_device_is_returned():
    client, db = _client(_user(), _device(), [])

    resp = client.get(f"/api/v1/iot/telemetry/{DEVICE_ID}/latest", headers=AUTH)

    assert resp.status_code == 200
    assert ORG_A in _params(db, 0).values()


# ── create ───────────────────────────────────────────────────


def _device_body(org: uuid.UUID) -> dict:
    return {"organization_id": str(org), "name": "d", "device_type": "gps_tracker"}


def _rule_body(org: uuid.UUID, **extra) -> dict:
    body = {
        "organization_id": str(org),
        "name": "r",
        "metric_name": "temperature",
        "condition": "gt",
        "threshold": 30.0,
    }
    body.update({k: str(v) for k, v in extra.items()})
    return body


CREATE_REQUESTS = [
    ("/api/v1/iot/devices", _device_body),
    ("/api/v1/iot/alert-rules", _rule_body),
]


@pytest.mark.parametrize(("path", "make_body"), CREATE_REQUESTS)
def test_create_in_other_org_is_forbidden(path, make_body):
    client, db = _client(_user())

    resp = client.post(path, json=make_body(ORG_B), headers=AUTH)

    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "ORG_FORBIDDEN"
    db.execute.assert_not_awaited()
    _assert_no_write(db)


@pytest.mark.parametrize(
    ("org", "code"), [(None, "ORG_REQUIRED"), ("not-a-uuid", "ORG_INVALID")]
)
@pytest.mark.parametrize(("path", "make_body"), CREATE_REQUESTS)
def test_create_without_valid_org_is_rejected(path, make_body, org, code):
    client, db = _client(_user(org=org))

    resp = client.post(path, json=make_body(ORG_A), headers=AUTH)

    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == code
    _assert_no_write(db)


@pytest.mark.parametrize(("user", "org"), [(_user(), ORG_A), (_admin(), ORG_B)])
def test_create_device_stores_resolved_org(monkeypatch, user, org):
    fake = AsyncMock(return_value=_device(org))
    monkeypatch.setattr("src.api.devices.register_device", fake)
    client, _ = _client(user)

    resp = client.post("/api/v1/iot/devices", json=_device_body(org), headers=AUTH)

    assert resp.status_code == 201
    assert fake.await_args.args[1]["organization_id"] == org


def test_create_rule_with_other_org_device_is_not_found():
    client, db = _client(_user(), None)

    resp = client.post(
        "/api/v1/iot/alert-rules",
        json=_rule_body(ORG_A, device_id=DEVICE_ID),
        headers=AUTH,
    )

    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "DEVICE_NOT_FOUND"
    assert ORG_A in _params(db, 0).values()
    _assert_no_write(db)


def test_create_rule_with_other_org_sensor_is_not_found():
    client, db = _client(_user(), None)

    resp = client.post(
        "/api/v1/iot/alert-rules",
        json=_rule_body(ORG_A, sensor_id=SENSOR_ID),
        headers=AUTH,
    )

    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "SENSOR_NOT_FOUND"
    assert ORG_A in _params(db, 0).values()
    _assert_no_write(db)


def test_admin_create_rule_with_device_of_different_org_is_rejected():
    client, db = _client(_admin(), _device(ORG_A))

    resp = client.post(
        "/api/v1/iot/alert-rules",
        json=_rule_body(ORG_B, device_id=DEVICE_ID),
        headers=AUTH,
    )

    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "DEVICE_ORG_MISMATCH"
    _assert_no_write(db)


def test_admin_create_rule_with_sensor_of_different_org_is_rejected():
    client, db = _client(_admin(), _sensor(ORG_A))

    resp = client.post(
        "/api/v1/iot/alert-rules",
        json=_rule_body(ORG_B, sensor_id=SENSOR_ID),
        headers=AUTH,
    )

    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "SENSOR_ORG_MISMATCH"
    _assert_no_write(db)


def test_create_rule_with_own_device_and_sensor_is_created():
    client, db = _client(_user(), _device(ORG_A), _sensor(ORG_A))

    def _add(obj):
        obj.id = uuid.uuid4()
        obj.created_at = datetime.now(timezone.utc)

    db.add = MagicMock(side_effect=_add)

    resp = client.post(
        "/api/v1/iot/alert-rules",
        json=_rule_body(ORG_A, device_id=DEVICE_ID, sensor_id=SENSOR_ID),
        headers=AUTH,
    )

    assert resp.status_code == 201
    assert resp.json()["data"]["organization_id"] == str(ORG_A)
    assert ORG_A in _params(db, 0).values()
    assert ORG_A in _params(db, 1).values()
    db.add.assert_called_once()


# ── ingestion: alert rules only from the device's organization ──


@pytest.mark.asyncio
async def test_check_alert_rules_only_uses_rules_of_device_org():
    db = MagicMock()
    db.execute = AsyncMock(return_value=_Result([]))

    await alert_service.check_alert_rules(
        db, device_id=DEVICE_ID, metric_name="temperature", value=99.0
    )

    sql = str(db.execute.await_args_list[0].args[0])
    assert "alert_rules.organization_id = (SELECT iot.devices.organization_id" in sql
    assert DEVICE_ID in _params(db, 0).values()
