"""請求管理 API"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from ..middleware.auth import (
    FINANCE_ROLES,
    TokenData,
    get_current_user,
    require_any_role,
)
from ..middleware.tenant import create_org, scope_org
from ..models.base import get_db
from ..schemas.schemas import (
    InvoiceCreateRequest,
    InvoiceListResponse,
    InvoicePayRequest,
    InvoiceResponse,
    InvoiceUpdateRequest,
)
from ..services import invoice_service, ledger_service

router = APIRouter()


@router.post(
    "/invoices",
    response_model=InvoiceResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_invoice(
    body: InvoiceCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    org = create_org(current_user, body.organization_id)
    if body.ledger_id is not None:
        # The linked ledger must belong to the invoice's organization (ADR-0004)
        ledger = await ledger_service.get_ledger(db, body.ledger_id, org)
        if not ledger:
            raise HTTPException(status_code=404, detail="工事台帳が見つかりません")
    require_any_role(current_user, FINANCE_ROLES)
    data = body.model_dump()
    data["organization_id"] = org
    return await invoice_service.create_invoice(db, data)


@router.get("/invoices", response_model=InvoiceListResponse)
async def list_invoices(
    organization_id: UUID | None = Query(None),
    ledger_id: UUID | None = Query(None),
    invoice_type: str | None = Query(None),
    status: str | None = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    items, total = await invoice_service.list_invoices(
        db,
        organization_id=scope_org(current_user, organization_id),
        ledger_id=ledger_id,
        invoice_type=invoice_type,
        status=status,
        page=page,
        per_page=per_page,
    )
    return InvoiceListResponse(items=items, total=total, page=page, per_page=per_page)  # type: ignore[arg-type]


@router.get("/invoices/{invoice_id}", response_model=InvoiceResponse)
async def get_invoice(
    invoice_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    invoice = await invoice_service.get_invoice(db, invoice_id, scope_org(current_user))
    if not invoice:
        raise HTTPException(status_code=404, detail="請求書が見つかりません")
    return invoice


@router.put("/invoices/{invoice_id}", response_model=InvoiceResponse)
async def update_invoice(
    invoice_id: UUID,
    body: InvoiceUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    invoice = await invoice_service.get_invoice(db, invoice_id, scope_org(current_user))
    if not invoice:
        raise HTTPException(status_code=404, detail="請求書が見つかりません")
    require_any_role(current_user, FINANCE_ROLES)
    return await invoice_service.update_invoice(
        db, invoice, body.model_dump(exclude_none=True)
    )


@router.post("/invoices/{invoice_id}/pay", response_model=InvoiceResponse)
async def pay_invoice(
    invoice_id: UUID,
    body: InvoicePayRequest,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    invoice = await invoice_service.get_invoice(db, invoice_id, scope_org(current_user))
    if not invoice:
        raise HTTPException(status_code=404, detail="請求書が見つかりません")
    require_any_role(current_user, FINANCE_ROLES)
    try:
        return await invoice_service.pay_invoice(
            db,
            invoice,
            paid_date=body.paid_date,
            payment_method=body.payment_method,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
