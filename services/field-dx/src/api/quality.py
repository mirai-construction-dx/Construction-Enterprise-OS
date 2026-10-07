"""品質管理 API"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ..middleware.auth import TokenData, get_current_user
from ..middleware.tenant import create_org, scope_org
from ..models.base import get_db
from ..schemas import (
    QualityCheckCreateRequest,
    QualityCheckListResponse,
    QualityCheckResponse,
    QualityCheckUpdateRequest,
    QualityStatsResponse,
)
from ..services import field_service

router = APIRouter()


class QualityCheckItem(BaseModel):
    id: str
    check_number: str
    check_type: str
    zone: str
    item: str
    result: str
    inspector: str
    inspection_date: str
    status: str
    note: str | None = None


class CorrectiveActionItem(BaseModel):
    id: str
    issue_number: str
    description: str
    zone: str
    severity: str
    assigned_to: str
    due_date: str
    status: str
    root_cause: str | None = None


_MOCK_QUALITY_CHECKS = [
    QualityCheckItem(
        id="qc1",
        check_number="QC-2024-001",
        check_type="コンクリート強度",
        zone="第1工区",
        item="圧縮強度試験",
        result="合格",
        inspector="品質管理部 田中",
        inspection_date="2024-05-20",
        status="passed",
        note="設計基準強度 24N/mm² 達成",
    ),
    QualityCheckItem(
        id="qc2",
        check_number="QC-2024-002",
        check_type="鉄筋検査",
        zone="第2工区",
        item="配筋間隔・かぶり厚",
        result="要是正",
        inspector="品質管理部 山田",
        inspection_date="2024-05-21",
        status="failed",
        note="かぶり厚不足（一部）",
    ),
    QualityCheckItem(
        id="qc3",
        check_number="QC-2024-003",
        check_type="型枠検査",
        zone="第3工区",
        item="寸法・精度確認",
        result="合格",
        inspector="品質管理部 鈴木",
        inspection_date="2024-05-22",
        status="passed",
    ),
]

_MOCK_CORRECTIVE_ACTIONS = [
    CorrectiveActionItem(
        id="ca1",
        issue_number="CA-2024-001",
        description="第2工区 かぶり厚不足の是正",
        zone="第2工区",
        severity="high",
        assigned_to="施工班 佐藤",
        due_date="2024-05-25",
        status="in_progress",
        root_cause="施工管理不足",
    ),
    CorrectiveActionItem(
        id="ca2",
        issue_number="CA-2024-002",
        description="第1工区 養生期間延長",
        zone="第1工区",
        severity="medium",
        assigned_to="施工班 高橋",
        due_date="2024-05-27",
        status="open",
    ),
]


@router.post(
    "/quality",
    response_model=QualityCheckResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_quality_check(
    body: QualityCheckCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    org_id = create_org(current_user, body.organization_id)
    data = body.model_dump()
    data["organization_id"] = org_id
    data["inspector_id"] = UUID(current_user.sub)
    check = await field_service.create_quality_check(db, data)
    return check


@router.get("/quality", response_model=QualityCheckListResponse)
async def list_quality_checks(
    project_id: UUID | None = Query(None),
    check_type: str | None = Query(None),
    status: str | None = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    items, total = await field_service.list_quality_checks(
        db,
        organization_id=scope_org(current_user),
        project_id=project_id,
        check_type=check_type,
        status=status,
        page=page,
        per_page=per_page,
    )
    return QualityCheckListResponse(
        items=[QualityCheckResponse.model_validate(item) for item in items],
        total=total,
        page=page,
        per_page=per_page,
    )


@router.put("/quality/{check_id}", response_model=QualityCheckResponse)
async def update_quality_check(
    check_id: UUID,
    body: QualityCheckUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    org_id = scope_org(current_user)
    check = await field_service.get_quality_check(db, check_id)
    if not check or (org_id is not None and check.organization_id != org_id):
        raise HTTPException(status_code=404, detail="品質チェックが見つかりません")
    return await field_service.update_quality_check(
        db, check, body.model_dump(exclude_none=True)
    )


@router.get(
    "/quality/{project_id}/stats",
    response_model=QualityStatsResponse,
)
async def quality_stats(
    project_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    return await field_service.get_quality_stats(
        db, project_id, scope_org(current_user)
    )


@router.get("/quality/checks")
async def list_quality_check_stubs(
    per_page: int = Query(20, ge=1, le=100),
    page: int = Query(1, ge=1),

    _user: TokenData = Depends(get_current_user),
):
    start = (page - 1) * per_page
    items = _MOCK_QUALITY_CHECKS[start : start + per_page]
    return {
        "items": [c.model_dump() for c in items],
        "total": len(_MOCK_QUALITY_CHECKS),
    }


@router.get("/quality/corrective")
async def list_corrective_actions(
    per_page: int = Query(20, ge=1, le=100),
    page: int = Query(1, ge=1),

    _user: TokenData = Depends(get_current_user),
):
    start = (page - 1) * per_page
    items = _MOCK_CORRECTIVE_ACTIONS[start : start + per_page]
    return {
        "items": [a.model_dump() for a in items],
        "total": len(_MOCK_CORRECTIVE_ACTIONS),
    }
