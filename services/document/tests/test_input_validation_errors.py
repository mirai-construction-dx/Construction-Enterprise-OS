"""クライアント入力の不備が 500 にならないことを守る回帰テスト。

症状:
    GET /api/v1/documents?project_id=<UUID でない値> が 500 を返す。
原因:
    `src/api/documents.py` の `list_documents` が `project_id` を検証せずに
    `UUID(project_id)` へ渡している（同ファイルの `upload_document` は
    既に `try/except` で 400 に変換している＝同一ファイル内の非対称）。
期待:
    クライアント入力の不備は 4xx（400）で返し、500 にしない。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from src.main import create_app
from src.models.base import get_db

BASE = "/api/v1/documents"


class _EmptyResult:
    """一覧クエリ用の空結果。"""

    def scalar(self) -> int:
        return 0

    def scalars(self):
        return self

    def all(self) -> list:
        return []

    def first(self):
        return None

    def scalar_one_or_none(self):
        return None


@pytest.fixture
def mock_db() -> AsyncMock:
    db = AsyncMock()

    async def mock_execute(*args, **kwargs):
        return _EmptyResult()

    db.execute = mock_execute
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    db.close = AsyncMock()
    db.flush = AsyncMock()
    return db


@pytest.fixture
def client(mock_db: AsyncMock) -> TestClient:
    app = create_app()

    async def mock_get_db():
        yield mock_db

    app.dependency_overrides[get_db] = mock_get_db
    # 500 を「例外」ではなく「応答」として観測するため raise_server_exceptions=False
    return TestClient(app, raise_server_exceptions=False)


def _auth_headers() -> dict[str, str]:
    import jwt

    from src.config import get_settings

    settings = get_settings()
    token = jwt.encode(
        {
            "sub": str(uuid4()),
            "type": "user",
            "org": str(uuid4()),
            "roles": ["admin"],
            "scopes": ["documents:read"],
        },
        settings.jwt_public_key,
        algorithm=settings.JWT_ALGORITHM,
    )
    return {"Authorization": f"Bearer {token}"}


class TestListDocumentsParamValidation:
    def test_malformed_project_id_returns_400_not_500(self, client: TestClient):
        """UUID でない project_id は 400 で拒否する（500 にしない）。"""
        response = client.get(
            BASE, params={"project_id": "not-a-uuid"}, headers=_auth_headers()
        )
        assert response.status_code == 400, (
            f"不正な project_id が 500 になった: {response.status_code} {response.text[:200]}"
        )
        # エラー本文の形式は upload 側（既存の 400）と揃っていること
        assert response.json()["detail"]["code"] == "INVALID_REQUEST"

    def test_empty_project_id_is_accepted(self, client: TestClient):
        """project_id 未指定は従来どおり 200。"""
        response = client.get(BASE, headers=_auth_headers())
        assert response.status_code == 200, response.text

    def test_valid_project_id_is_accepted(self, client: TestClient):
        """正しい UUID は従来どおり 200（過剰な拒否をしない）。"""
        response = client.get(
            BASE, params={"project_id": str(uuid4())}, headers=_auth_headers()
        )
        assert response.status_code == 200, response.text

    def test_malformed_project_id_requires_authentication(self):
        """未認証は 500 ではなく 401/403 が優先されること。"""
        app = create_app()
        unauthenticated = TestClient(app, raise_server_exceptions=False)
        response = unauthenticated.get(BASE, params={"project_id": "not-a-uuid"})
        assert response.status_code in (401, 403), response.text


class TestUploadDocumentsParamValidation:
    """既存の是正（upload 側）が退行していないことの固定。"""

    def test_malformed_project_id_on_upload_returns_400(self, client: TestClient):
        response = client.post(
            f"{BASE}/upload",
            data={"name": "テスト文書", "document_type": "pdf", "project_id": "not-a-uuid"},
            files={"file": ("t.pdf", b"%PDF-1.4 synthetic", "application/pdf")},
            headers=_auth_headers(),
        )
        assert response.status_code == 400, response.text


class TestListDocumentsEnumValidation:
    """native enum 列に渡すクエリ値も境界で拒否すること（DB エラー → 500 の防止）。"""

    @pytest.mark.parametrize("bad", ["bogus", "PDF", "application/pdf"])
    def test_unknown_document_type_returns_422(self, client: TestClient, bad: str):
        response = client.get(
            BASE, params={"document_type": bad}, headers=_auth_headers()
        )
        assert response.status_code == 422, (
            f"未知の document_type({bad!r}) が拒否されていない: "
            f"{response.status_code} {response.text[:200]}"
        )
        assert response.json()["detail"]["code"] == "INVALID_DOCUMENT_TYPE"

    @pytest.mark.parametrize("bad", ["bogus", "ACTIVE", "published"])
    def test_unknown_status_returns_422(self, client: TestClient, bad: str):
        response = client.get(BASE, params={"status": bad}, headers=_auth_headers())
        assert response.status_code == 422, (
            f"未知の status({bad!r}) が拒否されていない: "
            f"{response.status_code} {response.text[:200]}"
        )
        assert response.json()["detail"]["code"] == "INVALID_STATUS"

    @pytest.mark.parametrize(
        "params",
        [
            {"document_type": "pdf"},
            {"status": "approved"},
            {"document_type": "other", "status": "draft"},
            {"document_type": ""},  # 空文字は「絞り込み無し」として従来どおり受理
            {"status": ""},
        ],
    )
    def test_known_or_empty_enum_values_are_accepted(self, client: TestClient, params):
        response = client.get(BASE, params=params, headers=_auth_headers())
        assert response.status_code == 200, response.text


class TestListDocumentsFilterForwarding:
    """境界で検証した値が実際にサービス層の絞り込みへ渡ること（検証の空洞化防止）。"""

    def test_valid_project_id_is_forwarded(self, monkeypatch):
        from src.schemas import PaginationMeta

        captured: dict = {}

        async def fake_list_documents(db, **kwargs):
            captured.update(kwargs)
            return [], PaginationMeta(page=1, per_page=20, total=0, total_pages=0)

        monkeypatch.setattr(
            "src.api.documents.document_service.list_documents", fake_list_documents
        )

        project_id = uuid4()
        app = create_app()
        db = AsyncMock()

        async def mock_get_db():
            yield db

        app.dependency_overrides[get_db] = mock_get_db
        client = TestClient(app, raise_server_exceptions=False)

        response = client.get(
            BASE, params={"project_id": str(project_id)}, headers=_auth_headers()
        )
        assert response.status_code == 200, response.text
        assert captured["project_id"] == project_id

    def test_unknown_enum_is_not_forwarded(self, monkeypatch):
        """422 になる値はサービス層へ到達しないこと。"""
        called: list = []

        async def fake_list_documents(db, **kwargs):
            called.append(kwargs)
            return [], None

        monkeypatch.setattr(
            "src.api.documents.document_service.list_documents", fake_list_documents
        )

        app = create_app()
        db = AsyncMock()

        async def mock_get_db():
            yield db

        app.dependency_overrides[get_db] = mock_get_db
        client = TestClient(app, raise_server_exceptions=False)

        response = client.get(
            BASE, params={"status": "bogus"}, headers=_auth_headers()
        )
        assert response.status_code == 422
        assert called == [], "不正な enum 値がサービス層へ渡っている"
