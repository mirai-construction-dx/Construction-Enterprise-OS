"""Security policy API endpoints."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from ..middleware.auth import TokenData, get_current_user
from ..middleware.tenant import create_org, scope_org
from ..models.base import get_db
from ..schemas import APIResponse, PolicyCreate, PolicyUpdate
from ..services import policy_service

router = APIRouter()


def _policy_to_response(p) -> dict:
    return {
        "id": str(p.id),
        "organization_id": str(p.organization_id),
        "name": p.name,
        "description": p.description,
        "category": p.category,
        "content": p.content,
        "version": p.version,
        "status": p.status,
        "effective_date": p.effective_date.isoformat() if p.effective_date else None,
        "review_date": p.review_date.isoformat() if p.review_date else None,
        "approved_by": str(p.approved_by) if p.approved_by else None,
        "created_at": p.created_at.isoformat() if p.created_at else None,
        "updated_at": p.updated_at.isoformat() if p.updated_at else None,
    }


@router.post("/policies", status_code=status.HTTP_201_CREATED)
async def create_policy(
    body: PolicyCreate,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    policy = await policy_service.create_policy(
        db,
        organization_id=create_org(current_user, body.organization_id),
        name=body.name,
        category=body.category,
        content=body.content,
        description=body.description,
        effective_date=body.effective_date,
        review_date=body.review_date,
        approved_by=UUID(current_user.sub),
    )
    return APIResponse(data=_policy_to_response(policy))


@router.get("/policies")
async def list_policies(
    organization_id: UUID | None = Query(None),
    category: str | None = Query(None),
    status: str | None = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    policies = await policy_service.get_policies(
        db,
        organization_id=scope_org(current_user, organization_id),
        category=category,
        status=status,
        skip=skip,
        limit=limit,
    )
    return APIResponse(data=[_policy_to_response(p) for p in policies])


@router.get("/policies/{policy_id}")
async def get_policy(
    policy_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    policy = await policy_service.get_policy_by_id(
        db, policy_id, scope_org(current_user)
    )
    if not policy:
        raise HTTPException(
            status_code=404,
            detail={"code": "NOT_FOUND", "message": "Policy not found."},
        )
    return APIResponse(data=_policy_to_response(policy))


@router.put("/policies/{policy_id}")
async def update_policy(
    policy_id: UUID,
    body: PolicyUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    policy = await policy_service.update_policy(
        db,
        policy_id,
        organization_id=scope_org(current_user),
        name=body.name,
        description=body.description,
        category=body.category,
        content=body.content,
        status=body.status,
        effective_date=body.effective_date,
        review_date=body.review_date,
    )
    if not policy:
        raise HTTPException(
            status_code=404,
            detail={"code": "NOT_FOUND", "message": "Policy not found."},
        )
    return APIResponse(data=_policy_to_response(policy))


@router.post("/policies/{policy_id}/review")
async def review_policy(
    policy_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    policy = await policy_service.mark_policy_reviewed(
        db,
        policy_id,
        approved_by=UUID(current_user.sub),
        organization_id=scope_org(current_user),
    )
    if not policy:
        raise HTTPException(
            status_code=404,
            detail={"code": "NOT_FOUND", "message": "Policy not found."},
        )
    return APIResponse(data=_policy_to_response(policy))
