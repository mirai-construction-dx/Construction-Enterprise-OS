"""請求管理サービス"""

import uuid
from datetime import date, datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.models import Invoice


async def create_invoice(db: AsyncSession, data: dict) -> Invoice:
    amount = float(data.get("amount", 0))
    tax = float(data.get("tax_amount", 0))
    total = amount + tax

    invoice = Invoice(
        total_amount=total,
        **data,
    )
    db.add(invoice)
    await db.flush()
    await db.refresh(invoice)
    return invoice


async def get_invoice(
    db: AsyncSession,
    invoice_id: uuid.UUID,
    organization_id: uuid.UUID | None = None,
) -> Invoice | None:
    """Fetch an invoice; when ``organization_id`` is given, other organizations' rows are not found."""
    if organization_id is None:
        return await db.get(Invoice, invoice_id)
    result = await db.execute(
        select(Invoice).where(
            Invoice.id == invoice_id, Invoice.organization_id == organization_id
        )
    )
    return result.scalar_one_or_none()


async def list_invoices(
    db: AsyncSession,
    organization_id: uuid.UUID | None = None,
    ledger_id: uuid.UUID | None = None,
    invoice_type: str | None = None,
    status: str | None = None,
    page: int = 1,
    per_page: int = 20,
) -> tuple[list[Invoice], int]:
    query = select(Invoice)
    count_query = select(func.count(Invoice.id))

    if organization_id:
        query = query.where(Invoice.organization_id == organization_id)
        count_query = count_query.where(Invoice.organization_id == organization_id)
    if ledger_id:
        query = query.where(Invoice.ledger_id == ledger_id)
        count_query = count_query.where(Invoice.ledger_id == ledger_id)
    if invoice_type:
        query = query.where(Invoice.invoice_type == invoice_type)
        count_query = count_query.where(Invoice.invoice_type == invoice_type)
    if status:
        query = query.where(Invoice.status == status)
        count_query = count_query.where(Invoice.status == status)

    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    query = query.order_by(Invoice.created_at.desc())
    query = query.offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(query)
    items = list(result.scalars().all())

    return items, total


async def update_invoice(
    db: AsyncSession, invoice: Invoice, data: dict
) -> Invoice:
    for key, value in data.items():
        if value is not None:
            setattr(invoice, key, value)

    # Recalculate total from amount + tax
    if "amount" in data or "tax_amount" in data:
        invoice.total_amount = float(invoice.amount) + float(invoice.tax_amount)

    invoice.updated_at = datetime.now(timezone.utc)
    await db.flush()
    await db.refresh(invoice)
    return invoice


async def pay_invoice(
    db: AsyncSession,
    invoice: Invoice,
    paid_date: date | None = None,
    payment_method: str | None = None,
) -> Invoice:
    if invoice.status not in ("issued", "draft", "overdue"):
        raise ValueError(f"現在の状態({invoice.status})では支払処理できません")

    invoice.status = "paid"
    invoice.paid_date = paid_date or datetime.now(timezone.utc).date()
    if payment_method:
        invoice.payment_method = payment_method
    invoice.updated_at = datetime.now(timezone.utc)
    await db.flush()
    await db.refresh(invoice)
    return invoice
