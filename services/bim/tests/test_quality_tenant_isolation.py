"""BIM/CIM: テナント分離・権限境界の品質テスト（観点 Q1 / Q2 / Q5）

仕様根拠
--------
* docs/architecture/ADR-0001-ceos-responsibility-boundary.md:44
  「認可は **組織（テナント）＋案件（project）＋ロール**で行い、API 到達性は公開 API の契約に従う。」
* docs/api/overview.md:87
  「bim: `/api/v1/bim/{model_id}/elements`・`/elements/search`・`/pointcloud`」

本ファイルの方針
----------------
* ``test_defect_*`` は **仕様準拠の期待値を assert する**。失敗 = 実装欠陥。
* テナント絞り込みは SQL の **WHERE 句のみ** を対象に判定する。
* DB は mock。実 PostgreSQL・外部接続・ネットワークなし。fixture は synthetic のみ。
"""

import uuid
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from src.main import create_app
from src.middleware.auth import TokenData, get_current_user
from src.models.base import get_db

ORG_A = uuid.UUID("00000000-0000-0000-0000-0000000000aa")  # トークン保有組織
ORG_B = uuid.UUID("00000000-0000-0000-0000-0000000000bb")  # 他テナント
MODEL_B = uuid.UUID("00000000-0000-0000-0000-0000000000e1")
ELEMENT_B = uuid.UUID("00000000-0000-0000-0000-0000000000e2")
POINTCLOUD_B = uuid.UUID("00000000-0000-0000-0000-0000000000e3")
PROJECT_B = uuid.UUID("00000000-0000-0000-0000-0000000000e4")
USER_SUB = "00000000-0000-0000-0000-0000000000dd"
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
    for attr in ("created_at", "updated_at"):
        if hasattr(obj, attr) and getattr(obj, attr) is None:
            setattr(obj, attr, _NOW)
    if hasattr(obj, "status") and getattr(obj, "status", None) is None:
        setattr(obj, "status", "draft")
    if hasattr(obj, "is_colorized") and getattr(obj, "is_colorized", None) is None:
        setattr(obj, "is_colorized", False)
    if hasattr(obj, "is_classified") and getattr(obj, "is_classified", None) is None:
        setattr(obj, "is_classified", False)
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
    def _factory(
        *, items=None, total=0, results=None, raise_server_exceptions: bool = True
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

        async def _execute(statement, *args, **kwargs):
            statements.append(statement)
            if results:
                index = min(len(statements) - 1, len(results) - 1)
                spec = results[index]
                return _FakeResult(items=spec.get("items"), total=spec.get("total", 0))
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


def _model(org_id: uuid.UUID, model_id: uuid.UUID = MODEL_B, version="v1"):
    from src.models import BIMModel

    return BIMModel(
        id=model_id,
        organization_id=org_id,
        project_id=PROJECT_B,
        name="ダミーモデル",
        model_type="architecture",
        file_format="ifc",
        version=version,
        status="draft",
        tags=[],
        metadata_={},
        created_at=_NOW,
        updated_at=_NOW,
    )


def _element(model_id: uuid.UUID = MODEL_B, element_id: uuid.UUID = ELEMENT_B):
    from src.models import BIMElement

    return BIMElement(
        id=element_id,
        model_id=model_id,
        name="ダミー要素",
        element_type="wall",
        category="walls",
        properties={},
        created_at=_NOW,
    )


def _pointcloud(org_id: uuid.UUID, pc_id: uuid.UUID = POINTCLOUD_B):
    from src.models import PointCloud

    return PointCloud(
        id=pc_id,
        organization_id=org_id,
        project_id=PROJECT_B,
        name="ダミー点群",
        capture_method="laser_scan",
        capture_date=date(2026, 5, 20),
        point_count=1000,
        coordinate_system="EPSG:4326",
        is_colorized=False,
        is_classified=False,
        metadata_={},
        created_at=_NOW,
    )


# =============================================================================
# 欠陥検出テスト（失敗 = 欠陥）
# =============================================================================
class TestTenantIsolationDefects:
    def test_defect_list_models_is_not_tenant_scoped(self, make_client):
        """DEF-BIM-01: モデル一覧がトークン組織で絞り込まれていない。

        根拠: src/services/bim_service.py:70-99（model_type/status/project_id のみ）
              src/api/models.py:47-67
        期待: WHERE 句に organization_id が含まれる。
        """
        client, statements, _ = make_client(items=[_model(ORG_B)])
        response = client.get("/api/v1/bim/models")
        assert response.status_code == 200
        where_sql = _org_where_all(statements)
        assert "organization_id" in where_sql, (
            f"テナント絞り込みなし / actual WHERE = {where_sql!r}"
        )

    def test_defect_get_model_crosses_tenant(self, make_client):
        """DEF-BIM-02: 他テナントのBIMモデルを取得できる。

        根拠: src/services/bim_service.py:102-104（id のみで取得）
        """
        client, _, _ = make_client(items=[_model(ORG_B)])
        response = client.get(f"/api/v1/bim/models/{MODEL_B}")
        assert response.status_code in (403, 404), (
            f"他テナント(ORG_B)のモデルを 200 で返した: {response.status_code}"
        )

    def test_defect_update_model_crosses_tenant(self, make_client):
        """DEF-BIM-03: 他テナントのBIMモデルを更新できる。

        根拠: src/services/bim_service.py:107-123, src/api/models.py:85-98
        """
        client, _, _ = make_client(items=[_model(ORG_B)])
        response = client.put(
            f"/api/v1/bim/models/{MODEL_B}", json={"name": "改ざん"}
        )
        assert response.status_code in (403, 404), (
            f"他テナントのモデルを更新できた: {response.status_code}"
        )

    def test_defect_delete_model_crosses_tenant(self, make_client):
        """DEF-BIM-04: 他テナントのBIMモデルを削除できる。

        根拠: src/services/bim_service.py:126-132, src/api/models.py:101-113
        """
        client, _, _ = make_client(items=[_model(ORG_B)])
        response = client.delete(f"/api/v1/bim/models/{MODEL_B}")
        assert response.status_code in (403, 404), (
            f"他テナントのモデルを削除できた: {response.status_code}"
        )

    def test_defect_create_model_accepts_foreign_org_in_body(self, make_client):
        """DEF-BIM-05: モデル作成で body の organization_id をそのまま採用する（Q2）。

        根拠: src/schemas/__init__.py:42, src/services/bim_service.py:40-67
        期待: トークン org 以外は 400/403。
        """
        client, _, _ = make_client()
        response = client.post(
            "/api/v1/bim/models",
            json={
                "organization_id": str(ORG_B),
                "name": "他社テナント宛のモデル",
                "model_type": "architecture",
                "file_format": "ifc",
            },
        )
        assert response.status_code in (400, 403), (
            f"他テナント(ORG_B)宛のモデルを作成できた: {response.status_code}"
        )

    def test_defect_list_elements_is_not_tenant_scoped(self, make_client):
        """DEF-BIM-06: 要素一覧が model_id だけで絞られ、モデルの所有組織を検証しない。

        根拠: src/api/elements.py:30-64（モデル存在確認も organization 条件も無い）
        期待: 親モデルの所有組織で絞る（または 403/404）。
        """
        client, statements, _ = make_client(
            results=[{"items": [_element()], "total": 1}]
        )
        response = client.get(f"/api/v1/bim/{MODEL_B}/elements")
        assert response.status_code == 200
        unscoped = [
            where
            for where in (_where_clause(s) for s in statements)
            if "organization_id" not in where
        ]
        assert not unscoped, (
            f"テナント絞り込みの無いクエリが存在する / actual WHERE = {unscoped}"
        )

    def test_defect_get_element_crosses_tenant(self, make_client):
        """DEF-BIM-07: 他テナントのモデルに属する要素を取得できる。

        根拠: src/api/elements.py:67-82（要素IDのみで検索。要素に organization_id が無く
              親モデルへの join も無い）
        """
        client, _, _ = make_client(items=[_element(model_id=MODEL_B)])
        response = client.get(f"/api/v1/bim/elements/{ELEMENT_B}")
        assert response.status_code in (403, 404), (
            f"他テナントの要素を 200 で返した: {response.status_code}"
        )

    def test_defect_list_pointclouds_is_not_tenant_scoped(self, make_client):
        """DEF-BIM-08: 点群一覧がトークン組織で絞り込まれていない。

        根拠: src/api/pointcloud.py:64-95（project_id/capture_method のみ）
        """
        client, statements, _ = make_client(items=[_pointcloud(ORG_B)])
        response = client.get("/api/v1/bim/pointclouds")
        assert response.status_code == 200
        where_sql = _org_where_all(statements)
        assert "organization_id" in where_sql, (
            f"テナント絞り込みなし / actual WHERE = {where_sql!r}"
        )

    def test_defect_get_pointcloud_crosses_tenant(self, make_client):
        """DEF-BIM-09: 他テナントの点群を取得できる。

        根拠: src/api/pointcloud.py:98-113
        """
        client, _, _ = make_client(items=[_pointcloud(ORG_B)])
        response = client.get(f"/api/v1/bim/pointclouds/{POINTCLOUD_B}")
        assert response.status_code in (403, 404), (
            f"他テナントの点群を 200 で返した: {response.status_code}"
        )

    def test_defect_update_pointcloud_crosses_tenant(self, make_client):
        """DEF-BIM-10: 他テナントの点群を更新できる。

        根拠: src/api/pointcloud.py:116-142
        """
        client, _, _ = make_client(items=[_pointcloud(ORG_B)])
        response = client.put(
            f"/api/v1/bim/pointclouds/{POINTCLOUD_B}", json={"name": "改ざん"}
        )
        assert response.status_code in (403, 404), (
            f"他テナントの点群を更新できた: {response.status_code}"
        )

    def test_defect_delete_pointcloud_crosses_tenant(self, make_client):
        """DEF-BIM-11: 他テナントの点群を削除できる。

        根拠: src/api/pointcloud.py:145-162
        """
        client, _, _ = make_client(items=[_pointcloud(ORG_B)])
        response = client.delete(f"/api/v1/bim/pointclouds/{POINTCLOUD_B}")
        assert response.status_code in (403, 404), (
            f"他テナントの点群を削除できた: {response.status_code}"
        )

    def test_defect_create_pointcloud_accepts_foreign_org_in_body(self, make_client):
        """DEF-BIM-12: 点群作成で body の organization_id をそのまま採用する（Q2）。

        根拠: src/api/pointcloud.py:32-61
        """
        client, _, _ = make_client()
        response = client.post(
            "/api/v1/bim/pointclouds",
            json={
                "organization_id": str(ORG_B),
                "name": "他社テナント宛の点群",
            },
        )
        assert response.status_code in (400, 403), (
            f"他テナント(ORG_B)宛の点群を作成できた: {response.status_code}"
        )


# =============================================================================
# 検証済み（現状で仕様を満たす）テスト
# =============================================================================
class TestTenantIsolationVerified:
    def test_ok_unauthenticated_is_rejected(self):
        """未認証は 401（認証境界そのものは有効）。"""
        client = TestClient(create_app(), raise_server_exceptions=False)
        for path in (
            "/api/v1/bim/models",
            f"/api/v1/bim/{MODEL_B}/elements",
            "/api/v1/bim/pointclouds",
        ):
            assert client.get(path).status_code in (401, 403), path

    def test_ok_elements_search_is_tenant_scoped(self, make_client):
        """DEF-BIM-13 修正後: /elements/search は到達可能かつテナント絞り込み済み。

        ルーティング衝突（/elements/{element_id} に先に一致して 422）を解消したため、
        ここで search のテナント絞り込みを検証する（旧「未確認の記録」を更新）。
        """
        client, statements, _ = make_client(items=[])
        response = client.get("/api/v1/bim/elements/search?q=wall")
        assert response.status_code == 200, (
            f"要素検索が到達不能（ルーティング衝突）: status={response.status_code}"
        )
        where_sql = _org_where_all(statements)
        assert "organization_id" in where_sql, (
            f"search にテナント絞り込みがない / actual WHERE = {where_sql!r}"
        )
