"""品質テスト共通ヘルパー（QA-IoT）。

制約:
- synthetic fixture のみ。センサー値・座標は架空。実在構造物の実測値・個人情報を含まない。
- 外部 Provider / MQTT / 本番 DB / 実サービスへ接続しない（DB は AsyncMock）。
- 既存 `tests/test_iot.py` の mock_db / app / client 方式を踏襲する。
"""

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.dialects import postgresql
from sqlalchemy.sql.elements import TextClause

from src.main import create_app
from src.middleware.auth import TokenData, get_current_client, get_current_user
from src.models import AlertHistory, AlertRule, Device, Sensor, Telemetry
from src.models.base import get_db

# 先行テスト（test_iot.py）が src.api.* のモジュール属性を AsyncMock に
# 差し替えたままにするため、実関数へ復元するために使う。
import src.api.alerts as alerts_api
import src.api.devices as devices_api
import src.api.sensors as sensors_api
import src.api.telemetry as telemetry_api
from src.services import alert_service, device_service, telemetry_service

# ============================================
# synthetic identifiers（実在の値ではない）
# ============================================
ORG_A = uuid.UUID("00000000-0000-0000-0000-0000000000aa")  # トークン保持組織
ORG_B = uuid.UUID("00000000-0000-0000-0000-0000000000bb")  # 他テナント
USER_A = uuid.UUID("00000000-0000-0000-0000-0000000000cc")
USER_B = uuid.UUID("00000000-0000-0000-0000-0000000000ee")
DEVICE_A = uuid.UUID("00000000-0000-0000-0000-0000000000dd")
DEVICE_B = uuid.UUID("00000000-0000-0000-0000-0000000000ff")
SENSOR_A = uuid.UUID("00000000-0000-0000-0000-000000000011")
RULE_A = uuid.UUID("00000000-0000-0000-0000-000000000022")

NOW = datetime(2026, 5, 1, 0, 0, tzinfo=timezone.utc)
AUTH_HEADERS = {"Authorization": "Bearer synthetic-user-token"}
M2M_HEADERS = {"Authorization": "Bearer synthetic-client-token"}
API = "/api/v1/iot"

_REAL_BINDINGS = {
    devices_api: (
        ("register_device", device_service.register_device),
        ("get_device_by_id", device_service.get_device_by_id),
        ("get_devices_paginated", device_service.get_devices_paginated),
        ("update_device_svc", device_service.update_device),
        ("delete_device_svc", device_service.delete_device),
        ("device_heartbeat_svc", device_service.device_heartbeat),
    ),
    sensors_api: (
        ("add_sensor", device_service.add_sensor),
        ("get_sensors_by_device", device_service.get_sensors_by_device),
    ),
    telemetry_api: (
        ("ingest_telemetry", telemetry_service.ingest_telemetry),
        ("query_telemetry", telemetry_service.query_telemetry),
        ("get_latest_telemetry", telemetry_service.get_latest_telemetry),
        ("check_alert_rules", alert_service.check_alert_rules),
        ("get_device_by_id", device_service.get_device_by_id),
    ),
    alerts_api: (
        ("get_alert_rules", alert_service.get_alert_rules),
        ("get_alert_history", alert_service.get_alert_history),
        ("acknowledge_alert", alert_service.acknowledge_alert),
        ("resolve_alert", alert_service.resolve_alert),
    ),
}


@pytest.fixture(autouse=True)
def restore_api_bindings(monkeypatch):
    """test_iot.py が残したモジュール属性の AsyncMock 差し替えを実関数へ戻す。"""
    for module, pairs in _REAL_BINDINGS.items():
        for name, func in pairs:
            monkeypatch.setattr(module, name, func)
    yield


# ============================================
# mock DB
# ============================================
class MockResult:
    def __init__(self, scalar=None, items=None, total=None, rows=None):
        self._scalar = scalar
        self._items = items if items is not None else []
        self._total = total
        self._rows = rows if rows is not None else []

    def scalar_one_or_none(self):
        return self._scalar

    def scalars(self):
        return self

    def all(self):
        return self._items

    def first(self):
        return self._items[0] if self._items else None

    def scalar(self):
        return self._total if self._total is not None else self._scalar

    def fetchall(self):
        return self._rows


def _autofill(obj):
    """flush 時に server_default 相当（id / created_at 等）を補完する。"""
    if getattr(obj, "id", None) is None:
        if isinstance(obj, AlertHistory):
            obj.id = 1
        else:
            obj.id = uuid.uuid4()
    for attr in ("created_at", "registered_at", "updated_at"):
        if hasattr(obj, attr) and getattr(obj, attr) is None:
            setattr(obj, attr, NOW)
    if isinstance(obj, AlertHistory):
        if obj.message is None:
            obj.message = "(synthetic)"
        if obj.created_at is None:
            obj.created_at = NOW
    # SQLAlchemy の column default 相当を補完（実 DB では INSERT 時に適用される）
    if isinstance(obj, Sensor) and obj.is_active is None:
        obj.is_active = True
    if isinstance(obj, AlertRule) and obj.is_active is None:
        obj.is_active = True
    if isinstance(obj, Device) and obj.status is None:
        obj.status = "offline"


def make_mock_db() -> AsyncMock:
    db = AsyncMock()
    added: list = []

    db.add = MagicMock(side_effect=added.append)
    db.delete = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    db.close = AsyncMock()

    async def _flush():
        for obj in added:
            _autofill(obj)

    db.flush = AsyncMock(side_effect=_flush)
    db.execute = AsyncMock(return_value=MockResult())
    db.added = added  # type: ignore[attr-defined]
    return db


@pytest.fixture
def mock_db():
    return make_mock_db()


def build_client(mock_db, *, org=ORG_A, sub=USER_A, roles=("admin",), scopes=()):
    """依存性を差し替えた (app, TestClient) を返す。"""
    app = create_app()

    async def _get_db():
        yield mock_db

    async def _current_user():
        return TokenData(
            sub=str(sub), type="user", org=str(org), roles=list(roles), scopes=list(scopes)
        )

    async def _current_client():
        return TokenData(
            sub=str(sub),
            type="client",
            org=str(org),
            roles=list(roles),
            scopes=list(scopes),
        )

    app.dependency_overrides[get_db] = _get_db
    app.dependency_overrides[get_current_user] = _current_user
    app.dependency_overrides[get_current_client] = _current_client
    return app, TestClient(app)


@pytest.fixture
def client(mock_db):
    _app, _client = build_client(mock_db)
    return _client


@pytest.fixture
def client_no_auth():
    """認証オーバーライドなし（未認証アクセス検証用）。"""
    app = create_app()
    db = make_mock_db()

    async def _get_db():
        yield db

    app.dependency_overrides[get_db] = _get_db
    return TestClient(app)


# ============================================
# SQL 捕捉（DB 不要）
# ============================================
def record_execute(mock_db, results):
    """`db.execute` に渡された文を捕捉しつつ、指定結果を順に返す。"""
    captured = []
    queue = list(results)

    async def _execute(stmt, *args, **kwargs):
        captured.append(stmt)
        if queue:
            item = queue.pop(0)
            return item() if callable(item) else item
        return MockResult()

    mock_db.execute = AsyncMock(side_effect=_execute)
    return captured


def sql_text(stmt) -> str:
    if isinstance(stmt, TextClause):
        return str(stmt)
    return str(
        stmt.compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )


def where_clause(sql: str) -> str:
    """SELECT 文の WHERE 以降だけを返す（SELECT 列の organization_id と区別する）。"""
    idx = sql.upper().find("WHERE")
    return sql[idx:] if idx >= 0 else ""


# ============================================
# synthetic model factories
# ============================================
def make_device(**kw) -> Device:
    data = dict(
        id=DEVICE_A,
        organization_id=ORG_A,
        project_id=None,
        site_id=None,
        name="テストデバイスA",
        device_type="gps_tracker",
        serial_number="SYN-001",
        firmware_version="1.0",
        status="online",
        battery_level=80,
        location=None,
        metadata_={},
        last_seen_at=NOW,
        registered_at=NOW,
        updated_at=NOW,
    )
    data.update(kw)
    return Device(**data)


def make_sensor(**kw) -> Sensor:
    data = dict(
        id=SENSOR_A,
        device_id=DEVICE_A,
        name="テストセンサーA",
        sensor_type="temperature",
        unit="℃",
        min_value=-10.0,
        max_value=50.0,
        is_active=True,
        metadata_={},
        created_at=NOW,
    )
    data.update(kw)
    return Sensor(**data)


def make_rule(**kw) -> AlertRule:
    data = dict(
        id=RULE_A,
        organization_id=ORG_A,
        device_id=DEVICE_A,
        sensor_id=None,
        name="テストルールA",
        metric_name="temperature",
        condition="gt",
        threshold=30.0,
        severity="warning",
        is_active=True,
        cooldown_minutes=5,
        notification_channels=["in_app"],
        created_at=NOW,
    )
    data.update(kw)
    return AlertRule(**data)


def make_alert(**kw) -> AlertHistory:
    data = dict(
        id=1,
        rule_id=RULE_A,
        device_id=DEVICE_A,
        sensor_id=None,
        metric_name="temperature",
        current_value=35.0,
        threshold=30.0,
        severity="warning",
        message="テストルールA: temperature が 35.0 となり、しきい値 30.0 を超えました",
        acknowledged_by=None,
        acknowledged_at=None,
        resolved_at=None,
        created_at=NOW,
    )
    data.update(kw)
    return AlertHistory(**data)


def make_telemetry(**kw) -> Telemetry:
    data = dict(
        id=1,
        device_id=DEVICE_A,
        sensor_id=SENSOR_A,
        metric_name="temperature",
        value=25.5,
        unit="℃",
        timestamp=NOW,
        metadata_={},
    )
    data.update(kw)
    return Telemetry(**data)
