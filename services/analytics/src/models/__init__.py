"""Analytics データモデル — analytics スキーマ"""

import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class DataSource(Base):
    """データソース接続定義"""
    __tablename__ = "data_sources"
    __table_args__ = (
        Index("ix_data_sources_organization_id", "organization_id"),
        Index("ix_data_sources_source_type", "source_type"),
        Index("ix_data_sources_status", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    source_type: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # postgresql|timescaledb|elasticsearch|minio|kafka|csv_api
    # 保存時暗号化は「未実装」。connection_config は平文 JSONB として保存される（#138）。
    # API 応答には返さない（write-only）が、DB/バックアップには平文で残るため、
    # 暗号化（KMS/Secrets Manager 等）を実装するまでは認証情報の保存を前提にしない。
    connection_config: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(20), default="active")
    description: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    pipelines_as_source: Mapped[list["DataPipeline"]] = relationship(
        "DataPipeline", foreign_keys="DataPipeline.source_id", back_populates="source"
    )
    pipelines_as_target: Mapped[list["DataPipeline"]] = relationship(
        "DataPipeline", foreign_keys="DataPipeline.target_id", back_populates="target"
    )


class DataPipeline(Base):
    """ETLパイプライン定義"""
    __tablename__ = "data_pipelines"
    __table_args__ = (
        Index("ix_data_pipelines_organization_id", "organization_id"),
        Index("ix_data_pipelines_source_id", "source_id"),
        Index("ix_data_pipelines_target_id", "target_id"),
        Index("ix_data_pipelines_status", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    source_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("analytics.data_sources.id")
    )
    target_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("analytics.data_sources.id")
    )
    transform_logic: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    schedule: Mapped[str | None] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(20), default="draft")
    last_run: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    source: Mapped["DataSource | None"] = relationship(
        "DataSource", foreign_keys=[source_id], back_populates="pipelines_as_source"
    )
    target: Mapped["DataSource | None"] = relationship(
        "DataSource", foreign_keys=[target_id], back_populates="pipelines_as_target"
    )


class AnalyticsReport(Base):
    """BIレポート定義"""
    __tablename__ = "analytics_reports"
    __table_args__ = (
        Index("ix_analytics_reports_organization_id", "organization_id"),
        Index("ix_analytics_reports_report_type", "report_type"),
        Index("ix_analytics_reports_status", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    report_type: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # dashboard|chart|table|export
    query_config: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    schedule: Mapped[str | None] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(20), default="draft")
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
