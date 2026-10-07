"""安全管理: テナント分離・権限境界・行為者同定の品質テスト（観点 Q1 / Q2 / Q6）

仕様根拠（リポジトリ内の参照実装）
----------------------------------
* services/workflow/src/api/workflows.py:93-108 ``_organization_id(current_user)``
  → トークンの ``org`` が無ければ 403 ``ORG_REQUIRED``、UUID でなければ 403 ``ORG_INVALID``。
* services/workflow/src/api/cases.py:75-95 ``create_case``
  → ``organization_id = _organization_id(current_user)`` とし、
     ``body.organization_id != organization_id`` なら 403 ``ORG_FORBIDDEN``。
     行為者は ``submitted_by=UUID(current_user.sub)`` とトークンから導出。
* services/workflow/src/api/cases.py:57 ``can_view_instance(instance, UUID(current_user.sub), current_user.roles)``
  → 個別取得にも閲覧主体の検証がある。
* services/workflow/src/api/workflows.py:93 以降が「承認・証跡」の参照実装（task-9 指定）。
* docs/architecture/ADR-0001-ceos-responsibility-boundary.md:44
  「認可は **組織（テナント）＋案件（project）＋ロール**で行い、API 到達性は公開 API の契約に従う。」

本ファイルの方針
----------------
* ``test_defect_*`` は **仕様準拠の期待値を assert する**。失敗 = 実装欠陥。
* テナント絞り込みの判定は SQL の **WHERE 句のみ** を対象にする
  （SELECT 句の列一覧に organization_id が含まれるため全文一致は使えない）。
* DB は mock。実 PostgreSQL・外部接続・ネットワークなし。fixture は synthetic のみ。
"""

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from src.main import create_app
from src.middleware.auth import TokenData, get_current_user
from src.models.base import get_db

ORG_A = uuid.UUID("00000000-0000-0000-0000-0000000000aa")  # トークン保有組織
ORG_B = uuid.UUID("00000000-0000-0000-0000-0000000000bb")  # 他テナント
PROJECT_B = uuid.UUID("00000000-0000-0000-0000-0000000000e4")
USER_SUB = "00000000-0000-0000-0000-0000000000dd"  # トークン sub（認証済み本人）
OTHER_USER = uuid.UUID("00000000-0000-0000-0000-0000000000ff")
INSPECTION_B = uuid.UUID("00000000-0000-0000-0000-0000000000e1")
HAZARD_B = uuid.UUID("00000000-0000-0000-0000-0000000000e2")
INCIDENT_B = uuid.UUID("00000000-0000-0000-0000-0000000000e3")
_NOW = datetime(2026, 5, 24, 9, 0, 0, tzinfo=timezone.utc)


def _sql(statement) -> str:
    try:
        return " ".join(str(statement.compile()).split())
    except Exception as exc:  # pragma: no cover - 診断用
        return f"<compile failed: {exc}>"


def _where_clause(statement) -> str:
    sql = _sql(statement)
    marker = " WHERE "
    return sql.split(marker, 1)[1] if marker in sql else ""




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
        scalars=None,
        results=None,
        token_sub: str = USER_SUB,
        token_org: str | None = str(ORG_A),
        raise_server_exceptions: bool = True,
    ):
        """``results`` に execute 呼び出しごとの応答を並べると複数クエリを模擬できる。

        各要素は ``{"items": [...], "scalar": n}``。
        """
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
            if scalars is not None:
                return _FakeResult(items=items, scalar=scalars)
            return _FakeResult(items=items)

        db.execute = _execute

        app = create_app()

        async def _get_db():
            yield db

        async def _current_user():
            return TokenData(
                sub=token_sub, type="user", org=token_org, roles=["safety_admin"]
            )

        app.dependency_overrides[get_db] = _get_db
        app.dependency_overrides[get_current_user] = _current_user
        return (
            TestClient(app, raise_server_exceptions=raise_server_exceptions),
            statements,
            db,
        )

    return _factory


def _inspection(org_id: uuid.UUID, inspection_id: uuid.UUID = INSPECTION_B, status="scheduled"):
    from src.models import SafetyInspection

    return SafetyInspection(
        id=inspection_id,
        organization_id=org_id,
        project_id=PROJECT_B,
        title="ダミー安全巡視",
        inspection_type="daily",
        status=status,
        inspector_id=OTHER_USER,
        inspection_date=None,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _hazard(org_id: uuid.UUID, hazard_id: uuid.UUID = HAZARD_B, status="reported"):
    from src.models import HazardReport

    return HazardReport(
        id=hazard_id,
        organization_id=org_id,
        project_id=PROJECT_B,
        title="ダミー危険予知",
        description="ダミー詳細",
        hazard_type="fall",
        risk_level="high",
        severity="severe",
        status=status,
        reported_by=OTHER_USER,
        created_at=_NOW,
    )


def _incident(org_id: uuid.UUID, incident_id: uuid.UUID = INCIDENT_B, status="reported"):
    from src.models import SafetyIncident

    return SafetyIncident(
        id=incident_id,
        organization_id=org_id,
        project_id=PROJECT_B,
        title="ダミー事故",
        description="ダミー詳細",
        incident_type="injury",
        severity="moderate",
        status=status,
        incident_date=_NOW,
        reported_by=OTHER_USER,
        injured_count=0,
        fatality_count=0,
        is_osha_reportable=False,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _inspection_body(**overrides):
    body = {
        "organization_id": str(ORG_A),
        "title": "ダミー安全巡視",
        "inspection_type": "daily",
        "inspector_id": str(OTHER_USER),
    }
    body.update(overrides)
    return body


def _hazard_body(**overrides):
    body = {
        "organization_id": str(ORG_A),
        "title": "ダミー危険予知",
        "description": "ダミー詳細",
        "hazard_type": "fall",
        "risk_level": "high",
        "severity": "severe",
        "reported_by": str(OTHER_USER),
    }
    body.update(overrides)
    return body


def _incident_body(**overrides):
    body = {
        "organization_id": str(ORG_A),
        "title": "ダミー事故",
        "description": "ダミー詳細",
        "incident_type": "injury",
        "severity": "moderate",
        "incident_date": _NOW.isoformat(),
        "reported_by": str(OTHER_USER),
    }
    body.update(overrides)
    return body


# =============================================================================
# ① 一覧・個別取得のテナント境界（欠陥検出テスト / 失敗 = 欠陥）
# =============================================================================
class TestTenantScopingDefects:
    def test_defect_list_hazards_is_not_tenant_scoped(self, make_client):
        """DEF-SAF-01: 危険予知一覧がトークン組織で絞り込まれていない。

        根拠: src/api/hazards.py:62（organization_id は Query 由来）
              src/services/safety_service.py:220-221（None なら where を付けない）
        期待: WHERE 句に organization_id が含まれる。
        """
        client, statements, _ = make_client(items=[_hazard(ORG_B)])
        response = client.get("/api/v1/safety/hazards")
        assert response.status_code == 200
        where_sql = _where_clause(statements[0])
        assert "organization_id" in where_sql, (
            f"テナント絞り込みなし / actual WHERE = {where_sql!r}"
        )

    def test_defect_list_inspections_is_not_tenant_scoped(self, make_client):
        """DEF-SAF-02: 安全巡視一覧がトークン組織で絞り込まれていない。

        根拠: src/api/inspections.py:64, src/services/safety_service.py:57-58
        """
        client, statements, _ = make_client(items=[_inspection(ORG_B)])
        response = client.get("/api/v1/safety/inspections")
        assert response.status_code == 200
        where_sql = _where_clause(statements[0])
        assert "organization_id" in where_sql, (
            f"テナント絞り込みなし / actual WHERE = {where_sql!r}"
        )

    def test_defect_list_incidents_is_not_tenant_scoped(self, make_client):
        """DEF-SAF-03: 事故一覧がトークン組織で絞り込まれていない。

        根拠: src/api/incidents.py:69, src/services/safety_service.py:336-337
        """
        client, statements, _ = make_client(items=[_incident(ORG_B)])
        response = client.get("/api/v1/safety/incidents")
        assert response.status_code == 200
        where_sql = _where_clause(statements[0])
        assert "organization_id" in where_sql, (
            f"テナント絞り込みなし / actual WHERE = {where_sql!r}"
        )

    def test_defect_open_hazards_is_never_tenant_scoped(self, make_client):
        """DEF-SAF-04: 未クローズ危険予知が organization 条件を一切持たない。

        根拠: src/api/hazards.py:83-89（引数なし）, src/services/safety_service.py:241-246
              （``status != 'closed'`` のみ）
        期待: WHERE 句に organization_id が含まれる。
        """
        client, statements, _ = make_client(items=[_hazard(ORG_B)])
        response = client.get("/api/v1/safety/hazards/open")
        assert response.status_code == 200
        where_sql = _where_clause(statements[0])
        assert "organization_id" in where_sql, (
            f"テナント絞り込みなし / actual WHERE = {where_sql!r}"
        )

    def test_defect_query_org_param_can_select_another_tenant(self, make_client):
        """DEF-SAF-05: organization_id クエリでテナント越境の読み取りが可能。

        根拠: src/api/hazards.py:62, src/api/inspections.py:64, src/api/incidents.py:69
        期待: トークン org (ORG_A) 以外の組織IDが SQL のバインド値に現れない。
        """
        for path in (
            "/api/v1/safety/hazards",
            "/api/v1/safety/inspections",
            "/api/v1/safety/incidents",
        ):
            client, statements, _ = make_client(items=[])
            response = client.get(f"{path}?organization_id={ORG_B}")
            assert response.status_code == 200
            params = statements[0].compile().params
            assert ORG_B not in params.values(), (
                f"{path}: クエリ由来の organization_id がそのまま検索条件に使われている "
                f"(テナント越境) / bound params = {params}"
            )

    def test_defect_get_inspection_crosses_tenant(self, make_client):
        """DEF-SAF-06: 他テナントの安全巡視をID指定で取得できる。

        根拠: src/api/inspections.py:94-106, src/services/safety_service.py:70-75
        """
        client, _, _ = make_client(items=[_inspection(ORG_B)])
        response = client.get(f"/api/v1/safety/inspections/{INSPECTION_B}")
        assert response.status_code in (403, 404), (
            f"他テナント(ORG_B)の巡視を 200 で返した: {response.status_code}"
        )

    def test_defect_get_incident_crosses_tenant(self, make_client):
        """DEF-SAF-07: 他テナントの事故をID指定で取得できる。

        根拠: src/api/incidents.py:90-102, src/services/safety_service.py:349-354
        """
        client, _, _ = make_client(items=[_incident(ORG_B)])
        response = client.get(f"/api/v1/safety/incidents/{INCIDENT_B}")
        assert response.status_code in (403, 404), (
            f"他テナントの事故を 200 で返した: {response.status_code}"
        )

    def test_defect_update_hazard_crosses_tenant(self, make_client):
        """DEF-SAF-08: 他テナントの危険予知を更新できる。

        根拠: src/api/hazards.py:92-115, src/services/safety_service.py:262-263
        """
        client, _, _ = make_client(items=[_hazard(ORG_B)])
        response = client.put(
            f"/api/v1/safety/hazards/{HAZARD_B}", json={"status": "assessed"}
        )
        assert response.status_code in (403, 404), (
            f"他テナントの危険予知を更新できた: {response.status_code}"
        )

    def test_defect_update_inspection_crosses_tenant(self, make_client):
        """DEF-SAF-09: 他テナントの安全巡視を更新できる。

        根拠: src/api/inspections.py:109-134
        """
        client, _, _ = make_client(items=[_inspection(ORG_B)])
        response = client.put(
            f"/api/v1/safety/inspections/{INSPECTION_B}", json={"title": "改ざん"}
        )
        assert response.status_code in (403, 404), (
            f"他テナントの巡視を更新できた: {response.status_code}"
        )

    def test_defect_complete_inspection_crosses_tenant(self, make_client):
        """DEF-SAF-10: 他テナントの安全巡視を完了（結果確定）できる。

        根拠: src/api/inspections.py:137-157
        """
        client, _, _ = make_client(items=[_inspection(ORG_B)])
        response = client.post(
            f"/api/v1/safety/inspections/{INSPECTION_B}/complete",
            json={"is_safe": True, "score": 100},
        )
        assert response.status_code in (403, 404), (
            f"他テナントの巡視を完了できた: {response.status_code}"
        )

    def test_defect_update_incident_crosses_tenant(self, make_client):
        """DEF-SAF-11: 他テナントの事故を更新できる。

        根拠: src/api/incidents.py:105-131
        """
        client, _, _ = make_client(items=[_incident(ORG_B)])
        response = client.put(
            f"/api/v1/safety/incidents/{INCIDENT_B}", json={"status": "investigating"}
        )
        assert response.status_code in (403, 404), (
            f"他テナントの事故を更新できた: {response.status_code}"
        )

    def test_defect_inspection_stats_is_global(self, make_client):
        """DEF-SAF-12: 巡視統計が全テナント横断で集計される（organization 条件なし）。

        根拠: src/api/inspections.py:85-91（organization を受け取らない）
              src/services/safety_service.py:138-170（4クエリすべてに org 条件なし）
        期待: 集計クエリすべてに organization_id 条件が含まれる。
        """
        client, statements, _ = make_client(
            results=[{"scalar": 10}, {"scalar": 7}, {"scalar": 3}, {"scalar": 88.5}]
        )
        response = client.get("/api/v1/safety/inspections/stats")
        assert response.status_code == 200
        unscoped = [
            where
            for where in (_where_clause(s) for s in statements)
            if "organization_id" not in where
        ]
        assert not unscoped, (
            f"テナント絞り込みの無い集計クエリが存在する / actual WHERE = {unscoped}"
        )

    def test_defect_token_without_org_is_accepted(self, make_client):
        """DEF-SAF-13: 組織情報を持たないトークンでも安全情報を読み取れる。

        参照実装: services/workflow/src/api/workflows.py:93-101 は
                  ``org`` が無ければ 403 ``ORG_REQUIRED`` を返す。
        期待: 403。実際: 200（org 条件が付かないため全件が返る）。
        影響: 組織未所属トークンが全社の安全情報を閲覧できる（Q1）。
        """
        client, _, _ = make_client(items=[_hazard(ORG_B)], token_org=None)
        response = client.get("/api/v1/safety/hazards")
        assert response.status_code == 403, (
            f"org クレーム無しのトークンを受理した: {response.status_code}"
        )

    def test_defect_token_with_invalid_org_is_accepted(self, make_client):
        """DEF-SAF-14: 不正な org クレーム（非UUID）でも 403 にならない。

        参照実装: services/workflow/src/api/workflows.py:102-108 は 403 ``ORG_INVALID``。
        期待: 403。実際: 200。
        """
        client, _, _ = make_client(items=[_hazard(ORG_B)], token_org="not-a-uuid")
        response = client.get("/api/v1/safety/hazards")
        assert response.status_code == 403, (
            f"不正な org クレームのトークンを受理した: {response.status_code}"
        )


# =============================================================================
# ② 作成時の organization_id（欠陥検出テスト）
# =============================================================================
class TestCreateOrgSourceDefects:
    def test_defect_create_hazard_accepts_foreign_org_in_body(self, make_client):
        """DEF-SAF-15: 危険予知作成で body の organization_id をそのまま採用する（Q2）。

        参照実装: workflow/src/api/cases.py:80-82 は body.org != token.org を 403 で拒否。
        根拠: src/api/hazards.py:43-56, src/schemas/__init__.py:53
        期待: 400/403。実際: 201。
        """
        client, _, _ = make_client()
        response = client.post(
            "/api/v1/safety/hazards", json=_hazard_body(organization_id=str(ORG_B))
        )
        assert response.status_code in (400, 403), (
            f"他テナント(ORG_B)宛の危険予知を作成できた: {response.status_code}"
        )

    def test_defect_create_inspection_accepts_foreign_org_in_body(self, make_client):
        """DEF-SAF-16: 安全巡視作成で body の organization_id をそのまま採用する（Q2）。

        根拠: src/api/inspections.py:48-58, src/schemas/__init__.py:21
        """
        client, _, _ = make_client()
        response = client.post(
            "/api/v1/safety/inspections",
            json=_inspection_body(organization_id=str(ORG_B)),
        )
        assert response.status_code in (400, 403), (
            f"他テナント(ORG_B)宛の巡視を作成できた: {response.status_code}"
        )

    def test_defect_create_incident_accepts_foreign_org_in_body(self, make_client):
        """DEF-SAF-17: 事故作成で body の organization_id をそのまま採用する（Q2）。

        根拠: src/api/incidents.py:48-63, src/schemas/__init__.py:79
        """
        client, _, _ = make_client()
        response = client.post(
            "/api/v1/safety/incidents",
            json=_incident_body(organization_id=str(ORG_B)),
        )
        assert response.status_code in (400, 403), (
            f"他テナント(ORG_B)宛の事故を作成できた: {response.status_code}"
        )


# =============================================================================
# ③ 行為者（reported_by / investigated_by / inspector_id）の同定
# =============================================================================
class TestActorIdentityDefects:
    def test_defect_incident_reported_by_comes_from_body(self, make_client):
        """DEF-SAF-18: 事故の報告者が body 由来で、トークン本人と一致しなくても通る。

        参照実装: workflow/src/api/cases.py:85 ``submitted_by=UUID(current_user.sub)``
        根拠: src/api/incidents.py:56（reported_by=body.reported_by）, :100
        期待: reported_by はトークン sub。
        影響: 報告者のなりすましが可能（Q6 承認・証跡）。
        """
        client, _, db = make_client()
        response = client.post("/api/v1/safety/incidents", json=_incident_body())
        assert response.status_code == 201
        saved = db.add.call_args[0][0]
        assert saved.reported_by == uuid.UUID(USER_SUB), (
            f"報告者が body 由来: reported_by={saved.reported_by} (トークン sub={USER_SUB})"
        )

    def test_defect_incident_investigated_by_comes_from_body(self, make_client):
        """DEF-SAF-19: 事故の調査担当者が body 由来で指定できる。

        参照実装: workflow は操作者を常に ``UUID(current_user.sub)`` から導出する。
        根拠: src/api/incidents.py:119, src/schemas/__init__.py:99
        期待: investigated_by はトークン sub（またはロール検証つき）。
        影響: 調査記録の否認不能性が破綻（Q6）。
        """
        incident = _incident(ORG_A)
        client, _, _ = make_client(items=[incident])
        response = client.put(
            f"/api/v1/safety/incidents/{INCIDENT_B}",
            json={"status": "investigating", "investigated_by": str(OTHER_USER)},
        )
        assert response.status_code == 200
        assert incident.investigated_by == uuid.UUID(USER_SUB), (
            f"調査担当者が body 由来: investigated_by={incident.investigated_by} "
            f"(トークン sub={USER_SUB})"
        )

    def test_defect_hazard_reported_by_comes_from_body(self, make_client):
        """DEF-SAF-20: 危険予知の報告者が body 由来。

        根拠: src/api/hazards.py:51, :200
        期待: reported_by はトークン sub。
        """
        client, _, db = make_client()
        response = client.post("/api/v1/safety/hazards", json=_hazard_body())
        assert response.status_code == 201
        saved = db.add.call_args[0][0]
        assert saved.reported_by == uuid.UUID(USER_SUB), (
            f"報告者が body 由来: reported_by={saved.reported_by} (トークン sub={USER_SUB})"
        )

    def test_defect_inspection_inspector_id_comes_from_body(self, make_client):
        """DEF-SAF-21: 安全巡視の実施者(inspector_id)が body 由来。

        根拠: src/api/inspections.py:53, src/services/safety_service.py:37
        期待: inspector_id はトークン sub（実施者本人）。
        影響: 実施していない者を実施者として記録できる（Q6 証跡欠落）。
        """
        client, _, db = make_client()
        response = client.post("/api/v1/safety/inspections", json=_inspection_body())
        assert response.status_code == 201
        saved = db.add.call_args[0][0]
        assert saved.inspector_id == uuid.UUID(USER_SUB), (
            f"実施者が body 由来: inspector_id={saved.inspector_id} (トークン sub={USER_SUB})"
        )

    def test_defect_inspection_inspector_can_be_reassigned_by_body(self, make_client):
        """DEF-SAF-22: 更新APIで実施者を body から差し替えられる。

        根拠: src/api/inspections.py:121, src/services/safety_service.py:98-99
        期待: 実施者の変更はトークン sub に固定、または専用操作+ロール検証。
        """
        inspection = _inspection(ORG_A)
        client, _, _ = make_client(items=[inspection])
        response = client.put(
            f"/api/v1/safety/inspections/{INSPECTION_B}",
            json={"inspector_id": str(OTHER_USER)},
        )
        assert response.status_code == 200
        assert inspection.inspector_id == uuid.UUID(USER_SUB), (
            f"実施者が body で差し替えられた: inspector_id={inspection.inspector_id} "
            f"(トークン sub={USER_SUB})"
        )


# =============================================================================
# 検証済み（現状で仕様を満たす）テスト
# =============================================================================
class TestTenantIsolationVerified:
    def test_ok_unauthenticated_is_rejected(self):
        """未認証は 401（認証境界そのものは有効）。"""
        client = TestClient(create_app(), raise_server_exceptions=False)
        for path in (
            "/api/v1/safety/inspections",
            "/api/v1/safety/hazards",
            "/api/v1/safety/incidents",
            "/api/v1/safety/inspections/stats",
        ):
            assert client.get(path).status_code in (401, 403), path

    def test_ok_non_user_token_is_rejected(self):
        """type != user のトークンは 403（middleware の type 判定）。"""
        import warnings

        import jwt as pyjwt

        from src.config import get_settings

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            token = pyjwt.encode(
                {"sub": USER_SUB, "type": "service", "exp": 9999999999},
                get_settings().jwt_public_key,
                algorithm="HS256",
            )
        client = TestClient(create_app(), raise_server_exceptions=False)
        response = client.get(
            "/api/v1/safety/hazards", headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 403

    def test_ok_jwt_key_resolution_matches_other_services(self):
        """JWT 検証鍵は property 経由で解決され、他サービスと同一（既存修正の回帰）。"""
        import jwt as pyjwt

        from src.config import get_settings
        from src.middleware.auth import decode_token

        settings = get_settings()
        token = pyjwt.encode(
            {"sub": USER_SUB, "type": "user", "org": str(ORG_A), "exp": 9999999999},
            settings.jwt_public_key,
            algorithm="HS256",
        )
        assert decode_token(token) is not None

    def test_ok_documented_gap_no_single_hazard_get(self, make_client):
        """未実装の記録: 危険予知には個別取得APIが存在しない（欠陥と断定しない）。

        根拠: src/api/hazards.py（GET は ``/hazards`` と ``/hazards/open`` のみ）
        → 「個別取得のテナント境界」は検証対象が無い（該当なし）。更新は可能（DEF-SAF-08）。
        """
        client, _, _ = make_client()
        response = client.get(f"/api/v1/safety/hazards/{HAZARD_B}")
        assert response.status_code == 405
