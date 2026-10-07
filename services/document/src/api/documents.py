"""文書管理 API ルーター"""

from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    UploadFile,
    status,
)
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..middleware.auth import (
    APPROVAL_ROLES,
    MANAGEMENT_ROLES,
    TokenData,
    get_current_user,
    require_any_role,
)
from ..models.base import get_db
from ..schemas import (
    APIResponse,
    DocumentListResponse,
    DocumentResponse,
    DocumentUpdate,
    DocumentVersionListResponse,
    DocumentVersionResponse,
    MetaInfo,
)
from ..services import document_service, storage_service

router = APIRouter()
settings = get_settings()

MAX_UPLOAD_BYTES = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024

# DB の document_type enum と一致させる。Form 引数は Pydantic 検証を通らないため、
# ここで許可値を確認しないと DB 到達時に 500 になる。
ALLOWED_DOCUMENT_TYPES = frozenset(
    {"pdf", "cad", "bim", "photo", "video", "spreadsheet", "other"}
)

# 実行形式・スクリプト系の MIME 種別。文書管理として扱わない。
# 正式な許可リスト（allowlist）の方針は未確定のため、まずは危険種別の拒否から始める。
DANGEROUS_CONTENT_TYPES = frozenset(
    {
        "application/x-msdownload",
        "application/x-msdos-program",
        "application/x-dosexec",
        "application/x-executable",
        "application/vnd.microsoft.portable-executable",
        "application/x-msi",
        "application/java-archive",
        "application/x-sh",
        "application/x-shellscript",
    }
)

# DB の document_status enum と一致させる（migrations/000_base_schema.sql）。
ALLOWED_DOCUMENT_STATUSES = frozenset(
    {"draft", "under_review", "approved", "rejected", "obsolete", "deleted"}
)


def _api_response(data=None, meta=None, error=None, success=True):
    return APIResponse(success=success, data=data, error=error, meta=meta)


def _org_id(token_data: TokenData) -> UUID:
    return UUID(token_data.org) if token_data.org else UUID(int=0)


def _parse_enum_param(
    value: str | None, allowed: frozenset[str], field: str, code: str
) -> str | None:
    """許容値リストに無いクエリ値を 422 で拒否する。

    native enum 列の比較に素の文字列を渡すと DB エラー → 500 になるため、
    境界で拒否する（upload の document_type 検証と同じ挙動に揃える）。
    """
    if not value:
        # 未指定・空文字は「絞り込み無し」として従来どおり扱う（過剰な拒否をしない）
        return None
    if value not in allowed:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": code,
                "message": (
                    f"{field} が不正です。指定可能値: " + ", ".join(sorted(allowed))
                ),
            },
        )
    return value


def _parse_uuid_param(value: str | None, field: str) -> UUID | None:
    """クエリ/フォーム由来の UUID 文字列を検証する。

    不正な値をそのまま `UUID()` へ渡すと ValueError がグローバル例外ハンドラに
    到達して 500 になり、クライアント入力の不備がサーバ障害として扱われる。
    ここで 400 に変換する。
    """
    if not value:
        return None
    try:
        return UUID(value)
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "INVALID_REQUEST",
                "message": f"{field} の形式が不正です。UUID を指定してください。",
            },
        ) from None


@router.post("/upload")
async def upload_document(
    file: UploadFile = File(...),
    name: str = Form(...),
    document_type: str = Form("other"),
    project_id: str | None = Form(None),
    description: str | None = Form(None),
    tags: str = Form("[]"),
    metadata: str = Form("{}"),
    token_data: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not file.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "NO_FILE", "message": "ファイルが指定されていません。"},
        )

    file_content = await file.read()
    if len(file_content) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail={
                "code": "FILE_TOO_LARGE",
                "message": f"ファイルサイズが上限 ({settings.MAX_UPLOAD_SIZE_MB}MB) を超えています。",
            },
        )

    import json

    # クライアント入力の不備は 4xx として返す。ここで例外を通すと
    # グローバル例外ハンドラが 500 に変換し、原因が分からない障害になる。
    try:
        parsed_tags = json.loads(tags) if isinstance(tags, str) else tags
        parsed_metadata = (
            json.loads(metadata) if isinstance(metadata, str) else metadata
        )
        parsed_project_id = UUID(project_id) if project_id else None
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "INVALID_REQUEST",
                "message": "tags / metadata / project_id の形式が不正です。",
            },
        ) from None

    if not isinstance(parsed_tags, list):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "INVALID_TAGS",
                "message": "tags は配列で指定してください。",
            },
        )
    if parsed_metadata is not None and not isinstance(parsed_metadata, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "INVALID_METADATA",
                "message": "metadata はオブジェクトで指定してください。",
            },
        )
    if document_type not in ALLOWED_DOCUMENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "INVALID_DOCUMENT_TYPE",
                "message": (
                    "document_type が不正です。指定可能値: "
                    + ", ".join(sorted(ALLOWED_DOCUMENT_TYPES))
                ),
            },
        )

    content_type = file.content_type or "application/octet-stream"
    if content_type.split(";")[0].strip().lower() in DANGEROUS_CONTENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail={
                "code": "UNSUPPORTED_MEDIA_TYPE",
                "message": f"content_type {content_type} は受理できません。",
            },
        )

    try:
        document = await document_service.create_document(
            db=db,
            organization_id=UUID(token_data.org) if token_data.org else UUID(int=0),
            created_by=UUID(token_data.sub),
            name=name,
            file_name=file.filename,
            file_content=file_content,
            content_type=content_type,
            project_id=parsed_project_id,
            description=description,
            document_type=document_type,
            tags=parsed_tags,
            metadata=parsed_metadata,
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": "UPLOAD_FAILED", "message": str(e)},
        )

    return _api_response(data=DocumentResponse.model_validate(document).model_dump())


@router.get("")
async def list_documents(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    query: str | None = Query(None),
    document_type: str | None = Query(None),
    status: str | None = Query(None),
    project_id: str | None = Query(None),
    tags: str | None = Query(None),
    token_data: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    parsed_project_id = _parse_uuid_param(project_id, "project_id")
    parsed_document_type = _parse_enum_param(
        document_type, ALLOWED_DOCUMENT_TYPES, "document_type", "INVALID_DOCUMENT_TYPE"
    )
    parsed_status = _parse_enum_param(
        status, ALLOWED_DOCUMENT_STATUSES, "status", "INVALID_STATUS"
    )
    parsed_tags = tags.split(",") if tags else None

    documents, pmeta = await document_service.list_documents(
        db=db,
        organization_id=UUID(token_data.org) if token_data.org else UUID(int=0),
        page=page,
        per_page=per_page,
        query=query,
        document_type=parsed_document_type,
        status=parsed_status,
        project_id=parsed_project_id,
        tags=parsed_tags,
    )

    doc_list = [DocumentResponse.model_validate(d) for d in documents]
    result = DocumentListResponse(documents=doc_list, pagination=pmeta)

    meta = MetaInfo(
        page=pmeta.page,
        per_page=pmeta.per_page,
        total=pmeta.total,
        total_pages=pmeta.total_pages,
    )
    return _api_response(data=result.model_dump(), meta=meta)


@router.get("/{document_id}")
async def get_document(
    document_id: UUID,
    token_data: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    document = await document_service.get_document(db, document_id, _org_id(token_data))
    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "NOT_FOUND", "message": "文書が見つかりません。"},
        )
    return _api_response(data=DocumentResponse.model_validate(document).model_dump())


@router.get("/{document_id}/download")
async def download_document(
    document_id: UUID,
    token_data: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    document = await document_service.get_document(db, document_id, _org_id(token_data))
    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "NOT_FOUND", "message": "文書が見つかりません。"},
        )

    file_stream = storage_service.get_file_stream(document.storage_key)
    if file_stream is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "FILE_NOT_FOUND",
                "message": "ストレージにファイルが見つかりません。",
            },
        )

    from urllib.parse import quote

    safe_filename = quote(document.file_name)
    return StreamingResponse(
        file_stream,
        media_type=document.mime_type,
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{safe_filename}",
            "Content-Length": str(document.file_size),
        },
    )


@router.put("/{document_id}")
async def update_document(
    document_id: UUID,
    body: DocumentUpdate,
    token_data: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # 承認状態への遷移（approved / rejected）は承認ロールを要求する（DOC-1）
    if body.status in ("approved", "rejected"):
        require_any_role(token_data, APPROVAL_ROLES)
    document = await document_service.update_document(
        db=db,
        document_id=document_id,
        name=body.name,
        description=body.description,
        tags=body.tags,
        status=body.status,
        organization_id=_org_id(token_data),
    )
    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "NOT_FOUND", "message": "文書が見つかりません。"},
        )
    return _api_response(data=DocumentResponse.model_validate(document).model_dump())


@router.delete("/{document_id}")
async def delete_document(
    document_id: UUID,
    token_data: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # 文書削除は管理ロールを要求する（DOC-2）
    require_any_role(token_data, MANAGEMENT_ROLES)
    document = await document_service.soft_delete_document(
        db, document_id, _org_id(token_data)
    )
    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "NOT_FOUND", "message": "文書が見つかりません。"},
        )
    return _api_response(data=DocumentResponse.model_validate(document).model_dump())


@router.post("/{document_id}/versions")
async def upload_new_version(
    document_id: UUID,
    file: UploadFile = File(...),
    change_description: str | None = Form(None),
    token_data: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not file.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "NO_FILE", "message": "ファイルが指定されていません。"},
        )

    file_content = await file.read()
    if len(file_content) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail={
                "code": "FILE_TOO_LARGE",
                "message": f"ファイルサイズが上限 ({settings.MAX_UPLOAD_SIZE_MB}MB) を超えています。",
            },
        )

    content_type = file.content_type or "application/octet-stream"

    try:
        version = await document_service.create_new_version(
            db=db,
            document_id=document_id,
            created_by=UUID(token_data.sub),
            file_content=file_content,
            file_name=file.filename,
            content_type=content_type,
            change_description=change_description,
            organization_id=_org_id(token_data),
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": "VERSION_UPLOAD_FAILED", "message": str(e)},
        )

    if not version:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "NOT_FOUND", "message": "文書が見つかりません。"},
        )

    return _api_response(
        data=DocumentVersionResponse.model_validate(version).model_dump()
    )


@router.get("/{document_id}/versions")
async def list_document_versions(
    document_id: UUID,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    token_data: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    document = await document_service.get_document(db, document_id, _org_id(token_data))
    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "NOT_FOUND", "message": "文書が見つかりません。"},
        )

    versions, pmeta = await document_service.list_versions(
        db=db,
        document_id=document_id,
        page=page,
        per_page=per_page,
    )

    vlist = [DocumentVersionResponse.model_validate(v) for v in versions]
    result = DocumentVersionListResponse(versions=vlist, pagination=pmeta)

    meta = MetaInfo(
        page=pmeta.page,
        per_page=pmeta.per_page,
        total=pmeta.total,
        total_pages=pmeta.total_pages,
    )
    return _api_response(data=result.model_dump(), meta=meta)


@router.get("/{document_id}/versions/{version_number}")
async def get_document_version(
    document_id: UUID,
    version_number: int,
    token_data: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    document = await document_service.get_document(db, document_id, _org_id(token_data))
    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "NOT_FOUND", "message": "文書が見つかりません。"},
        )

    version = await document_service.get_version(db, document_id, version_number)
    if not version:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "NOT_FOUND", "message": "バージョンが見つかりません。"},
        )
    return _api_response(
        data=DocumentVersionResponse.model_validate(version).model_dump()
    )
