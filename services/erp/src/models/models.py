"""ERP データモデル — erp スキーマ"""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class ProjectLedger(Base):
    """工事台帳"""
    __tablename__ = "project_ledger"
    __table_args__ = (
        Index("ix_project_ledger_organization_id", "organization_id"),
        Index("ix_project_ledger_project_id", "project_id"),
        Index("ix_project_ledger_status", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    project_code: Mapped[str] = mapped_column(String(50), nullable=False)
    project_name: Mapped[str] = mapped_column(String(500), nullable=False)
    project_type: Mapped[str] = mapped_column(String(50), nullable=False)
    client_name: Mapped[str | None] = mapped_column(String(255))
    contract_amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)
    budget_amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), default=0)
    actual_cost: Mapped[Decimal] = mapped_column(Numeric(15, 2), default=0)
    estimated_profit: Mapped[Decimal | None] = mapped_column(Numeric(15, 2))
    progress_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=0)
    status: Mapped[str] = mapped_column(String(20), default="planning")
    start_date: Mapped[date | None] = mapped_column(Date)
    planned_end_date: Mapped[date | None] = mapped_column(Date)
    actual_end_date: Mapped[date | None] = mapped_column(Date)
    location: Mapped[str | None] = mapped_column(String(500))
    manager_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    budgets: Mapped[list["Budget"]] = relationship("Budget", back_populates="ledger")
    cost_items: Mapped[list["CostItem"]] = relationship("CostItem", back_populates="ledger")
    invoices: Mapped[list["Invoice"]] = relationship("Invoice", back_populates="ledger")
    labor_costs: Mapped[list["LaborCost"]] = relationship("LaborCost", back_populates="ledger")


class Budget(Base):
    """予算項目"""
    __tablename__ = "budgets"
    __table_args__ = (
        Index("ix_budgets_ledger_id", "ledger_id"),
        Index("ix_budgets_organization_id", "organization_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    ledger_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("erp.project_ledger.id")
    )
    category: Mapped[str] = mapped_column(String(100), nullable=False)
    planned_amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)
    actual_amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), default=0)
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    ledger: Mapped["ProjectLedger"] = relationship("ProjectLedger", back_populates="budgets")
    cost_items: Mapped[list["CostItem"]] = relationship("CostItem", back_populates="budget")

    @property
    def variance(self) -> Decimal:
        return self.planned_amount - self.actual_amount


class CostItem(Base):
    """原価明細"""
    __tablename__ = "cost_items"
    __table_args__ = (
        Index("ix_cost_items_ledger_id", "ledger_id"),
        Index("ix_cost_items_budget_id", "budget_id"),
        Index("ix_cost_items_organization_id", "organization_id"),
        Index("ix_cost_items_status", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    ledger_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("erp.project_ledger.id")
    )
    budget_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("erp.budgets.id")
    )
    category: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)
    cost_date: Mapped[date] = mapped_column(Date, nullable=False)
    vendor_name: Mapped[str | None] = mapped_column(String(255))
    invoice_number: Mapped[str | None] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(20), default="pending")
    approved_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    receipt_file_key: Mapped[str | None] = mapped_column(String(1000))
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    ledger: Mapped["ProjectLedger"] = relationship("ProjectLedger", back_populates="cost_items")
    budget: Mapped["Budget"] = relationship("Budget", back_populates="cost_items")


class Invoice(Base):
    """請求書"""
    __tablename__ = "invoices"
    __table_args__ = (
        Index("ix_invoices_ledger_id", "ledger_id"),
        Index("ix_invoices_organization_id", "organization_id"),
        Index("ix_invoices_status", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    ledger_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("erp.project_ledger.id")
    )
    invoice_number: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    invoice_type: Mapped[str] = mapped_column(String(20), nullable=False)
    vendor_name: Mapped[str] = mapped_column(String(255), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)
    tax_amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), default=0)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)
    issue_date: Mapped[date] = mapped_column(Date, nullable=False)
    due_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), default="draft")
    paid_date: Mapped[date | None] = mapped_column(Date)
    payment_method: Mapped[str | None] = mapped_column(String(50))
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    ledger: Mapped["ProjectLedger"] = relationship("ProjectLedger", back_populates="invoices")


class LaborCost(Base):
    """労務費"""
    __tablename__ = "labor_costs"
    __table_args__ = (
        Index("ix_labor_costs_ledger_id", "ledger_id"),
        Index("ix_labor_costs_organization_id", "organization_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    ledger_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("erp.project_ledger.id")
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    worker_name: Mapped[str] = mapped_column(String(255), nullable=False)
    work_date: Mapped[date] = mapped_column(Date, nullable=False)
    work_hours: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    hourly_rate: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    total_cost: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)
    work_type: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    ledger: Mapped["ProjectLedger"] = relationship("ProjectLedger", back_populates="labor_costs")
