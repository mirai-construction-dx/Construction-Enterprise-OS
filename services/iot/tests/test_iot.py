"""IoT Service 結合テスト"""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from src.main import create_app
from src.models.base import get_db
from src.middleware.auth import get_current_user, get_current_client


class MockResult:
    def __init__(self, return_value=None, return_values=None):
        self._return_value = return_value
        self._return_values = return_values or []
        self._iter_idx = 0

    def scalar_one_or_none(self):
        return self._return_value

    def scalars(self):
        return self

    def all(self):
        if isinstance(self._return_value, list):
            return self._return_value
        return [self._return_value] if self._return_value else []

    def first(self):
        return self._return_value

    def scalar(self):
        return self._return_value

    def fetchall(self):
        return self._return_value or []


class MockFetchRow:
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


def _make_mock_user(sub="00000000-0000-0000-0000-000000000001"):
    user = MagicMock()
    user.sub = sub
    user.type = "user"
    user.org = "00000000-0000-0000-0000-000000000001"
    user.roles = ["admin"]
    user.scopes = []
    return user


def _make_mock_client(sub="00000000-0000-0000-0000-000000000002"):
    client = MagicMock()
    client.sub = sub
    client.type = "client"
    client.org = "00000000-0000-0000-0000-000000000001"
    client.roles = []
    client.scopes = ["iot:ingest"]
    return client


def _make_mock_device(device_id=None):
    from datetime import datetime, timezone
    d = MagicMock()
    d.id = device_id or uuid4()
    d.organization_id = uuid4()
    d.project_id = None
    d.site_id = None
    d.name = "Mock Device"
    d.device_type = "gps_tracker"
    d.serial_number = "MOCK-001"
    d.firmware_version = "1.0"
    d.status = "online"
    d.battery_level = 85
    d.location = None
    d.metadata_ = {}
    d.last_seen_at = None
    d.registered_at = datetime.now(timezone.utc)
    d.updated_at = datetime.now(timezone.utc)
    d.sensors = []
    return d


async def _mock_get_current_user():
    return _make_mock_user()


async def _mock_get_current_client():
    return _make_mock_client()


@pytest.fixture
def app():
    _app = create_app()
    mock_db = AsyncMock()

    async def mock_execute(*args, **kwargs):
        return MockResult()

    async def mock_commit():
        pass

    async def mock_rollback():
        pass

    async def mock_close():
        pass

    async def mock_flush():
        pass

    mock_db.execute = mock_execute
    mock_db.commit = mock_commit
    mock_db.rollback = mock_rollback
    mock_db.close = mock_close
    mock_db.flush = mock_flush
    mock_db.add = MagicMock()
    mock_db.delete = MagicMock()

    async def mock_get_db():
        yield mock_db

    _app.dependency_overrides[get_db] = mock_get_db
    _app.dependency_overrides[get_current_user] = _mock_get_current_user
    _app.dependency_overrides[get_current_client] = _mock_get_current_client
    return _app


@pytest.fixture
def client(app):
    return TestClient(app)


@pytest.fixture
def auth_headers():
    return {"Authorization": "Bearer mock-user-token"}


@pytest.fixture
def m2m_headers():
    return {"Authorization": "Bearer mock-client-token"}


# ============================================
# Health Check
# ============================================
def test_health_check(client):
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["service"] == "iot-service"


# ============================================
# Auth Required Tests (no auth headers)
# ============================================
@pytest.fixture
def app_no_auth():
    """App without auth dependency overrides - for testing auth rejection"""
    _app = create_app()
    mock_db = AsyncMock()

    async def mock_execute(*args, **kwargs):
        return MockResult()

    mock_db.execute = mock_execute
    mock_db.commit = AsyncMock()
    mock_db.rollback = AsyncMock()
    mock_db.close = AsyncMock()
    mock_db.flush = AsyncMock()
    mock_db.add = MagicMock()
    mock_db.delete = MagicMock()

    async def mock_get_db():
        yield mock_db

    _app.dependency_overrides[get_db] = mock_get_db
    return _app


@pytest.fixture
def unauth_client(app_no_auth):
    return TestClient(app_no_auth)


def test_devices_list_requires_auth(unauth_client):
    response = unauth_client.get("/api/v1/iot/devices")
    assert response.status_code == 401


def test_create_device_requires_auth(unauth_client):
    response = unauth_client.post("/api/v1/iot/devices", json={"name": "test"})
    assert response.status_code == 401


def test_telemetry_query_requires_auth(unauth_client):
    response = unauth_client.get("/api/v1/iot/telemetry/00000000-0000-0000-0000-000000000001?start_time=2024-01-01T00:00:00Z&end_time=2024-01-02T00:00:00Z")
    assert response.status_code == 401


def test_telemetry_ingest_requires_auth(unauth_client):
    response = unauth_client.post("/api/v1/iot/telemetry/ingest", json={"data": []})
    assert response.status_code == 401


def test_alert_rules_requires_auth(unauth_client):
    response = unauth_client.get("/api/v1/iot/alert-rules")
    assert response.status_code == 401


# ============================================
# Device CRUD Tests (with auth override)
# ============================================
def test_create_device_with_auth(client, auth_headers):
    mock_device = _make_mock_device()

    import src.api.devices as devices_module
    devices_module.register_device = AsyncMock(return_value=mock_device)

    response = client.post(
        "/api/v1/iot/devices",
        json={
            "organization_id": "00000000-0000-0000-0000-000000000001",
            "name": "Test GPS Tracker",
            "device_type": "gps_tracker",
            "serial_number": "GPS-001",
        },
        headers=auth_headers,
    )
    assert response.status_code == 201
    data = response.json()
    assert data["success"] is True


def test_heartbeat_with_m2m_auth(client, m2m_headers):
    device_id = str(uuid4())
    mock_device = _make_mock_device(device_id=device_id)

    import src.api.devices as devices_module
    devices_module.device_heartbeat_svc = AsyncMock(return_value=mock_device)

    response = client.post(
        f"/api/v1/iot/devices/{device_id}/heartbeat",
        json={"battery_level": 85},
        headers=m2m_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True


# ============================================
# Telemetry Ingest + Alert Rule Check
# ============================================
def test_telemetry_ingest_batch(client, m2m_headers):
    device_id = str(uuid4())
    sensor_id = str(uuid4())

    import src.api.telemetry as telemetry_module
    telemetry_module.ingest_telemetry = AsyncMock(return_value=2)
    telemetry_module.check_alert_rules = AsyncMock(return_value=[])
    telemetry_module.get_device_by_id = AsyncMock(return_value=_make_mock_device())

    response = client.post(
        "/api/v1/iot/telemetry/ingest",
        json={
            "data": [
                {
                    "device_id": device_id,
                    "sensor_id": sensor_id,
                    "metric_name": "temperature",
                    "value": 25.5,
                    "unit": "°C",
                },
                {
                    "device_id": device_id,
                    "sensor_id": sensor_id,
                    "metric_name": "humidity",
                    "value": 60.0,
                    "unit": "%",
                },
            ]
        },
        headers=m2m_headers,
    )
    assert response.status_code == 202
    data = response.json()
    assert data["data"]["ingested"] == 2


def test_telemetry_ingest_empty_batch(client, m2m_headers):
    response = client.post(
        "/api/v1/iot/telemetry/ingest",
        json={"data": []},
        headers=m2m_headers,
    )
    assert response.status_code == 422


# ============================================
# Alert Rule Evaluation (Unit Tests)
# ============================================
class TestAlertConditionEvaluation:
    def test_gt_condition(self):
        from src.services.alert_service import _evaluate_condition
        assert _evaluate_condition("gt", 30.0, 25.0) is True
        assert _evaluate_condition("gt", 25.0, 25.0) is False
        assert _evaluate_condition("gt", 20.0, 25.0) is False

    def test_lt_condition(self):
        from src.services.alert_service import _evaluate_condition
        assert _evaluate_condition("lt", 20.0, 25.0) is True
        assert _evaluate_condition("lt", 25.0, 25.0) is False
        assert _evaluate_condition("lt", 30.0, 25.0) is False

    def test_gte_condition(self):
        from src.services.alert_service import _evaluate_condition
        assert _evaluate_condition("gte", 30.0, 25.0) is True
        assert _evaluate_condition("gte", 25.0, 25.0) is True
        assert _evaluate_condition("gte", 20.0, 25.0) is False

    def test_lte_condition(self):
        from src.services.alert_service import _evaluate_condition
        assert _evaluate_condition("lte", 20.0, 25.0) is True
        assert _evaluate_condition("lte", 25.0, 25.0) is True
        assert _evaluate_condition("lte", 30.0, 25.0) is False

    def test_eq_condition(self):
        from src.services.alert_service import _evaluate_condition
        assert _evaluate_condition("eq", 25.0, 25.0) is True
        assert _evaluate_condition("eq", 26.0, 25.0) is False

    def test_invalid_condition(self):
        from src.services.alert_service import _evaluate_condition
        assert _evaluate_condition("invalid", 30.0, 25.0) is False


class TestAlertMessageGeneration:
    def test_alert_message_gt(self):
        from src.services.alert_service import _build_alert_message
        rule = MagicMock()
        rule.name = "High Temperature"
        rule.metric_name = "temperature"
        rule.condition = "gt"
        rule.threshold = 30.0
        msg = _build_alert_message(rule, 35.0)
        assert "超えました" in msg
        assert "35.0" in msg

    def test_alert_message_lt(self):
        from src.services.alert_service import _build_alert_message
        rule = MagicMock()
        rule.name = "Low Battery"
        rule.metric_name = "battery"
        rule.condition = "lt"
        rule.threshold = 10.0
        msg = _build_alert_message(rule, 5.0)
        assert "下回りました" in msg


# ============================================
# Cooldown Logic Test
# ============================================
@pytest.mark.asyncio
async def test_cooldown_logic():
    import uuid

    from src.services.alert_service import check_alert_rules

    mock_db = AsyncMock()

    rule_id = uuid.uuid4()
    device_id = uuid.uuid4()
    sensor_id = uuid.uuid4()

    mock_rule = MagicMock()
    mock_rule.id = rule_id
    mock_rule.is_active = True
    mock_rule.metric_name = "temperature"
    mock_rule.condition = "gt"
    mock_rule.threshold = 30.0
    mock_rule.severity = "warning"
    mock_rule.cooldown_minutes = 5

    class MockRuleResult:
        def scalars(self):
            return self

        def all(self):
            return [mock_rule]

    mock_rule_result = MockRuleResult()

    recent_alert = MagicMock()

    class MockRecentResult:
        def scalar_one_or_none(self):
            return recent_alert

    mock_recent_result = MockRecentResult()

    async def mock_execute_side_effect(query, *args, **kwargs):
        query_str = str(query)
        if "alert_history" in query_str:
            return mock_recent_result
        return mock_rule_result

    mock_db.execute = mock_execute_side_effect
    mock_db.add = MagicMock()
    mock_db.flush = AsyncMock()

    result = await check_alert_rules(
        mock_db,
        device_id=device_id,
        metric_name="temperature",
        value=35.0,
        sensor_id=sensor_id,
    )

    assert result == []


# ============================================
# Schema Validation Tests (uses client with auth)
# ============================================
def test_device_create_invalid_type(client, auth_headers):
    response = client.post(
        "/api/v1/iot/devices",
        json={"name": "Test", "device_type": ""},
        headers=auth_headers,
    )
    # organization_id is required, so 422
    assert response.status_code == 422


def test_alert_rule_invalid_condition(client, auth_headers):
    response = client.post(
        "/api/v1/iot/alert-rules",
        json={
            "organization_id": "00000000-0000-0000-0000-000000000001",
            "name": "Test Rule",
            "metric_name": "temperature",
            "condition": "invalid",
            "threshold": 30.0,
        },
        headers=auth_headers,
    )
    assert response.status_code == 422


def test_alert_rule_invalid_severity(client, auth_headers):
    response = client.post(
        "/api/v1/iot/alert-rules",
        json={
            "organization_id": "00000000-0000-0000-0000-000000000001",
            "name": "Test Rule",
            "metric_name": "temperature",
            "condition": "gt",
            "threshold": 30.0,
            "severity": "unknown",
        },
        headers=auth_headers,
    )
    assert response.status_code == 422
