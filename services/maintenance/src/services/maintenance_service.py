"""Maintenance service business logic layer."""

import json
from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import DisasterReport, InspectionSchedule, MaintenanceRecord, RecoveryPlan


def _utcnow():
    return datetime.now(timezone.utc)


# ═══════════════════════════════════════════════════════
# Disaster Reports
# ═══════════════════════════════════════════════════════


async def create_disaster_report(
    db: AsyncSession,
    organization_id: UUID,
    title: str,
    disaster_type: str,
    severity: str,
    occurred_at: datetime,
    description: str,
    reported_by: UUID,
    project_id: UUID | None = None,
    location: str | None = None,
    estimated_cost: Decimal | None = None,
    casualties: int = 0,
    evacuation_required: bool = False,
) -> DisasterReport:
    report = DisasterReport(
        organization_id=organization_id,
        project_id=project_id,
        title=title,
        disaster_type=disaster_type,
        severity=severity,
        occurred_at=occurred_at,
        location=location,
        description=description,
        estimated_cost=estimated_cost,
        casualties=casualties,
        evacuation_required=evacuation_required,
        reported_by=reported_by,
        status="reported",
    )
    db.add(report)
    await db.flush()
    return report


async def get_disaster_reports(
    db: AsyncSession,
    organization_id: UUID | None = None,
    disaster_type: str | None = None,
    severity: str | None = None,
    status: str | None = None,
    skip: int = 0,
    limit: int = 50,
) -> list[DisasterReport]:
    stmt = select(DisasterReport)
    if organization_id is not None:
        stmt = stmt.where(DisasterReport.organization_id == organization_id)
    if disaster_type:
        stmt = stmt.where(DisasterReport.disaster_type == disaster_type)
    if severity:
        stmt = stmt.where(DisasterReport.severity == severity)
    if status:
        stmt = stmt.where(DisasterReport.status == status)
    stmt = stmt.order_by(DisasterReport.created_at.desc()).offset(skip).limit(limit)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_disaster_report_by_id(
    db: AsyncSession, report_id: UUID, organization_id: UUID | None = None
) -> DisasterReport | None:
    """Fetch by id; ``organization_id`` restricts to that organization (None = no filter)."""
    stmt = select(DisasterReport).where(DisasterReport.id == report_id)
    if organization_id is not None:
        stmt = stmt.where(DisasterReport.organization_id == organization_id)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def update_disaster_report(
    db: AsyncSession,
    report_id: UUID,
    organization_id: UUID | None = None,
    title: str | None = None,
    status: str | None = None,
    severity: str | None = None,
    damage_assessment: str | None = None,
    estimated_cost: Decimal | None = None,
    casualties: int | None = None,
    evacuation_required: bool | None = None,
) -> DisasterReport | None:
    report = await get_disaster_report_by_id(db, report_id, organization_id)
    if not report:
        return None
    if title is not None:
        report.title = title
    if status is not None:
        report.status = status
    if severity is not None:
        report.severity = severity
    if damage_assessment is not None:
        report.damage_assessment = damage_assessment
    if estimated_cost is not None:
        report.estimated_cost = estimated_cost
    if casualties is not None:
        report.casualties = casualties
    if evacuation_required is not None:
        report.evacuation_required = evacuation_required
    report.updated_at = _utcnow()
    await db.flush()
    return report


# ═══════════════════════════════════════════════════════
# Recovery Plans
# ═══════════════════════════════════════════════════════


async def create_recovery_plan(
    db: AsyncSession,
    organization_id: UUID,
    disaster_report_id: UUID,
    title: str,
    created_by: UUID,
    description: str | None = None,
    priority: str = "medium",
    estimated_duration_days: int | None = None,
    estimated_cost: Decimal | None = None,
    start_date: date | None = None,
    contractor: str | None = None,
    resources_needed: str | None = None,
) -> RecoveryPlan:
    plan = RecoveryPlan(
        organization_id=organization_id,
        disaster_report_id=disaster_report_id,
        title=title,
        description=description,
        priority=priority,
        estimated_duration_days=estimated_duration_days,
        estimated_cost=estimated_cost,
        start_date=start_date,
        contractor=contractor,
        resources_needed=resources_needed,
        created_by=created_by,
        status="planned",
    )
    db.add(plan)
    await db.flush()
    return plan


async def get_recovery_plan_by_id(
    db: AsyncSession, plan_id: UUID, organization_id: UUID | None = None
) -> RecoveryPlan | None:
    """Fetch by id; ``organization_id`` restricts to that organization (None = no filter)."""
    stmt = select(RecoveryPlan).where(RecoveryPlan.id == plan_id)
    if organization_id is not None:
        stmt = stmt.where(RecoveryPlan.organization_id == organization_id)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def get_recovery_plans_for_disaster(
    db: AsyncSession, disaster_report_id: UUID, organization_id: UUID | None = None
) -> list[RecoveryPlan]:
    stmt = select(RecoveryPlan).where(RecoveryPlan.disaster_report_id == disaster_report_id)
    # Defense in depth: child plans are also filtered by their own organization (ADR-0004).
    if organization_id is not None:
        stmt = stmt.where(RecoveryPlan.organization_id == organization_id)
    stmt = stmt.order_by(RecoveryPlan.created_at.desc())
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def update_recovery_plan(
    db: AsyncSession,
    plan_id: UUID,
    organization_id: UUID | None = None,
    title: str | None = None,
    description: str | None = None,
    priority: str | None = None,
    status: str | None = None,
    estimated_duration_days: int | None = None,
    estimated_cost: Decimal | None = None,
    actual_cost: Decimal | None = None,
    start_date: date | None = None,
    completed_date: date | None = None,
    contractor: str | None = None,
    resources_needed: str | None = None,
    progress_percent: Decimal | None = None,
) -> RecoveryPlan | None:
    plan = await get_recovery_plan_by_id(db, plan_id, organization_id)
    if not plan:
        return None
    if title is not None:
        plan.title = title
    if description is not None:
        plan.description = description
    if priority is not None:
        plan.priority = priority
    if status is not None:
        plan.status = status
        if status == "completed":
            plan.completed_date = date.today()  # type: ignore[assignment]
            plan.progress_percent = Decimal("100.00")
    if estimated_duration_days is not None:
        plan.estimated_duration_days = estimated_duration_days
    if estimated_cost is not None:
        plan.estimated_cost = estimated_cost
    if actual_cost is not None:
        plan.actual_cost = actual_cost
    if start_date is not None:
        plan.start_date = start_date  # type: ignore[assignment]
    if completed_date is not None:
        plan.completed_date = completed_date  # type: ignore[assignment]
    if contractor is not None:
        plan.contractor = contractor
    if resources_needed is not None:
        plan.resources_needed = resources_needed
    if progress_percent is not None:
        plan.progress_percent = progress_percent
    plan.updated_at = _utcnow()
    await db.flush()
    return plan


# ═══════════════════════════════════════════════════════
# Maintenance Records
# ═══════════════════════════════════════════════════════


async def create_maintenance_record(
    db: AsyncSession,
    organization_id: UUID,
    asset_name: str,
    asset_type: str,
    maintenance_type: str,
    description: str,
    project_id: UUID | None = None,
    cost: Decimal | None = None,
    contractor: str | None = None,
    scheduled_date: date | None = None,
    next_maintenance_date: date | None = None,
    location: str | None = None,
    performed_by: UUID | None = None,
    notes: str | None = None,
) -> MaintenanceRecord:
    record = MaintenanceRecord(
        organization_id=organization_id,
        project_id=project_id,
        asset_name=asset_name,
        asset_type=asset_type,
        maintenance_type=maintenance_type,
        description=description,
        cost=cost,
        contractor=contractor,
        scheduled_date=scheduled_date,
        next_maintenance_date=next_maintenance_date,
        location=location,
        performed_by=performed_by,
        notes=notes,
        status="scheduled",
    )
    db.add(record)
    await db.flush()
    return record


async def get_maintenance_records(
    db: AsyncSession,
    organization_id: UUID | None = None,
    asset_type: str | None = None,
    maintenance_type: str | None = None,
    status: str | None = None,
    skip: int = 0,
    limit: int = 50,
) -> list[MaintenanceRecord]:
    stmt = select(MaintenanceRecord)
    if organization_id is not None:
        stmt = stmt.where(MaintenanceRecord.organization_id == organization_id)
    if asset_type:
        stmt = stmt.where(MaintenanceRecord.asset_type == asset_type)
    if maintenance_type:
        stmt = stmt.where(MaintenanceRecord.maintenance_type == maintenance_type)
    if status:
        stmt = stmt.where(MaintenanceRecord.status == status)
    stmt = stmt.order_by(MaintenanceRecord.created_at.desc()).offset(skip).limit(limit)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_maintenance_record_by_id(
    db: AsyncSession, record_id: UUID, organization_id: UUID | None = None
) -> MaintenanceRecord | None:
    """Fetch by id; ``organization_id`` restricts to that organization (None = no filter)."""
    stmt = select(MaintenanceRecord).where(MaintenanceRecord.id == record_id)
    if organization_id is not None:
        stmt = stmt.where(MaintenanceRecord.organization_id == organization_id)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def update_maintenance_record(
    db: AsyncSession,
    record_id: UUID,
    organization_id: UUID | None = None,
    asset_name: str | None = None,
    status: str | None = None,
    work_performed: str | None = None,
    cost: Decimal | None = None,
    contractor: str | None = None,
    completed_date: date | None = None,
    next_maintenance_date: date | None = None,
    performed_by: UUID | None = None,
    notes: str | None = None,
) -> MaintenanceRecord | None:
    record = await get_maintenance_record_by_id(db, record_id, organization_id)
    if not record:
        return None
    if asset_name is not None:
        record.asset_name = asset_name
    if status is not None:
        record.status = status
        if status == "completed":
            record.completed_date = record.completed_date or date.today()  # type: ignore[assignment]
    if work_performed is not None:
        record.work_performed = work_performed
    if cost is not None:
        record.cost = cost
    if contractor is not None:
        record.contractor = contractor
    if completed_date is not None:
        record.completed_date = completed_date  # type: ignore[assignment]
    if next_maintenance_date is not None:
        record.next_maintenance_date = next_maintenance_date  # type: ignore[assignment]
    if performed_by is not None:
        record.performed_by = performed_by
    if notes is not None:
        record.notes = notes
    record.updated_at = _utcnow()
    await db.flush()
    return record


async def get_overdue_maintenance(
    db: AsyncSession,
    organization_id: UUID | None = None,
) -> list[MaintenanceRecord]:
    today = date.today()
    stmt = (
        select(MaintenanceRecord)
        .where(
            MaintenanceRecord.scheduled_date < today,
            MaintenanceRecord.status != "completed",
            MaintenanceRecord.status != "deferred",
        )
        .order_by(MaintenanceRecord.scheduled_date.asc())
    )
    if organization_id is not None:
        stmt = stmt.where(MaintenanceRecord.organization_id == organization_id)
    result = await db.execute(stmt)
    return list(result.scalars().all())


# ═══════════════════════════════════════════════════════
# Inspection Schedules
# ═══════════════════════════════════════════════════════


async def create_inspection_schedule(
    db: AsyncSession,
    organization_id: UUID,
    asset_name: str,
    asset_type: str,
    inspection_type: str,
    frequency: str,
    next_inspection_date: date,
    inspector: str | None = None,
    notes: str | None = None,
) -> InspectionSchedule:
    inspection = InspectionSchedule(
        organization_id=organization_id,
        asset_name=asset_name,
        asset_type=asset_type,
        inspection_type=inspection_type,
        frequency=frequency,
        next_inspection_date=next_inspection_date,
        inspector=inspector,
        notes=notes,
        status="scheduled",
    )
    db.add(inspection)
    await db.flush()
    return inspection


async def get_inspection_schedules(
    db: AsyncSession,
    organization_id: UUID | None = None,
    status: str | None = None,
    skip: int = 0,
    limit: int = 50,
) -> list[InspectionSchedule]:
    stmt = select(InspectionSchedule)
    if organization_id is not None:
        stmt = stmt.where(InspectionSchedule.organization_id == organization_id)
    if status:
        stmt = stmt.where(InspectionSchedule.status == status)
    stmt = stmt.order_by(InspectionSchedule.next_inspection_date.asc()).offset(skip).limit(limit)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_inspection_schedule_by_id(
    db: AsyncSession, inspection_id: UUID, organization_id: UUID | None = None
) -> InspectionSchedule | None:
    """Fetch by id; ``organization_id`` restricts to that organization (None = no filter)."""
    stmt = select(InspectionSchedule).where(InspectionSchedule.id == inspection_id)
    if organization_id is not None:
        stmt = stmt.where(InspectionSchedule.organization_id == organization_id)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def update_inspection_schedule(
    db: AsyncSession,
    inspection_id: UUID,
    organization_id: UUID | None = None,
    status: str | None = None,
    checklist: list | None = None,
    notes: str | None = None,
    next_inspection_date: date | None = None,
    inspector: str | None = None,
) -> InspectionSchedule | None:
    inspection = await get_inspection_schedule_by_id(db, inspection_id, organization_id)
    if not inspection:
        return None
    if status is not None:
        inspection.status = status
        if status == "completed":
            inspection.last_inspection_date = date.today()  # type: ignore[assignment]
    if checklist is not None:
        inspection.checklist = json.dumps(checklist)  # type: ignore[assignment]
    if notes is not None:
        inspection.notes = notes
    if next_inspection_date is not None:
        inspection.next_inspection_date = next_inspection_date  # type: ignore[assignment]
    if inspector is not None:
        inspection.inspector = inspector
    inspection.updated_at = _utcnow()
    await db.flush()
    return inspection


async def complete_inspection(
    db: AsyncSession,
    inspection_id: UUID,
    checklist: list | None = None,
    notes: str | None = None,
    organization_id: UUID | None = None,
) -> InspectionSchedule | None:
    return await update_inspection_schedule(
        db,
        inspection_id,
        organization_id=organization_id,
        status="completed",
        checklist=checklist,
        notes=notes,
    )


async def get_upcoming_inspections(
    db: AsyncSession,
    organization_id: UUID | None = None,
) -> list[InspectionSchedule]:
    from datetime import timedelta

    today = date.today()
    thirty_days = today + timedelta(days=30)
    stmt = (
        select(InspectionSchedule)
        .where(
            InspectionSchedule.next_inspection_date >= today,
            InspectionSchedule.next_inspection_date <= thirty_days,
            InspectionSchedule.status == "scheduled",
        )
        .order_by(InspectionSchedule.next_inspection_date.asc())
    )
    if organization_id is not None:
        stmt = stmt.where(InspectionSchedule.organization_id == organization_id)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_overdue_inspections(
    db: AsyncSession,
    organization_id: UUID | None = None,
) -> list[InspectionSchedule]:
    today = date.today()
    stmt = (
        select(InspectionSchedule)
        .where(
            InspectionSchedule.next_inspection_date < today,
            InspectionSchedule.status.notin_(["completed", "cancelled"]),
        )
        .order_by(InspectionSchedule.next_inspection_date.asc())
    )
    if organization_id is not None:
        stmt = stmt.where(InspectionSchedule.organization_id == organization_id)
    result = await db.execute(stmt)
    return list(result.scalars().all())
