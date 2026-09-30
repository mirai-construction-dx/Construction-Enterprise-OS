"""文書管理 ビジネスロジック"""

import logging
import math
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Document, DocumentVersion
from ..schemas import PaginationMeta
from .search_service import count_search_documents, search_documents
from .storage_service import generate_storage_key, upload_file

logger = logging.getLogger(__name__)


async def create_document(
    db: AsyncSession,
    organization_id: UUID,
    created_by: UUID,
    name: str,
    file_name: str,
    file_content: bytes,
    content_type: str,
    project_id: UUID | None = None,
    description: str | None = None,
    document_type: str = "other",
    tags: list[str] | None = None,
    metadata: dict | None = None,
) -> Document:
    file_size = len(file_content)
    doc_id = UUID(int=0)  # placeholder, updated after flush

    storage_key = generate_storage_key(organization_id, doc_id, 1, file_name)

    document = Document(
        organization_id=organization_id,
        project_id=project_id,
        name=name,
        description=description,
        document_type=document_type,
        status="draft",
        current_version=1,
        file_name=file_name,
        file_size=file_size,
        mime_type=content_type,
        storage_key=storage_key,
        tags=tags or [],
        metadata_=metadata,
        created_by=created_by,
    )
    db.add(document)
    await db.flush()

    storage_key = generate_storage_key(organization_id, document.id, 1, file_name)
    document.storage_key = storage_key

    version = DocumentVersion(
        document_id=document.id,
        version_number=1,
        file_name=file_name,
        file_size=file_size,
        mime_type=content_type,
        storage_key=storage_key,
        change_description="Initial version",
        created_by=created_by,
    )
    db.add(version)

    upload_success = upload_file(file_content, storage_key, content_type)
    if not upload_success:
        raise RuntimeError("Failed to upload file to storage")

    await db.flush()
    await db.refresh(document)
    return document


async def get_document(
    db: AsyncSession, document_id: UUID, organization_id: UUID | None = None
) -> Document | None:
    stmt = select(Document).where(Document.id == document_id)
    if organization_id is not None:
        stmt = stmt.where(Document.organization_id == organization_id)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def list_documents(
    db: AsyncSession,
    organization_id: UUID | None,
    page: int = 1,
    per_page: int = 20,
    query: str | None = None,
    document_type: str | None = None,
    status: str | None = None,
    project_id: UUID | None = None,
    tags: list[str] | None = None,
) -> tuple[list[Document], PaginationMeta]:
    total = await count_search_documents(
        db,
        organization_id=organization_id,
        query=query,
        document_type=document_type,
        status=status,
        project_id=project_id,
        tags=tags,
    )

    offset = (page - 1) * per_page

    documents = await search_documents(
        db,
        organization_id=organization_id,
        query=query,
        document_type=document_type,
        status=status,
        project_id=project_id,
        tags=tags,
    )
    documents = documents[offset : offset + per_page]

    total_pages = math.ceil(total / per_page) if per_page > 0 else 0
    meta = PaginationMeta(
        page=page, per_page=per_page, total=total, total_pages=total_pages
    )

    return documents, meta


async def update_document(
    db: AsyncSession,
    document_id: UUID,
    name: str | None = None,
    description: str | None = None,
    tags: list[str] | None = None,
    status: str | None = None,
    organization_id: UUID | None = None,
) -> Document | None:
    document = await get_document(db, document_id, organization_id)
    if not document:
        return None

    if name is not None:
        document.name = name
    if description is not None:
        document.description = description
    if tags is not None:
        document.tags = tags
    if status is not None:
        document.status = status

    await db.flush()
    await db.refresh(document)
    return document


async def soft_delete_document(
    db: AsyncSession, document_id: UUID, organization_id: UUID | None = None
) -> Document | None:
    document = await get_document(db, document_id, organization_id)
    if not document:
        return None

    document.status = "deleted"
    await db.flush()
    await db.refresh(document)
    return document


async def create_new_version(
    db: AsyncSession,
    document_id: UUID,
    created_by: UUID,
    file_content: bytes,
    file_name: str,
    content_type: str,
    change_description: str | None = None,
    organization_id: UUID | None = None,
) -> DocumentVersion | None:
    document = await get_document(db, document_id, organization_id)
    if not document:
        return None

    new_version_number = document.current_version + 1
    storage_key = generate_storage_key(
        document.organization_id, document.id, new_version_number, file_name
    )

    version = DocumentVersion(
        document_id=document.id,
        version_number=new_version_number,
        file_name=file_name,
        file_size=len(file_content),
        mime_type=content_type,
        storage_key=storage_key,
        change_description=change_description,
        created_by=created_by,
    )
    db.add(version)

    upload_success = upload_file(file_content, storage_key, content_type)
    if not upload_success:
        raise RuntimeError("Failed to upload new version to storage")

    document.current_version = new_version_number
    document.file_name = file_name
    document.file_size = len(file_content)
    document.mime_type = content_type
    document.storage_key = storage_key

    await db.flush()
    await db.refresh(version)
    return version


async def list_versions(
    db: AsyncSession,
    document_id: UUID,
    page: int = 1,
    per_page: int = 20,
) -> tuple[list[DocumentVersion], PaginationMeta]:
    count_stmt = select(func.count(DocumentVersion.id)).where(
        DocumentVersion.document_id == document_id
    )
    result = await db.execute(count_stmt)
    total = result.scalar() or 0

    offset = (page - 1) * per_page
    stmt = (
        select(DocumentVersion)
        .where(DocumentVersion.document_id == document_id)
        .order_by(DocumentVersion.version_number.desc())
        .offset(offset)
        .limit(per_page)
    )
    versions_result = await db.execute(stmt)
    versions: list[DocumentVersion] = list(versions_result.scalars().all())

    total_pages = math.ceil(total / per_page) if per_page > 0 else 0
    meta = PaginationMeta(
        page=page, per_page=per_page, total=total, total_pages=total_pages
    )

    return versions, meta


async def get_version(
    db: AsyncSession, document_id: UUID, version_number: int
) -> DocumentVersion | None:
    stmt = select(DocumentVersion).where(
        DocumentVersion.document_id == document_id,
        DocumentVersion.version_number == version_number,
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()
