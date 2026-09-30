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
from ..middleware.auth import TokenData, get_current_user
from ..middleware.tenant import create_org, scope_org, token_org
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


def _api_response(data=None, meta=None, error=None, success=True):
    return APIResponse(success=success, data=data, error=error, meta=meta)


@router.post("/upload")
async def upload_document(
    file: UploadFile = File(...),
    name: str = Form(...),
    document_type: str = Form("other"),
    project_id: str | None = Form(None),
    description: str | None = Form(None),
    tags: str = Form("[]"),
    metadata: str = Form("{}"),
    organization_id: UUID | None = Form(None),
    token_data: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not file.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "NO_FILE", "message": "ファイルが指定されていません。"},
        )

    # ADR-0004: regular users may only create in their own org; admin may target the body org.
    doc_org = (
        create_org(token_data, organization_id)
        if organization_id is not None
        else token_org(token_data)
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

    parsed_tags = json.loads(tags) if isinstance(tags, str) else tags
    parsed_metadata = json.loads(metadata) if isinstance(metadata, str) else metadata
    parsed_project_id = UUID(project_id) if project_id else None

    content_type = file.content_type or "application/octet-stream"

    try:
        document = await document_service.create_document(
            db=db,
            organization_id=doc_org,
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
    organization_id: UUID | None = Query(None),
    token_data: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_filter = scope_org(token_data, organization_id)
    parsed_project_id = UUID(project_id) if project_id else None
    parsed_tags = tags.split(",") if tags else None

    documents, pmeta = await document_service.list_documents(
        db=db,
        organization_id=org_filter,
        page=page,
        per_page=per_page,
        query=query,
        document_type=document_type,
        status=status,
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
    document = await document_service.get_document(db, document_id, scope_org(token_data))
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
    document = await document_service.get_document(db, document_id, scope_org(token_data))
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
    document = await document_service.update_document(
        db=db,
        document_id=document_id,
        name=body.name,
        description=body.description,
        tags=body.tags,
        status=body.status,
        organization_id=scope_org(token_data),
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
    document = await document_service.soft_delete_document(
        db, document_id, scope_org(token_data)
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
    # Resolve the org before the try block so a 403 is not swallowed into a 500.
    org_filter = scope_org(token_data)

    try:
        version = await document_service.create_new_version(
            db=db,
            document_id=document_id,
            created_by=UUID(token_data.sub),
            file_content=file_content,
            file_name=file.filename,
            content_type=content_type,
            change_description=change_description,
            organization_id=org_filter,
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
    document = await document_service.get_document(db, document_id, scope_org(token_data))
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
    document = await document_service.get_document(db, document_id, scope_org(token_data))
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
