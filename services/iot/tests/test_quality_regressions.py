"""品質回帰テスト: ADR-0004 テナント分離に加えて保持する欠陥修正の回帰。

- アラート状態遷移: 未確認 resolve 禁止 / 二重 ack 非上書き / resolve 冪等 / 解決済みへの ack 禁止
- トークン sub が UUID でない場合に 500 にならない
- battery_level の範囲検証（0-100）
- start_time > end_time の 422
- retired デバイスを heartbeat で復帰させない
"""

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from src.main import create_app
from src.middleware.auth import TokenData, get_current_user
from src.models.base import get_db
from src.schemas import DeviceHeartbeatRequest, DeviceUpdateRequest
from src.services import alert_service, device_service
from src.services.alert_service import AlertStateError

AUTH = {"Authorization": "Bearer mock-token"}


def _alert(**overrides):
    alert = MagicMock()
    alert.id = 1
    alert.acknowledged_by = None
    alert.acknowledged_at = None
    alert.resolved_at = None
    for key, value in overrides.items():
        setattr(alert, key, value)
    return alert


def _db(return_value):
    db = AsyncMock()
    db.execute = AsyncMock(
        return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=return_value))
    )
    db.flush = AsyncMock()
    return db


def _client(user: TokenData) -> TestClient:
    app = create_app()
    db = AsyncMock()

    async def _get_db():
        yield db

    async def _current_user():
        return user

    app.dependency_overrides[get_db] = _get_db
    app.dependency_overrides[get_current_user] = _current_user
    return TestClient(app)


def _user(
    sub: str = str(uuid.uuid4()),
    org: str = str(uuid.uuid4()),
    roles: list[str] | None = None,
) -> TokenData:
    return TokenData(
        sub=sub,
        type="user",
        org=org,
        roles=roles if roles is not None else ["site_manager"],
    )


# ── alert state machine ──────────────────────────────────────


@pytest.mark.asyncio
async def test_resolve_requires_acknowledge():
    alert = _alert(acknowledged_at=None, resolved_at=None)
    with pytest.raises(AlertStateError):
        await alert_service.resolve_alert(_db(alert), 1)
    assert alert.resolved_at is None


@pytest.mark.asyncio
async def test_second_acknowledge_does_not_overwrite_first_actor():
    old = datetime(2026, 1, 1, tzinfo=timezone.utc)
    first = uuid.uuid4()
    alert = _alert(acknowledged_by=first, acknowledged_at=old)
    result = await alert_service.acknowledge_alert(_db(alert), 1, uuid.uuid4())
    assert result is alert
    assert alert.acknowledged_by == first
    assert alert.acknowledged_at == old


@pytest.mark.asyncio
async def test_resolve_is_idempotent():
    old = datetime(2026, 1, 1, tzinfo=timezone.utc)
    alert = _alert(acknowledged_at=old, resolved_at=old)
    result = await alert_service.resolve_alert(_db(alert), 1)
    assert result is alert
    assert alert.resolved_at == old


@pytest.mark.asyncio
async def test_acknowledge_after_resolve_is_rejected():
    old = datetime(2026, 1, 1, tzinfo=timezone.utc)
    alert = _alert(acknowledged_at=None, resolved_at=old)
    with pytest.raises(AlertStateError):
        await alert_service.acknowledge_alert(_db(alert), 1, uuid.uuid4())


@pytest.mark.asyncio
async def test_heartbeat_does_not_resurrect_retired_device():
    device = MagicMock()
    device.status = "retired"
    await device_service.device_heartbeat(_db(device), uuid.uuid4(), {}, uuid.uuid4())
    assert device.status == "retired"


# ── API-level boundary validation ─────────────────────────────


def test_acknowledge_with_invalid_sub_returns_403():
    client = _client(_user(sub="not-a-uuid"))
    resp = client.post("/api/v1/iot/alerts/1/acknowledge", headers=AUTH)
    assert resp.status_code == 403


@pytest.mark.parametrize(
    "path", ["/api/v1/iot/alerts/1/acknowledge", "/api/v1/iot/alerts/1/resolve"]
)
def test_alert_action_with_empty_roles_is_forbidden(path):
    client = _client(_user(roles=[]))
    resp = client.post(path, headers=AUTH)
    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "FORBIDDEN"


def test_telemetry_start_after_end_is_rejected():
    client = _client(_user())
    resp = client.get(
        f"/api/v1/iot/telemetry/{uuid.uuid4()}"
        "?start_time=2026-05-02T00:00:00Z&end_time=2026-05-01T00:00:00Z",
        headers=AUTH,
    )
    assert resp.status_code == 422


def test_battery_level_range_is_validated():
    with pytest.raises(ValidationError):
        DeviceHeartbeatRequest(battery_level=150)
    with pytest.raises(ValidationError):
        DeviceUpdateRequest(battery_level=-1)
