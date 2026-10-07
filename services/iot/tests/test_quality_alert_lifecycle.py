"""品質テスト: アラートのライフサイクル（Q6/Q8）・テレメトリ境界（Q3/Q4/Q8）・
heartbeat 冪等性（Q8）・閾値比較（Q3/Q6）。

検証仮説:
  ② acknowledge → resolve の状態遷移（未 ack での resolve、二重 ack、解決済みへの再操作）
  ④ テレメトリの時刻範囲・単位・欠測の扱いと境界（start > end、未来時刻、巨大範囲）
  ⑤ heartbeat の再実行・重複（冪等性）
  ⑥ alert-rules の閾値比較の境界値（> と >=、等号）

未修正の欠陥は xfail(strict=True)。「要判断」の項目は現状動作を記録するテストとして残す。
"""

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from src.services.alert_service import _evaluate_condition, check_alert_rules
from tests.quality_helpers import (
    API,
    AUTH_HEADERS,
    M2M_HEADERS,
    ORG_A,
    ORG_B,
    MockResult,
    build_client,
    client,  # noqa: F401  (pytest fixture)
    client_no_auth,  # noqa: F401  (pytest fixture)
    make_alert,
    make_device,
    make_rule,
    mock_db,  # noqa: F401  (pytest fixture)
    record_execute,
    restore_api_bindings,  # noqa: F401  (autouse fixture)
    sql_text,
    USER_A,
    USER_B,
    DEVICE_A,
    DEVICE_B,
)

ALERTS = f"{API}/alerts"
TELEMETRY = f"{API}/telemetry"
DEVICES = f"{API}/devices"
OLD = datetime(2026, 1, 1, tzinfo=timezone.utc)
START = "2026-05-01T00:00:00Z"
END = "2026-05-01T23:59:59Z"


# ============================================
# ② acknowledge → resolve の状態遷移
# ============================================
class TestAlertLifecycle:
    def test_acknowledge_records_token_identity(self, client, mock_db):
        """正の対照: 確認者はトークン由来で記録される。"""
        alert = make_alert(acknowledged_by=None, acknowledged_at=None)
        record_execute(mock_db, [MockResult(scalar=alert)])
        response = client.post(f"{ALERTS}/1/acknowledge", headers=AUTH_HEADERS)
        assert response.status_code == 200
        assert alert.acknowledged_by == USER_A
        assert alert.acknowledged_at is not None

    def test_acknowledge_not_found_returns_404(self, client, mock_db):
        record_execute(mock_db, [MockResult(scalar=None)])
        response = client.post(f"{ALERTS}/999/acknowledge", headers=AUTH_HEADERS)
        assert response.status_code == 404

    def test_resolve_requires_acknowledge(self, client, mock_db):
        alert = make_alert(acknowledged_at=None, resolved_at=None)
        record_execute(mock_db, [MockResult(scalar=alert)])
        response = client.post(f"{ALERTS}/1/resolve", headers=AUTH_HEADERS)
        assert response.status_code in (400, 409), (
            f"未確認のアラートが {response.status_code} で解決された"
        )
        assert alert.resolved_at is None

    def test_second_acknowledge_does_not_overwrite_first_actor(self, client, mock_db):
        alert = make_alert(acknowledged_by=USER_B, acknowledged_at=OLD)
        record_execute(mock_db, [MockResult(scalar=alert)])
        response = client.post(f"{ALERTS}/1/acknowledge", headers=AUTH_HEADERS)
        assert response.status_code in (200, 409)
        assert alert.acknowledged_by == USER_B, (
            f"先の確認者 {USER_B} が {alert.acknowledged_by} に上書きされた"
        )
        assert alert.acknowledged_at == OLD

    def test_resolve_is_idempotent(self, client, mock_db):
        alert = make_alert(acknowledged_at=OLD, resolved_at=OLD)
        record_execute(mock_db, [MockResult(scalar=alert)])
        response = client.post(f"{ALERTS}/1/resolve", headers=AUTH_HEADERS)
        assert response.status_code in (200, 409)
        assert alert.resolved_at == OLD, (
            f"解決済みの resolved_at が {alert.resolved_at} に上書きされた"
        )

    def test_acknowledge_after_resolve_rejected(self, client, mock_db):
        alert = make_alert(acknowledged_at=None, resolved_at=OLD)
        record_execute(mock_db, [MockResult(scalar=alert)])
        response = client.post(f"{ALERTS}/1/acknowledge", headers=AUTH_HEADERS)
        assert response.status_code in (400, 409), (
            f"解決済みアラートを {response.status_code} で確認できた"
        )

    def test_acknowledge_with_invalid_identity_returns_4xx(self, mock_db):
        alert = make_alert()
        record_execute(mock_db, [MockResult(scalar=alert)])
        app, _ = build_client(mock_db, sub="not-a-uuid")
        # 汎用 Exception ハンドラは例外を再送出するため 500 を観測する
        safe_client = TestClient(app, raise_server_exceptions=False)
        response = safe_client.post(f"{ALERTS}/1/acknowledge", headers=AUTH_HEADERS)
        assert response.status_code in (401, 403), (
            f"不正な利用者IDが {response.status_code} になった"
        )

    def test_resolve_records_no_resolver_identity(self, client, mock_db):
        """構造証跡: resolve は実行者を記録しない（resolved_by 列が存在しない）。"""
        from src.models import AlertHistory

        assert "resolved_by" not in AlertHistory.__table__.columns
        alert = make_alert(acknowledged_at=OLD, resolved_at=None)
        record_execute(mock_db, [MockResult(scalar=alert)])
        response = client.post(f"{ALERTS}/1/resolve", headers=AUTH_HEADERS)
        assert response.status_code == 200
        assert not hasattr(alert, "resolved_by") or getattr(alert, "resolved_by", None) is None


# ============================================
# ④ テレメトリの時刻範囲・単位・欠測
# ============================================
class TestTelemetryBoundaries:
    def test_start_after_end_is_rejected(self, client, mock_db):
        record_execute(mock_db, [MockResult(items=[])])
        response = client.get(
            f"{TELEMETRY}/{DEVICE_A}"
            "?start_time=2026-05-02T00:00:00Z&end_time=2026-05-01T00:00:00Z",
            headers=AUTH_HEADERS,
        )
        assert response.status_code == 422, (
            f"start > end が {response.status_code} で受理された"
        )

    def test_time_range_is_inclusive_bounds(self, client, mock_db):
        """正の対照: 範囲は両端を含む（>= start AND <= end）。"""
        captured = record_execute(
            mock_db, [MockResult(scalar=make_device()), MockResult(items=[])]
        )
        response = client.get(
            f"{TELEMETRY}/{DEVICE_A}?start_time={START}&end_time={END}",
            headers=AUTH_HEADERS,
        )
        assert response.status_code == 200
        sql = sql_text(captured[-1])
        assert ">=" in sql and "<=" in sql, f"範囲が両端包含でない: {sql!r}"

    def test_limit_bounds_are_validated(self, client, mock_db):
        record_execute(mock_db, [MockResult(items=[])])
        low = client.get(
            f"{TELEMETRY}/{DEVICE_A}?start_time={START}&end_time={END}&limit=0",
            headers=AUTH_HEADERS,
        )
        record_execute(mock_db, [MockResult(items=[])])
        high = client.get(
            f"{TELEMETRY}/{DEVICE_A}?start_time={START}&end_time={END}&limit=10001",
            headers=AUTH_HEADERS,
        )
        assert low.status_code == 422
        assert high.status_code == 422

    def test_huge_time_range_is_accepted(self, client, mock_db):
        """現状記録（要判断）: 期間上限の検証がなく 1970→2999 も受理される。"""
        record_execute(
            mock_db, [MockResult(scalar=make_device()), MockResult(items=[])]
        )
        response = client.get(
            f"{TELEMETRY}/{DEVICE_A}"
            "?start_time=1970-01-01T00:00:00Z&end_time=2999-12-31T00:00:00Z",
            headers=AUTH_HEADERS,
        )
        assert response.status_code == 200

    def test_naive_datetime_is_accepted(self, client, mock_db):
        """現状記録（要判断）: タイムゾーン無しの時刻がそのまま受理される。"""
        record_execute(
            mock_db, [MockResult(scalar=make_device()), MockResult(items=[])]
        )
        response = client.get(
            f"{TELEMETRY}/{DEVICE_A}"
            "?start_time=2026-05-01T00:00:00&end_time=2026-05-02T00:00:00",
            headers=AUTH_HEADERS,
        )
        assert response.status_code == 200

    def test_ingest_accepts_missing_unit(self, client, mock_db):
        """現状記録（要判断）: 単位なしの計測値が受理される（Q4 単位表記）。"""
        record_execute(mock_db, [MockResult(scalar=make_device())])
        response = client.post(
            f"{TELEMETRY}/ingest",
            json={"data": [{"device_id": str(DEVICE_A), "metric_name": "temperature", "value": 25.5}]},
            headers=M2M_HEADERS,
        )
        assert response.status_code == 202
        assert response.json()["data"]["ingested"] == 1

    def test_ingest_accepts_future_timestamp(self, client, mock_db):
        """現状記録（要判断）: 未来時刻の計測値がそのまま受理される。"""
        record_execute(mock_db, [MockResult(scalar=make_device())])
        response = client.post(
            f"{TELEMETRY}/ingest",
            json={
                "data": [
                    {
                        "device_id": str(DEVICE_A),
                        "metric_name": "temperature",
                        "value": 25.5,
                        "unit": "℃",
                        "timestamp": "2099-01-01T00:00:00Z",
                    }
                ]
            },
            headers=M2M_HEADERS,
        )
        assert response.status_code == 202

    def test_ingest_requires_value(self, client):
        """欠測: value が無い計測値は 422 で拒否される。"""
        response = client.post(
            f"{TELEMETRY}/ingest",
            json={"data": [{"device_id": str(DEVICE_A), "metric_name": "temperature"}]},
            headers=M2M_HEADERS,
        )
        assert response.status_code == 422


# ============================================
# ⑤ heartbeat の冪等性・状態遷移
# ============================================
class TestHeartbeatIdempotency:
    def test_heartbeat_is_idempotent_for_same_input(self, client, mock_db):
        device = make_device(status="offline", battery_level=50, last_seen_at=None)
        record_execute(
            mock_db, [MockResult(scalar=device), MockResult(scalar=device)]
        )
        first = client.post(
            f"{DEVICES}/{DEVICE_A}/heartbeat",
            json={"battery_level": 50},
            headers=M2M_HEADERS,
        )
        state_after_first = (device.status, device.battery_level)
        second = client.post(
            f"{DEVICES}/{DEVICE_A}/heartbeat",
            json={"battery_level": 50},
            headers=M2M_HEADERS,
        )
        assert first.status_code == 200
        assert second.status_code == 200
        assert (device.status, device.battery_level) == state_after_first
        assert device.status == "online"
        assert device.last_seen_at is not None

    def test_heartbeat_does_not_resurrect_retired_device(self, client, mock_db):
        device = make_device(status="retired")
        record_execute(mock_db, [MockResult(scalar=device)])
        response = client.post(
            f"{DEVICES}/{DEVICE_A}/heartbeat", json={}, headers=M2M_HEADERS
        )
        assert device.status == "retired", (
            f"retired が {device.status} に変わった（{response.status_code}）"
        )

    def test_heartbeat_rejects_out_of_range_battery(self, client, mock_db):
        device = make_device()
        record_execute(mock_db, [MockResult(scalar=device)])
        response = client.post(
            f"{DEVICES}/{DEVICE_A}/heartbeat",
            json={"battery_level": 150},
            headers=M2M_HEADERS,
        )
        assert response.status_code == 422, (
            f"範囲外の battery_level が {response.status_code} で受理された"
        )

    def test_heartbeat_other_tenant_device_rejected(self, client, mock_db):
        device = make_device(organization_id=ORG_B)
        record_execute(mock_db, [MockResult(scalar=device)])
        response = client.post(
            f"{DEVICES}/{DEVICE_B}/heartbeat",
            json={"battery_level": 10},
            headers=M2M_HEADERS,
        )
        assert response.status_code == 404, (
            f"他テナント {ORG_B} のデバイスを {response.status_code} で更新した"
        )
        assert device.battery_level != 10

    def test_heartbeat_requires_auth(self, client_no_auth):
        response = client_no_auth.post(
            f"{DEVICES}/{DEVICE_A}/heartbeat", json={"battery_level": 50}
        )
        assert response.status_code == 401


# ============================================
# ⑥ 閾値比較の境界
# ============================================
class TestAlertThresholdBoundaries:
    @pytest.mark.parametrize(
        "condition,value,threshold,expected",
        [
            ("gt", 30.0, 30.0, False),
            ("gte", 30.0, 30.0, True),
            ("lt", 30.0, 30.0, False),
            ("lte", 30.0, 30.0, True),
            ("eq", 30.0, 30.0, True),
            ("gt", 30.0000001, 30.0, True),
            ("lte", 30.0000001, 30.0, False),
        ],
    )
    def test_equality_boundary(self, condition, value, threshold, expected):
        assert _evaluate_condition(condition, value, threshold) is expected

    def test_unknown_condition_does_not_trigger(self):
        assert _evaluate_condition("between", 30.0, 30.0) is False

    def test_nan_never_triggers(self):
        nan = float("nan")
        for condition in ("gt", "lt", "gte", "lte", "eq"):
            assert _evaluate_condition(condition, nan, 30.0) is False

    def test_float_equality_is_not_exact(self):
        """現状記録（要判断）: eq は浮動小数の厳密比較のため 0.1+0.2 != 0.3。"""
        assert _evaluate_condition("eq", 0.1 + 0.2, 0.3) is False

    def test_infinity_triggers_gt(self):
        """現状記録（要判断）: inf の投入が許容され gt が成立する。"""
        assert _evaluate_condition("gt", float("inf"), 30.0) is True

    async def test_check_alert_rules_creates_alert_at_gte_boundary(self, mock_db):
        rule = make_rule(condition="gte", threshold=30.0)
        record_execute(mock_db, [MockResult(items=[rule]), MockResult(scalar=None)])
        created = await check_alert_rules(
            mock_db, device_id=DEVICE_A, metric_name="temperature", value=30.0
        )
        assert len(created) == 1
        assert created[0].threshold == 30.0
        assert created[0].current_value == 30.0

    async def test_check_alert_rules_does_not_trigger_below_gt(self, mock_db):
        rule = make_rule(condition="gt", threshold=30.0)
        record_execute(mock_db, [MockResult(items=[rule]), MockResult(scalar=None)])
        created = await check_alert_rules(
            mock_db, device_id=DEVICE_A, metric_name="temperature", value=30.0
        )
        assert created == []

    async def test_cooldown_boundary_suppresses_at_exact_elapsed(self, mock_db):
        """境界記録: created_at >= (now - cooldown) は「最近」とみなされ抑止される。"""
        rule = make_rule(condition="gt", threshold=30.0, cooldown_minutes=5)
        recent = make_alert()
        record_execute(mock_db, [MockResult(items=[rule]), MockResult(scalar=recent)])
        created = await check_alert_rules(
            mock_db, device_id=DEVICE_A, metric_name="temperature", value=35.0
        )
        assert created == []

    def test_alert_rule_condition_is_validated_by_api(self, client, mock_db):
        response = client.post(
            f"{API}/alert-rules",
            json={
                "organization_id": str(ORG_A),
                "name": "テストルールA",
                "metric_name": "temperature",
                "condition": "between",
                "threshold": 30.0,
            },
            headers=AUTH_HEADERS,
        )
        assert response.status_code == 422
