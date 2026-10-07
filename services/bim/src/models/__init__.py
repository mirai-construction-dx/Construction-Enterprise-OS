"""BIM関連 SQLAlchemy モデル"""

import uuid
from datetime import date, datetime

from geoalchemy2 import Geometry
from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class BIMModel(Base):
    __tablename__ = "bim_models"
    __table_args__ = (
        Index("ix_bim_models_org", "organization_id"),
        Index("ix_bim_models_project", "project_id"),
        Index("ix_bim_models_type", "model_type"),
        Index("ix_bim_models_status", "status"),
        Index("ix_bim_models_format", "file_format"),
        Index("ix_bim_models_discipline", "discipline"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    model_type: Mapped[str] = mapped_column(String(50), nullable=False)
    file_format: Mapped[str] = mapped_column(String(50), nullable=False)
    file_size: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    file_key: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="draft")
    author: Mapped[str | None] = mapped_column(String(255), nullable=True)
    software: Mapped[str | None] = mapped_column(String(255), nullable=True)
    coordinate_system: Mapped[str | None] = mapped_column(String(100), nullable=True)
    bounding_box: Mapped[dict | None] = mapped_column(JSONB, default=dict)
    discipline: Mapped[str | None] = mapped_column(String(100), nullable=True)
    lod: Mapped[str | None] = mapped_column(String(20), nullable=True)
    tags: Mapped[list | None] = mapped_column(ARRAY(Text), default=list)
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSONB, default=dict)
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    elements: Mapped[list["BIMElement"]] = relationship(
        back_populates="model", cascade="all, delete-orphan"
    )


class BIMElement(Base):
    __tablename__ = "bim_elements"
    __table_args__ = (
        Index("ix_bim_elements_model", "model_id"),
        Index("ix_bim_elements_type", "element_type"),
        Index("ix_bim_elements_category", "category"),
        Index("ix_bim_elements_level", "level_name"),
        Index("ix_bim_elements_location", "location", postgresql_using="gist"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # model_id に ForeignKey が無いと relationship の join 条件を解決できず、
    # mapper 構成時に NoForeignKeysError となり BIM サービスのDBアクセスが全て失敗する。
    model_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("bim.bim_models.id", ondelete="CASCADE"),
        nullable=False,
    )
    element_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    name: Mapped[str | None] = mapped_column(String(500), nullable=True)
    element_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    category: Mapped[str | None] = mapped_column(String(100), nullable=True)
    properties: Mapped[dict | None] = mapped_column(JSONB, default=dict)
    quantity: Mapped[float | None] = mapped_column(Float, nullable=True)
    unit: Mapped[str | None] = mapped_column(String(50), nullable=True)
    level_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    building_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    location: Mapped[str | None] = mapped_column(
        Geometry(geometry_type="POINTZ", srid=4326, spatial_index=False), nullable=True
    )
    bounding_box: Mapped[dict | None] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    model: Mapped["BIMModel"] = relationship(back_populates="elements")


class PointCloud(Base):
    __tablename__ = "point_clouds"
    __table_args__ = (
        Index("ix_point_clouds_org", "organization_id"),
        Index("ix_point_clouds_project", "project_id"),
        Index("ix_point_clouds_method", "capture_method"),
        Index("ix_point_clouds_location", "location", postgresql_using="gist"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    capture_method: Mapped[str | None] = mapped_column(String(50), nullable=True)
    capture_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    point_count: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    file_size: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    file_format: Mapped[str | None] = mapped_column(String(50), nullable=True)
    file_key: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    coordinate_system: Mapped[str | None] = mapped_column(String(100), nullable=True)
    bounding_box: Mapped[dict | None] = mapped_column(JSONB, default=dict)
    density: Mapped[float | None] = mapped_column(Float, nullable=True)
    accuracy_mm: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_colorized: Mapped[bool] = mapped_column(Boolean, default=False)
    is_classified: Mapped[bool] = mapped_column(Boolean, default=False)
    version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    source_model_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    source_video_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    location: Mapped[str | None] = mapped_column(
        Geometry(geometry_type="POLYGON", srid=4326, spatial_index=False), nullable=True
    )
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSONB, default=dict)
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
