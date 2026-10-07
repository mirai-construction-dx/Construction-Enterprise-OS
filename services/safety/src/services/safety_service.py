"""Safety service business logic layer."""

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import HazardReport, SafetyIncident, SafetyInspection


def _utcnow():
    return datetime.now(timezone.utc)


# 危険予知の語彙。リポジトリ内に正式な定義資料が無いため、実装と既存テスト
# （tests/test_safety.py の reported→assessed→mitigated→closed）で使われている値から
# 暫定の許可リストを構成する。**正式な語彙は人の確認が必要**。
HAZARD_SEVERITIES = frozenset({"minor", "moderate", "severe", "catastrophic"})
HAZARD_RISK_LEVELS = frozenset({"low", "medium", "high", "critical"})
HAZARD_STATUSES = frozenset(
    {"reported", "assessed", "in_progress", "mitigated", "resolved", "closed"}
)
# 終端状態。ここから差し戻す更新は拒否する（是正完了記録の取消を防ぐ）。
HAZARD_TERMINAL_STATUSES = frozenset({"closed"})


class HazardTransitionError(ValueError):
    """許可されない状態遷移。"""


class InspectionResultReversalError(ValueError):
    """確定済み巡視の合否を巻き戻す再完了。"""


INSPECTION_TERMINAL_STATUSES = frozenset({"passed", "failed"})


# ═══════════════════════════════════════════════════════
# Inspections
# ═══════════════════════════════════════════════════════

async def create_inspection(
    db: AsyncSession,
    organization_id: UUID,
    title: str,
    inspection_type: str,
    inspector_id: UUID,
    project_id: UUID | None = None,
    site_id: UUID | None = None,
    inspection_date: datetime | None = None,
    location: str | None = None,
) -> SafetyInspection:
    inspection = SafetyInspection(
        organization_id=organization_id,
        project_id=project_id,
        site_id=site_id,
        title=title,
        inspection_type=inspection_type,
        inspector_id=inspector_id,
        inspection_date=inspection_date,
        location=location,
        status="scheduled",
    )
    db.add(inspection)
    await db.flush()
    return inspection


async def get_inspections(
    db: AsyncSession,
    organization_id: UUID | None = None,
    inspection_type: str | None = None,
    status: str | None = None,
    project_id: UUID | None = None,
    skip: int = 0,
    limit: int = 50,
) -> list[SafetyInspection]:
    stmt = select(SafetyInspection)
    if organization_id:
        stmt = stmt.where(SafetyInspection.organization_id == organization_id)
    if inspection_type:
        stmt = stmt.where(SafetyInspection.inspection_type == inspection_type)
    if status:
        stmt = stmt.where(SafetyInspection.status == status)
    if project_id:
        stmt = stmt.where(SafetyInspection.project_id == project_id)
    stmt = stmt.order_by(SafetyInspection.created_at.desc()).offset(skip).limit(limit)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_inspection_by_id(
    db: AsyncSession,
    inspection_id: UUID,
    organization_id: UUID | None = None,
) -> SafetyInspection | None:
    stmt = select(SafetyInspection).where(SafetyInspection.id == inspection_id)
    if organization_id is not None:
        stmt = stmt.where(SafetyInspection.organization_id == organization_id)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def update_inspection(
    db: AsyncSession,
    inspection_id: UUID,
    organization_id: UUID | None = None,
    title: str | None = None,
    status: str | None = None,
    inspector_id: UUID | None = None,
    inspection_date: datetime | None = None,
    location: str | None = None,
    findings: str | None = None,
    corrective_actions: str | None = None,
    score: int | None = None,
    is_safe: bool | None = None,
) -> SafetyInspection | None:
    inspection = await get_inspection_by_id(db, inspection_id, organization_id)
    if not inspection:
        return None
    if title is not None:
        inspection.title = title
    if status is not None:
        inspection.status = status
    if inspector_id is not None:
        inspection.inspector_id = inspector_id
    if inspection_date is not None:
        inspection.inspection_date = inspection_date
    if location is not None:
        inspection.location = location
    if findings is not None:
        inspection.findings = findings
    if corrective_actions is not None:
        inspection.corrective_actions = corrective_actions
    if score is not None:
        inspection.score = score
    if is_safe is not None:
        inspection.is_safe = is_safe
    inspection.updated_at = _utcnow()
    await db.flush()
    return inspection


async def complete_inspection(
    db: AsyncSession,
    inspection_id: UUID,
    is_safe: bool,
    actor_id: UUID | None = None,
    organization_id: UUID | None = None,
    findings: str | None = None,
    corrective_actions: str | None = None,
    score: int | None = None,
) -> SafetyInspection | None:
    inspection = await get_inspection_by_id(db, inspection_id, organization_id)
    if not inspection:
        return None
    # 確定済みの合否を反転させる再完了は拒否する（是正記録の否認不能性を守る）。
    # 同一結果での再送は冪等に受理し、未指定の項目は既存値を保持する。
    if (
        inspection.status in INSPECTION_TERMINAL_STATUSES
        and inspection.is_safe is not None
        and inspection.is_safe != is_safe
    ):
        raise InspectionResultReversalError(
            f"inspection {inspection_id} is already finalized as "
            f"{'passed' if inspection.is_safe else 'failed'}"
        )
    inspection.is_safe = is_safe
    inspection.status = "passed" if is_safe else "failed"
    if findings is not None:
        inspection.findings = findings
    if corrective_actions is not None:
        inspection.corrective_actions = corrective_actions
    if score is not None:
        inspection.score = score
    # 実行者と実施日の証跡を残す（ボディの値ではなくトークンの sub を使う）
    if actor_id is not None:
        inspection.inspector_id = actor_id
    if inspection.inspection_date is None:
        inspection.inspection_date = _utcnow().date()
    inspection.updated_at = _utcnow()
    await db.flush()
    return inspection


async def get_inspection_stats(
    db: AsyncSession,
    organization_id: UUID | None = None,
) -> dict:
    def _scoped(stmt):
        if organization_id is not None:
            return stmt.where(SafetyInspection.organization_id == organization_id)
        return stmt

    total_stmt = _scoped(select(func.count()).select_from(SafetyInspection))
    total_result = await db.execute(total_stmt)
    total = total_result.scalar() or 0

    passed_stmt = _scoped(
        select(func.count())
        .select_from(SafetyInspection)
        .where(SafetyInspection.status == "passed")
    )
    passed_result = await db.execute(passed_stmt)
    passed = passed_result.scalar() or 0

    failed_stmt = _scoped(
        select(func.count())
        .select_from(SafetyInspection)
        .where(SafetyInspection.status == "failed")
    )
    failed_result = await db.execute(failed_stmt)
    failed = failed_result.scalar() or 0

    avg_stmt = _scoped(
        select(func.avg(SafetyInspection.score)).select_from(SafetyInspection)
    )
    avg_result = await db.execute(avg_stmt)
    avg_score = avg_result.scalar()

    return {
        "total": total,
        "passed": passed,
        "failed": failed,
        # 平均 0.0 は falsy のため ``if avg_score`` では欠測(None)と区別できない。
        # 欠測は avg_score is None の場合のみ。
        "average_score": round(float(avg_score), 2) if avg_score is not None else None,
    }


# ═══════════════════════════════════════════════════════
# Hazard Reports
# ═══════════════════════════════════════════════════════

async def create_hazard(
    db: AsyncSession,
    organization_id: UUID,
    title: str,
    description: str,
    hazard_type: str,
    risk_level: str,
    severity: str,
    reported_by: UUID,
    project_id: UUID | None = None,
    site_id: UUID | None = None,
    location: str | None = None,
    assigned_to: UUID | None = None,
) -> HazardReport:
    hazard = HazardReport(
        organization_id=organization_id,
        project_id=project_id,
        site_id=site_id,
        title=title,
        description=description,
        hazard_type=hazard_type,
        risk_level=risk_level,
        severity=severity,
        reported_by=reported_by,
        location=location,
        assigned_to=assigned_to,
        status="reported",
    )
    db.add(hazard)
    await db.flush()
    return hazard


async def get_hazards(
    db: AsyncSession,
    organization_id: UUID | None = None,
    hazard_type: str | None = None,
    risk_level: str | None = None,
    status: str | None = None,
    skip: int = 0,
    limit: int = 50,
) -> list[HazardReport]:
    stmt = select(HazardReport)
    if organization_id:
        stmt = stmt.where(HazardReport.organization_id == organization_id)
    if hazard_type:
        stmt = stmt.where(HazardReport.hazard_type == hazard_type)
    if risk_level:
        stmt = stmt.where(HazardReport.risk_level == risk_level)
    if status:
        stmt = stmt.where(HazardReport.status == status)
    stmt = stmt.order_by(HazardReport.created_at.desc()).offset(skip).limit(limit)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_hazard_by_id(
    db: AsyncSession,
    hazard_id: UUID,
    organization_id: UUID | None = None,
) -> HazardReport | None:
    stmt = select(HazardReport).where(HazardReport.id == hazard_id)
    if organization_id is not None:
        stmt = stmt.where(HazardReport.organization_id == organization_id)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def get_open_hazards(
    db: AsyncSession, organization_id: UUID | None = None
) -> list[HazardReport]:
    stmt = (
        select(HazardReport)
        .where(HazardReport.status.notin_(["resolved", "closed"]))
        .order_by(HazardReport.created_at.desc())
    )
    if organization_id is not None:
        stmt = stmt.where(HazardReport.organization_id == organization_id)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def update_hazard(
    db: AsyncSession,
    hazard_id: UUID,
    organization_id: UUID | None = None,
    title: str | None = None,
    description: str | None = None,
    status: str | None = None,
    risk_level: str | None = None,
    severity: str | None = None,
    assigned_to: UUID | None = None,
    mitigation: str | None = None,
) -> HazardReport | None:
    hazard = await get_hazard_by_id(db, hazard_id, organization_id)
    if not hazard:
        return None
    if title is not None:
        hazard.title = title
    if description is not None:
        hazard.description = description
    if status is not None:
        if hazard.status in HAZARD_TERMINAL_STATUSES and status != hazard.status:
            raise HazardTransitionError(
                f"status '{hazard.status}' is terminal; cannot transition to '{status}'"
            )
        hazard.status = status
        if status in ("resolved", "closed"):
            hazard.resolved_at = _utcnow()
    if risk_level is not None:
        hazard.risk_level = risk_level
    if severity is not None:
        hazard.severity = severity
    if assigned_to is not None:
        hazard.assigned_to = assigned_to
    if mitigation is not None:
        hazard.mitigation = mitigation
    await db.flush()
    return hazard


# ═══════════════════════════════════════════════════════
# Safety Incidents
# ═══════════════════════════════════════════════════════

async def create_safety_incident(
    db: AsyncSession,
    organization_id: UUID,
    title: str,
    description: str,
    incident_type: str,
    severity: str,
    incident_date: datetime,
    reported_by: UUID,
    project_id: UUID | None = None,
    site_id: UUID | None = None,
    location: str | None = None,
    injured_count: int = 0,
    fatality_count: int = 0,
    is_osha_reportable: bool = False,
) -> SafetyIncident:
    incident = SafetyIncident(
        organization_id=organization_id,
        project_id=project_id,
        site_id=site_id,
        title=title,
        description=description,
        incident_type=incident_type,
        severity=severity,
        incident_date=incident_date,
        location=location,
        injured_count=injured_count,
        fatality_count=fatality_count,
        reported_by=reported_by,
        is_osha_reportable=is_osha_reportable,
        status="reported",
    )
    db.add(incident)
    await db.flush()
    return incident


async def get_safety_incidents(
    db: AsyncSession,
    organization_id: UUID | None = None,
    incident_type: str | None = None,
    severity: str | None = None,
    status: str | None = None,
    skip: int = 0,
    limit: int = 50,
) -> list[SafetyIncident]:
    stmt = select(SafetyIncident)
    if organization_id:
        stmt = stmt.where(SafetyIncident.organization_id == organization_id)
    if incident_type:
        stmt = stmt.where(SafetyIncident.incident_type == incident_type)
    if severity:
        stmt = stmt.where(SafetyIncident.severity == severity)
    if status:
        stmt = stmt.where(SafetyIncident.status == status)
    stmt = stmt.order_by(SafetyIncident.created_at.desc()).offset(skip).limit(limit)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_safety_incident_by_id(
    db: AsyncSession,
    incident_id: UUID,
    organization_id: UUID | None = None,
) -> SafetyIncident | None:
    stmt = select(SafetyIncident).where(SafetyIncident.id == incident_id)
    if organization_id is not None:
        stmt = stmt.where(SafetyIncident.organization_id == organization_id)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def update_safety_incident(
    db: AsyncSession,
    incident_id: UUID,
    organization_id: UUID | None = None,
    title: str | None = None,
    description: str | None = None,
    status: str | None = None,
    severity: str | None = None,
    investigated_by: UUID | None = None,
    root_cause: str | None = None,
    corrective_actions: str | None = None,
    injured_count: int | None = None,
    fatality_count: int | None = None,
    is_osha_reportable: bool | None = None,
) -> SafetyIncident | None:
    incident = await get_safety_incident_by_id(db, incident_id, organization_id)
    if not incident:
        return None
    if title is not None:
        incident.title = title
    if description is not None:
        incident.description = description
    if status is not None:
        incident.status = status
        if status in ("resolved", "closed"):
            incident.resolved_at = _utcnow()
    if severity is not None:
        incident.severity = severity
    if investigated_by is not None:
        incident.investigated_by = investigated_by
    if root_cause is not None:
        incident.root_cause = root_cause
    if corrective_actions is not None:
        incident.corrective_actions = corrective_actions
    if injured_count is not None:
        incident.injured_count = injured_count
    if fatality_count is not None:
        incident.fatality_count = fatality_count
    if is_osha_reportable is not None:
        incident.is_osha_reportable = is_osha_reportable
    incident.updated_at = _utcnow()
    await db.flush()
    return incident
