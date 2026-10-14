"""アラートルール / アラート履歴 API のテスト (Issue #101)。

現在の実装の挙動を固定する。DB は AsyncMock で差し替え、
サービス関数は monkeypatch で差し替える（テスト間でパッチを漏らさない）。
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from src.main import create_app
from src.middleware.auth import get_current_user
from src.models.base import get_db
from src.services import alert_service

USER_SUB = "00000000-0000-0000-0000-000000000001"
ORG_ID = "00000000-0000-0000-0000-000000000001"


def _make_mock_user():
    user = MagicMock()
    user.sub = USER_SUB
    user.type = "user"
    user.org = ORG_ID
    user.roles = ["admin"]
    user.scopes = []
    return user


async def _mock_get_current_user():
    return _make_mock_user()


def _make_alert(alert_id: int = 1, **overrides):
    """AlertHistoryResponse の全フィールドを持つ擬似 ORM オブジェクト。"""
    alert = MagicMock()
    alert.id = alert_id
    alert.rule_id = None
    alert.device_id = uuid4()
    alert.sensor_id = None
    alert.metric_name = "temperature"
    alert.current_value = 35.0
    alert.threshold = 30.0
    alert.severity = "critical"
    alert.message = "High Temperature"
    alert.acknowledged_by = None
    alert.acknowledged_at = None
    alert.resolved_at = None
    alert.created_at = datetime.now(timezone.utc)
    for key, value in overrides.items():
        setattr(alert, key, value)
    return alert


@pytest.fixture
def mock_db():
    db = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    db.close = AsyncMock()
    db.flush = AsyncMock()
    db.execute = AsyncMock()

    def _add(obj):
        # INSERT 時に DB が採番する値（id / created_at）を模擬する
        obj.id = uuid4()
        obj.created_at = datetime.now(timezone.utc)

    db.add = MagicMock(side_effect=_add)
    return db


@pytest.fixture
def client(mock_db):
    app = create_app()

    async def _get_db():
        yield mock_db

    app.dependency_overrides[get_db] = _get_db
    app.dependency_overrides[get_current_user] = _mock_get_current_user
    return TestClient(app)


@pytest.fixture
def unauth_client(mock_db):
    app = create_app()

    async def _get_db():
        yield mock_db

    app.dependency_overrides[get_db] = _get_db
    return TestClient(app)


AUTH = {"Authorization": "Bearer mock-user-token"}


# ============================================
# POST /alert-rules
# ============================================
def test_create_alert_rule_returns_201_with_rule(client, mock_db):
    device_id = str(uuid4())
    # The referenced device must exist in the rule's organization (ADR-0004).
    device = MagicMock()
    device.organization_id = UUID(ORG_ID)
    mock_db.execute = AsyncMock(
        return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=device))
    )
    response = client.post(
        "/api/v1/iot/alert-rules",
        json={
            "organization_id": ORG_ID,
            "device_id": device_id,
            "name": "High Temperature",
            "metric_name": "temperature",
            "condition": "gt",
            "threshold": 30.0,
            "severity": "critical",
            "cooldown_minutes": 10,
        },
        headers=AUTH,
    )

    assert response.status_code == 201
    body = response.json()
    assert body["success"] is True
    data = body["data"]
    assert data["organization_id"] == ORG_ID
    assert data["device_id"] == device_id
    assert data["name"] == "High Temperature"
    assert data["metric_name"] == "temperature"
    assert data["condition"] == "gt"
    assert data["threshold"] == 30.0
    assert data["severity"] == "critical"
    assert data["is_active"] is True
    assert data["cooldown_minutes"] == 10
    assert data["notification_channels"] == ["in_app"]
    UUID(data["id"])
    mock_db.add.assert_called_once()
    mock_db.flush.assert_awaited()


def test_create_alert_rule_applies_schema_defaults(client):
    response = client.post(
        "/api/v1/iot/alert-rules",
        json={
            "organization_id": ORG_ID,
            "name": "Any device",
            "metric_name": "humidity",
            "condition": "lte",
            "threshold": 10,
        },
        headers=AUTH,
    )

    assert response.status_code == 201
    data = response.json()["data"]
    assert data["device_id"] is None
    assert data["sensor_id"] is None
    assert data["severity"] == "warning"
    assert data["cooldown_minutes"] == 5


def test_create_alert_rule_requires_auth(unauth_client):
    response = unauth_client.post("/api/v1/iot/alert-rules", json={})
    assert response.status_code == 401


# ============================================
# GET /alert-rules
# ============================================
def test_list_alert_rules_passes_filters_to_service(client, monkeypatch):
    rule = MagicMock()
    rule.id = uuid4()
    rule.organization_id = UUID(ORG_ID)
    rule.device_id = None
    rule.sensor_id = None
    rule.name = "Rule A"
    rule.metric_name = "temperature"
    rule.condition = "gt"
    rule.threshold = 30.0
    rule.severity = "warning"
    rule.is_active = True
    rule.cooldown_minutes = 5
    rule.notification_channels = ["in_app"]
    rule.created_at = datetime.now(timezone.utc)
    fake = AsyncMock(return_value=[rule])
    monkeypatch.setattr("src.api.alerts.get_alert_rules", fake)
    device_id = uuid4()

    response = client.get(
        f"/api/v1/iot/alert-rules?organization_id={ORG_ID}&device_id={device_id}",
        headers=AUTH,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert [r["name"] for r in body["data"]] == ["Rule A"]
    assert fake.await_args.kwargs == {
        "organization_id": UUID(ORG_ID),
        "device_id": device_id,
    }


def test_list_alert_rules_empty(client, monkeypatch):
    fake = AsyncMock(return_value=[])
    monkeypatch.setattr("src.api.alerts.get_alert_rules", fake)

    response = client.get("/api/v1/iot/alert-rules", headers=AUTH)

    assert response.status_code == 200
    assert response.json()["data"] == []
    assert fake.await_args.kwargs == {"organization_id": None, "device_id": None}


# ============================================
# GET /alerts
# ============================================
def test_list_alerts_passes_severity_and_acknowledged_filters(client, monkeypatch):
    alert = _make_alert(7)
    fake = AsyncMock(return_value=([alert], 45))
    monkeypatch.setattr("src.api.alerts.get_alert_history", fake)

    response = client.get(
        "/api/v1/iot/alerts?severity=critical&acknowledged=false&page=2&per_page=20",
        headers=AUTH,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["data"]["total"] == 45
    assert [a["id"] for a in body["data"]["alerts"]] == [7]
    assert body["meta"] == {"page": 2, "per_page": 20, "total": 45, "total_pages": 3}
    assert fake.await_args.kwargs == {
        "page": 2,
        "per_page": 20,
        "severity": "critical",
        "device_id": None,
        "acknowledged": False,
        "organization_id": None,  # admin token without organization filter
    }


def test_list_alerts_acknowledged_true_is_forwarded(client, monkeypatch):
    fake = AsyncMock(return_value=([], 0))
    monkeypatch.setattr("src.api.alerts.get_alert_history", fake)

    response = client.get("/api/v1/iot/alerts?acknowledged=true", headers=AUTH)

    assert response.status_code == 200
    assert fake.await_args.kwargs["acknowledged"] is True
    assert fake.await_args.kwargs["severity"] is None


def test_list_alerts_empty_result_has_zero_total_pages(client, monkeypatch):
    monkeypatch.setattr(
        "src.api.alerts.get_alert_history", AsyncMock(return_value=([], 0))
    )

    response = client.get("/api/v1/iot/alerts", headers=AUTH)

    assert response.status_code == 200
    body = response.json()
    assert body["data"] == {"alerts": [], "total": 0}
    assert body["meta"] == {"page": 1, "per_page": 20, "total": 0, "total_pages": 0}


@pytest.mark.parametrize("query", ["page=0", "per_page=0", "per_page=101"])
def test_list_alerts_rejects_out_of_range_paging(client, query):
    response = client.get(f"/api/v1/iot/alerts?{query}", headers=AUTH)
    assert response.status_code == 422


def test_list_alerts_requires_auth(unauth_client):
    response = unauth_client.get("/api/v1/iot/alerts")
    assert response.status_code == 401


# ============================================
# get_alert_history (filter SQL)
# ============================================
class _CountResult:
    def __init__(self, value):
        self._value = value

    def scalar(self):
        return self._value


class _RowsResult:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return self

    def all(self):
        return self._rows


async def _run_history(**kwargs):
    statements = []

    async def execute(stmt, *args, **kw):
        statements.append(str(stmt))
        if len(statements) == 1:
            return _CountResult(3)
        return _RowsResult([])

    db = MagicMock()
    db.execute = execute
    alerts, total = await alert_service.get_alert_history(db, **kwargs)
    return alerts, total, statements


@pytest.mark.asyncio
async def test_get_alert_history_acknowledged_false_filters_null():
    _, total, (count_sql, rows_sql) = await _run_history(acknowledged=False)
    assert total == 3
    for sql in (count_sql, rows_sql):
        assert "alert_history.acknowledged_at IS NULL" in sql
        assert "IS NOT NULL" not in sql


@pytest.mark.asyncio
async def test_get_alert_history_acknowledged_true_filters_not_null():
    _, _, (count_sql, rows_sql) = await _run_history(acknowledged=True)
    for sql in (count_sql, rows_sql):
        assert "alert_history.acknowledged_at IS NOT NULL" in sql


@pytest.mark.asyncio
async def test_get_alert_history_severity_filter():
    _, _, (count_sql, rows_sql) = await _run_history(severity="critical")
    for sql in (count_sql, rows_sql):
        assert "alert_history.severity = :severity_1" in sql
        assert "acknowledged_at IS" not in sql


@pytest.mark.asyncio
async def test_get_alert_history_without_filters_has_no_where():
    _, _, (count_sql, rows_sql) = await _run_history()
    assert "WHERE" not in count_sql
    assert "WHERE" not in rows_sql
    assert "ORDER BY iot.alert_history.created_at DESC" in rows_sql
    assert "LIMIT :param_1 OFFSET :param_2" in rows_sql


# ============================================
# POST /alerts/{id}/acknowledge
# ============================================
def test_acknowledge_alert_sets_user_and_timestamp(client, mock_db):
    alert = _make_alert(11)
    mock_db.execute = AsyncMock(
        return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=alert))
    )

    response = client.post("/api/v1/iot/alerts/11/acknowledge", headers=AUTH)

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["id"] == 11
    assert data["acknowledged_by"] == USER_SUB
    assert data["acknowledged_at"] is not None
    assert data["resolved_at"] is None
    mock_db.flush.assert_awaited()


def test_acknowledge_alert_not_found(client, mock_db):
    mock_db.execute = AsyncMock(
        return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None))
    )

    response = client.post("/api/v1/iot/alerts/999/acknowledge", headers=AUTH)

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "ALERT_NOT_FOUND"


def test_acknowledge_alert_non_integer_id_is_422(client):
    response = client.post(f"/api/v1/iot/alerts/{uuid4()}/acknowledge", headers=AUTH)
    assert response.status_code == 422


def test_acknowledge_alert_requires_auth(unauth_client):
    response = unauth_client.post("/api/v1/iot/alerts/1/acknowledge")
    assert response.status_code == 401


# ============================================
# POST /alerts/{id}/resolve
# ============================================
def test_resolve_alert_sets_resolved_at(client, mock_db):
    # DEF-08a: resolve requires a prior acknowledge (state-machine order).
    alert = _make_alert(12, acknowledged_at=datetime.now(timezone.utc))
    mock_db.execute = AsyncMock(
        return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=alert))
    )

    response = client.post("/api/v1/iot/alerts/12/resolve", headers=AUTH)

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["id"] == 12
    assert data["resolved_at"] is not None
    assert data["acknowledged_by"] is None
    mock_db.flush.assert_awaited()


def test_resolve_alert_not_found(client, mock_db):
    mock_db.execute = AsyncMock(
        return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None))
    )

    response = client.post("/api/v1/iot/alerts/999/resolve", headers=AUTH)

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "ALERT_NOT_FOUND"
