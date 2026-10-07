"""安全管理: 状態遷移・証跡・集計・永続化の品質テスト（観点 Q6 / Q8 / Q3）

仕様根拠（リポジトリ内の参照実装）
----------------------------------
* services/workflow/src/api/cases.py:85 ``submitted_by=UUID(current_user.sub)``
  → 操作者（実行者）はトークンから導出し、body では指定できない。
* services/workflow/src/api/workflows.py:93-108 → 組織・ロールの検証を経て状態遷移させる。
* 巡視の状態遷移語彙（scheduled / in_progress / passed / failed 等）を定義した
  リポジトリ内資料は発見できなかった → **語彙・許容遷移は未確認**。したがって
  「どの遷移を禁じるか」は断定せず、**遷移ガードが存在しないこと**と
  **証跡が残らないこと**のみを欠陥として報告する。
* 点検スコアの値域（0..100）はスキーマで規定されている（src/schemas/__init__.py:39,47）。

本ファイルの方針
----------------
* ``test_defect_*`` は仕様準拠の期待値を assert する。失敗 = 実装欠陥。
* DB は mock。実 PostgreSQL・外部接続なし。fixture は synthetic のみ。
"""

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from src.main import create_app
from src.middleware.auth import TokenData, get_current_user
from src.models.base import get_db

ORG_A = uuid.UUID("00000000-0000-0000-0000-0000000000aa")
PROJECT_A = uuid.UUID("00000000-0000-0000-0000-0000000000e4")
USER_SUB = "00000000-0000-0000-0000-0000000000dd"
INSPECTOR_ORIGINAL = uuid.UUID("00000000-0000-0000-0000-0000000000cc")
INSPECTION_A = uuid.UUID("00000000-0000-0000-0000-0000000000e1")
HAZARD_A = uuid.UUID("00000000-0000-0000-0000-0000000000e2")
_NOW = datetime(2026, 5, 24, 9, 0, 0, tzinfo=timezone.utc)


def _sql(statement) -> str:
    try:
        return " ".join(str(statement.compile()).split())
    except Exception as exc:  # pragma: no cover - 診断用
        return f"<compile failed: {exc}>"




class _Unset:
    """scalar を明示的に None として渡すためのセンチネル。"""

    def __repr__(self):  # pragma: no cover - 診断用
        return "<UNSET>"


_UNSET = _Unset()

class _FakeResult:
    def __init__(self, items=None, scalar=_UNSET, total=0):
        self._items = list(items or [])
        self._scalar = scalar
        self._total = total

    def scalar_one_or_none(self):
        return self._items[0] if self._items else None

    def scalar(self):
        # scalar を明示指定した場合は None もそのまま返す（欠測の模擬）。
        return self._total if self._scalar is _UNSET else self._scalar

    def scalars(self):
        return self

    def all(self):
        return self._items

    def first(self):
        return self._items[0] if self._items else None


@pytest.fixture
def make_client():
    def _factory(
        *,
        items=None,
        results=None,
        raise_server_exceptions: bool = True,
        roles: tuple[str, ...] = ("safety_admin", "inspector"),
    ):
        statements: list = []
        db = AsyncMock()
        db.add = MagicMock()
        db.delete = AsyncMock()
        db.commit = AsyncMock()
        db.rollback = AsyncMock()
        db.close = AsyncMock()
        db.flush = AsyncMock()
        db.refresh = AsyncMock()

        async def _execute(statement, *args, **kwargs):
            statements.append(statement)
            if results:
                index = min(len(statements) - 1, len(results) - 1)
                spec = results[index]
                return _FakeResult(
                    items=spec.get("items"),
                    scalar=spec.get("scalar", _UNSET),
                    total=spec.get("total", 0),
                )
            return _FakeResult(items=items)

        db.execute = _execute

        app = create_app()

        async def _get_db():
            yield db

        async def _current_user():
            return TokenData(
                sub=USER_SUB, type="user", org=str(ORG_A),
                roles=list(roles),
            )

        app.dependency_overrides[get_db] = _get_db
        app.dependency_overrides[get_current_user] = _current_user
        return (
            TestClient(app, raise_server_exceptions=raise_server_exceptions),
            statements,
            db,
        )

    return _factory


def _inspection(status="scheduled", inspection_date=None, findings=None, score=None):
    from src.models import SafetyInspection

    return SafetyInspection(
        id=INSPECTION_A,
        organization_id=ORG_A,
        project_id=PROJECT_A,
        title="ダミー安全巡視",
        inspection_type="daily",
        status=status,
        inspector_id=INSPECTOR_ORIGINAL,
        inspection_date=inspection_date,
        location=None,
        findings=findings,
        corrective_actions=None,
        score=score,
        is_safe=None,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _hazard(status="reported"):
    from src.models import HazardReport

    return HazardReport(
        id=HAZARD_A,
        organization_id=ORG_A,
        project_id=PROJECT_A,
        title="ダミー危険予知",
        description="ダミー詳細",
        hazard_type="fall",
        risk_level="high",
        severity="severe",
        status=status,
        reported_by=INSPECTOR_ORIGINAL,
        created_at=_NOW,
    )


def _hazard_body(**overrides):
    body = {
        "organization_id": str(ORG_A),
        "title": "ダミー危険予知",
        "description": "ダミー詳細",
        "hazard_type": "fall",
        "risk_level": "high",
        "severity": "severe",
        "reported_by": str(INSPECTOR_ORIGINAL),
    }
    body.update(overrides)
    return body


# =============================================================================
# ④ 巡視 complete の実行者・実施日・証跡（欠陥検出テスト / 失敗 = 欠陥）
# =============================================================================
class TestInspectionCompleteDefects:
    def test_defect_complete_does_not_record_the_actor(self, make_client):
        """DEF-SAF-23: complete しても実施者(inspector_id)がトークン sub で記録されない。

        根拠: src/api/inspections.py:137-157（current_user を service へ渡していない）
              src/services/safety_service.py:117-135（inspector_id を更新しない）
              src/schemas/__init__.py:43-47（InspectionComplete に実施者・実施日の入力が無い）
        参照実装: workflow/src/api/cases.py:85 は操作者を ``UUID(current_user.sub)`` から導出。
        期待: 完了操作の実施者が inspector_id に記録される。
        実際: 作成時の inspector_id のまま（誰が完了させたかが残らない）。
        影響: 「誰が点検を完了させたか」の証跡が無い（Q6）。
        """
        inspection = _inspection(status="in_progress")
        client, _, _ = make_client(items=[inspection])
        response = client.post(
            f"/api/v1/safety/inspections/{INSPECTION_A}/complete",
            json={"is_safe": True, "findings": "異常なし", "score": 95},
        )
        assert response.status_code == 200
        assert str(inspection.inspector_id) == USER_SUB, (
            "完了操作の実施者が記録されていない: "
            f"inspector_id={inspection.inspector_id} (トークン sub={USER_SUB})"
        )

    def test_defect_complete_does_not_stamp_the_inspection_date(self, make_client):
        """DEF-SAF-24: complete しても実施日(inspection_date)が記録されない。

        根拠: src/services/safety_service.py:117-135（inspection_date を設定しない）
              src/api/inspections.py:56（作成時に None を許容）
        期待: 完了時点の実施日が未設定なら記録される。
        実際: inspection_date=None のまま完了し、応答も null。
        影響: 点検の実施日が証跡として残らない（Q6）。
        """
        inspection = _inspection(status="in_progress", inspection_date=None)
        client, _, _ = make_client(items=[inspection])
        response = client.post(
            f"/api/v1/safety/inspections/{INSPECTION_A}/complete",
            json={"is_safe": True, "score": 90},
        )
        assert response.status_code == 200
        assert response.json()["data"]["inspection_date"] is not None, (
            "完了後も実施日が未記録(null)のまま"
        )

    def test_defect_complete_can_be_repeated_and_reverses_the_result(self, make_client):
        """DEF-SAF-25: 二重 complete を拒否せず、確定済みの合否を巻き戻せる。

        根拠: src/services/safety_service.py:125-135（現在の status を一切検証しない）
              src/api/inspections.py:137-157（状態ガードなし）
        手順: status="passed" の巡視に対して is_safe=false で再度 complete。
        期待: 409/400（確定済みの再確定を拒否）。実際: 200 で "failed" に上書き。
        影響: 点検結果が後から改変でき、是正記録の否認不能性が破綻する（Q6/Q8）。
        """
        inspection = _inspection(status="passed")
        inspection.is_safe = True
        inspection.score = 95
        client, _, _ = make_client(items=[inspection])
        response = client.post(
            f"/api/v1/safety/inspections/{INSPECTION_A}/complete",
            json={"is_safe": False, "score": 10},
        )
        assert response.status_code in (400, 409), (
            f"確定済み巡視の再完了を受理した: status={response.status_code}, "
            f"結果={inspection.status}, score={inspection.score}"
        )

    def test_defect_repeat_complete_erases_existing_findings(self, make_client):
        """DEF-SAF-26: 二重 complete で既存の findings が None 上書きされ証跡が消える。

        根拠: src/services/safety_service.py:130 ``inspection.findings = findings``
              （None でも無条件に代入）, src/schemas/__init__.py:45（findings は省略可）
        手順: findings 付きで complete → findings なしで再度 complete。
        期待: 既存の指摘事項が保持される（または再完了が拒否される）。
        実際: findings が null に置き換わる。
        影響: 点検記録の証跡が消失し、後から追跡できない（Q6/Q8）。
        """
        inspection = _inspection(status="in_progress", findings="先行して記録した指摘")
        client, _, _ = make_client(items=[inspection])
        first = client.post(
            f"/api/v1/safety/inspections/{INSPECTION_A}/complete",
            json={"is_safe": True, "findings": "先行して記録した指摘", "score": 90},
        )
        assert first.status_code == 200
        second = client.post(
            f"/api/v1/safety/inspections/{INSPECTION_A}/complete",
            json={"is_safe": True, "score": 90},
        )
        assert second.status_code == 200
        assert inspection.findings == "先行して記録した指摘", (
            f"再完了で findings が上書きされた: findings={inspection.findings!r}"
        )


# =============================================================================
# ⑤ 危険予知の severity / status 遷移と境界値（欠陥検出テスト）
# =============================================================================
class TestHazardStateDefects:
    def test_defect_hazard_severity_is_unvalidated_free_text(self, make_client):
        """DEF-SAF-27: severity が自由文字列で値域検証が無く、任意の値を受け付ける。

        根拠: src/schemas/__init__.py:60（max_length=20 のみ）
              src/services/safety_service.py:199（そのまま保存）
        期待: 語彙外の値は 422。
        実際: 201。
        未確認: severity の正規語彙（例: minor/moderate/severe/catastrophic）を定義した
                リポジトリ内資料は見つかっていない。**語彙の確定とロール要件的な仕様判断は
                人の確認が必要**（本テストは「検証が存在しない」ことのみを立証する）。
        影響: severity での絞り込み・集計が表記ゆれで破綻する（Q4/Q8）。
        """
        client, _, _ = make_client()
        response = client.post(
            "/api/v1/safety/hazards", json=_hazard_body(severity="__invalid__")
        )
        assert response.status_code == 422, (
            f"語彙外の severity を受理した（値域検証なし）: {response.status_code}"
        )

    def test_defect_hazard_risk_level_is_unvalidated_free_text(self, make_client):
        """DEF-SAF-28: risk_level も自由文字列で値域検証が無い。

        根拠: src/schemas/__init__.py:59
        期待: 422 / 実際: 201。語彙はリポジトリ内に定義が無く **未確認**。
        """
        client, _, _ = make_client()
        response = client.post(
            "/api/v1/safety/hazards", json=_hazard_body(risk_level="__invalid__")
        )
        assert response.status_code == 422, (
            f"語彙外の risk_level を受理した（値域検証なし）: {response.status_code}"
        )

    def test_defect_hazard_status_transition_has_no_guard(self, make_client):
        """DEF-SAF-29: 危険予知の status 遷移ガードが無く、クローズ済みを差し戻せる。

        根拠: src/services/safety_service.py:269-272（status を無条件に代入）
              src/schemas/__init__.py:69（HazardUpdate.status は自由文字列）
        手順: status="closed"（resolved_at 設定済み）の hazard を "reported" に更新。
        期待: 400/409（終端状態からの差し戻しを拒否）。
        実際: 200 で "reported" に戻り、resolved_at は残置（矛盾状態）。
        影響: 是正完了記録の取消が痕跡なく行える（Q6/Q8）。
        """
        hazard = _hazard(status="closed")
        hazard.resolved_at = _NOW
        client, _, _ = make_client(items=[hazard])
        response = client.put(
            f"/api/v1/safety/hazards/{HAZARD_A}", json={"status": "reported"}
        )
        assert response.status_code in (400, 409), (
            f"クローズ済み危険予知を差し戻せた: status={response.status_code}, "
            f"new_status={hazard.status}, resolved_at={hazard.resolved_at}"
        )

    def test_defect_hazard_resolved_status_does_not_set_resolved_at(self, make_client):
        """DEF-SAF-30: hazard は status="resolved" で resolved_at を設定しない（incidents と非一貫）。

        根拠: src/services/safety_service.py:271-272 は ``status == "closed"`` のみ
              （対して incidents は :380-381 で ``status in ("resolved", "closed")``）
        期待: 終端状態とみなす status で resolved_at が記録される（同一サービス内で一貫）。
        実際: hazard を "resolved" にしても resolved_at は None。
        未確認: どちらの status 語彙が正しいかは資料上未確認（不整合の指摘に留める）。
        """
        hazard = _hazard(status="reported")
        client, _, _ = make_client(items=[hazard])
        response = client.put(
            f"/api/v1/safety/hazards/{HAZARD_A}", json={"status": "resolved"}
        )
        assert response.status_code == 200
        assert hazard.resolved_at is not None, (
            "status='resolved' で resolved_at が記録されない（incidents は resolved でも記録）"
        )

    def test_defect_open_hazards_does_not_exclude_resolved(self, make_client):
        """DEF-SAF-31: 未クローズ一覧の除外条件が "closed" のみで、"resolved" を除外しない。

        根拠: src/services/safety_service.py:244
              ``where(HazardReport.status.notin_(["closed"]))``
        期待: 解決済み（"resolved"）も未クローズ一覧から除外する。
        実際: 除外されず「未対応」として残る。
        未確認: status 語彙が未定義のため、除外すべき語彙の確定は人の確認が必要。
        """
        client, statements, _ = make_client(items=[])
        response = client.get("/api/v1/safety/hazards/open")
        assert response.status_code == 200
        # 除外リスト（IN のバインド値）を取り出す。列名 resolved_at との部分一致を避ける。
        params = statements[0].compile().params
        excluded: list = []
        for value in params.values():
            if isinstance(value, (list, tuple, set)):
                excluded.extend(value)
        assert "resolved" in excluded, (
            f"未クローズ判定の除外語彙が {excluded} のみ（resolved が除外されない）"
        )


# =============================================================================
# ⑥ 巡視統計の計算再現性（欠陥検出テスト + 検証済み）
# =============================================================================
class TestInspectionStatsDefects:
    def test_defect_average_score_zero_becomes_null(self, make_client):
        """DEF-SAF-32: 平均点が 0.0 のとき None を返す（0 と「データ無し」の混同）。

        根拠: src/services/safety_service.py:169
              ``round(float(avg_score), 2) if avg_score else None``
              → 平均 0.0 は falsy のため None になる。
        期待: average_score == 0.0。実際: null。
        影響: 全点検が 0 点の現場で「データ無し」と誤表示される（Q3）。
        """
        client, _, _ = make_client(
            results=[{"scalar": 3}, {"scalar": 1}, {"scalar": 2}, {"scalar": 0.0}]
        )
        response = client.get("/api/v1/safety/inspections/stats")
        assert response.status_code == 200
        assert response.json()["data"]["average_score"] == 0.0, (
            f"平均0.0が欠測扱いになった: average_score={response.json()['data']['average_score']!r}"
        )


# =============================================================================
# ⑦ 永続化（セッションのコミット）
# =============================================================================
class _SessionCtx:
    """async_sessionmaker() の戻り値（async context manager）を模擬。"""

    def __init__(self, session):
        self._session = session

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, *exc_info):
        return False


class TestPersistenceDefects:
    async def test_defect_get_db_never_commits_the_transaction(self, monkeypatch):
        """DEF-SAF-33: get_db が commit しないため、書き込みが永続化されない。

        根拠: src/models/base.py:27-35（``yield session`` の後に commit が無い）
              src/services/safety_service.py の作成系は ``db.flush()`` のみで
              ``commit()`` を呼ばない（safety/src 全体で commit 呼び出しゼロ）。
              対照: services/field-dx/src/models/base.py:25-35 ほか **22サービス中17サービス**が
                    ``get_db`` 内で ``await session.commit()`` を実行する。
        期待: 正常終了時に commit が 1 回以上呼ばれる。
        実際: commit は一度も呼ばれず、close 時に暗黙ロールバックされる。
        影響: POST/PUT が 201/200 を返しても DB に反映されず、データが消失する（Q8）。
        """
        from src.models import base as base_module

        session = AsyncMock()
        monkeypatch.setattr(base_module, "async_session", lambda: _SessionCtx(session))

        generator = base_module.get_db()
        await generator.__anext__()
        with pytest.raises(StopAsyncIteration):
            await generator.__anext__()

        assert session.commit.await_count >= 1, (
            "get_db が commit していない（作成/更新が永続化されない）: "
            f"commit.await_count={session.commit.await_count}"
        )


# =============================================================================
# 検証済み（現状で仕様を満たす）テスト
# =============================================================================
class TestWorkflowVerified:
    def test_ok_complete_requires_inspection_role(self, make_client):
        """検査（合否確定）は admin/inspector ロールを要求する（fail-closed）。"""
        inspection = _inspection(status="in_progress")
        client, _, _ = make_client(items=[inspection], roles=["site_worker"])
        response = client.post(
            f"/api/v1/safety/inspections/{INSPECTION_A}/complete",
            json={"is_safe": True, "score": 95},
        )
        assert response.status_code == 403, (
            f"検査ロール無しで合否確定できた: {response.status_code}"
        )

    def test_ok_complete_sets_status_from_is_safe(self, make_client):
        """正常系: complete の is_safe が status(passed/failed) へ反映される。"""
        passed = _inspection(status="in_progress")
        client, _, _ = make_client(items=[passed])
        body = client.post(
            f"/api/v1/safety/inspections/{INSPECTION_A}/complete",
            json={"is_safe": True, "score": 95},
        ).json()
        assert passed.status == "passed"
        assert body["data"]["status"] == "passed"
        assert passed.is_safe is True

        failed = _inspection(status="in_progress")
        client, _, _ = make_client(items=[failed])
        client.post(
            f"/api/v1/safety/inspections/{INSPECTION_A}/complete",
            json={"is_safe": False, "findings": "露出配線", "score": 30},
        )
        assert failed.status == "failed"
        assert failed.findings == "露出配線"

    @pytest.mark.parametrize("score", [0, 100])
    def test_ok_inspection_score_boundaries_are_accepted(self, make_client, score):
        """境界値: スコア 0 と 100 は受理される（schema の ge=0, le=100）。"""
        inspection = _inspection(status="in_progress")
        client, _, _ = make_client(items=[inspection])
        response = client.post(
            f"/api/v1/safety/inspections/{INSPECTION_A}/complete",
            json={"is_safe": True, "score": score},
        )
        assert response.status_code == 200
        assert inspection.score == score

    @pytest.mark.parametrize("score", [-1, 101])
    def test_ok_inspection_score_out_of_range_is_rejected(self, make_client, score):
        """境界値: スコア -1 と 101 は 422 で拒否される（DB へ到達しない）。"""
        client, statements, _ = make_client(items=[_inspection()])
        response = client.post(
            f"/api/v1/safety/inspections/{INSPECTION_A}/complete",
            json={"is_safe": True, "score": score},
        )
        assert response.status_code == 422
        assert statements == []

    def test_ok_inspection_stats_has_no_zero_division(self, make_client):
        """集計: 0 件でもゼロ除算せず total/passed/failed=0, average_score=null。"""
        client, _, _ = make_client(
            results=[{"scalar": 0}, {"scalar": 0}, {"scalar": 0}, {"scalar": None}]
        )
        body = client.get("/api/v1/safety/inspections/stats").json()["data"]
        assert body == {
            "total": 0,
            "passed": 0,
            "failed": 0,
            "average_score": None,
        }

    def test_ok_inspection_stats_is_deterministic_and_rounded(self, make_client):
        """集計: 同一入力→同一出力、平均は小数2桁に丸められる。"""
        sequence = [
            {"scalar": 4},
            {"scalar": 3},
            {"scalar": 1},
            {"scalar": 88.556},
        ]
        client, _, _ = make_client(results=list(sequence))
        first = client.get("/api/v1/safety/inspections/stats").json()
        client, _, _ = make_client(results=list(sequence))
        second = client.get("/api/v1/safety/inspections/stats").json()
        assert first == second
        # round(88.556, 2) == 88.56（丸め桁は実装どおり。丸め規約の仕様は未確認）
        assert first["data"]["average_score"] == pytest.approx(88.56)
        assert first["data"]["total"] == 4
        assert first["data"]["passed"] == 3
        assert first["data"]["failed"] == 1

    def test_ok_hazard_closed_sets_resolved_at(self, make_client):
        """正常系: hazard を "closed" にすると resolved_at が記録される。"""
        hazard = _hazard(status="mitigated")
        client, _, _ = make_client(items=[hazard])
        response = client.put(
            f"/api/v1/safety/hazards/{HAZARD_A}", json={"status": "closed"}
        )
        assert response.status_code == 200
        assert hazard.status == "closed"
        assert hazard.resolved_at is not None

    async def test_ok_get_db_rolls_back_on_exception(self, monkeypatch):
        """異常系: 例外時は rollback が呼ばれる（復旧経路そのものは機能している）。"""
        from src.models import base as base_module

        session = AsyncMock()
        monkeypatch.setattr(base_module, "async_session", lambda: _SessionCtx(session))

        generator = base_module.get_db()
        await generator.__anext__()
        with pytest.raises(RuntimeError):
            await generator.athrow(RuntimeError("boom"))

        assert session.rollback.await_count == 1
