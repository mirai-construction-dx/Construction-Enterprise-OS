"""GIS: テナント分離・権限境界の品質テスト（観点 Q1 / Q2）

仕様根拠
--------
* docs/architecture/ADR-0001-ceos-responsibility-boundary.md:44
  「認可は **組織（テナント）＋案件（project）＋ロール**で行い、API 到達性は公開 API の契約に従う。」
* docs/architecture/01-auth-platform.md:28 行レベルセキュリティ（プロジェクト単位の参照制限）
* docs/architecture/01-auth-platform.md:33 組織管理 P0（会社→事業部→現場の階層構造）

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
SITE_B = uuid.UUID("00000000-0000-0000-0000-0000000000e1")
INFRA_B = uuid.UUID("00000000-0000-0000-0000-0000000000e2")
ZONE_B = uuid.UUID("00000000-0000-0000-0000-0000000000e3")
USER_SUB = "00000000-0000-0000-0000-0000000000dd"
_NOW = datetime(2026, 5, 24, 9, 0, 0, tzinfo=timezone.utc)

# 明らかに架空のダミー座標（実在構造物の座標ではない）
DUMMY_POINT = "SRID=4326;POINT(139.0000 35.0000)"
DUMMY_POLY = (
    "SRID=4326;POLYGON((139.0000 35.0000, 139.0100 35.0000, "
    "139.0100 35.0100, 139.0000 35.0100, 139.0000 35.0000))"
)


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
        """``results`` に execute 呼び出しごとの応答を並べると、複数クエリの
        エンドポイント（site 取得 → 近傍検索 等）を正確に模擬できる。
        指定が尽きたら最後の要素を繰り返す。
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
                    items=spec.get("items"), total=spec.get("total", 0)
                )
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


def _site(org_id: uuid.UUID, site_id: uuid.UUID = SITE_B):
    from src.models import ConstructionSite

    return ConstructionSite(
        id=site_id,
        organization_id=org_id,
        name="ダミー現場",
        location=DUMMY_POINT,
        status="active",
        metadata_={},
        created_at=_NOW,
        updated_at=_NOW,
    )


def _infra(org_id: uuid.UUID, infra_id: uuid.UUID = INFRA_B):
    from src.models import Infrastructure

    return Infrastructure(
        id=infra_id,
        organization_id=org_id,
        name="ダミー設備",
        infra_type="dummy",
        location=DUMMY_POINT,
        status="active",
        metadata_={},
        created_at=_NOW,
        updated_at=_NOW,
    )


def _zone(org_id: uuid.UUID, zone_id: uuid.UUID = ZONE_B):
    from src.models import HazardZone

    return HazardZone(
        id=zone_id,
        organization_id=org_id,
        name="ダミー危険区域",
        hazard_type="dummy",
        zone_area=DUMMY_POLY,
        risk_level="high",
        metadata_={},
        created_at=_NOW,
    )


# =============================================================================
# 欠陥検出テスト（失敗 = 欠陥）
# =============================================================================
class TestTenantIsolationDefects:
    def test_defect_list_sites_is_not_tenant_scoped(self, make_client):
        """DEF-GIS-01: 現場一覧がトークン組織で絞り込まれていない（全社横断の読み取り）。

        根拠: src/api/sites.py:111-143（site_type / status のみで where。organization_id 条件なし）
        期待: WHERE 句に organization_id が含まれる。
        """
        client, statements, _ = make_client(items=[_site(ORG_B)])
        response = client.get("/api/v1/gis/sites")
        assert response.status_code == 200
        where_sql = _org_where_all(statements)
        assert "organization_id" in where_sql, (
            f"テナント絞り込みなし / actual WHERE = {where_sql!r}"
        )

    def test_defect_nearby_search_is_not_tenant_scoped(self, make_client):
        """DEF-GIS-02: /nearby（空間検索）がトークン組織で絞り込まれていない。

        根拠: src/api/sites.py:146-169
        """
        client, statements, _ = make_client(items=[_site(ORG_B)])
        response = client.get("/api/v1/gis/sites/nearby?lat=35.0&lng=139.0&radius_m=1000")
        assert response.status_code == 200
        where_sql = _org_where_all(statements)
        assert "organization_id" in where_sql, (
            f"テナント絞り込みなし / actual WHERE = {where_sql!r}"
        )

    def test_defect_in_area_search_is_not_tenant_scoped(self, make_client):
        """DEF-GIS-03: /in-area（範囲検索）がトークン組織で絞り込まれていない。

        根拠: src/api/sites.py:172-198
        """
        client, statements, _ = make_client(items=[_site(ORG_B)])
        response = client.get(
            "/api/v1/gis/sites/in-area?min_lat=35.0&min_lng=139.0&max_lat=35.1&max_lng=139.1"
        )
        assert response.status_code == 200
        where_sql = _org_where_all(statements)
        assert "organization_id" in where_sql, (
            f"テナント絞り込みなし / actual WHERE = {where_sql!r}"
        )

    def test_defect_get_site_crosses_tenant(self, make_client):
        """DEF-GIS-04: 他テナントの現場をID指定で取得できる。

        根拠: src/api/sites.py:201-216（id のみで検索）
        """
        client, _, _ = make_client(items=[_site(ORG_B)])
        response = client.get(f"/api/v1/gis/sites/{SITE_B}")
        assert response.status_code in (403, 404), (
            f"他テナント(ORG_B)の現場を 200 で返した: {response.status_code}"
        )

    def test_defect_update_site_crosses_tenant(self, make_client):
        """DEF-GIS-05: 他テナントの現場を更新できる。

        根拠: src/api/sites.py:219-251
        """
        client, _, _ = make_client(items=[_site(ORG_B)])
        response = client.put(f"/api/v1/gis/sites/{SITE_B}", json={"name": "改ざん"})
        assert response.status_code in (403, 404), (
            f"他テナントの現場を更新できた: {response.status_code}"
        )

    def test_defect_delete_site_crosses_tenant(self, make_client):
        """DEF-GIS-06: 他テナントの現場を削除できる。

        根拠: src/api/sites.py:254-271
        """
        client, _, db = make_client(items=[_site(ORG_B)])
        response = client.delete(f"/api/v1/gis/sites/{SITE_B}")
        assert response.status_code in (403, 404), (
            f"他テナントの現場を削除できた: {response.status_code}"
        )

    def test_defect_create_site_accepts_foreign_org_in_body(self, make_client):
        """DEF-GIS-07: 現場作成で body の organization_id をそのまま採用する（Q2）。

        根拠: src/schemas/__init__.py:61（organization_id: UUID）
              src/api/sites.py:88-104（body.organization_id を保存）
        期待: トークン org 以外は 400/403。
        """
        client, _, _ = make_client()
        response = client.post(
            "/api/v1/gis/sites",
            json={
                "organization_id": str(ORG_B),
                "name": "他社テナント宛の現場",
                "location": {"type": "Point", "coordinates": [139.0, 35.0]},
            },
        )
        assert response.status_code in (400, 403), (
            f"他テナント(ORG_B)宛の現場を作成できた: {response.status_code}"
        )

    def test_defect_list_infrastructure_is_not_tenant_scoped(self, make_client):
        """DEF-GIS-08: インフラ設備一覧がテナント絞り込みされていない。

        根拠: src/api/infrastructure.py:93-129
        """
        client, statements, _ = make_client(items=[_infra(ORG_B)])
        response = client.get("/api/v1/gis/infrastructure")
        assert response.status_code == 200
        where_sql = _org_where_all(statements)
        assert "organization_id" in where_sql, (
            f"テナント絞り込みなし / actual WHERE = {where_sql!r}"
        )

    def test_defect_infrastructure_near_site_is_not_tenant_scoped(self, make_client):
        """DEF-GIS-09: /near-site が現場の所有組織を検証していない。

        根拠: src/api/infrastructure.py:132-163（site を id だけで取得し、無条件に近傍検索）
        期待: 現場取得の WHERE 句に organization_id が含まれる。
        """
        client, statements, _ = make_client(
            results=[{"items": [_site(ORG_B)]}, {"items": []}]
        )
        response = client.get(f"/api/v1/gis/infrastructure/near-site/{SITE_B}")
        assert response.status_code == 200
        first_where = _org_where_all(statements)
        assert "organization_id" in first_where, (
            f"現場の所有組織を検証していない / actual WHERE = {first_where!r}"
        )

    def test_defect_get_infrastructure_crosses_tenant(self, make_client):
        """DEF-GIS-10: 他テナントのインフラ設備を取得できる。

        根拠: src/api/infrastructure.py:166-181
        """
        client, _, _ = make_client(items=[_infra(ORG_B)])
        response = client.get(f"/api/v1/gis/infrastructure/{INFRA_B}")
        assert response.status_code in (403, 404), (
            f"他テナントの設備を 200 で返した: {response.status_code}"
        )

    def test_defect_list_hazard_zones_is_not_tenant_scoped(self, make_client):
        """DEF-GIS-11: 危険区域一覧がテナント絞り込みされていない。

        根拠: src/api/areas.py:91-123
        """
        client, statements, _ = make_client(items=[_zone(ORG_B)])
        response = client.get("/api/v1/gis/hazard-zones")
        assert response.status_code == 200
        where_sql = _org_where_all(statements)
        assert "organization_id" in where_sql, (
            f"テナント絞り込みなし / actual WHERE = {where_sql!r}"
        )

    def test_defect_intersecting_zones_is_not_tenant_scoped(self, make_client):
        """DEF-GIS-12: /intersecting/{site_id} が現場の所有組織を検証していない。

        根拠: src/api/areas.py:126-162（site を id だけで取得し、zone 側にも org 条件なし）
        """
        site = _site(ORG_B)
        site.work_area = DUMMY_POLY  # 現場ポリゴン有り → 危険区域検索まで到達させる
        client, statements, _ = make_client(
            results=[{"items": [site]}, {"items": []}]
        )
        response = client.get(f"/api/v1/gis/hazard-zones/intersecting/{SITE_B}")
        assert response.status_code == 200
        assert len(statements) == 2, "現場取得と危険区域検索の2クエリを想定"
        unscoped = [
            where
            for where in (_where_clause(s) for s in statements)
            if "organization_id" not in where
        ]
        assert not unscoped, (
            f"テナント絞り込みの無いクエリが存在する / actual WHERE = {unscoped}"
        )

    def test_defect_get_hazard_zone_crosses_tenant(self, make_client):
        """DEF-GIS-13: 他テナントの危険区域を取得できる。

        根拠: src/api/areas.py:165-180
        """
        client, _, _ = make_client(items=[_zone(ORG_B)])
        response = client.get(f"/api/v1/gis/hazard-zones/{ZONE_B}")
        assert response.status_code in (403, 404), (
            f"他テナントの危険区域を 200 で返した: {response.status_code}"
        )

    def test_defect_update_hazard_zone_crosses_tenant(self, make_client):
        """DEF-GIS-14: 他テナントの危険区域を更新できる。

        根拠: src/api/areas.py:183-211
        """
        client, _, _ = make_client(items=[_zone(ORG_B)])
        response = client.put(
            f"/api/v1/gis/hazard-zones/{ZONE_B}", json={"risk_level": "low"}
        )
        assert response.status_code in (403, 404), (
            f"他テナントの危険区域を更新できた: {response.status_code}"
        )


# =============================================================================
# 検証済み（現状で仕様を満たす）テスト
# =============================================================================
class TestTenantIsolationVerified:
    def test_ok_unauthenticated_is_rejected(self):
        """未認証は 401（認証境界そのものは有効）。"""
        client = TestClient(create_app(), raise_server_exceptions=False)
        for path in (
            "/api/v1/gis/sites",
            "/api/v1/gis/sites/nearby?lat=35.0&lng=139.0&radius_m=1000",
            "/api/v1/gis/infrastructure",
            "/api/v1/gis/hazard-zones",
        ):
            assert client.get(path).status_code in (401, 403), path

    def test_ok_invalid_token_is_rejected(self):
        """改竄/不正トークンは 401。"""
        client = TestClient(create_app(), raise_server_exceptions=False)
        response = client.get(
            "/api/v1/gis/sites", headers={"Authorization": "Bearer not-a-jwt"}
        )
        assert response.status_code == 401

    def test_ok_geojson_features_expose_organization_id(self, make_client):
        """応答 Feature の properties に organization_id が含まれる（監査可能性）。

        テナント絞り込みの欠落(DEF-GIS-01..14)の影響範囲を確認するための記録。
        """
        client, _, _ = make_client(items=[_site(ORG_B)])
        body = client.get("/api/v1/gis/sites").json()
        feature = body["data"]["features"][0]
        assert feature["properties"]["organization_id"] == str(ORG_B)
