"""Vector DB operations API endpoints."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from ..middleware.auth import TokenData, get_current_user
from ..middleware.tenant import create_org, scope_org
from ..models.base import get_db
from ..schemas import (
    APIResponse,
    VectorIndexCreate,
    VectorIndexRequest,
    VectorIndexUpdate,
    VectorSearchRequest,
)
from ..services import vision_service

router = APIRouter()


def _index_to_response(idx) -> dict:
    return {
        "id": str(idx.id),
        "organization_id": str(idx.organization_id),
        "collection_name": idx.collection_name,
        "dimension": idx.dimension,
        "index_type": idx.index_type,
        "metric": idx.metric,
        "document_count": idx.document_count,
        "total_vectors": idx.total_vectors,
        "is_active": idx.is_active,
        "created_at": idx.created_at.isoformat() if idx.created_at else None,
    }


@router.post("/vectors/indices", status_code=status.HTTP_201_CREATED)
async def create_index(
    body: VectorIndexCreate,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    vi = await vision_service.create_vector_index(
        db,
        organization_id=create_org(current_user, body.organization_id),
        collection_name=body.collection_name,
        dimension=body.dimension,
        index_type=body.index_type,
        metric=body.metric,
    )
    return APIResponse(data=_index_to_response(vi))


@router.get("/vectors/indices")
async def list_indices(
    organization_id: UUID | None = Query(None),
    is_active: bool | None = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    indices = await vision_service.get_vector_indices(
        db,
        organization_id=scope_org(current_user, organization_id),
        is_active=is_active,
        skip=skip,
        limit=limit,
    )
    return APIResponse(data=[_index_to_response(i) for i in indices])


@router.get("/vectors/indices/{index_id}")
async def get_index(
    index_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    vi = await vision_service.get_vector_index_by_id(
        db, index_id, scope_org(current_user)
    )
    if not vi:
        raise HTTPException(
            status_code=404,
            detail={"code": "NOT_FOUND", "message": "Vector index not found."},
        )
    return APIResponse(data=_index_to_response(vi))


@router.patch("/vectors/indices/{index_id}")
async def update_index(
    index_id: UUID,
    body: VectorIndexUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    vi = await vision_service.update_vector_index(
        db,
        index_id,
        is_active=body.is_active,
        organization_id=scope_org(current_user),
    )
    if not vi:
        raise HTTPException(
            status_code=404,
            detail={"code": "NOT_FOUND", "message": "Vector index not found."},
        )
    return APIResponse(data=_index_to_response(vi))


@router.delete("/vectors/indices/{index_id}")
async def delete_index(
    index_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    org_id = scope_org(current_user)
    # Scoped lookup first: another organization's index is reported as not found (404)
    # and no DELETE statement is issued at all.
    if not await vision_service.get_vector_index_by_id(db, index_id, org_id):
        raise HTTPException(
            status_code=404,
            detail={"code": "NOT_FOUND", "message": "Vector index not found."},
        )
    deleted = await vision_service.delete_vector_index(db, index_id, org_id)
    if not deleted:
        raise HTTPException(
            status_code=404,
            detail={"code": "NOT_FOUND", "message": "Vector index not found."},
        )
    return APIResponse(data={"deleted": True})


@router.post("/vectors/search")
async def semantic_search(
    body: VectorSearchRequest,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    # Search is restricted to an index visible to the caller (regular users: token org only).
    vi = await vision_service.get_vector_index_by_id(
        db, body.index_id, scope_org(current_user)
    )
    if not vi:
        raise HTTPException(
            status_code=404,
            detail={"code": "NOT_FOUND", "message": "Vector index not found."},
        )

    results = vision_service.build_search_results(body.query_text, body.top_k)
    return APIResponse(data=results)


@router.post("/vectors/index", status_code=status.HTTP_201_CREATED)
async def index_documents(
    body: VectorIndexRequest,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    org_id = scope_org(current_user)
    vi = await vision_service.get_vector_index_by_id(db, body.index_id, org_id)
    if not vi:
        raise HTTPException(
            status_code=404,
            detail={"code": "NOT_FOUND", "message": "Vector index not found."},
        )

    if not body.documents:
        raise HTTPException(
            status_code=400,
            detail={"code": "INVALID_REQUEST", "message": "No documents provided."},
        )

    doc_count = len(body.documents)
    vector_count = doc_count
    await vision_service.increment_vector_counts(
        db,
        body.index_id,
        added_docs=doc_count,
        added_vectors=vector_count,
        organization_id=org_id,
    )

    indexed = [
        {
            "source_id": str(doc.source_id),
            "source_type": doc.source_type,
            "chunks_indexed": 1,
            "status": "completed",
        }
        for doc in body.documents
    ]

    return APIResponse(
        data={
            "indexed_count": doc_count,
            "total_vectors": vector_count,
            "documents": indexed,
        }
    )
