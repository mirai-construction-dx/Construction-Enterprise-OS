"""API リクエスト/レスポンス スキーマ"""

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field


# ============================================
# 工事台帳 (ProjectLedger)
# ============================================
class LedgerCreateRequest(BaseModel):
    # organization_id はトークンの org クレームから導出する（ボディは信用しない）
    project_id: UUID
    project_code: str = Field(max_length=50)
    project_name: str = Field(max_length=500)
    project_type: str = Field(max_length=50)
    client_name: str | None = None
    contract_amount: Decimal = Field(gt=0)
    budget_amount: Decimal = Field(default=Decimal("0"))
    status: str = "planning"
    start_date: date | None = None
    planned_end_date: date | None = None
    location: str | None = None
    manager_id: UUID | None = None


class LedgerUpdateRequest(BaseModel):
    project_code: str | None = None
    project_name: str | None = None
    project_type: str | None = None
    client_name: str | None = None
    contract_amount: Decimal | None = Field(default=None, gt=0)
    budget_amount: Decimal | None = None
    progress_rate: Decimal | None = Field(default=None, ge=0, le=100)
    status: str | None = None
    start_date: date | None = None
    planned_end_date: date | None = None
    actual_end_date: date | None = None
    location: str | None = None
    manager_id: UUID | None = None


class BudgetSummary(BaseModel):
    category: str
    planned_amount: Decimal
    actual_amount: Decimal
    variance: Decimal

    model_config = {"from_attributes": True}


class FinancialSummary(BaseModel):
    contract_amount: Decimal
    budget_amount: Decimal
    actual_cost: Decimal
    estimated_profit: Decimal
    profit_margin: Decimal
    progress_rate: Decimal
    budget_utilization: Decimal


class LedgerResponse(BaseModel):
    id: UUID
    organization_id: UUID
    project_id: UUID
    project_code: str
    project_name: str
    project_type: str
    client_name: str | None
    contract_amount: Decimal
    budget_amount: Decimal
    actual_cost: Decimal
    estimated_profit: Decimal | None
    progress_rate: Decimal
    status: str
    start_date: date | None
    planned_end_date: date | None
    actual_end_date: date | None
    location: str | None
    manager_id: UUID | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class LedgerDetailResponse(LedgerResponse):
    budgets: list["BudgetItemResponse"] = []
    cost_summary: dict[str, Decimal] = {}


class LedgerListResponse(BaseModel):
    items: list[LedgerResponse]
    total: int
    page: int
    per_page: int


# ============================================
# 予算 (Budget)
# ============================================
class BudgetCreateRequest(BaseModel):
    # organization_id はトークンの org クレームから導出する（ボディは信用しない）
    category: str = Field(max_length=100)
    planned_amount: Decimal = Field(gt=0)
    note: str | None = None


class BudgetUpdateRequest(BaseModel):
    planned_amount: Decimal | None = None
    note: str | None = None


class BudgetItemResponse(BaseModel):
    id: UUID
    organization_id: UUID
    ledger_id: UUID | None
    category: str
    planned_amount: Decimal
    actual_amount: Decimal
    variance: Decimal
    note: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class BudgetSummaryResponse(BaseModel):
    ledger_id: UUID
    budget_items: list[BudgetItemResponse]
    total_planned: Decimal
    total_actual: Decimal
    total_variance: Decimal


# ============================================
# 原価 (CostItem)
# ============================================
class CostCreateRequest(BaseModel):
    # organization_id / created_by はトークン（org / sub）から導出する
    budget_id: UUID | None = None
    category: str = Field(max_length=100)
    description: str
    amount: Decimal = Field(gt=0)
    cost_date: date
    vendor_name: str | None = None
    invoice_number: str | None = None
    receipt_file_key: str | None = None


class CostUpdateRequest(BaseModel):
    category: str | None = None
    description: str | None = None
    amount: Decimal | None = Field(default=None, gt=0)
    cost_date: date | None = None
    vendor_name: str | None = None
    invoice_number: str | None = None
    receipt_file_key: str | None = None


class CostApproveRequest(BaseModel):
    # approved_by はトークンの sub クレームから導出する（ボディは信用しない）
    pass


class CostItemResponse(BaseModel):
    id: UUID
    organization_id: UUID
    ledger_id: UUID | None
    budget_id: UUID | None
    category: str
    description: str
    amount: Decimal
    cost_date: date
    vendor_name: str | None
    invoice_number: str | None
    status: str
    approved_by: UUID | None
    approved_at: datetime | None
    receipt_file_key: str | None
    created_by: UUID | None
    created_at: datetime

    model_config = {"from_attributes": True}


class CostListResponse(BaseModel):
    items: list[CostItemResponse]
    total: int
    page: int
    per_page: int


# ============================================
# 請求書 (Invoice)
# ============================================
class InvoiceCreateRequest(BaseModel):
    # organization_id はトークンの org クレームから導出する（ボディは信用しない）
    ledger_id: UUID | None = None
    invoice_number: str = Field(max_length=100)
    invoice_type: str = Field(max_length=20)
    vendor_name: str = Field(max_length=255)
    amount: Decimal = Field(gt=0)
    tax_amount: Decimal = Field(default=Decimal("0"))
    issue_date: date
    due_date: date | None = None
    payment_method: str | None = None
    notes: str | None = None


class InvoiceUpdateRequest(BaseModel):
    amount: Decimal | None = None
    tax_amount: Decimal | None = None
    due_date: date | None = None
    status: str | None = None
    payment_method: str | None = None
    notes: str | None = None


class InvoicePayRequest(BaseModel):
    paid_date: date | None = None
    payment_method: str | None = None


class InvoiceResponse(BaseModel):
    id: UUID
    organization_id: UUID
    ledger_id: UUID | None
    invoice_number: str
    invoice_type: str
    vendor_name: str
    amount: Decimal
    tax_amount: Decimal
    total_amount: Decimal
    issue_date: date
    due_date: date | None
    status: str
    paid_date: date | None
    payment_method: str | None
    notes: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class InvoiceListResponse(BaseModel):
    items: list[InvoiceResponse]
    total: int
    page: int
    per_page: int
