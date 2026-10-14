"""BIM/CIM: 版管理・要素ツリー・点群の座標系/出典の品質テスト（観点 Q4 / Q5 / Q8）

仕様根拠と「未確認」の扱い
--------------------------
* docs/api/overview.md:87 「bim: `/api/v1/bim/{model_id}/elements`・`/elements/search`・`/pointcloud`」
  → ``/elements/search`` は公開 API 契約として文書化されている。
* docs/みらい建設土木DX・AI統合基盤 全体構成 V3.5.html:326
  「3D再構築物（点群・メッシュ・カメラ軌跡）… 元動画ID、処理手法、座標系、精度、生成版を保持」
  → 点群に求められるメタデータ（処理手法・座標系・精度・生成版・元動画ID）の参考仕様。
  ただし同表は ArcSphere Civil Twin / MCIP・MCAH 側の保持項目であり、
  本サービスの必須要件として明記された資料は見つかっていない → 必須性は **未確認**。
* 測地系（JGD2011 / EPSG:6668 等）の採用を規定したリポジトリ内資料は無い → **未確認**。
  コード上で確認できるのは ``srid=4326`` の使用のみ。

本ファイルの方針
----------------
* ``test_defect_*`` は仕様準拠の期待値を assert する。失敗 = 実装欠陥。
* 実装が存在しない機能（要素ツリー等）は「未確認/未実装」として記録し、欠陥と断定しない。
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
MODEL_A = uuid.UUID("00000000-0000-0000-0000-0000000000e1")
ELEMENT_A = uuid.UUID("00000000-0000-0000-0000-0000000000e2")
PC_A = uuid.UUID("00000000-0000-0000-0000-0000000000e3")
USER_SUB = "00000000-0000-0000-0000-0000000000dd"
_NOW = datetime(2026, 5, 24, 9, 0, 0, tzinfo=timezone.utc)


def _auto_refresh(obj):
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
    def _factory(*, items=None, total=0, results=None, raise_server_exceptions=True):
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
            return TokenData(sub=USER_SUB, type="user", org=str(ORG_A), roles=["bim_manager"])

        app.dependency_overrides[get_db] = _get_db
        app.dependency_overrides[get_current_user] = _current_user
        return (
            TestClient(app, raise_server_exceptions=raise_server_exceptions),
            statements,
            db,
        )

    return _factory


def _model_body(**overrides):
    body = {
        "organization_id": str(ORG_A),
        "name": "ダミーモデル",
        "model_type": "architecture",
        "file_format": "ifc",
    }
    body.update(overrides)
    return body


# =============================================================================
# 欠陥検出テスト（失敗 = 欠陥）
# =============================================================================
class TestVersionAndRoutingDefects:
    def test_defect_elements_search_route_is_shadowed(self, make_client):
        """DEF-BIM-13: 文書化された /elements/search がルーティング衝突で到達不能。

        根拠: src/api/elements.py:30（``/{model_id}/elements``）, :67（``/elements/{element_id}``）,
              :133（``/elements/search``）
              FastAPI は登録順に照合するため ``/elements/search`` は
              ``/elements/{element_id}`` に先に一致し、element_id="search" の UUID 変換で 422 になる。
              契約の文書: docs/api/overview.md:87
        症状: 要素検索APIが常に 422 を返し、機能しない。
        期待: 200。
        """
        client, _, _ = make_client(items=[])
        response = client.get("/api/v1/bim/elements/search?q=wall")
        assert response.status_code == 200, (
            f"要素検索が到達不能（ルーティング衝突）: status={response.status_code}, "
            f"body={str(response.json())[:200]}"
        )

    def test_defect_model_version_is_not_assigned_or_required(self, make_client):
        """DEF-BIM-14: モデル登録時に版番号が採番されず、未指定のまま登録できる（Q5）。

        根拠: src/schemas/__init__.py:50（version は任意の自由文字列）
              src/services/bim_service.py:40-67（版の採番・必須検証・改訂履歴の記録なし）
        期待: 登録されたモデルには版番号が存在する（サーバ採番 or 必須入力）。
        実際: version 未指定で 200、レスポンスの version は None。
        未確認: 版番号体系（規則・版の粒度）を規定したリポジトリ内資料は無い。
        """
        client, _, _ = make_client()
        response = client.post("/api/v1/bim/models", json=_model_body())
        assert response.status_code == 200
        version = response.json()["data"]["version"]
        assert version, (
            f"版番号が採番・必須化されていない: version={version!r}"
        )

    def test_defect_pointcloud_has_no_version_field(self, make_client):
        """DEF-BIM-15: 点群に「生成版」を保持する項目が無い（Q5）。

        根拠: src/schemas/__init__.py:165-225（PointCloudCreate/Response に版の項目なし）
              src/models/__init__.py:116-157（PointCloud に version 列なし）
        参考仕様: docs/…V3.5.html:326「…処理手法、座標系、精度、生成版を保持」
        期待: レスポンスに版（version 等）が含まれる。
        未確認: 本サービスでの必須性は資料上確認できない。
        """
        client, _, _ = make_client()
        response = client.post(
            "/api/v1/bim/pointclouds",
            json={"organization_id": str(ORG_A), "name": "ダミー点群"},
        )
        assert response.status_code == 200
        data = response.json()["data"]
        assert any(key in data for key in ("version", "generation", "revision")), (
            f"点群に生成版の項目が無い: keys={sorted(data)}"
        )

    def test_defect_pointcloud_has_no_source_model_linkage(self, make_client):
        """DEF-BIM-16: 点群と元モデル（BIMモデル）の紐付け項目が無い（Q5 / H9）。

        根拠: src/schemas/__init__.py:165-225・src/models/__init__.py:116-157
              （PointCloud に model_id 等の外部参照が無い）
        期待: 点群から元モデルを辿れる参照が存在する。
        影響: 点群とモデル版の対応が取れず、出来形照合の証跡が追跡できない。
        """
        client, _, _ = make_client()
        response = client.post(
            "/api/v1/bim/pointclouds",
            json={"organization_id": str(ORG_A), "name": "ダミー点群"},
        )
        assert response.status_code == 200
        data = response.json()["data"]
        assert any(
            key in data for key in ("model_id", "bim_model_id", "source_model_id")
        ), f"点群から元モデルへの紐付けが無い: keys={sorted(data)}"

    def test_defect_pointcloud_has_no_source_provenance_field(self, make_client):
        """DEF-BIM-17: 点群に出典（元動画ID等）の項目が無い（Q5 版・由来）。

        根拠: src/schemas/__init__.py:165-225（capture_method はあるが元データ参照が無い）
        参考仕様: docs/…V3.5.html:326「元動画ID、処理手法、座標系、精度、生成版を保持」
        期待: 出典（元データ識別子）を保持する項目が存在する。
        未確認: 本サービスでの必須性は資料上確認できない。
        """
        client, _, _ = make_client()
        response = client.post(
            "/api/v1/bim/pointclouds",
            json={"organization_id": str(ORG_A), "name": "ダミー点群"},
        )
        assert response.status_code == 200
        data = response.json()["data"]
        assert any(
            key in data
            for key in (
                "source_id",
                "source_video_id",
                "original_video_id",
                "provenance",
                "source",
            )
        ), f"点群に出典の項目が無い: keys={sorted(data)}"


# =============================================================================
# 検証済み / 未実装の記録
# =============================================================================
class TestVersionAndStructureVerified:
    def test_ok_model_version_is_returned_when_supplied(self, make_client):
        """version を指定した場合はレスポンスに保持される（往復の一貫性）。"""
        client, _, _ = make_client()
        response = client.post(
            "/api/v1/bim/models", json=_model_body(version="v1.2")
        )
        assert response.status_code == 200
        assert response.json()["data"]["version"] == "v1.2"

    def test_ok_documented_gap_no_element_parent_child_tree(self, make_client):
        """未実装の記録: 要素ツリー（親子関係）は存在しない（欠陥と断定しない）。

        根拠: src/models/__init__.py:76-113（BIMElement に parent_id / 子要素参照が無い）
        → 「循環参照・孤児」の検証対象そのものが未実装。H8 の当該項目は **該当なし/未確認**。
        """
        from src.models import BIMModel, BIMElement

        columns = set(BIMElement.__table__.c.keys())
        assert "parent_id" not in columns
        assert "parent_element_id" not in columns
        model = BIMModel(
            id=MODEL_A,
            organization_id=ORG_A,
            name="ダミーモデル",
            model_type="architecture",
            file_format="ifc",
            status="draft",
            tags=[],
            metadata_={},
            created_at=_NOW,
            updated_at=_NOW,
        )
        # 親モデル参照 → モデル, count → 0, 本体 → []
        client, _, _ = make_client(
            results=[{"items": [model], "total": 0}, {"items": [], "total": 0}]
        )
        body = client.get(f"/api/v1/bim/{MODEL_A}/elements").json()
        assert body["data"] == []

    def test_ok_documented_gap_element_location_not_exposed(self, make_client):
        """未実装の記録: 要素の座標（location POINTZ）は API 応答に露出しない。

        根拠: src/models/__init__.py:105-107（location は Geometry(POINTZ, srid=4326)）
              src/schemas/__init__.py:132-147（BIMElementResponse に location が無い）
        → 要素単位の座標系・単位は API から検証不能（未確認）。
        """
        from src.models import BIMElement

        assert BIMElement.__table__.c.location.type.srid == 4326
        assert BIMElement.__table__.c.location.type.geometry_type == "POINTZ"
        from src.schemas import BIMElementResponse

        assert "location" not in BIMElementResponse.model_fields

    def test_ok_documented_gap_wkt_helper_has_no_range_validation(self):
        """Low の記録: WKT 変換ヘルパーに緯度経度の範囲検証が無い。

        根拠: src/services/bim_service.py:16-34（``srid=4326`` を固定し値を検証しない）
        補足: 本ヘルパーは API エンドポイントから参照されておらず（呼び出し元はテストのみ）、
              現時点で外部入力は到達しないため **影響は Low / 到達不能**。
              範囲外座標がそのまま WKT 化されることを記録する。
        """
        from src.services.bim_service import geojson_to_wkt_element

        element = geojson_to_wkt_element(
            {"type": "Point", "coordinates": [999.0, 999.0]}
        )
        assert element is not None
        assert element.srid == 4326
        assert "999.0 999.0" in str(element)

    def test_ok_documented_gap_pointcloud_missing_geometry_raises(self):
        """記録: 座標が空の Point を WKT 化すると IndexError になる（未使用経路）。

        根拠: src/services/bim_service.py:24（``coords[0] coords[1]``）
        API からは到達しないため現時点で影響なし（Low / 到達不能）。
        到達可能になった場合は GIS の DEF-GIS-17 と同種の 500 になる。
        """
        from src.services.bim_service import geojson_to_wkt_element

        with pytest.raises(IndexError):
            geojson_to_wkt_element({"type": "Point", "coordinates": []})

    def test_ok_pointcloud_coordinate_system_is_free_text_documented(self, make_client):
        """記録済み挙動: coordinate_system は自由文字列で、値域の検証が無い（未確認）。

        根拠: src/schemas/__init__.py:176（max_length=100 のみ）
        測地系の規格名・版をリポジトリ資料で確認できないため、
        どの値が正しいかは判定しない（未確認）。
        """
        client, _, _ = make_client()
        response = client.post(
            "/api/v1/bim/pointclouds",
            json={
                "organization_id": str(ORG_A),
                "name": "ダミー点群",
                "coordinate_system": "任意の文字列",
                "accuracy_mm": 5.0,
            },
        )
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["coordinate_system"] == "任意の文字列"
        assert data["accuracy_mm"] == pytest.approx(5.0)
        # 単位はフィールド名(accuracy_mm)のみで、応答に単位メタデータは無い
        assert "unit" not in data
