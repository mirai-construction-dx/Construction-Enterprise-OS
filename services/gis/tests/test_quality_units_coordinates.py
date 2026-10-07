"""GIS: 緯度経度の範囲検証・座標参照系・単位の品質テスト（観点 Q4 / Q8）

仕様根拠と「未確認」の扱い
--------------------------
* リポジトリ内に測地系（JGD2011 / EPSG:6668 等）や精度・単位を規定した資料は発見できなかった。
  → **測地系規格は「未確認」**として扱い、名称・版を創作しない。
* コード上で確認できる事実: SQLAlchemy モデルは ``Geometry(..., srid=4326)`` を使用
  （src/models/__init__.py:35-40, 76-82, 110-113）、WKT 生成も ``SRID=4326`` を固定
  （src/services/geo_service.py:38-50）。したがって「コード上の SRID は 4326」までは断定できる。
* QA 用 PostgreSQL には PostGIS が導入されていないため（``select * from pg_extension`` が
  ``plpgsql`` のみ）、PostGIS 関数の距離解釈を**実測検証することはできなかった**。
  距離の単位に関する結論は「コードに geography キャストが無い」という事実に留める。

本ファイルの方針
----------------
* ``test_defect_*`` は仕様準拠の期待値を assert する。失敗 = 実装欠陥。
* DB は mock。実 PostgreSQL への書き込み・DDL は一切行わない。fixture は synthetic のみ。
"""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from src.main import create_app
from src.middleware.auth import TokenData, get_current_user
from src.models.base import get_db

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


def _where_clause(statement) -> str:
    sql = _sql(statement)
    marker = " WHERE "
    return sql.split(marker, 1)[1] if marker in sql else ""


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
        db.refresh = AsyncMock()

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


def _site_payload(**overrides):
    payload = {
        "organization_id": str(ORG_A),
        "name": "ダミー現場",
        "site_type": "building",
        "status": "active",
        "location": {"type": "Point", "coordinates": [DUMMY_LON, DUMMY_LAT]},
    }
    payload.update(overrides)
    return payload


# =============================================================================
# 欠陥検出テスト（失敗 = 欠陥）
# =============================================================================
class TestCoordinateAndUnitDefects:
    def test_defect_create_site_accepts_latitude_out_of_range(self, make_client):
        """DEF-GIS-15: 書き込み系の緯度に範囲検証が無く、lat=999 を受理する。

        根拠: src/schemas/__init__.py:38-41（GeoJSONGeometry.coordinates: Any、範囲制約なし）
              src/services/geo_service.py:32-52（値の検証なしで WKT 化）
              ※ 検索系は Query(ge=-90, le=90) で検証されている（src/api/sites.py:148-149）
        期待: 422。実際: 200 で受理し、範囲外座標をそのまま返す。
        """
        client, _, _ = make_client()
        response = client.post(
            "/api/v1/gis/sites",
            json=_site_payload(
                location={"type": "Point", "coordinates": [DUMMY_LON, 999.0]}
            ),
        )
        assert response.status_code == 422, (
            f"緯度 999.0 を受理した（書き込み系の範囲検証なし）: {response.status_code}"
        )

    def test_defect_create_site_accepts_longitude_out_of_range(self, make_client):
        """DEF-GIS-16: 書き込み系の経度に範囲検証が無く、lon=999 を受理する。

        根拠: src/schemas/__init__.py:38-41, src/services/geo_service.py:32-52
        期待: 422。実際: 200。
        """
        client, _, _ = make_client()
        response = client.post(
            "/api/v1/gis/sites",
            json=_site_payload(
                location={"type": "Point", "coordinates": [999.0, DUMMY_LAT]}
            ),
        )
        assert response.status_code == 422, (
            f"経度 999.0 を受理した（書き込み系の範囲検証なし）: {response.status_code}"
        )

    def test_defect_create_site_with_incomplete_point_returns_500(self, make_client):
        """DEF-GIS-17: 座標要素が不足した Point で IndexError が送出され 500 になる。

        根拠: src/services/geo_service.py:38（``coords[1]`` を検証なしで参照）
              src/api/main.py:66-78 の包括ハンドラが INTERNAL_ERROR に変換
        期待: 422（入力検証エラー）。実際: 500（未処理例外）。
        影響: 不正入力がサーバ内部エラーになり、監視ノイズと情報漏洩面を作る（Q8）。
        """
        client, _, _ = make_client(raise_server_exceptions=False)
        response = client.post(
            "/api/v1/gis/sites",
            json=_site_payload(
                location={"type": "Point", "coordinates": [DUMMY_LON]}
            ),
        )
        assert response.status_code == 422, (
            f"座標要素不足の Point が 500 になった（IndexError 未処理）: {response.status_code}"
        )

    def test_defect_nearby_radius_has_no_geography_cast(self, make_client):
        """DEF-GIS-18: radius_m（メートル）が geography キャスト無しで ST_DWithin に渡る。

        根拠: src/api/sites.py:154-162（半径の説明は "半径radius_m以内"）
              src/models/__init__.py:35-40（location は Geometry(srid=4326)）
              src/api/infrastructure.py:150-156（同型の呼び出し）
        期待: geography へのキャスト、または球面距離関数（ST_DistanceSphere 等）の使用。
        実際: ``ST_DWithin(location, ST_GeomFromText(...), :radius)`` を geometry 同士で評価。
        未確認: PostGIS 未導入の QA DB では距離単位（度/メートル）の実測ができなかったため、
               「半径がメートルとして扱われない」という数値的帰結は **未確認**（コード上の
               geography キャスト欠落のみを本テストの証拠とする）。
        """
        client, statements, _ = make_client(items=[])
        response = client.get(
            f"/api/v1/gis/sites/nearby?lat={DUMMY_LAT}&lng={DUMMY_LON}&radius_m=1000"
        )
        assert response.status_code == 200
        sql = _sql(statements[0]).lower()
        assert "geography" in sql, (
            "radius_m に geography キャスト/球面距離関数が無い "
            f"(geometry は SRID の座標単位で評価される) / actual SQL = {_sql(statements[0])}"
        )

    def test_defect_inverted_bounding_box_is_accepted(self, make_client):
        """DEF-GIS-19: min>max の逆転バウンディングボックスを受理する。

        根拠: src/api/sites.py:172-198（4値それぞれの範囲のみ検証し、大小関係を検証しない）
        期待: 422（min_lat<=max_lat / min_lng<=max_lng）。実際: 200。
        影響: 自己交差した POLYGON を ST_Intersects に渡し、検索結果が不定になる（Q8）。
        """
        client, _, _ = make_client(items=[])
        response = client.get(
            "/api/v1/gis/sites/in-area?min_lat=36.0&min_lng=140.0&max_lat=35.0&max_lng=139.0"
        )
        assert response.status_code == 422, (
            f"逆転した bbox(min>max)を受理した: {response.status_code}"
        )

    def test_defect_hazard_zone_risk_order_is_lexical_not_severity(self, make_client):
        """DEF-GIS-20: 危険区域の並び順が severity ではなく文字列辞書順になっている。

        根拠: src/api/areas.py:156 ``order_by(HazardZone.risk_level.desc())``
        症状: 文字列降順では "medium" > "low" > "high" > "critical" となり、
              最も危険な critical が最後に来る。
        期待: severity 順（critical → high → medium → low）。
        未確認: 並び順を規定したリポジトリ内資料は無いため、順序そのものは仕様未確認。
              ただしコードの意図（``.desc()`` = 危険度の高い順）とは矛盾する。
        """
        lexical_desc = sorted(["critical", "high", "medium", "low"], reverse=True)
        assert lexical_desc == ["critical", "high", "medium", "low"], (
            f"文字列降順の並びは {lexical_desc} であり severity 順にならない"
        )


# =============================================================================
# 検証済み（現状で仕様を満たす）テスト
# =============================================================================
class TestCoordinateAndUnitVerified:
    @pytest.mark.parametrize(
        "query",
        [
            "lat=91&lng=139.0",
            "lat=-91&lng=139.0",
            "lat=35.0&lng=181",
            "lat=35.0&lng=-181",
            "lat=35.0&lng=139.0&radius_m=0",
            "lat=35.0&lng=139.0&radius_m=-1",
        ],
    )
    def test_ok_nearby_rejects_out_of_range_params(self, make_client, query):
        """検索系 /nearby は Query(ge/le, gt) で範囲外を 422 にする（有効な検証）。"""
        client, statements, _ = make_client()
        response = client.get(f"/api/v1/gis/sites/nearby?{query}")
        assert response.status_code == 422
        assert statements == []  # DB へ到達していない

    @pytest.mark.parametrize(
        "query",
        [
            "min_lat=91&min_lng=139.0&max_lat=92&max_lng=140.0",
            "min_lat=35.0&min_lng=139.0&max_lat=36.0&max_lng=181",
        ],
    )
    def test_ok_in_area_rejects_out_of_range_params(self, make_client, query):
        """/in-area も各値の範囲外を 422 にする。"""
        client, statements, _ = make_client()
        response = client.get(f"/api/v1/gis/sites/in-area?{query}")
        assert response.status_code == 422
        assert statements == []

    def test_ok_wkt_generation_uses_srid_4326(self):
        """コード上の SRID は 4326（WGS84）。WKT 生成がそれを明示する。

        測地系規格（JGD2011/EPSG:6668 等）の採用はリポジトリ資料で確認できないため未確認。
        """
        from src.schemas import GeoJSONGeometry
        from src.services.geo_service import geojson_to_wkt

        geom = GeoJSONGeometry(type="Point", coordinates=[DUMMY_LON, DUMMY_LAT])
        assert geojson_to_wkt(geom) == "SRID=4326;POINT(139.0 35.0)"

    def test_ok_model_geometry_declares_srid_4326(self):
        """モデルのジオメトリ列が SRID=4326 を明示している（コード上の事実）。"""
        from src.models import ConstructionSite, HazardZone, Infrastructure

        assert ConstructionSite.__table__.c.location.type.srid == 4326
        assert ConstructionSite.__table__.c.work_area.type.srid == 4326
        assert Infrastructure.__table__.c.location.type.srid == 4326
        assert HazardZone.__table__.c.zone_area.type.srid == 4326

    def test_ok_response_has_no_crs_member_documented(self, make_client):
        """記録済み挙動: 応答 GeoJSON に crs メンバーは無い。

        RFC 7946 では GeoJSON の座標参照系は WGS84 固定とされ crs は削除されているため、
        これ自体は欠陥と断定しない（単位・測地系の応答明示は仕様未確認）。
        ただし応答から SRID を判別できないことは運用上の確認課題として残す。
        """
        from src.models import ConstructionSite

        from datetime import datetime, timezone

        site = ConstructionSite(
            id=uuid.uuid4(),
            organization_id=ORG_A,
            name="ダミー現場",
            location=f"SRID=4326;POINT({DUMMY_LON} {DUMMY_LAT})",
            status="active",
            metadata_={},
            created_at=datetime(2026, 5, 24, tzinfo=timezone.utc),
            updated_at=datetime(2026, 5, 24, tzinfo=timezone.utc),
        )
        client, _, _ = make_client(items=[site])
        body = client.get("/api/v1/gis/sites").json()
        assert "crs" not in body
        assert "crs" not in body["data"]
        feature = body["data"]["features"][0]
        assert feature["geometry"]["type"] == "Point"
        assert feature["geometry"]["coordinates"] == [DUMMY_LON, DUMMY_LAT]

    def test_ok_area_sqm_is_client_supplied_not_computed_documented(self, make_client):
        """記録済み挙動: area_sqm はクライアント申告値で、サーバ側の面積計算は無い。

        根拠: src/api/sites.py:99（body.area_sqm をそのまま保存）
        単位（m²）はフィールド名のみで保証されず、測量精度の仕様も未確認（創作しない）。
        幾何からの面積算出が無いことを記録する。
        """
        client, _, db = make_client()
        response = client.post(
            "/api/v1/gis/sites",
            json=_site_payload(
                work_area={
                    "type": "Polygon",
                    "coordinates": [
                        [
                            [139.0, 35.0],
                            [139.01, 35.0],
                            [139.01, 35.01],
                            [139.0, 35.01],
                            [139.0, 35.0],
                        ]
                    ]
                },
                area_sqm=12345.678,
            ),
        )
        assert response.status_code == 200
        saved = db.add.call_args[0][0]
        assert saved.area_sqm == pytest.approx(12345.678)
        props = response.json()["data"]["properties"]
        assert props["area_sqm"] == pytest.approx(12345.678)
        assert "unit" not in props  # 単位の明示は無い（仕様未確認）
