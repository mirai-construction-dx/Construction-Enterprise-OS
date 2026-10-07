"""現場DX: テナント分離・権限境界の品質テスト（観点 Q1 / Q2 / Q6）

仕様根拠
--------
* docs/architecture/ADR-0001-ceos-responsibility-boundary.md:44
  「認可は **組織（テナント）＋案件（project）＋ロール**で行い、API 到達性は公開 API の契約に従う。」
* docs/architecture/01-auth-platform.md:33 「組織管理 | P0 | 会社→事業部→現場の階層構造」
* docs/architecture/01-auth-platform.md:28 「データレベル認可 | P2 | 行レベルセキュリティ（プロジェクト単位の参照制限）」

本ファイルの方針
----------------
* ``test_defect_*`` は **仕様準拠の期待値を assert する**。
  したがって **失敗 = 実装欠陥**（テストの誤りではない）。各 docstring に欠陥IDと根拠行を記す。
* DB は mock。実 PostgreSQL・外部サービス・ネットワークへは一切接続しない。
* fixture は synthetic のみ（UUID は ``00000000-0000-0000-0000-0000000000xx``）。
"""

import uuid
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from src.main import create_app
from src.middleware.auth import TokenData, get_current_user
from src.models.base import get_db

# ---- synthetic fixture 値（実在組織・実在案件ではない） --------------------------
ORG_A = uuid.UUID("00000000-0000-0000-0000-0000000000aa")  # トークン保有組織
ORG_B = uuid.UUID("00000000-0000-0000-0000-0000000000bb")  # 他テナント
PROJECT_A = uuid.UUID("00000000-0000-0000-0000-0000000000cc")
PROJECT_B = uuid.UUID("00000000-0000-0000-0000-0000000000ee")
USER_SUB = "00000000-0000-0000-0000-0000000000dd"  # トークン sub（= 認証済み本人）
OTHER_USER = uuid.UUID("00000000-0000-0000-0000-0000000000ff")

_NOW = datetime(2026, 5, 24, 9, 0, 0, tzinfo=timezone.utc)


def _sql(statement) -> str:
    try:
        return " ".join(str(statement.compile()).split())
    except Exception as exc:  # pragma: no cover - 診断用
        return f"<compile failed: {exc}>"


def _where_clause(statement) -> str:
    """SQL から WHERE 句以降だけを取り出す。

    全 SQL に対する部分一致では SELECT 句の列一覧（organization_id を含む）に
    誤って一致するため、絞り込み条件の判定には本ヘルパを使う。
    """
    sql = _sql(statement)
    marker = " WHERE "
    return sql.split(marker, 1)[1] if marker in sql else ""


def _org_where_all(statements) -> str:
    """すべての文に organization_id 条件があるかを検査するための補助。

    一覧 API は「count クエリ → 本体クエリ」の順に SELECT を発行する。
    count だけに組織条件を足して本体を忘れた部分修正でも通ってしまわないよう、
    捕捉した全クエリに条件があることを要求する。
    全件に条件があれば "organization_id" を返し、1 件でも欠ければ WHERE 句の
    ダンプを返す（既存の assert "organization_id" in where_sql がそのまま機能する）。
    """
    clauses = [_where_clause(s) for s in statements]
    if not clauses:
        return ""
    if all("organization_id" in c for c in clauses):
        return "organization_id"
    return " ; ".join(clauses)


def _auto_refresh(obj):
    """mock DB の refresh をエミュレートし、サーバ既定値を埋める。"""
    if getattr(obj, "id", None) is None:
        obj.id = uuid.uuid4()
    for attr in ("created_at", "updated_at", "recorded_at"):
        if hasattr(obj, attr) and getattr(obj, attr) is None:
            setattr(obj, attr, _NOW)
    if hasattr(obj, "status") and getattr(obj, "status", None) is None:
        cls_name = type(obj).__name__
        setattr(
            obj,
            "status",
            {"DailyReport": "draft", "ProgressRecord": "pending", "QualityCheck": "pending"}.get(
                cls_name, "pending"
            ),
        )
    return obj


class _FakeResult:
    """SQLAlchemy Result の最小スタブ。count は scalar()、行取得は scalars().all()。"""

    def __init__(self, items=None, value=None, total=0):
        self._items = list(items or [])
        self._value = value
        self._total = total

    def scalar_one_or_none(self):
        if self._value is not None:
            return self._value
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
    """TestClient と「実行された SQL 文」の記録リストを返すファクトリ。"""

    def _factory(
        *,
        items=None,
        total=0,
        get_value=None,
        token_org: str = str(ORG_A),
        token_sub: str = USER_SUB,
        raise_server_exceptions: bool = True,
    ):
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
        db.get = AsyncMock(return_value=get_value)

        async def _execute(statement, *args, **kwargs):
            statements.append(statement)
            return _FakeResult(items=items, total=total)

        db.execute = _execute

        app = create_app()

        async def _get_db():
            yield db

        async def _current_user():
            return TokenData(
                sub=token_sub, type="user", org=token_org, roles=["admin"]
            )

        app.dependency_overrides[get_db] = _get_db
        app.dependency_overrides[get_current_user] = _current_user
        client = TestClient(app, raise_server_exceptions=raise_server_exceptions)
        return client, statements, db

    return _factory


def _progress(org_id: uuid.UUID, project_id: uuid.UUID = PROJECT_A):
    from src.models import ProgressRecord

    return ProgressRecord(
        id=uuid.uuid4(),
        organization_id=org_id,
        project_id=project_id,
        activity_name="出来形ダミー工",
        progress_percent=50.0,
        status="in_progress",
        recorded_by=uuid.uuid4(),
        recorded_at=_NOW,
        updated_at=_NOW,
    )


def _report(org_id: uuid.UUID, status: str = "draft"):
    from src.models import DailyReport

    return DailyReport(
        id=uuid.uuid4(),
        organization_id=org_id,
        project_id=PROJECT_A,
        report_date=date(2026, 5, 24),
        work_description="ダミー作業",
        status=status,
        created_by=uuid.uuid4(),
        created_at=_NOW,
        updated_at=_NOW,
    )


def _quality(org_id: uuid.UUID):
    from src.models import QualityCheck

    return QualityCheck(
        id=uuid.uuid4(),
        organization_id=org_id,
        project_id=PROJECT_A,
        check_item="ダミー検査",
        check_type="dummy",
        is_conforming=True,
        check_date=date(2026, 5, 24),
        inspector_id=uuid.uuid4(),
        status="passed",
        created_at=_NOW,
        updated_at=_NOW,
    )


# =============================================================================
# 欠陥検出テスト（失敗 = 欠陥）
# =============================================================================
class TestTenantIsolationDefects:
    def test_defect_list_progress_has_no_token_tenant_filter(self, make_client):
        """DEF-FLD-01: 一覧APIがトークンの organization で絞り込まれていない。

        根拠: src/api/progress.py:148-171（organization_id は Query 由来）
              src/services/field_service.py:138-140（None なら where を付けない）
        期待: token org (ORG_A) による絞り込みが SQL に存在する。
        """
        client, statements, _ = make_client()
        response = client.get("/api/v1/field/progress")
        assert response.status_code == 200
        where_sql = _org_where_all(statements)
        assert "organization_id" in where_sql, (
            "トークン org によるテナント絞り込みが WHERE 句に存在しない "
            f"(全テナント横断の読み取り) / actual WHERE = {where_sql!r}"
        )

    def test_defect_list_quality_has_no_token_tenant_filter(self, make_client):
        """DEF-FLD-02: GET /quality がトークンの organization で絞り込まれていない。

        根拠: src/api/quality.py:125-150, src/services/field_service.py:233-235
        """
        client, statements, _ = make_client()
        response = client.get("/api/v1/field/quality")
        assert response.status_code == 200
        where_sql = _org_where_all(statements)
        assert "organization_id" in where_sql, (
            f"テナント絞り込みなし / actual WHERE = {where_sql!r}"
        )

    def test_defect_list_reports_has_no_token_tenant_filter(self, make_client):
        """DEF-FLD-03: GET /reports がトークンの organization で絞り込まれていない。

        根拠: src/api/reports.py:35-59, src/services/field_service.py:44-46
        """
        client, statements, _ = make_client()
        response = client.get("/api/v1/field/reports")
        assert response.status_code == 200
        where_sql = _org_where_all(statements)
        assert "organization_id" in where_sql, (
            f"テナント絞り込みなし / actual WHERE = {where_sql!r}"
        )

    def test_defect_query_org_param_can_select_another_tenant(self, make_client):
        """DEF-FLD-04: organization_id クエリでテナント越境の読み取りが可能。

        根拠: src/api/progress.py:150（organization_id: UUID | None = Query(None)）
        期待: トークン org (ORG_A) 以外の組織IDが SQL のバインド値に現れない。
        攻撃: 侵害された/別組織のユーザーが ?organization_id=<他社> を付与するだけで他社の出来形を取得。
        """
        client, statements, _ = make_client()
        response = client.get(f"/api/v1/field/progress?organization_id={ORG_B}")
        assert response.status_code in (200, 403)
        params = statements[0].compile().params
        assert ORG_B not in params.values(), (
            "クエリ由来の organization_id がそのまま検索条件に使われている "
            f"(テナント越境) / bound params = {params}"
        )

    def test_defect_get_progress_by_id_crosses_tenant(self, make_client):
        """DEF-FLD-05: 他テナントの出来形記録をID指定で取得できる。

        根拠: src/api/progress.py:181-183（get_progress_record に対象外 org の判定が無い）
              src/services/field_service.py:121-124（PK 取得のみ）
        期待: 404 または 403。実際: 200 + 他テナントの内容を返す。
        """
        other = _progress(ORG_B)
        client, _, _ = make_client(get_value=other)
        response = client.get(f"/api/v1/field/progress/{other.id}")
        assert response.status_code in (403, 404), (
            f"他テナント(ORG_B)の出来形記録を 200 で返した: {response.status_code}"
        )

    def test_defect_update_progress_by_id_crosses_tenant(self, make_client):
        """DEF-FLD-06: 他テナントの出来形記録を更新できる。

        根拠: src/api/progress.py:174-186
        """
        other = _progress(ORG_B)
        client, _, _ = make_client(get_value=other)
        response = client.put(
            f"/api/v1/field/progress/{other.id}", json={"progress_percent": 99.0}
        )
        assert response.status_code in (403, 404), (
            f"他テナントの出来形記録を更新できた: {response.status_code}"
        )

    def test_defect_get_report_by_id_crosses_tenant(self, make_client):
        """DEF-FLD-07: 他テナントの作業日報をID指定で取得できる。

        根拠: src/api/reports.py:62-71
        """
        other = _report(ORG_B)
        client, _, _ = make_client(get_value=other)
        response = client.get(f"/api/v1/field/reports/{other.id}")
        assert response.status_code in (403, 404), (
            f"他テナントの日報を 200 で返した: {response.status_code}"
        )

    def test_defect_submit_report_crosses_tenant(self, make_client):
        """DEF-FLD-08: 他テナントの日報を提出（状態遷移）できる。

        根拠: src/api/reports.py:89-104
        """
        other = _report(ORG_B, status="draft")
        client, _, _ = make_client(get_value=other)
        response = client.post(f"/api/v1/field/reports/{other.id}/submit")
        assert response.status_code in (403, 404), (
            f"他テナントの日報を提出状態へ遷移できた: {response.status_code}"
        )

    def test_defect_approve_report_crosses_tenant(self, make_client):
        """DEF-FLD-09: 他テナントの日報を承認できる。

        根拠: src/api/reports.py:107-123
        """
        other = _report(ORG_B, status="submitted")
        client, _, _ = make_client(get_value=other)
        response = client.post(
            f"/api/v1/field/reports/{other.id}/approve?approved_by={OTHER_USER}"
        )
        assert response.status_code in (403, 404), (
            f"他テナントの日報を承認できた: {response.status_code}"
        )

    def test_defect_approver_identity_comes_from_query_not_token(self, make_client):
        """DEF-FLD-10: 承認者がクエリ引数で指定でき、トークン本人と一致しなくても通る。

        根拠: src/api/reports.py:113（approved_by: UUID = Query(...)）
        期待: 承認者(approved_by)はトークン sub から導出される（なりすまし不可）。
        影響: 承認の否認不能性が破綻（Q6 承認・証跡）。
        """
        report = _report(ORG_A, status="submitted")
        client, _, _ = make_client(get_value=report)
        response = client.post(
            f"/api/v1/field/reports/{report.id}/approve?approved_by={OTHER_USER}"
        )
        assert response.status_code == 200
        assert report.approved_by == uuid.UUID(USER_SUB), (
            "承認者がクエリ引数で上書きされた: "
            f"approved_by={report.approved_by} (トークン sub={USER_SUB})"
        )

    def test_defect_create_progress_accepts_foreign_org_in_body(self, make_client):
        """DEF-FLD-11: 作成時に request body の organization_id をそのまま採用する（Q2）。

        根拠: src/schemas/__init__.py:77（organization_id: UUID）
              src/api/progress.py:139-145（body をそのまま service へ）
              src/services/field_service.py:111-118
        期待: トークン org 以外の organization_id は 400/403。
        """
        client, _, _ = make_client()
        response = client.post(
            "/api/v1/field/progress",
            json={
                "organization_id": str(ORG_B),
                "project_id": str(PROJECT_B),
                "activity_name": "他社案件への書き込み",
                "status": "pending",
                "recorded_by": str(OTHER_USER),
            },
        )
        assert response.status_code in (400, 403), (
            f"他テナント(ORG_B)宛の出来形記録を作成できた: {response.status_code}"
        )

    def test_defect_create_report_accepts_foreign_org_in_body(self, make_client):
        """DEF-FLD-12: 日報作成でも body の organization_id をそのまま採用する（Q2）。

        根拠: src/schemas/__init__.py:13, src/api/reports.py:26-32
        """
        client, _, _ = make_client()
        response = client.post(
            "/api/v1/field/reports",
            json={
                "organization_id": str(ORG_B),
                "project_id": str(PROJECT_B),
                "report_date": "2026-05-24",
                "work_description": "他社案件への日報書き込み",
                "created_by": str(OTHER_USER),
            },
        )
        assert response.status_code in (400, 403), (
            f"他テナント(ORG_B)宛の日報を作成できた: {response.status_code}"
        )

    def test_defect_create_quality_accepts_foreign_org_in_body(self, make_client):
        """DEF-FLD-13: 品質チェック作成でも body の organization_id をそのまま採用する（Q2）。

        根拠: src/schemas/__init__.py:153, src/api/quality.py:111-122
        """
        client, _, _ = make_client()
        response = client.post(
            "/api/v1/field/quality",
            json={
                "organization_id": str(ORG_B),
                "project_id": str(PROJECT_B),
                "check_item": "他社案件への品質記録",
                "check_type": "dummy",
                "check_date": "2026-05-24",
                "inspector_id": str(OTHER_USER),
            },
        )
        assert response.status_code in (400, 403), (
            f"他テナント(ORG_B)宛の品質チェックを作成できた: {response.status_code}"
        )

    def test_defect_progress_summary_not_tenant_scoped(self, make_client):
        """DEF-FLD-14: 案件サマリが project_id だけで集計され、テナント検証が無い。

        根拠: src/api/progress.py:189-198, src/services/field_service.py:171-177
        期待: 他テナントの project_id を指定した場合もトークン org で絞る（または 404）。
        """
        client, statements, _ = make_client(items=[_progress(ORG_B)])
        response = client.get(f"/api/v1/field/progress/{PROJECT_B}/summary")
        assert response.status_code == 200
        where_sql = _org_where_all(statements)
        assert "organization_id" in where_sql, (
            f"テナント絞り込みなし / actual WHERE = {where_sql!r}"
        )

    def test_defect_quality_stats_not_tenant_scoped(self, make_client):
        """DEF-FLD-15: 品質統計が project_id だけで集計され、テナント検証が無い。

        根拠: src/api/quality.py:168-177, src/services/field_service.py:269-275
        """
        client, statements, _ = make_client(items=[_quality(ORG_B)])
        response = client.get(f"/api/v1/field/quality/{PROJECT_B}/stats")
        assert response.status_code == 200
        where_sql = _org_where_all(statements)
        assert "organization_id" in where_sql, (
            f"テナント絞り込みなし / actual WHERE = {where_sql!r}"
        )

    def test_defect_update_quality_crosses_tenant(self, make_client):
        """DEF-FLD-16: 他テナントの品質チェックを更新できる。

        根拠: src/api/quality.py:153-165
        """
        other = _quality(ORG_B)
        client, _, _ = make_client(get_value=other)
        response = client.put(
            f"/api/v1/field/quality/{other.id}", json={"status": "passed"}
        )
        assert response.status_code in (403, 404), (
            f"他テナントの品質チェックを更新できた: {response.status_code}"
        )

    def test_defect_jwt_key_resolution_differs_from_other_services(self):
        """DEF-FLD-17（是正済み回帰）: 3サービスで同一の鍵解決を使う。

        根拠: services/field-dx/src/middleware/auth.py は ``settings.jwt_public_key``
              （プロパティ）を検証鍵に使う（gis/bim と同一）。
        期待: 正規鍵で署名したトークンを検証でき、空鍵トークンは受理しない。
        注: PyJWT 2.14+ は空鍵での署名自体を拒否するため、生成できた場合のみ後段を検証する。
        """
        import warnings

        import jwt as pyjwt

        from src.config import get_settings
        from src.middleware.auth import decode_token

        settings = get_settings()
        canonical_key = settings.jwt_public_key  # 3サービス共通で使うべき鍵
        payload = {"sub": USER_SUB, "type": "user", "org": str(ORG_A), "exp": 9999999999}

        canonical_token = pyjwt.encode(payload, canonical_key, algorithm="HS256")
        assert decode_token(canonical_token) is not None, (
            "正規鍵(dev-only-do-not-use-in-production)で署名したトークンを "
            "field-dx が検証できない（他サービス gis/bim は検証できる）"
        )

        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                empty_key_token = pyjwt.encode(payload, "", algorithm="HS256")
        except Exception:
            # PyJWT 2.14+ は空鍵署名を拒否する（それ自体が偽造防止になる）
            empty_key_token = None

        if empty_key_token is not None:
            assert decode_token(empty_key_token) is None, (
                "空鍵で署名されたトークンを field-dx が受理した（鍵未設定時の偽造可能）"
            )


# =============================================================================
# 検証済み（現状で仕様を満たす）テスト
# =============================================================================
class TestTenantIsolationVerified:
    def test_ok_unauthenticated_is_rejected(self):
        """未認証は 401（認証境界そのものは有効）。"""
        client = TestClient(create_app(), raise_server_exceptions=False)
        for path in (
            "/api/v1/field/progress",
            "/api/v1/field/quality",
            "/api/v1/field/reports",
        ):
            assert client.get(path).status_code in (401, 403), path

    def test_ok_non_user_token_is_rejected(self):
        """type != user のトークンは 403（middleware の type 判定そのものの検証）。

        鍵解決の欠陥(DEF-FLD-17)に依存しないよう、実装が実際に使う鍵で署名する。
        """
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
            "/api/v1/field/progress",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 403

    def test_ok_list_response_total_matches_filtered_count(self, make_client):
        """一覧の meta(total/page/per_page) は service の戻り値と一致する（決定性）。"""
        client, _, _ = make_client(items=[_progress(ORG_A)], total=1)
        response = client.get("/api/v1/field/progress?page=1&per_page=20")
        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 1
        assert body["page"] == 1
        assert body["per_page"] == 20
        assert len(body["items"]) == 1
