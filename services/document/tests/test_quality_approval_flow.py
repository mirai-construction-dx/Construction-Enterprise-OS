"""Q1(権限境界) / Q2(データ分離) / Q8(異常・復旧) 文書フローの品質テスト。

対象仮説:
  H2 テナント境界: GET/PUT/DELETE/download が他組織の文書を操作しないこと
  H4 /internal/* の認証(内部キー必須・未設定時 fail-closed)
  H5 アップロードのサイズ/種別検証、異常入力時のエラーコード

方針:
  実 DB / MinIO / 外部サービスへ接続しない(service 層は patch、DB は AsyncMock)。
  `@pytest.mark.xfail(strict=True)` は未修正の欠陥の証跡(成功ではない)。
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import jwt
import pytest
from fastapi.testclient import TestClient

from src.config import get_settings
from src.main import create_app
from src.models import Document
from src.models.base import get_db
from src.services import canonical_storage, document_service, storage_service
from src.services.canonical_storage import StorageResult
from src.services.storage_service import generate_storage_key

UTC = timezone.utc

ORG_A = UUID("00000000-0000-0000-0000-0000000000aa")
ORG_B = UUID("00000000-0000-0000-0000-0000000000bb")
USER_A = UUID("00000000-0000-0000-0000-0000000000cc")
DOC_ID = UUID("00000000-0000-0000-0000-0000000000dd")

INTERNAL_KEY = "test-internal-key-local-only"


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
        "roles": roles if roles is not None else ["admin"],
        "scopes": scopes if scopes is not None else ["documents:read", "documents:write"],
    }
    token = jwt.encode(payload, settings.jwt_public_key, algorithm=settings.JWT_ALGORITHM)
    return {"Authorization": f"Bearer {token}"}


def _make_document(org_id: UUID = ORG_A, status: str = "draft") -> Document:
    return Document(
        id=DOC_ID,
        organization_id=org_id,
        name="テスト図面",
        document_type="pdf",
        status=status,
        current_version=1,
        file_name="drawing.pdf",
        file_size=11,
        mime_type="application/pdf",
        storage_key=generate_storage_key(org_id, DOC_ID, 1, "drawing.pdf"),
        tags=[],
        created_by=USER_A,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


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
    return _app


@pytest.fixture
def client(app):
    return TestClient(app)


@pytest.fixture
def client_no_raise(app):
    """500 応答を例外として再送出させず、ステータスとして観測する。"""
    return TestClient(app, raise_server_exceptions=False)


# ——— H2: テナント境界 ———


class TestTenantBoundary:
    @pytest.mark.parametrize(
        "method,suffix",
        [("get", ""), ("get", "/download"), ("get", "/versions"), ("put", ""), ("delete", "")],
    )
    def test_endpoints_require_auth(self, client, method, suffix):
        response = client.request(
            method.upper(), f"/api/v1/documents/{DOC_ID}{suffix}"
        )
        assert response.status_code == 401

    def test_get_document_passes_token_org_to_lookup(self, client):
        get_document = AsyncMock(return_value=_make_document())
        with patch.object(document_service, "get_document", get_document):
            response = client.get(
                f"/api/v1/documents/{DOC_ID}", headers=_auth_headers()
            )
        assert response.status_code == 200
        assert get_document.call_args.args[2] == ORG_A

    def test_get_document_hides_other_organization_document(self, client):
        with patch.object(document_service, "get_document", AsyncMock(return_value=None)):
            response = client.get(
                f"/api/v1/documents/{DOC_ID}", headers=_auth_headers(org_id=ORG_B)
            )
        assert response.status_code == 404

    def test_download_passes_token_org_to_lookup(self, client):
        get_document = AsyncMock(return_value=_make_document())
        with (
            patch.object(document_service, "get_document", get_document),
            patch.object(
                storage_service, "get_file_stream", MagicMock(return_value=None)
            ),
        ):
            response = client.get(
                f"/api/v1/documents/{DOC_ID}/download", headers=_auth_headers()
            )
        assert response.status_code == 404  # ストレージ未検出で 404
        assert get_document.call_args.args[2] == ORG_A

    def test_download_hides_other_organization_document(self, client):
        with patch.object(document_service, "get_document", AsyncMock(return_value=None)):
            response = client.get(
                f"/api/v1/documents/{DOC_ID}/download", headers=_auth_headers(org_id=ORG_B)
            )
        assert response.status_code == 404

    def test_update_passes_token_org_to_lookup(self, client):
        update = AsyncMock(return_value=_make_document())
        with patch.object(document_service, "update_document", update):
            response = client.put(
                f"/api/v1/documents/{DOC_ID}",
                json={"name": "更新後"},
                headers=_auth_headers(),
            )
        assert response.status_code == 200
        assert update.call_args.kwargs["organization_id"] == ORG_A

    def test_delete_passes_token_org_to_lookup(self, client):
        delete = AsyncMock(return_value=_make_document(status="deleted"))
        with patch.object(document_service, "soft_delete_document", delete):
            response = client.delete(
                f"/api/v1/documents/{DOC_ID}", headers=_auth_headers()
            )
        assert response.status_code == 200
        assert delete.call_args.args[2] == ORG_A

    @pytest.mark.xfail(strict=True, reason="DEFECT-DOC-1: 文書ステータス変更にロール検査が無く承認偽装が可能")
    def test_defect_approval_status_can_be_set_without_approval_role(self, client):
        """[欠陥] 文書ステータスを任意ロールのトークンで 'approved' にできる。

        Q1/Q6: 承認状態の変更にロール検査が無い。roles=[] / scopes=[] の
        トークンでも PUT 1 回で承認済みにでき、承認の偽装が可能。
        """
        approved = _make_document(status="approved")
        with patch.object(document_service, "update_document", AsyncMock(return_value=approved)):
            response = client.put(
                f"/api/v1/documents/{DOC_ID}",
                json={"status": "approved"},
                headers=_auth_headers(roles=[], scopes=[]),
            )
        assert response.status_code == 403, "権限なしで承認状態へ遷移できてしまう"

    @pytest.mark.xfail(strict=True, reason="DEFECT-DOC-2: 文書削除に権限検査が無い")
    def test_defect_delete_without_management_role(self, client):
        """[欠陥] 文書削除にロール検査が無い(roles=[] でも削除できる)。"""
        deleted = _make_document(status="deleted")
        with patch.object(
            document_service, "soft_delete_document", AsyncMock(return_value=deleted)
        ):
            response = client.delete(
                f"/api/v1/documents/{DOC_ID}", headers=_auth_headers(roles=[])
            )
        assert response.status_code == 403, "権限なしで文書を削除できてしまう"


# ——— H5: アップロード検証と異常入力 ———


class TestUploadValidation:
    def test_upload_propagates_token_identity_to_service(self, client):
        create = AsyncMock(return_value=_make_document())
        with patch.object(document_service, "create_document", create):
            response = client.post(
                "/api/v1/documents/upload",
                files={"file": ("drawing.pdf", b"hello world", "application/pdf")},
                data={"name": "テスト図面"},
                headers=_auth_headers(),
            )
        assert response.status_code == 200
        assert create.call_args.kwargs["organization_id"] == ORG_A
        assert create.call_args.kwargs["created_by"] == USER_A

    def test_oversized_upload_is_rejected_with_413(self, client):
        with patch("src.api.documents.MAX_UPLOAD_BYTES", 4):
            response = client.post(
                "/api/v1/documents/upload",
                files={"file": ("big.pdf", b"0123456789", "application/pdf")},
                data={"name": "大きすぎる"},
                headers=_auth_headers(),
            )
        assert response.status_code == 413
        assert response.json()["detail"]["code"] == "FILE_TOO_LARGE"

    def test_storage_failure_is_not_reported_as_success(self, client):
        """保存失敗を成功に見せかけない(fail-loud)。"""
        create = AsyncMock(side_effect=RuntimeError("storage unavailable"))
        with patch.object(document_service, "create_document", create):
            response = client.post(
                "/api/v1/documents/upload",
                files={"file": ("drawing.pdf", b"hello", "application/pdf")},
                data={"name": "テスト"},
                headers=_auth_headers(),
            )
        assert response.status_code == 500
        assert response.json()["detail"]["code"] == "UPLOAD_FAILED"

    def test_malformed_tags_returns_400(self, client_no_raise):
        """[修正済 DEFECT-DOC-3] tags の不正 JSON は 500 ではなく 400 を返す。"""
        response = client_no_raise.post(
            "/api/v1/documents/upload",
            files={"file": ("drawing.pdf", b"hello", "application/pdf")},
            data={"name": "テスト", "tags": "{not-json"},
            headers=_auth_headers(),
        )
        assert response.status_code == 400
        assert response.json()["detail"]["code"] == "INVALID_REQUEST"

    def test_non_list_tags_returns_400(self, client_no_raise):
        """[修正済 DEFECT-DOC-3] tags が配列でない場合も 400 で返す。"""
        response = client_no_raise.post(
            "/api/v1/documents/upload",
            files={"file": ("drawing.pdf", b"hello", "application/pdf")},
            data={"name": "テスト", "tags": '{"unexpected": "object"}'},
            headers=_auth_headers(),
        )
        assert response.status_code == 400
        assert response.json()["detail"]["code"] == "INVALID_TAGS"

    def test_non_object_metadata_returns_400(self, client_no_raise):
        """[修正済 DEFECT-DOC-3] metadata がオブジェクトでない場合も 400 で返す。"""
        response = client_no_raise.post(
            "/api/v1/documents/upload",
            files={"file": ("drawing.pdf", b"hello", "application/pdf")},
            data={"name": "テスト", "metadata": "[1, 2, 3]"},
            headers=_auth_headers(),
        )
        assert response.status_code == 400
        assert response.json()["detail"]["code"] == "INVALID_METADATA"

    def test_invalid_project_id_returns_400(self, client_no_raise):
        """[修正済 DEFECT-DOC-4] project_id の不正 UUID は 500 ではなく 400 を返す。"""
        response = client_no_raise.post(
            "/api/v1/documents/upload",
            files={"file": ("drawing.pdf", b"hello", "application/pdf")},
            data={"name": "テスト", "project_id": "not-a-uuid"},
            headers=_auth_headers(),
        )
        assert response.status_code == 400
        assert response.json()["detail"]["code"] == "INVALID_REQUEST"

    def test_invalid_document_type_is_rejected_with_422(self, client):
        """[修正済 DEFECT-DOC-5] 未定義の document_type は API 層で 422 になる。"""
        create = AsyncMock(return_value=_make_document())
        with patch.object(document_service, "create_document", create):
            response = client.post(
                "/api/v1/documents/upload",
                files={"file": ("drawing.pdf", b"hello", "application/pdf")},
                data={"name": "テスト", "document_type": "not_a_document_type"},
                headers=_auth_headers(),
            )
        assert response.status_code == 422
        assert response.json()["detail"]["code"] == "INVALID_DOCUMENT_TYPE"
        create.assert_not_awaited()

    def test_allowed_document_types_match_db_enum(self):
        """許可リストが DB enum と乖離していないこと(定数ドリフトの回帰)。"""
        from src.api.documents import ALLOWED_DOCUMENT_TYPES

        db_values = set(Document.__table__.c.document_type.type.enums)
        assert ALLOWED_DOCUMENT_TYPES == db_values

    @pytest.mark.xfail(strict=True, reason="DEFECT-DOC-6: MIME 種別の許可リスト検証が無い")
    def test_defect_no_content_type_allowlist(self, client):
        """[欠陥] アップロードの MIME 種別検証が無く実行形式等も受理される。"""
        create = AsyncMock(return_value=_make_document())
        with patch.object(document_service, "create_document", create):
            response = client.post(
                "/api/v1/documents/upload",
                files={"file": ("payload.bin", b"\x7fELF", "application/x-msdownload")},
                data={"name": "実行形式"},
                headers=_auth_headers(),
            )
        assert response.status_code == 415, "危険な MIME 種別が受理された"

    def test_version_upload_oversize_is_rejected(self, client):
        with patch("src.api.documents.MAX_UPLOAD_BYTES", 4):
            response = client.post(
                f"/api/v1/documents/{DOC_ID}/versions",
                files={"file": ("big.pdf", b"0123456789", "application/pdf")},
                headers=_auth_headers(),
            )
        assert response.status_code == 413


# ——— H4: /internal/* の内部認証 ———


@pytest.fixture
def internal_key(monkeypatch):
    get_settings.cache_clear()
    monkeypatch.setenv("INTERNAL_API_KEY", INTERNAL_KEY)
    yield INTERNAL_KEY
    get_settings.cache_clear()


INTERNAL_PATHS = [
    f"/api/v1/documents/internal/{DOC_ID}/store-canonical",
    f"/api/v1/documents/internal/{DOC_ID}/store-work-area",
]


class TestInternalApiAuth:
    def test_internal_endpoints_reject_missing_key(self, client, internal_key):
        for path in INTERNAL_PATHS:
            response = client.post(path)
            assert response.status_code == 403, path
            assert response.json()["detail"]["code"] == "INTERNAL_AUTH_REQUIRED"

    def test_internal_endpoints_reject_wrong_key(self, client, internal_key):
        for path in INTERNAL_PATHS:
            response = client.post(path, headers={"X-Internal-API-Key": "wrong"})
            assert response.status_code == 403, path

    def test_internal_endpoints_fail_closed_when_key_unset(self, client, monkeypatch):
        get_settings.cache_clear()
        monkeypatch.delenv("INTERNAL_API_KEY", raising=False)
        try:
            for path in INTERNAL_PATHS:
                response = client.post(
                    path, headers={"X-Internal-API-Key": INTERNAL_KEY}
                )
                assert response.status_code == 403, path
        finally:
            get_settings.cache_clear()

    def test_internal_rejects_other_organization_header(self, app, internal_key):
        get_document = AsyncMock(return_value=_make_document(org_id=ORG_A))
        with patch.object(document_service, "get_document", get_document):
            response = TestClient(app).post(
                INTERNAL_PATHS[0],
                headers={
                    "X-Internal-API-Key": INTERNAL_KEY,
                    "X-Organization-ID": str(ORG_B),
                },
            )
        assert response.status_code == 403
        assert response.json()["detail"]["code"] == "ORGANIZATION_MISMATCH"

    def test_internal_rejects_missing_organization_header(self, app, internal_key):
        get_document = AsyncMock(return_value=_make_document(org_id=ORG_A))
        with patch.object(document_service, "get_document", get_document):
            response = TestClient(app).post(
                INTERNAL_PATHS[0], headers={"X-Internal-API-Key": INTERNAL_KEY}
            )
        assert response.status_code == 403

    def test_internal_accepts_matching_org_and_key(self, app, internal_key):
        """正しいキー + 一致する組織なら成功する(認証が機能することの対照)。"""
        get_document = AsyncMock(return_value=_make_document(org_id=ORG_A))
        store = AsyncMock(
            return_value=StorageResult(
                backend="filesystem",
                relative_path="canonical/org/doc/v1/drawing.pdf",
                size_bytes=11,
            )
        )
        with (
            patch.object(document_service, "get_document", get_document),
            patch.object(canonical_storage, "store_canonical", store),
        ):
            response = TestClient(app).post(
                INTERNAL_PATHS[0],
                headers={
                    "X-Internal-API-Key": INTERNAL_KEY,
                    "X-Organization-ID": str(ORG_A),
                },
            )
        assert response.status_code == 200
        assert response.json()["data"]["stored"] is True
