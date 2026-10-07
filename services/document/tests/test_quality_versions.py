"""Q5(版・由来) / Q1(権限境界) 文書版管理の品質テスト。

対象仮説:
  H1 版番号の単調増加・重複アップロードでの巻き戻り/再利用の有無
  H3 ストレージキーの推測可能性(連番・文書名由来の列挙攻撃)
  H2 テナント境界(GET /versions 系が他組織の文書を返さないこと)

方針:
  既存 tests/ と同じく create_app() + dependency_overrides + TestClient を用いる。
  実 DB / MinIO / 外部サービスへは接続しない(upload_file は patch、DB は AsyncMock)。
  実在企業名・実在個人名は使わず synthetic fixture のみ用いる。

注: `@pytest.mark.xfail(strict=True)` は「未修正の欠陥」を表す。
    成功(合格)ではなく、期待した正しい挙動が現状では成立しないことの証跡である。
    コードが修正されると XPASS となり strict により失敗へ変わる(=マーカー除去の強制)。
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import jwt
import pytest
from fastapi.testclient import TestClient

from src.config import get_settings
from src.main import create_app
from src.models import Document, DocumentVersion
from src.models.base import get_db
from src.schemas import PaginationMeta
from src.services import document_service
from src.services.document_service import create_new_version
from src.services.storage_service import generate_storage_key

UTC = timezone.utc

ORG_A = UUID("00000000-0000-0000-0000-0000000000aa")
ORG_B = UUID("00000000-0000-0000-0000-0000000000bb")
USER_A = UUID("00000000-0000-0000-0000-0000000000cc")
DOC_ID = UUID("00000000-0000-0000-0000-0000000000dd")


# ——— helpers ———


def _auth_headers(
    user_id: UUID = USER_A,
    org_id: UUID = ORG_A,
    roles: list[str] | None = None,
    scopes: list[str] | None = None,
) -> dict:
    settings = get_settings()
    payload = {
        "sub": str(user_id),
        "type": "user",
        "org": str(org_id),
        "roles": roles if roles is not None else ["site_manager"],
        "scopes": scopes if scopes is not None else ["documents:read", "documents:write"],
    }
    token = jwt.encode(payload, settings.jwt_public_key, algorithm=settings.JWT_ALGORITHM)
    return {"Authorization": f"Bearer {token}"}


def _make_document(
    doc_id: UUID = DOC_ID,
    org_id: UUID = ORG_A,
    current_version: int = 1,
    file_name: str = "drawing.pdf",
    status: str = "draft",
) -> Document:
    return Document(
        id=doc_id,
        organization_id=org_id,
        name="テスト図面",
        document_type="pdf",
        status=status,
        current_version=current_version,
        file_name=file_name,
        file_size=100,
        mime_type="application/pdf",
        storage_key=generate_storage_key(org_id, doc_id, current_version, file_name),
        tags=[],
        created_by=USER_A,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


def _mock_db_for(doc: Document | None):
    """execute() が常に doc を返す AsyncMock DB。"""
    mock_db = AsyncMock()
    mock_db.add = MagicMock()
    mock_db.flush = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = doc
    mock_db.execute = AsyncMock(return_value=result)

    async def _refresh(obj):
        if isinstance(obj, DocumentVersion):
            obj.id = uuid4()
            obj.created_at = datetime.now(UTC)

    mock_db.refresh = _refresh
    return mock_db


@pytest.fixture
def app():
    _app = create_app()
    mock_db = AsyncMock()
    mock_db.flush = AsyncMock()
    mock_db.commit = AsyncMock()
    mock_db.rollback = AsyncMock()
    mock_db.close = AsyncMock()
    mock_db.add = MagicMock()

    async def _get_db():
        yield mock_db

    _app.dependency_overrides[get_db] = _get_db
    _app.state.mock_db = mock_db
    return _app


@pytest.fixture
def client(app):
    return TestClient(app)


async def _append_versions(doc: Document, count: int) -> list[int]:
    """同一文書へ count 回の新版アップロードを行い、採番された版番号を返す。"""
    mock_db = _mock_db_for(doc)
    assigned: list[int] = []
    with patch("src.services.document_service.upload_file", return_value=True):
        for _ in range(count):
            version = await create_new_version(
                mock_db,
                document_id=doc.id,
                created_by=USER_A,
                file_content=b"payload",
                file_name="drawing.pdf",
                content_type="application/pdf",
                change_description="rev",
                organization_id=doc.organization_id,
            )
            assigned.append(version.version_number)
    return assigned


# ——— H1: 版番号の単調増加 ———


class TestVersionMonotonicity:
    @pytest.mark.asyncio
    async def test_new_version_increments_by_one_each_time(self):
        doc = _make_document(current_version=1)
        assigned = await _append_versions(doc, 3)

        assert assigned == [2, 3, 4]
        assert doc.current_version == 4

    @pytest.mark.asyncio
    async def test_duplicate_upload_never_reuses_or_rewinds_version(self):
        """同一文書・同一ファイル名の重複アップロードでも版が飛ばない/巻き戻らない。"""
        doc = _make_document(current_version=1, file_name="same.pdf")
        assigned = await _append_versions(doc, 4)

        assert assigned == sorted(assigned)
        assert len(set(assigned)) == len(assigned), "同一版番号が再利用された"
        assert min(assigned) == 2 and max(assigned) == 5
        assert doc.current_version >= max(assigned)

    @pytest.mark.asyncio
    async def test_version_number_is_derived_from_counter_not_row_count(self):
        """版番号は行数ではなく current_version から採番される(行欠損でも再利用しない)。"""
        doc = _make_document(current_version=7)
        assigned = await _append_versions(doc, 1)
        assert assigned == [8]

    @pytest.mark.asyncio
    async def test_new_version_after_soft_delete_still_advances(self):
        """soft delete 済み文書でも版番号が巻き戻らない。"""
        doc = _make_document(current_version=3, status="deleted")
        assigned = await _append_versions(doc, 2)
        assert assigned == [4, 5]

    def test_version_unique_index_declared_on_model(self):
        """(document_id, version_number) の一意制約が ORM に宣言されていること。"""
        indexes = {idx.name: idx for idx in DocumentVersion.__table__.indexes}
        target = indexes.get("ix_document_versions_document_id_version")
        assert target is not None, "版番号の一意インデックスが未宣言"
        assert target.unique is True
        assert [c.name for c in target.columns] == ["document_id", "version_number"]

    def test_version_unique_index_present_in_migration(self):
        """DDL(マイグレーション)側にも一意インデックスが存在すること。"""
        from pathlib import Path

        sql = (
            Path(__file__).resolve().parents[1]
            / "migrations"
            / "000_base_schema.sql"
        ).read_text(encoding="utf-8")
        assert "UNIQUE INDEX" in sql.upper()
        assert "ix_document_versions_document_id_version" in sql

    @pytest.mark.asyncio
    async def test_new_version_is_scoped_to_token_organization(self):
        """他組織の document_id を指定しても版を作れない(組織スコープが WHERE に入る)。"""
        other_org_doc = _make_document(org_id=ORG_B)
        mock_db = _mock_db_for(None)
        captured = {}
        original_execute = mock_db.execute

        async def _capture(stmt):
            captured["stmt"] = stmt
            return await original_execute(stmt)

        mock_db.execute = _capture
        with patch("src.services.document_service.upload_file", return_value=True):
            version = await create_new_version(
                mock_db,
                document_id=other_org_doc.id,
                created_by=USER_A,
                file_content=b"payload",
                file_name="x.pdf",
                content_type="application/pdf",
                organization_id=ORG_A,
            )
        assert version is None
        where = str(captured["stmt"]).split("WHERE", 1)[-1]
        assert "organization_id" in where

    @pytest.mark.asyncio
    async def test_new_version_returns_none_for_unknown_document(self):
        mock_db = _mock_db_for(None)
        with patch("src.services.document_service.upload_file", return_value=True):
            version = await create_new_version(
                mock_db,
                document_id=uuid4(),
                created_by=USER_A,
                file_content=b"payload",
                file_name="x.pdf",
                content_type="application/pdf",
                organization_id=ORG_A,
            )
        assert version is None


# ——— H3: ストレージキーの推測可能性 ———


class TestStorageKeyPredictability:
    def test_key_uses_uuid_components_not_sequence(self):
        key = generate_storage_key(ORG_A, DOC_ID, 3, "drawing.pdf")
        assert str(ORG_A) in key and str(DOC_ID) in key
        # 連番のみ(例: "1/2/3")や文書名のみの列挙可能キーになっていないこと。
        assert "v3" in key
        assert key.startswith(f"{ORG_A}/{DOC_ID}/")

    def test_key_is_unique_per_organization_and_document(self):
        key_a = generate_storage_key(ORG_A, DOC_ID, 1, "drawing.pdf")
        key_b = generate_storage_key(ORG_B, DOC_ID, 1, "drawing.pdf")
        key_c = generate_storage_key(ORG_A, uuid4(), 1, "drawing.pdf")
        assert len({key_a, key_b, key_c}) == 3

    def test_key_contains_version_segment(self):
        assert "/v1/" in generate_storage_key(ORG_A, DOC_ID, 1, "a.pdf")
        assert "/v12/" in generate_storage_key(ORG_A, DOC_ID, 12, "a.pdf")

    def test_put_object_receives_the_generated_key(self):
        """生成キーが実際に put_object の Key として渡ること。"""
        from src.services import storage_service

        fake_s3 = MagicMock()
        with patch.object(storage_service.boto3, "client", return_value=fake_s3):
            assert storage_service.upload_file(b"data", "org/doc/v1/a.pdf", "application/pdf")
        assert fake_s3.put_object.call_args.kwargs["Key"] == "org/doc/v1/a.pdf"

    def test_defect_storage_key_does_not_sanitize_traversal_filename(self):
        """[欠陥] 生ストレージキーが file_name を無害化していない。

        正本保存経路 (canonical_storage.sanitize_path_component) は '/', '..' を
        除去するが、S3/MinIO 生キー生成は未処理。file_name に区切り文字を混ぜると
        オブジェクトキーへ任意の擬似ディレクトリを注入できる。
        """
        key = generate_storage_key(ORG_A, DOC_ID, 1, "../../etc/passwd")
        assert ".." not in key, f"ストレージキーに path traversal が混入: {key!r}"

    def test_canonical_path_sanitizes_traversal_filename(self):
        """対照: 正本パス生成は無害化される(既存の正しい挙動の回帰)。"""
        from src.services.canonical_storage import canonical_relative_path

        doc = _make_document(file_name="../../etc/passwd")
        path = canonical_relative_path(doc)
        assert ".." not in path
        assert "/etc/" not in path
        assert str(ORG_A) in path


# ——— H2: 版一覧/取得のテナント境界(API 層) ———


class TestVersionEndpointBoundary:
    def test_version_endpoints_require_auth(self, client):
        for method, url in [
            ("GET", f"/api/v1/documents/{DOC_ID}/versions"),
            ("GET", f"/api/v1/documents/{DOC_ID}/versions/1"),
            ("POST", f"/api/v1/documents/{DOC_ID}/versions"),
        ]:
            response = client.request(method, url)
            assert response.status_code == 401, f"{method} {url} -> {response.status_code}"

    def test_version_number_boundary_values_return_404(self, client):
        for version_number in (0, -1, 999999):
            with (
                patch.object(
                    document_service, "get_document", AsyncMock(return_value=_make_document())
                ),
                patch.object(
                    document_service, "get_version", AsyncMock(return_value=None)
                ),
            ):
                response = client.get(
                    f"/api/v1/documents/{DOC_ID}/versions/{version_number}",
                    headers=_auth_headers(),
                )
            assert response.status_code == 404, f"version={version_number}"

    def test_list_versions_passes_token_organization_to_lookup(self, client):
        """版一覧は document をトークン由来 org で取得し、他組織文書を 404 にする。"""
        get_document = AsyncMock(return_value=_make_document())
        list_versions = AsyncMock(
            return_value=(
                [],
                PaginationMeta(page=1, per_page=20, total=0, total_pages=0),
            )
        )
        with (
            patch.object(document_service, "get_document", get_document),
            patch.object(document_service, "list_versions", list_versions),
        ):
            response = client.get(
                f"/api/v1/documents/{DOC_ID}/versions", headers=_auth_headers()
            )

        assert response.status_code == 200
        assert get_document.call_args.args[2] == ORG_A

    def test_list_versions_returns_404_when_document_outside_token_org(self, client):
        """サービスが None を返す(他組織)場合は 404 で存在を隠す。"""
        with patch.object(
            document_service, "get_document", AsyncMock(return_value=None)
        ):
            response = client.get(
                f"/api/v1/documents/{DOC_ID}/versions",
                headers=_auth_headers(org_id=ORG_B),
            )
        assert response.status_code == 404
