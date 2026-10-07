"""現場DX: 出来形数量・進捗率の計算/丸め・品質閾値・写真メタデータの品質テスト（観点 Q3 / Q4 / Q8）

仕様根拠
--------
* docs/architecture/01-auth-platform.md:28 行レベルセキュリティ（プロジェクト単位の参照制限）
* 出来形・品質の計算式そのものを規定したリポジトリ内資料は発見できていない。
  したがって「あるべき丸め桁・閾値」は断定せず、**計算が存在するか／入力検証があるか**のみを検証する。
  閾値の仕様は「未確認」として報告する（創作しない）。

本ファイルの方針
----------------
* ``test_defect_*`` は仕様準拠の期待値を assert する。失敗 = 実装欠陥。
* DB は mock。実 PostgreSQL・外部接続なし。fixture は synthetic のみ。
"""

import uuid
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from src.main import create_app
from src.middleware.auth import TokenData, get_current_user
from src.models.base import get_db

ORG_A = uuid.UUID("00000000-0000-0000-0000-0000000000aa")
PROJECT_A = uuid.UUID("00000000-0000-0000-0000-0000000000cc")
USER_SUB = "00000000-0000-0000-0000-0000000000dd"
_NOW = datetime(2026, 5, 24, 9, 0, 0, tzinfo=timezone.utc)


def _auto_refresh(obj):
    """mock DB の refresh をエミュレートし、サーバ既定値を埋める。"""
    if getattr(obj, "id", None) is None:
        obj.id = uuid.uuid4()
    for attr in ("created_at", "updated_at", "recorded_at"):
        if hasattr(obj, attr) and getattr(obj, attr) is None:
            setattr(obj, attr, _NOW)
    if hasattr(obj, "status") and getattr(obj, "status", None) is None:
        setattr(obj, "status", "pending")
    return obj


class _FakeResult:
    def __init__(self, items=None, total=0):
        self._items = list(items or [])
        self._total = total

    def scalar_one_or_none(self):
        return self._items[0] if self._items else None

    def scalar(self):
        return self._total

    def scalars(self):
        return self

    def all(self):
        return self._items

    def first(self):
        return self._items[0] if self._items else None


@pytest.fixture
def make_client():
    def _factory(*, items=None, total=0, raise_server_exceptions: bool = True):
        statements: list = []
        db = AsyncMock()
        db.add = MagicMock()
        db.delete = AsyncMock()
        db.commit = AsyncMock()
        db.rollback = AsyncMock()
        db.close = AsyncMock()
        db.flush = AsyncMock()

        async def _refresh(obj):
            _auto_refresh(obj)

        db.refresh = _refresh
        db.get = AsyncMock(return_value=None)

        async def _execute(statement, *args, **kwargs):
            statements.append(statement)
            return _FakeResult(items=items, total=total)

        db.execute = _execute

        app = create_app()

        async def _get_db():
            yield db

        async def _current_user():
            return TokenData(
                sub=USER_SUB, type="user", org=str(ORG_A), roles=["admin"]
            )

        app.dependency_overrides[get_db] = _get_db
        app.dependency_overrides[get_current_user] = _current_user
        return (
            TestClient(app, raise_server_exceptions=raise_server_exceptions),
            statements,
            db,
        )

    return _factory


def _progress(percent, status="in_progress"):
    from src.models import ProgressRecord

    return ProgressRecord(
        id=uuid.uuid4(),
        organization_id=ORG_A,
        project_id=PROJECT_A,
        activity_name="ダミー工",
        progress_percent=percent,
        status=status,
        recorded_by=uuid.uuid4(),
        recorded_at=_NOW,
        updated_at=_NOW,
    )


def _quality(is_conforming, status="passed"):
    from src.models import QualityCheck

    return QualityCheck(
        id=uuid.uuid4(),
        organization_id=ORG_A,
        project_id=PROJECT_A,
        check_item="ダミー検査",
        check_type="dummy",
        is_conforming=is_conforming,
        check_date=date(2026, 5, 24),
        inspector_id=uuid.uuid4(),
        status=status,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _progress_payload(**overrides):
    payload = {
        "organization_id": str(ORG_A),
        "project_id": str(PROJECT_A),
        "activity_name": "出来形ダミー工",
        "recorded_by": str(uuid.uuid4()),
    }
    payload.update(overrides)
    return payload


# =============================================================================
# 欠陥検出テスト（失敗 = 欠陥）
# =============================================================================
class TestCalculationAndBoundaryDefects:
    def test_defect_progress_percent_above_100_is_accepted(self, make_client):
        """DEF-FLD-18: 進捗率に上限検証が無く 100% 超を受け付ける。

        根拠: src/schemas/__init__.py:88（progress_percent: float | None = None、境界なし）
              src/api/progress.py:134-145
        期待: 422（0..100 の範囲外を拒否）。実際: 201 で受理。
        """
        client, _, _ = make_client()
        response = client.post(
            "/api/v1/field/progress",
            json=_progress_payload(progress_percent=150.0),
        )
        assert response.status_code == 422, (
            f"進捗率 150.0% を受理した（上限検証なし）: {response.status_code}"
        )

    def test_defect_progress_percent_negative_is_accepted(self, make_client):
        """DEF-FLD-19: 進捗率に下限検証が無く負値を受け付ける。

        根拠: src/schemas/__init__.py:88
        期待: 422。実際: 201。
        """
        client, _, _ = make_client()
        response = client.post(
            "/api/v1/field/progress",
            json=_progress_payload(progress_percent=-12.5),
        )
        assert response.status_code == 422, (
            f"進捗率 -12.5% を受理した（下限検証なし）: {response.status_code}"
        )

    def test_defect_progress_percent_is_not_derived_from_quantities(self, make_client):
        """DEF-FLD-20: 出来形数量から進捗率を算出していない（申告値の丸写し）。

        根拠: src/api/progress.py:139-145（body をそのまま保存）
              src/services/field_service.py:111-118（計算処理なし）
        期待: planned=100 / actual=50 のとき progress_percent が 50.0 に算出される。
        実際: 未指定なら None のまま保存され、数量との整合検証も無い。
        影響: 出来形数量と進捗率が独立に申告でき、出来高の正しさを担保できない。
        """
        client, _, db = make_client()
        response = client.post(
            "/api/v1/field/progress",
            json=_progress_payload(
                planned_quantity=100.0, actual_quantity=50.0, unit="m3"
            ),
        )
        assert response.status_code == 201
        saved = db.add.call_args[0][0]
        assert saved.progress_percent == pytest.approx(50.0), (
            f"数量から進捗率が算出されていない: progress_percent={saved.progress_percent}"
        )

    def test_defect_quality_conformance_is_client_declared(self, make_client):
        """DEF-FLD-21: 品質合否がクライアント申告で確定し、測定値・規格値との突合が無い。

        根拠: src/schemas/__init__.py:152-164（standard_value/measured_value は自由文字列、
              is_conforming はクライアントが与える bool）
              src/api/quality.py:116-122 → src/services/field_service.py:205-212
        期待: 合否の根拠（measured_value）が無いのに「適合」を主張する入力は 422。
        実際: 201。サーバ側に閾値ロジックは存在しない（ハードコード以前に未実装）。
        影響: 品質合否が改ざん可能な申告値になり、検査証跡の信頼性が失われる（Q6）。
        """
        client, _, _ = make_client()
        response = client.post(
            "/api/v1/field/quality",
            json={
                "organization_id": str(ORG_A),
                "project_id": str(PROJECT_A),
                "check_item": "圧縮強度",
                "check_type": "strength_test",
                "is_conforming": True,  # 測定値なしで「適合」
                "check_date": "2026-05-24",
                "inspector_id": str(uuid.uuid4()),
            },
        )
        assert response.status_code == 422, (
            f"測定値なしの『適合』申告を受理した: {response.status_code}"
        )

    def test_defect_undetermined_quality_check_lowers_conformance_rate(self, make_client):
        """DEF-FLD-22: 未判定(is_conforming=None)を分母に含め、適合率を過小算出する。

        根拠: src/services/field_service.py:277-289
              total_checks = len(checks) / conforming_count は is_conforming が真の件数のみ
              → conformance_rate = conforming / total * 100
        期待: 未判定は分母から除外（適合1・未判定1 → 100.0）。
        実際: 1/2*100 = 50.0。
        影響: 検査未完の現場で品質成績が過小評価される（Q3 計算再現性・Q8）。
        """
        client, _, _ = make_client(
            items=[_quality(True), _quality(None, status="pending")]
        )
        response = client.get(f"/api/v1/field/quality/{PROJECT_A}/stats")
        assert response.status_code == 200
        rate = response.json()["conformance_rate"]
        assert rate == pytest.approx(100.0), (
            f"未判定を含めた分母で適合率を算出: conformance_rate={rate} (期待 100.0)"
        )


# =============================================================================
# 検証済み（現状で仕様を満たす / 挙動を記録する）テスト
# =============================================================================
class TestCalculationVerified:
    def test_ok_summary_zero_records_has_no_zero_division(self, make_client):
        """記録0件でもゼロ除算せず overall_progress=0.0 を返す。"""
        client, _, _ = make_client(items=[])
        response = client.get(f"/api/v1/field/progress/{PROJECT_A}/summary")
        assert response.status_code == 200
        body = response.json()
        assert body["total_activities"] == 0
        assert body["overall_progress"] == 0.0

    def test_ok_summary_overall_progress_is_arithmetic_mean(self, make_client):
        """overall_progress = progress_percent の単純平均（100/50/0 → 50.0）。"""
        client, _, _ = make_client(
            items=[_progress(100.0, "completed"), _progress(50.0), _progress(0.0, "pending")]
        )
        response = client.get(f"/api/v1/field/progress/{PROJECT_A}/summary")
        body = response.json()
        assert body["overall_progress"] == pytest.approx(50.0)
        assert body["completed"] == 1
        assert body["pending"] == 1

    def test_ok_summary_is_deterministic(self, make_client):
        """同一入力 → 同一出力（決定性）。"""
        records = [_progress(33.3), _progress(66.7)]
        client, _, _ = make_client(items=records)
        first = client.get(f"/api/v1/field/progress/{PROJECT_A}/summary").json()
        second = client.get(f"/api/v1/field/progress/{PROJECT_A}/summary").json()
        assert first == second

    def test_ok_summary_null_progress_counted_as_zero_documented(self, make_client):
        """記録済み挙動: progress_percent=None は分母に含まれ 0 として平均される。

        100.0 と None → 100/2 = 50.0。仕様資料が無いため良否は断定しない（未確認）。
        """
        client, _, _ = make_client(items=[_progress(100.0), _progress(None)])
        body = client.get(f"/api/v1/field/progress/{PROJECT_A}/summary").json()
        assert body["total_activities"] == 2
        assert body["overall_progress"] == pytest.approx(50.0)

    def test_ok_quality_stats_zero_checks_has_no_zero_division(self, make_client):
        """品質チェック0件でもゼロ除算せず conformance_rate=0.0 を返す。"""
        client, _, _ = make_client(items=[])
        body = client.get(f"/api/v1/field/quality/{PROJECT_A}/stats").json()
        assert body["total_checks"] == 0
        assert body["conformance_rate"] == 0.0

    def test_ok_quality_stats_rate_has_no_explicit_rounding_documented(self, make_client):
        """記録済み挙動: 適合率に明示的な丸めが無く、生の浮動小数を返す。

        2/3*100 = 66.66666... を丸めずに返す。丸め桁の仕様資料は無いため未確認。
        """
        client, _, _ = make_client(
            items=[_quality(True), _quality(True), _quality(False, status="failed")]
        )
        body = client.get(f"/api/v1/field/quality/{PROJECT_A}/stats").json()
        assert body["conformance_rate"] == pytest.approx(200.0 / 3.0, rel=1e-12)
        assert body["passed"] == 2
        assert body["failed"] == 1

    def test_ok_summary_is_unitless_percentage_documented(self, make_client):
        """記録済み挙動: サマリは百分率のみで、数量の合計（単位混在の恐れ）は返さない。

        unit 混在による合計誤りは現状のレスポンスには存在しない。
        """
        client, _, _ = make_client(items=[_progress(100.0)])
        body = client.get(f"/api/v1/field/progress/{PROJECT_A}/summary").json()
        assert set(body) == {
            "project_id",
            "total_activities",
            "completed",
            "in_progress",
            "delayed",
            "pending",
            "overall_progress",
        }
        assert "unit" not in body


class TestPhotoMetadataGap:
    def test_ok_documented_gap_photos_read_only_no_position_or_time_validation(
        self, make_client
    ):
        """未実装の記録（欠陥ではなく未確認/Info）: 写真APIは読取専用 stub。

        根拠: src/api/photos.py:1（"現場写真 API — stub"）, :10-18（SitePhoto に入力面なし）
        撮影位置(緯度経度)・撮影時刻を受け取る書き込み経路が存在しないため、
        範囲外座標・未来時刻の検証は **検証不能（未実装）**。taken_at は固定文字列。
        """
        client, _, _ = make_client()
        response = client.get("/api/v1/field/photos")
        assert response.status_code == 200
        item = response.json()["items"][0]
        assert item["taken_at"] == "2024-05-20T08:30:45"
        assert "latitude" not in item and "longitude" not in item
        # 現在のAPI面（読取のみ）
        assert client.post("/api/v1/field/photos", json={}).status_code == 405
