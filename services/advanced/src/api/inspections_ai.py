"""点検AIエンドポイント"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from ..middleware.auth import (
    MANAGEMENT_ROLES,
    TokenData,
    get_current_user,
    require_any_role,
)
from ..middleware.tenant import create_org, scope_org
from ..models.base import get_db
from ..schemas import (
    APIResponse,
    DefectSummaryResponse,
    InspectionRecordCreateRequest,
    InspectionRecordResponse,
    InspectionRecordUpdateRequest,
)
from ..services.advanced_service import (
    create_inspection_record,
    get_inspection_record_by_id,
    list_inspection_records,
    update_inspection_record,
    delete_inspection_record,
    get_defect_summary,
)

router = APIRouter()


def _to_response(record) -> InspectionRecordResponse:
    return InspectionRecordResponse(
        id=record.id,
        organization_id=record.organization_id,
        asset_name=record.asset_name,
        asset_type=record.asset_type,
        inspection_method=record.inspection_method,
        ai_model_used=record.ai_model_used,
        defect_type=record.defect_type,
        severity=record.severity,
        confidence=record.confidence,
        defect_count=record.defect_count,
        location=record.location,
        image_keys=record.image_keys if record.image_keys else [],
        ai_analysis=record.ai_analysis if record.ai_analysis else {},
        inspector_id=record.inspector_id,
        inspection_date=record.inspection_date,
        requires_action=record.requires_action,
        created_at=record.created_at,
    )


@router.post(
    "",
    response_model=APIResponse[InspectionRecordResponse],
    status_code=status.HTTP_201_CREATED,
)
async def create_inspection(
    request: Request,
    body: InspectionRecordCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    data = body.model_dump()
    data["organization_id"] = create_org(current_user, body.organization_id)
    record = await create_inspection_record(db, data)
    return APIResponse(data=_to_response(record))


@router.get("", response_model=APIResponse)
async def list_inspections(
    request: Request,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    asset_type: str | None = Query(None),
    severity: str | None = Query(None),
    defect_type: str | None = Query(None),
    organization_id: UUID | None = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    records, total = await list_inspection_records(
        db,
        page=page,
        per_page=per_page,
        asset_type=asset_type,
        severity=severity,
        defect_type=defect_type,
        organization_id=scope_org(current_user, organization_id),
    )
    total_pages = max((total + per_page - 1) // per_page, 1) if total > 0 else 0

    return APIResponse(
        data={"records": [_to_response(r) for r in records], "total": total},
        meta={  # type: ignore[arg-type]
            "page": page,
            "per_page": per_page,
            "total": total,
            "total_pages": total_pages,
        },
    )


@router.get("/defect-summary", response_model=APIResponse[DefectSummaryResponse])
async def defect_summary(
    request: Request,
    organization_id: UUID | None = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    # Aggregate over the caller's organization only; another organization -> 403 (ADR-0004).
    # A cross-org admin may pass any organization, or none to aggregate across organizations.
    summary = await get_defect_summary(db, scope_org(current_user, organization_id))
    return APIResponse(data=summary)


@router.get("/{record_id}", response_model=APIResponse[InspectionRecordResponse])
async def get_inspection(
    request: Request,
    record_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    record = await get_inspection_record_by_id(db, record_id, scope_org(current_user))
    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "NOT_FOUND", "message": "点検記録が見つかりません。"},
        )
    return APIResponse(data=_to_response(record))


@router.put("/{record_id}", response_model=APIResponse[InspectionRecordResponse])
async def update_inspection(
    request: Request,
    record_id: UUID,
    body: InspectionRecordUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    record = await update_inspection_record(
        db, record_id, body.model_dump(exclude_unset=True), scope_org(current_user)
    )
    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "NOT_FOUND", "message": "点検記録が見つかりません。"},
        )
    return APIResponse(data=_to_response(record))


@router.delete("/{record_id}", response_model=APIResponse)
async def delete_inspection(
    request: Request,
    record_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    org_id = scope_org(current_user)  # 組織検証を先に（fail-closed）
    require_any_role(current_user, MANAGEMENT_ROLES)
    deleted = await delete_inspection_record(db, record_id, org_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "NOT_FOUND", "message": "点検記録が見つかりません。"},
        )
    return APIResponse(data={"message": "点検記録を削除しました。"})
