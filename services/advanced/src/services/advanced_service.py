"""Advanced 統合ビジネスサービス"""

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import (
    MarineConstruction,
    InspectionRecord,
    DesignReview,
    PredictiveModel,
)


def _by_id_stmt(model: Any, record_id: UUID, organization_id: UUID | None) -> Select:
    """By-id lookup scoped to an organization (ADR-0004).

    ``organization_id=None`` means no organization filter and is only passed for a cross-org
    admin. Another organization's record is simply not found (404, no existence leak).
    """
    stmt = select(model).where(model.id == record_id)
    if organization_id is not None:
        stmt = stmt.where(model.organization_id == organization_id)
    return stmt


# ============================================
# 港湾施工管理
# ============================================
async def create_marine_construction(
    db: AsyncSession, data: dict
) -> MarineConstruction:
    record = MarineConstruction(
        organization_id=data["organization_id"],
        project_id=data.get("project_id"),
        name=data["name"],
        construction_type=data["construction_type"],
        water_depth=data.get("water_depth"),
        tide_info=data.get("tide_info"),
        wave_condition=data.get("wave_condition"),
        equipment_deployed=data.get("equipment_deployed"),
        material_volume=data.get("material_volume"),
        location=data.get("location"),
        start_date=data.get("start_date"),
        end_date=data.get("end_date"),
        supervisor_id=data.get("supervisor_id"),
    )
    db.add(record)
    await db.flush()
    return record


async def get_marine_construction_by_id(
    db: AsyncSession, record_id: UUID, organization_id: UUID | None = None
) -> MarineConstruction | None:
    result = await db.execute(
        _by_id_stmt(MarineConstruction, record_id, organization_id)
    )
    return result.scalar_one_or_none()


async def list_marine_constructions(
    db: AsyncSession,
    page: int = 1,
    per_page: int = 20,
    construction_type: str | None = None,
    status: str | None = None,
    project_id: UUID | None = None,
    organization_id: UUID | None = None,
) -> tuple[list[MarineConstruction], int]:
    query = select(MarineConstruction)
    count_query = select(func.count(MarineConstruction.id))

    if construction_type:
        query = query.where(MarineConstruction.construction_type == construction_type)
        count_query = count_query.where(
            MarineConstruction.construction_type == construction_type
        )
    if status:
        query = query.where(MarineConstruction.status == status)
        count_query = count_query.where(MarineConstruction.status == status)
    if project_id:
        query = query.where(MarineConstruction.project_id == project_id)
        count_query = count_query.where(MarineConstruction.project_id == project_id)
    if organization_id is not None:
        query = query.where(MarineConstruction.organization_id == organization_id)
        count_query = count_query.where(
            MarineConstruction.organization_id == organization_id
        )

    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    query = query.order_by(MarineConstruction.created_at.desc())
    query = query.offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(query)
    records = list(result.scalars().all())

    return records, total


async def update_marine_construction(
    db: AsyncSession,
    record_id: UUID,
    data: dict,
    organization_id: UUID | None = None,
) -> MarineConstruction | None:
    result = await db.execute(
        _by_id_stmt(MarineConstruction, record_id, organization_id)
    )
    record = result.scalar_one_or_none()
    if not record:
        return None

    for key, value in data.items():
        if hasattr(record, key) and value is not None:
            setattr(record, key, value)

    await db.flush()
    return record


async def delete_marine_construction(
    db: AsyncSession, record_id: UUID, organization_id: UUID | None = None
) -> bool:
    result = await db.execute(
        _by_id_stmt(MarineConstruction, record_id, organization_id)
    )
    record = result.scalar_one_or_none()
    if not record:
        return False
    await db.delete(record)
    await db.flush()
    return True


# ============================================
# 点検AI
# ============================================
async def create_inspection_record(db: AsyncSession, data: dict) -> InspectionRecord:
    record = InspectionRecord(
        organization_id=data["organization_id"],
        asset_name=data["asset_name"],
        asset_type=data["asset_type"],
        inspection_method=data.get("inspection_method"),
        ai_model_used=data.get("ai_model_used"),
        defect_type=data.get("defect_type"),
        severity=data.get("severity"),
        confidence=data.get("confidence"),
        defect_count=data.get("defect_count"),
        location=data.get("location"),
        image_keys=data.get("image_keys", []),
        ai_analysis=data.get("ai_analysis", {}),
        inspector_id=data.get("inspector_id"),
        inspection_date=data["inspection_date"],
        requires_action=data.get("requires_action", False),
    )
    db.add(record)
    await db.flush()
    return record


async def get_inspection_record_by_id(
    db: AsyncSession, record_id: UUID, organization_id: UUID | None = None
) -> InspectionRecord | None:
    result = await db.execute(_by_id_stmt(InspectionRecord, record_id, organization_id))
    return result.scalar_one_or_none()


async def list_inspection_records(
    db: AsyncSession,
    page: int = 1,
    per_page: int = 20,
    asset_type: str | None = None,
    severity: str | None = None,
    defect_type: str | None = None,
    organization_id: UUID | None = None,
) -> tuple[list[InspectionRecord], int]:
    query = select(InspectionRecord)
    count_query = select(func.count(InspectionRecord.id))

    if asset_type:
        query = query.where(InspectionRecord.asset_type == asset_type)
        count_query = count_query.where(InspectionRecord.asset_type == asset_type)
    if severity:
        query = query.where(InspectionRecord.severity == severity)
        count_query = count_query.where(InspectionRecord.severity == severity)
    if defect_type:
        query = query.where(InspectionRecord.defect_type == defect_type)
        count_query = count_query.where(InspectionRecord.defect_type == defect_type)
    if organization_id is not None:
        query = query.where(InspectionRecord.organization_id == organization_id)
        count_query = count_query.where(
            InspectionRecord.organization_id == organization_id
        )

    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    query = query.order_by(InspectionRecord.inspection_date.desc())
    query = query.offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(query)
    records = list(result.scalars().all())

    return records, total


async def update_inspection_record(
    db: AsyncSession,
    record_id: UUID,
    data: dict,
    organization_id: UUID | None = None,
) -> InspectionRecord | None:
    result = await db.execute(_by_id_stmt(InspectionRecord, record_id, organization_id))
    record = result.scalar_one_or_none()
    if not record:
        return None

    for key, value in data.items():
        if hasattr(record, key) and value is not None:
            setattr(record, key, value)

    await db.flush()
    return record


async def delete_inspection_record(
    db: AsyncSession, record_id: UUID, organization_id: UUID | None = None
) -> bool:
    result = await db.execute(_by_id_stmt(InspectionRecord, record_id, organization_id))
    record = result.scalar_one_or_none()
    if not record:
        return False
    await db.delete(record)
    await db.flush()
    return True


async def get_defect_summary(
    db: AsyncSession, organization_id: UUID | None = None
) -> dict:
    # organization_id=None is only passed for a cross-org admin (ADR-0004)
    query = select(InspectionRecord)
    if organization_id is not None:
        query = query.where(InspectionRecord.organization_id == organization_id)
    result = await db.execute(query)
    records = list(result.scalars().all())

    total = len(records)
    by_severity: dict[str, int] = {}
    by_asset_type: dict[str, int] = {}
    by_defect_type: dict[str, int] = {}
    requires_action_count = 0
    confidence_sum = 0.0
    confidence_count = 0

    for r in records:
        if r.severity:
            by_severity[r.severity] = by_severity.get(r.severity, 0) + 1
        by_asset_type[r.asset_type] = by_asset_type.get(r.asset_type, 0) + 1
        if r.defect_type:
            by_defect_type[r.defect_type] = by_defect_type.get(r.defect_type, 0) + 1
        if r.requires_action:
            requires_action_count += 1
        if r.confidence is not None:
            confidence_sum += r.confidence
            confidence_count += 1

    return {
        "total_inspections": total,
        "by_severity": by_severity,
        "by_asset_type": by_asset_type,
        "by_defect_type": by_defect_type,
        "requires_action_count": requires_action_count,
        "average_confidence": round(confidence_sum / confidence_count, 4)
        if confidence_count
        else None,
    }


# ============================================
# AI設計照査
# ============================================
async def create_design_review(db: AsyncSession, data: dict) -> DesignReview:
    record = DesignReview(
        organization_id=data["organization_id"],
        project_id=data.get("project_id"),
        design_document_id=data.get("design_document_id"),
        review_type=data["review_type"],
        ai_suggestions=data.get("ai_suggestions", []),
        compliance_checks=data.get("compliance_checks", {}),
        reviewer_id=data.get("reviewer_id"),
    )
    db.add(record)
    await db.flush()
    return record


async def get_design_review_by_id(
    db: AsyncSession, record_id: UUID, organization_id: UUID | None = None
) -> DesignReview | None:
    result = await db.execute(_by_id_stmt(DesignReview, record_id, organization_id))
    return result.scalar_one_or_none()


async def list_design_reviews(
    db: AsyncSession,
    page: int = 1,
    per_page: int = 20,
    review_type: str | None = None,
    status: str | None = None,
    project_id: UUID | None = None,
    organization_id: UUID | None = None,
) -> tuple[list[DesignReview], int]:
    query = select(DesignReview)
    count_query = select(func.count(DesignReview.id))

    if review_type:
        query = query.where(DesignReview.review_type == review_type)
        count_query = count_query.where(DesignReview.review_type == review_type)
    if status:
        query = query.where(DesignReview.status == status)
        count_query = count_query.where(DesignReview.status == status)
    if project_id:
        query = query.where(DesignReview.project_id == project_id)
        count_query = count_query.where(DesignReview.project_id == project_id)
    if organization_id is not None:
        query = query.where(DesignReview.organization_id == organization_id)
        count_query = count_query.where(DesignReview.organization_id == organization_id)

    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    query = query.order_by(DesignReview.created_at.desc())
    query = query.offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(query)
    records = list(result.scalars().all())

    return records, total


async def update_design_review(
    db: AsyncSession,
    record_id: UUID,
    data: dict,
    organization_id: UUID | None = None,
) -> DesignReview | None:
    result = await db.execute(_by_id_stmt(DesignReview, record_id, organization_id))
    record = result.scalar_one_or_none()
    if not record:
        return None

    if "status" in data and data["status"] in ("completed", "requires_revision"):
        data["reviewed_at"] = datetime.now(timezone.utc)

    for key, value in data.items():
        if hasattr(record, key) and value is not None:
            setattr(record, key, value)

    await db.flush()
    return record


async def delete_design_review(
    db: AsyncSession, record_id: UUID, organization_id: UUID | None = None
) -> bool:
    result = await db.execute(_by_id_stmt(DesignReview, record_id, organization_id))
    record = result.scalar_one_or_none()
    if not record:
        return False
    await db.delete(record)
    await db.flush()
    return True


async def get_compliance_report(
    db: AsyncSession, review_id: UUID, organization_id: UUID | None = None
) -> dict | None:
    result = await db.execute(_by_id_stmt(DesignReview, review_id, organization_id))
    review = result.scalar_one_or_none()
    if not review:
        return None

    compliance = review.compliance_checks or {}
    suggestions: list = review.ai_suggestions or []  # type: ignore[assignment]
    violations = compliance.get("violations", [])
    passed = 0
    failed = 0
    standards_checked: list[str] = []

    if isinstance(compliance, dict):
        for key, value in compliance.items():
            if key == "standard" and isinstance(value, str):
                standards_checked.append(value)
            elif key == "standards" and isinstance(value, list):
                standards_checked = value
            elif key == "passed" and isinstance(value, int):
                passed = value
            elif key == "failed" and isinstance(value, int):
                failed = value
            elif key == "violations" and isinstance(value, list):
                violations = value

    return {
        "review_id": review.id,
        "review_type": review.review_type,
        "status": review.status,
        "standards_checked": standards_checked,
        "passed_count": passed,
        "failed_count": failed,
        "violations": violations,
        "suggestions": suggestions,
    }


# ============================================
# 予知保全
# ============================================
async def create_predictive_model(db: AsyncSession, data: dict) -> PredictiveModel:
    record = PredictiveModel(
        organization_id=data["organization_id"],
        asset_name=data["asset_name"],
        asset_type=data["asset_type"],
        model_type=data["model_type"],
        training_data_count=data.get("training_data_count"),
        accuracy=data.get("accuracy"),
        failure_probability=data.get("failure_probability"),
        remaining_life_days=data.get("remaining_life_days"),
        recommendations=data.get("recommendations", []),
        input_metrics=data.get("input_metrics", {}),
        next_maintenance_predicted=data.get("next_maintenance_predicted"),
    )
    db.add(record)
    await db.flush()
    return record


async def get_predictive_model_by_id(
    db: AsyncSession, record_id: UUID, organization_id: UUID | None = None
) -> PredictiveModel | None:
    result = await db.execute(_by_id_stmt(PredictiveModel, record_id, organization_id))
    return result.scalar_one_or_none()


async def list_predictive_models(
    db: AsyncSession,
    page: int = 1,
    per_page: int = 20,
    model_type: str | None = None,
    status: str | None = None,
    asset_type: str | None = None,
    organization_id: UUID | None = None,
) -> tuple[list[PredictiveModel], int]:
    query = select(PredictiveModel)
    count_query = select(func.count(PredictiveModel.id))

    if model_type:
        query = query.where(PredictiveModel.model_type == model_type)
        count_query = count_query.where(PredictiveModel.model_type == model_type)
    if status:
        query = query.where(PredictiveModel.status == status)
        count_query = count_query.where(PredictiveModel.status == status)
    if asset_type:
        query = query.where(PredictiveModel.asset_type == asset_type)
        count_query = count_query.where(PredictiveModel.asset_type == asset_type)
    if organization_id is not None:
        query = query.where(PredictiveModel.organization_id == organization_id)
        count_query = count_query.where(
            PredictiveModel.organization_id == organization_id
        )

    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    query = query.order_by(PredictiveModel.created_at.desc())
    query = query.offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(query)
    records = list(result.scalars().all())

    return records, total


async def update_predictive_model(
    db: AsyncSession,
    record_id: UUID,
    data: dict,
    organization_id: UUID | None = None,
) -> PredictiveModel | None:
    result = await db.execute(_by_id_stmt(PredictiveModel, record_id, organization_id))
    record = result.scalar_one_or_none()
    if not record:
        return None

    if "status" in data and data["status"] == "active":
        data["last_trained_at"] = datetime.now(timezone.utc)

    for key, value in data.items():
        if hasattr(record, key) and value is not None:
            setattr(record, key, value)

    await db.flush()
    return record


async def delete_predictive_model(
    db: AsyncSession, record_id: UUID, organization_id: UUID | None = None
) -> bool:
    result = await db.execute(_by_id_stmt(PredictiveModel, record_id, organization_id))
    record = result.scalar_one_or_none()
    if not record:
        return False
    await db.delete(record)
    await db.flush()
    return True


async def get_prediction_result(
    db: AsyncSession, model_id: UUID, organization_id: UUID | None = None
) -> dict | None:
    result = await db.execute(_by_id_stmt(PredictiveModel, model_id, organization_id))
    model = result.scalar_one_or_none()
    if not model:
        return None

    return {
        "model_id": model.id,
        "asset_name": model.asset_name,
        "asset_type": model.asset_type,
        "model_type": model.model_type,
        "status": model.status,
        "failure_probability": model.failure_probability,
        "remaining_life_days": model.remaining_life_days,
        "next_maintenance_predicted": model.next_maintenance_predicted,
        "recommendations": model.recommendations,
    }
