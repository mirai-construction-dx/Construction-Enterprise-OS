"""#133: radius_m（メートル）評価と location: null の入力検証（回帰テスト）

対象欠陥:
* ``/sites/nearby`` と ``/infrastructure/near-site`` の ``ST_DWithin`` が
  SRID=4326 の geometry 同士で評価され、``radius_m`` が「度」として解釈される。
  -> 両オペランドを geography にキャストしてメートル評価にする。
* ``PUT`` で ``location: null`` を送ると ``geojson_to_wkt(None)`` が
  AttributeError を送出し 500 になる。 -> 422 を返す。

実 PostgreSQL / PostGIS は QA 環境に無いため、距離の数値境界そのものは実測できない。
本ファイルは「メートル評価を保証する SQL 形状（geography キャスト）」と
「radius_m の入力境界」を検証する。数値距離の実測ができないことは残課題として明記する。
"""

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from src.main import create_app
from src.middleware.auth import TokenData, get_current_user
from src.models.base import get_db
from src.models import ConstructionSite, Infrastructure

ORG_A = uuid.UUID("00000000-0000-0000-0000-0000000000aa")
USER_SUB = "00000000-0000-0000-0000-0000000000dd"

# 明らかに架空のダミー座標（実在構造物の座標ではない）
DUMMY_LAT = 35.0
DUMMY_LON = 139.0


def _sql(statement) -> str:
    try:
        return " ".join(str(statement.compile()).split())
    except Exception as exc:  # pragma: no cover - 診断用
        return f"<compile failed: {exc}>"


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


def _make_site() -> ConstructionSite:
    return ConstructionSite(
        id=uuid.uuid4(),
        organization_id=ORG_A,
        name="ダミー現場",
        location=f"SRID=4326;POINT({DUMMY_LON} {DUMMY_LAT})",
        status="active",
        metadata_={},
        created_at=datetime(2026, 5, 24, tzinfo=timezone.utc),
        updated_at=datetime(2026, 5, 24, tzinfo=timezone.utc),
    )


def _make_infrastructure() -> Infrastructure:
    return Infrastructure(
        id=uuid.uuid4(),
        organization_id=ORG_A,
        name="ダミー設備",
        infra_type="water",
        location=f"SRID=4326;POINT({DUMMY_LON} {DUMMY_LAT})",
        status="active",
        metadata_={},
        created_at=datetime(2026, 5, 24, tzinfo=timezone.utc),
        updated_at=datetime(2026, 5, 24, tzinfo=timezone.utc),
    )


@pytest.fixture
def make_client():
    def _factory(*, results=None):
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
                return _FakeResult(items=spec.get("items"), total=spec.get("total", 0))
            return _FakeResult()

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
        return TestClient(app), statements, db

    return _factory


# =============================================================================
# 距離評価: geography キャスト（メートル評価）の回帰
# =============================================================================
class TestDistanceIsEvaluatedInMetres:
    def test_infrastructure_near_site_uses_geography_cast(self, make_client):
        """/infrastructure/near-site の ST_DWithin は両オペランドを geography にする。

        geometry 同士の ST_DWithin では radius_m が座標単位（度）として解釈されるため、
        geography キャストが無い実装はメートル評価にならない。
        """
        site = _make_site()
        client, statements, _ = make_client(
            results=[{"items": [site]}, {"items": []}]
        )
        response = client.get(
            f"/api/v1/gis/infrastructure/near-site/{site.id}?radius_m=1000"
        )
        assert response.status_code == 200
        assert len(statements) == 2, "現場取得と近接設備検索の2クエリを想定"
        sql = _sql(statements[1]).lower()
        assert sql.count("geography") >= 2, (
            "ST_DWithin の両オペランドが geography にキャストされていない "
            f"(geometry は SRID の座標単位で評価される) / actual SQL = {_sql(statements[1])}"
        )

    def test_near_site_passes_radius_metres_to_geography_query(self, make_client):
        """radius_m の値がそのまま（メートルとして）距離式へ渡る。"""
        site = _make_site()
        client, statements, _ = make_client(
            results=[{"items": [site]}, {"items": []}]
        )
        response = client.get(
            f"/api/v1/gis/infrastructure/near-site/{site.id}?radius_m=250"
        )
        assert response.status_code == 200
        compiled = statements[1].compile()
        assert 250.0 in compiled.params.values(), (
            "radius_m が距離式のパラメータとして渡っていない "
            f"/ params = {sorted(compiled.params.values(), key=str)}"
        )

    def test_sites_nearby_uses_geography_cast(self, make_client):
        """/sites/nearby も geography キャストを維持している（回帰防止）。"""
        client, statements, _ = make_client()
        response = client.get(
            f"/api/v1/gis/sites/nearby?lat={DUMMY_LAT}&lng={DUMMY_LON}&radius_m=1000"
        )
        assert response.status_code == 200
        sql = _sql(statements[0]).lower()
        assert "geography" in sql, (
            "sites/nearby の geography キャストが失われている "
            f"/ actual SQL = {_sql(statements[0])}"
        )

    @pytest.mark.parametrize("radius", ["0", "-1"])
    def test_near_site_rejects_non_positive_radius(self, make_client, radius):
        """radius_m の境界: 0 と負値は 422（DB へ到達しない）。"""
        client, statements, _ = make_client()
        response = client.get(
            f"/api/v1/gis/infrastructure/near-site/{uuid.uuid4()}?radius_m={radius}"
        )
        assert response.status_code == 422
        assert statements == []


# =============================================================================
# PUT location: null は 422（500 にしない）
# =============================================================================
class TestUpdateLocationNull:
    def test_update_site_with_null_location_returns_422(self, make_client):
        """PUT /sites/{id} に location: null を送ると 422。

        修正前は geojson_to_wkt(None) が AttributeError を送出し、包括ハンドラが
        500 (INTERNAL_ERROR) に変換していた。
        """
        site = _make_site()
        client, _, _ = make_client(results=[{"items": [site]}])
        response = client.put(
            f"/api/v1/gis/sites/{site.id}", json={"location": None}
        )
        assert response.status_code == 422, (
            f"location: null が 422 でなく {response.status_code} になった "
            f"/ body = {str(response.json())[:200]}"
        )

    def test_update_infrastructure_with_null_location_returns_422(self, make_client):
        """PUT /infrastructure/{id} に location: null を送ると 422。"""
        infra = _make_infrastructure()
        client, _, _ = make_client(results=[{"items": [infra]}])
        response = client.put(
            f"/api/v1/gis/infrastructure/{infra.id}", json={"location": None}
        )
        assert response.status_code == 422, (
            f"location: null が 422 でなく {response.status_code} になった "
            f"/ body = {str(response.json())[:200]}"
        )

    def test_update_site_with_valid_location_still_succeeds(self, make_client):
        """有効な location の更新は従来どおり成功する（回帰防止）。"""
        site = _make_site()
        client, _, _ = make_client(results=[{"items": [site]}])
        response = client.put(
            f"/api/v1/gis/sites/{site.id}",
            json={"location": {"type": "Point", "coordinates": [139.1, 35.1]}},
        )
        assert response.status_code == 200
        assert response.json()["data"]["geometry"]["coordinates"] == [139.1, 35.1]
