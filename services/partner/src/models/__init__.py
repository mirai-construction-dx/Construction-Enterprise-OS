"""協力会社データモデル"""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    Numeric,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class Partner(Base):
    __tablename__ = "partners"
    __table_args__ = (
        Index("ix_partners_organization_id", "organization_id"),
        Index("ix_partners_company_type", "company_type"),
        Index("ix_partners_status", "status"),
        Index("ix_partners_name", "name"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    name_kana: Mapped[str | None] = mapped_column(String(255))
    company_type: Mapped[str] = mapped_column(String(50), nullable=False)
    tax_id: Mapped[str | None] = mapped_column(String(50))
    address: Mapped[str | None] = mapped_column(String(500))
    phone: Mapped[str | None] = mapped_column(String(20))
    email: Mapped[str | None] = mapped_column(String(255))
    website: Mapped[str | None] = mapped_column(String(500))
    representative_name: Mapped[str | None] = mapped_column(String(255))
    employee_count: Mapped[int | None] = mapped_column(Integer)
    established_year: Mapped[int | None] = mapped_column(Integer)
    specializations: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    license_info: Mapped[dict | None] = mapped_column(JSONB)
    insurance_info: Mapped[dict | None] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(20), default="active")
    rating: Mapped[float | None] = mapped_column(Float)
    registered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    contacts: Mapped[list["PartnerContact"]] = relationship(
        "PartnerContact", back_populates="partner", cascade="all, delete-orphan"
    )
    contracts: Mapped[list["Contract"]] = relationship(
        "Contract", back_populates="partner", foreign_keys="Contract.partner_id"
    )
    evaluations: Mapped[list["Evaluation"]] = relationship(
        "Evaluation", back_populates="partner"
    )
    assignments: Mapped[list["ProjectAssignment"]] = relationship(
        "ProjectAssignment", back_populates="partner"
    )


class PartnerContact(Base):
    __tablename__ = "partner_contacts"
    __table_args__ = (Index("ix_partner_contacts_partner_id", "partner_id"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    partner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("partner.partners.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    title: Mapped[str | None] = mapped_column(String(255))
    department: Mapped[str | None] = mapped_column(String(255))
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(20))
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    partner: Mapped["Partner"] = relationship("Partner", back_populates="contacts")


class Contract(Base):
    __tablename__ = "contracts"
    __table_args__ = (
        Index("ix_contracts_organization_id", "organization_id"),
        Index("ix_contracts_partner_id", "partner_id"),
        Index("ix_contracts_project_id", "project_id"),
        Index("ix_contracts_status", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False
    )
    partner_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("partner.partners.id")
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    contract_number: Mapped[str | None] = mapped_column(String(100))
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    contract_type: Mapped[str] = mapped_column(String(50), nullable=False)
    amount: Mapped[float] = mapped_column(Numeric(15, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="JPY")
    start_date: Mapped[datetime] = mapped_column(Date, nullable=False)
    end_date: Mapped[datetime | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), default="draft")
    terms: Mapped[str | None] = mapped_column(Text)
    signed_by_our: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    signed_by_partner: Mapped[str | None] = mapped_column(String(255))
    signed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    partner: Mapped["Partner | None"] = relationship(
        "Partner", back_populates="contracts", foreign_keys=[partner_id]
    )
    assignment: Mapped["ProjectAssignment | None"] = relationship(
        "ProjectAssignment",
        back_populates="contract",
        foreign_keys="ProjectAssignment.contract_id",
    )


class Evaluation(Base):
    __tablename__ = "evaluations"
    __table_args__ = (
        Index("ix_evaluations_partner_id", "partner_id"),
        Index("ix_evaluations_project_id", "project_id"),
        Index("ix_evaluations_evaluator_id", "evaluator_id"),
        UniqueConstraint(
            "partner_id",
            "project_id",
            "evaluator_id",
            name="uq_evaluations_partner_project_evaluator",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False
    )
    partner_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("partner.partners.id")
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    evaluator_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    overall_score: Mapped[float] = mapped_column(Numeric(3, 1), nullable=False)
    quality_score: Mapped[float | None] = mapped_column(Numeric(3, 1))
    safety_score: Mapped[float | None] = mapped_column(Numeric(3, 1))
    schedule_score: Mapped[float | None] = mapped_column(Numeric(3, 1))
    cost_score: Mapped[float | None] = mapped_column(Numeric(3, 1))
    communication_score: Mapped[float | None] = mapped_column(Numeric(3, 1))
    comment: Mapped[str | None] = mapped_column(Text)
    evaluation_period_start: Mapped[datetime | None] = mapped_column(Date)
    evaluation_period_end: Mapped[datetime | None] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    partner: Mapped["Partner | None"] = relationship(
        "Partner", back_populates="evaluations"
    )


class ProjectAssignment(Base):
    __tablename__ = "project_assignments"
    __table_args__ = (
        Index("ix_project_assignments_partner_id", "partner_id"),
        Index("ix_project_assignments_project_id", "project_id"),
        Index("ix_project_assignments_contract_id", "contract_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False
    )
    partner_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("partner.partners.id")
    )
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    contract_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("partner.contracts.id")
    )
    role: Mapped[str] = mapped_column(String(100), nullable=False)
    scope_of_work: Mapped[str | None] = mapped_column(Text)
    start_date: Mapped[datetime | None] = mapped_column(Date)
    end_date: Mapped[datetime | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), default="active")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    partner: Mapped["Partner | None"] = relationship(
        "Partner", back_populates="assignments"
    )
    contract: Mapped["Contract | None"] = relationship(
        "Contract", back_populates="assignment", foreign_keys=[contract_id]
    )
