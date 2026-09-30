"""工事台帳 API"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from ..middleware.auth import TokenData, get_current_user
from ..middleware.tenant import create_org, scope_org
from ..models.base import get_db
from ..schemas.schemas import (
    FinancialSummary,
    LedgerCreateRequest,
    LedgerDetailResponse,
    LedgerListResponse,
    LedgerResponse,
    LedgerUpdateRequest,
)
from ..services import ledger_service

router = APIRouter()


@router.get("/ledger/summary")
async def get_ledger_overall_summary(
    # 全社の財務サマリー。同一ファイルの他ルート同様に認証を要求する
    _user: TokenData = Depends(get_current_user),
):
    """全工事台帳の財務サマリー（フロントエンドダッシュボード用スタブ）"""
    return {
        "total_revenue": 850000000,
        "total_cost": 680000000,
        "gross_profit": 170000000,
        "operating_profit": 145000000,
        "projects_count": 12,
        "gross_margin": 0.2,
        "operating_margin": 0.171,
    }


@router.post(
    "/ledger", response_model=LedgerResponse, status_code=status.HTTP_201_CREATED
)
async def create_ledger(
    body: LedgerCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    data = body.model_dump()
    data["organization_id"] = create_org(current_user, body.organization_id)
    ledger = await ledger_service.create_ledger(db, data)
    return ledger


@router.get("/ledger", response_model=LedgerListResponse)
async def list_ledgers(
    organization_id: UUID | None = Query(None),
    status: str | None = Query(None),
    project_type: str | None = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    items, total = await ledger_service.list_ledgers(
        db,
        organization_id=scope_org(current_user, organization_id),
        status=status,
        project_type=project_type,
        page=page,
        per_page=per_page,
    )
    return LedgerListResponse(items=items, total=total, page=page, per_page=per_page)  # type: ignore[arg-type]


@router.get("/ledger/{ledger_id}", response_model=LedgerDetailResponse)
async def get_ledger(
    ledger_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    ledger = await ledger_service.get_ledger(db, ledger_id, scope_org(current_user))
    if not ledger:
        raise HTTPException(status_code=404, detail="工事台帳が見つかりません")
    detail = await ledger_service.get_ledger_detail(db, ledger)
    return LedgerDetailResponse(
        **{k: v for k, v in detail.items() if k != "ledger"},
        **LedgerResponse.model_validate(ledger).model_dump(),
    )


@router.put("/ledger/{ledger_id}", response_model=LedgerResponse)
async def update_ledger(
    ledger_id: UUID,
    body: LedgerUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    ledger = await ledger_service.get_ledger(db, ledger_id, scope_org(current_user))
    if not ledger:
        raise HTTPException(status_code=404, detail="工事台帳が見つかりません")
    return await ledger_service.update_ledger(
        db, ledger, body.model_dump(exclude_none=True)
    )


@router.get("/ledger/{ledger_id}/summary", response_model=FinancialSummary)
async def get_financial_summary(
    ledger_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    ledger = await ledger_service.get_ledger(db, ledger_id, scope_org(current_user))
    if not ledger:
        raise HTTPException(status_code=404, detail="工事台帳が見つかりません")
    return await ledger_service.get_financial_summary(ledger)
