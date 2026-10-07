"""品質テスト: IoT のテナント分離（Q1 権限境界 / Q2 データ分離）。

検証仮説:
  ① デバイス / テレメトリ / アラートの org 境界
     - 一覧がクエリ `organization_id` 依存で、省略時は全テナントか
     - 個別取得・更新・削除・子リソースに組織検査があるか
     - 作成時にボディの `organization_id` を保存していないか
  ③ `alert_history` に `organization_id` 列が無いことの影響（構造的に分離不能でないか）

期待値は仕様（トークンの `org` クレームがテナントの唯一の根拠）に基づく。
未修正の欠陥は xfail(strict=True)。修正されると XPASS→FAIL になり気付ける。
"""

import pytest

from src.models import AlertHistory
from tests.quality_helpers import (
    API,
    AUTH_HEADERS,
    DEVICE_A,
    DEVICE_B,
    M2M_HEADERS,
    ORG_A,
    ORG_B,
    SENSOR_A,
    MockResult,
    build_client,
    client,  # noqa: F401  (pytest fixture)
    client_no_auth,  # noqa: F401  (pytest fixture)
    make_device,
    make_rule,
    make_sensor,
    make_telemetry,
    mock_db,  # noqa: F401  (pytest fixture)
    record_execute,
    restore_api_bindings,  # noqa: F401  (autouse fixture)
    sql_text,
    where_clause,
)

DEVICES = f"{API}/devices"
TELEMETRY = f"{API}/telemetry"
START = "2026-05-01T00:00:00Z"
END = "2026-05-01T23:59:59Z"


class MockFetchRow:
    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)


# ============================================
# ①-a デバイス一覧の org 境界
# ============================================
class TestDeviceListTenantSource:
    def test_device_list_without_org_is_tenant_scoped(self, client, mock_db):
        captured = record_execute(mock_db, [MockResult(total=0), MockResult(items=[])])
        response = client.get(DEVICES, headers=AUTH_HEADERS)
        assert response.status_code == 200
        sql = where_clause(sql_text(captured[-1]))
        assert "organization_id" in sql, f"デバイス一覧がテナントで絞られていない: {sql!r}"

    def test_device_list_honors_token_org_not_query_org(self, client, mock_db):
        captured = record_execute(mock_db, [MockResult(total=0), MockResult(items=[])])
        response = client.get(
            f"{DEVICES}?organization_id={ORG_B}", headers=AUTH_HEADERS
        )
        assert response.status_code == 200
        sql = where_clause(sql_text(captured[-1]))
        assert str(ORG_B) not in sql, (
            f"クエリ指定の他テナント {ORG_B} で絞られた: {sql!r}"
        )
        assert str(ORG_A) in sql


# ============================================
# ①-b デバイス個別 CRUD の org 境界
# ============================================
class TestDeviceDetailTenantBoundary:
    def test_get_device_other_tenant_rejected(self, client, mock_db):
        record_execute(mock_db, [MockResult(scalar=make_device(organization_id=ORG_B))])
        response = client.get(f"{DEVICES}/{DEVICE_B}", headers=AUTH_HEADERS)
        assert response.status_code == 404, (
            f"他テナント {ORG_B} のデバイスを {response.status_code} で返した"
        )

    @pytest.mark.xfail(
        strict=True, reason="DEF-02b: PUT /devices/{id} に組織検査がなく他テナントを更新する"
    )
    def test_update_device_other_tenant_rejected(self, client, mock_db):
        record_execute(mock_db, [MockResult(scalar=make_device(organization_id=ORG_B))])
        response = client.put(
            f"{DEVICES}/{DEVICE_B}", json={"name": "改ざんデバイス"}, headers=AUTH_HEADERS
        )
        assert response.status_code == 404, (
            f"他テナント {ORG_B} のデバイスを {response.status_code} で更新した"
        )

    @pytest.mark.xfail(
        strict=True,
        reason="DEF-02c: DELETE /devices/{id} に組織検査がなく他テナントを削除する",
    )
    def test_delete_device_other_tenant_rejected(self, client, mock_db):
        record_execute(mock_db, [MockResult(scalar=make_device(organization_id=ORG_B))])
        response = client.delete(f"{DEVICES}/{DEVICE_B}", headers=AUTH_HEADERS)
        assert response.status_code == 404, (
            f"他テナント {ORG_B} のデバイスを {response.status_code} で削除した"
        )
        assert mock_db.delete.await_count == 0

    @pytest.mark.xfail(
        strict=True,
        reason="DEF-03a: POST /devices がボディの organization_id をそのまま保存する",
    )
    def test_create_device_uses_token_org(self, client, mock_db):
        response = client.post(
            DEVICES,
            json={
                "organization_id": str(ORG_B),
                "name": "テストデバイスA",
                "device_type": "gps_tracker",
            },
            headers=AUTH_HEADERS,
        )
        assert response.status_code == 201
        created = mock_db.add.call_args[0][0]
        assert created.organization_id == ORG_A, (
            f"ボディの他テナント {ORG_B} が保存された: {created.organization_id}"
        )


# ============================================
# ①-c 子リソース（sensors）の org 境界
# ============================================
class TestDeviceChildTenantBoundary:
    @pytest.mark.xfail(
        strict=True,
        reason="DEF-04a: GET /devices/{id}/sensors に組織検査がなく他テナントのセンサーを返す",
    )
    def test_list_sensors_other_tenant_rejected(self, client, mock_db):
        foreign = make_sensor(device_id=DEVICE_B, name="他テナントセンサー")
        record_execute(mock_db, [MockResult(items=[foreign])])
        response = client.get(f"{DEVICES}/{DEVICE_B}/sensors", headers=AUTH_HEADERS)
        assert response.status_code == 404, (
            f"他テナント {ORG_B} のセンサーを {response.status_code} で返した"
        )

    @pytest.mark.xfail(
        strict=True,
        reason="DEF-04b: POST /devices/{id}/sensors に組織検査がなく他テナントへ追加できる",
    )
    def test_add_sensor_other_tenant_rejected(self, client, mock_db):
        record_execute(mock_db, [MockResult(scalar=make_device(organization_id=ORG_B))])
        response = client.post(
            f"{DEVICES}/{DEVICE_B}/sensors",
            json={"name": "テストセンサーA", "sensor_type": "temperature", "unit": "℃"},
            headers=AUTH_HEADERS,
        )
        assert response.status_code == 404, (
            f"他テナント {ORG_B} のデバイスへ {response.status_code} でセンサー追加した"
        )


# ============================================
# ①-d アラートルールの org 境界
# ============================================
class TestAlertRuleTenantSource:
    @pytest.mark.xfail(
        strict=True,
        reason="DEF-05a: GET /alert-rules が organization_id 省略時に全テナントを返す",
    )
    def test_alert_rule_list_without_org_is_tenant_scoped(self, client, mock_db):
        captured = record_execute(mock_db, [MockResult(items=[])])
        response = client.get(f"{API}/alert-rules", headers=AUTH_HEADERS)
        assert response.status_code == 200
        sql = where_clause(sql_text(captured[-1]))
        assert "organization_id" in sql, (
            f"アラートルール一覧がテナントで絞られていない: {sql!r}"
        )

    @pytest.mark.xfail(
        strict=True,
        reason="DEF-05b: GET /alert-rules がクエリ指定の他テナント組織を信頼する",
    )
    def test_alert_rule_list_honors_token_org(self, client, mock_db):
        captured = record_execute(mock_db, [MockResult(items=[])])
        response = client.get(
            f"{API}/alert-rules?organization_id={ORG_B}", headers=AUTH_HEADERS
        )
        assert response.status_code == 200
        sql = where_clause(sql_text(captured[-1]))
        assert str(ORG_B) not in sql, f"クエリ指定の {ORG_B} で絞られた: {sql!r}"
        assert str(ORG_A) in sql

    @pytest.mark.xfail(
        strict=True,
        reason="DEF-05c: POST /alert-rules がボディの organization_id をそのまま保存する",
    )
    def test_create_alert_rule_uses_token_org(self, client, mock_db):
        response = client.post(
            f"{API}/alert-rules",
            json={
                "organization_id": str(ORG_B),
                "name": "テストルールA",
                "metric_name": "temperature",
                "condition": "gt",
                "threshold": 30.0,
            },
            headers=AUTH_HEADERS,
        )
        assert response.status_code == 201
        created = mock_db.add.call_args[0][0]
        assert created.organization_id == ORG_A, (
            f"ボディの他テナント {ORG_B} が保存された: {created.organization_id}"
        )


# ============================================
# ③ アラート履歴の構造的テナント分離不能
# ============================================
class TestAlertHistoryStructuralGap:
    def test_alert_history_model_has_no_organization_column(self):
        """構造証跡: alert_history に組織列が無く、SQL 単体では org 分離できない。

        この PASS は欠陥の不存在を意味しない（欠陥は下の xfail で示す）。
        """
        assert "organization_id" not in AlertHistory.__table__.columns
        assert "resolved_by" not in AlertHistory.__table__.columns

    @pytest.mark.xfail(
        strict=True,
        reason="DEF-06a: GET /alerts が organization_id を受け取らず全テナントを返す（構造的に分離不能）",
    )
    def test_alert_list_is_tenant_scoped(self, client, mock_db):
        captured = record_execute(mock_db, [MockResult(total=0), MockResult(items=[])])
        response = client.get(
            f"{API}/alerts?organization_id={ORG_B}", headers=AUTH_HEADERS
        )
        assert response.status_code == 200
        sql = where_clause(sql_text(captured[-1]))
        assert "organization_id" in sql, (
            f"アラート履歴がテナントで絞られていない: {sql!r}"
        )

    @pytest.mark.xfail(
        strict=True,
        reason="DEF-06b: device_id が NULL のグローバルルールが他テナントのデバイスにも適用される",
    )
    async def test_global_rule_from_other_org_not_applied(self, mock_db):
        from src.services.alert_service import check_alert_rules

        foreign_rule = make_rule(
            organization_id=ORG_B, device_id=None, condition="gt", threshold=30.0
        )
        record_execute(mock_db, [MockResult(items=[foreign_rule]), MockResult(scalar=None)])

        created = await check_alert_rules(
            mock_db, device_id=DEVICE_A, metric_name="temperature", value=35.0
        )
        assert created == [], (
            f"他テナント {ORG_B} のグローバルルールでアラートが生成された: {created}"
        )
        assert not mock_db.add.called

    @pytest.mark.xfail(
        strict=True,
        reason="DEF-06c: アラートルール評価クエリが organization_id で絞られていない",
    )
    async def test_alert_rule_evaluation_query_is_tenant_scoped(self, mock_db):
        from src.services.alert_service import check_alert_rules

        record_execute(mock_db, [MockResult(items=[]), MockResult(scalar=None)])
        await check_alert_rules(
            mock_db, device_id=DEVICE_A, metric_name="temperature", value=35.0
        )
        sql = where_clause(sql_text(mock_db.execute.call_args_list[0][0][0]))
        assert "organization_id" in sql, (
            f"ルール評価がテナントで絞られていない: {sql!r}"
        )


# ============================================
# ①-e テレメトリの org 境界
# ============================================
class TestTelemetryTenantBoundary:
    @pytest.mark.xfail(
        strict=True,
        reason="DEF-07a: GET /telemetry/{device_id} に組織検査がなく他テナントの計測値を返す",
    )
    def test_query_telemetry_other_tenant_rejected(self, client, mock_db):
        foreign = make_telemetry(device_id=DEVICE_B, value=99.9)
        record_execute(mock_db, [MockResult(items=[foreign])])
        response = client.get(
            f"{TELEMETRY}/{DEVICE_B}?start_time={START}&end_time={END}",
            headers=AUTH_HEADERS,
        )
        assert response.status_code == 404, (
            f"他テナント {ORG_B} のテレメトリを {response.status_code} で返した"
        )

    @pytest.mark.xfail(
        strict=True,
        reason="DEF-07b: GET /telemetry/{device_id}/latest に組織検査がない",
    )
    def test_latest_telemetry_other_tenant_rejected(self, client, mock_db):
        row = MockFetchRow(
            sensor_id=SENSOR_A,
            metric_name="temperature",
            value=99.9,
            unit="℃",
            timestamp="2026-05-01T00:00:00+00:00",
        )
        record_execute(mock_db, [MockResult(rows=[row])])
        response = client.get(f"{TELEMETRY}/{DEVICE_B}/latest", headers=AUTH_HEADERS)
        assert response.status_code == 404, (
            f"他テナント {ORG_B} の最新値を {response.status_code} で返した"
        )

    @pytest.mark.xfail(
        strict=True,
        reason="DEF-07c: POST /telemetry/ingest がデバイス所有組織を検証せず他テナントへ書込める",
    )
    def test_ingest_rejects_foreign_device(self, client, mock_db):
        response = client.post(
            f"{TELEMETRY}/ingest",
            json={
                "data": [
                    {
                        "device_id": str(DEVICE_B),
                        "metric_name": "temperature",
                        "value": 25.5,
                        "unit": "℃",
                    }
                ]
            },
            headers=M2M_HEADERS,
        )
        assert response.status_code in (403, 404), (
            f"他テナント {ORG_B} のデバイスへ {response.status_code} で取り込んだ"
        )

    def test_ingest_accepts_own_device(self, client, mock_db):
        """正の対照: 自テナントのデバイスへの投入は 202。"""
        response = client.post(
            f"{TELEMETRY}/ingest",
            json={
                "data": [
                    {
                        "device_id": str(DEVICE_A),
                        "metric_name": "temperature",
                        "value": 25.5,
                        "unit": "℃",
                    }
                ]
            },
            headers=M2M_HEADERS,
        )
        assert response.status_code == 202
        assert response.json()["data"]["ingested"] == 1


# ============================================
# stub エンドポイントの org 非分離（構造証跡）
# ============================================
class TestStubEndpointsTenantGap:
    def test_machines_return_identical_data_for_two_tenants(self, mock_db):
        """構造証跡: machines は org 概念がなく、2テナントで同一応答（実データ化時に漏えい）。"""
        _appA, client_a = build_client(mock_db, org=ORG_A)
        _appB, client_b = build_client(mock_db, org=ORG_B)
        body_a = client_a.get(f"{API}/machines", headers=AUTH_HEADERS).json()
        body_b = client_b.get(f"{API}/machines", headers=AUTH_HEADERS).json()
        assert body_a == body_b
        assert body_a["total"] > 0

    def test_standalone_sensors_return_identical_data_for_two_tenants(self, mock_db):
        """構造証跡: /sensors（stub）も 2テナントで同一応答。"""
        _appA, client_a = build_client(mock_db, org=ORG_A)
        _appB, client_b = build_client(mock_db, org=ORG_B)
        body_a = client_a.get(f"{API}/sensors", headers=AUTH_HEADERS).json()
        body_b = client_b.get(f"{API}/sensors", headers=AUTH_HEADERS).json()
        assert body_a == body_b
        assert body_a["total"] > 0


# ============================================
# 未認証アクセス（Q1）
# ============================================
class TestAuthRequiredQuality:
    @pytest.mark.parametrize(
        "method,path",
        [
            ("get", DEVICES),
            ("get", f"{API}/alert-rules"),
            ("get", f"{API}/alerts"),
            ("get", f"{API}/machines"),
            ("get", f"{TELEMETRY}/{DEVICE_A}?start_time={START}&end_time={END}"),
        ],
    )
    def test_reads_require_auth(self, client_no_auth, method, path):
        response = getattr(client_no_auth, method)(path)
        assert response.status_code == 401

    def test_acknowledge_requires_auth(self, client_no_auth):
        response = client_no_auth.post(f"{API}/alerts/1/acknowledge")
        assert response.status_code == 401

    def test_ingest_requires_auth(self, client_no_auth):
        response = client_no_auth.post(f"{TELEMETRY}/ingest", json={"data": []})
        assert response.status_code == 401
