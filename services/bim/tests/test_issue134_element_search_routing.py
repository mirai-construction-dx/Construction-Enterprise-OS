"""#134: GET /api/v1/bim/elements/search のルーティング回帰テスト

``/elements/search`` が ``/elements/{element_id}`` より前に登録されていないと、
FastAPI は登録順に照合するため "search" が UUID として解釈され 422 になる。
本テストは TestClient 経由で到達性（literal ルートが動的ルートに吸われないこと）を固定する。

補足: 本欠陥の修正（search ルートの先行登録）は main の d34af88（PR #159）で
既に適用済みであり、本ファイルは再発防止の回帰ガードである。
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from src.main import create_app
from src.middleware.auth import TokenData, get_current_user
from src.models.base import get_db

ORG_A = "00000000-0000-0000-0000-0000000000aa"
USER_SUB = "00000000-0000-0000-0000-0000000000dd"


class _FakeResult:
    def scalar(self):
        return 0

    def scalars(self):
        return self

    def all(self):
        return []


@pytest.fixture
def client():
    app = create_app()
    db = AsyncMock()
    db.execute = AsyncMock(return_value=_FakeResult())
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    db.close = AsyncMock()

    async def _get_db():
        yield db

    async def _current_user():
        return TokenData(sub=USER_SUB, type="user", org=ORG_A, roles=["bim_manager"])

    app.dependency_overrides[get_db] = _get_db
    app.dependency_overrides[get_current_user] = _current_user
    return TestClient(app)


class TestElementSearchRouting:
    def test_search_route_is_reachable_not_shadowed_by_element_id(self, client):
        """literal な /elements/search が到達でき、200 を返す（422 にならない）。"""
        response = client.get("/api/v1/bim/elements/search?q=wall")
        assert response.status_code == 200, (
            "GET /api/v1/bim/elements/search が /elements/{element_id} に吸われた "
            f"(status={response.status_code}, body={str(response.json())[:200]})"
        )
        assert response.json()["data"] == []

    def test_non_uuid_element_path_is_still_validated_as_element_id(self, client):
        """literal ルート追加後も /elements/{element_id} の UUID 検証は維持される。

        "not-a-uuid" は search ではないため動的ルートに一致し、UUID 変換で 422 になる。
        これにより「search が動的ルートを置き換えた」のではなく
        「literal ルートが動的ルートより先に一致している」ことを確認する。
        """
        response = client.get("/api/v1/bim/elements/not-a-uuid")
        assert response.status_code == 422, (
            "動的ルート /elements/{element_id} の UUID 検証が失われた "
            f"(status={response.status_code})"
        )
