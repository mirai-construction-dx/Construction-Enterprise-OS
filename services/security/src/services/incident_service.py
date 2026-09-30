"""Security incident service layer."""

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import IncidentUpdate, SecurityIncident


def _utcnow():
    return datetime.now(timezone.utc)


async def create_incident(
    db: AsyncSession,
    organization_id: UUID,
    title: str,
    severity: str,
    incident_type: str,
    description: str | None = None,
    source_ip: str | None = None,
    affected_systems: list[str] | None = None,
    detected_by: str | None = None,
) -> SecurityIncident:
    incident = SecurityIncident(
        organization_id=organization_id,
        title=title,
        severity=severity,
        incident_type=incident_type,
        description=description,
        source_ip=source_ip,
        affected_systems=affected_systems,
        detected_by=detected_by,
        status="open",
    )
    db.add(incident)
    await db.flush()
    return incident


async def get_incidents(
    db: AsyncSession,
    organization_id: UUID | None = None,
    severity: str | None = None,
    status: str | None = None,
    incident_type: str | None = None,
    skip: int = 0,
    limit: int = 50,
) -> list[SecurityIncident]:
    stmt = select(SecurityIncident)
    if organization_id is not None:
        stmt = stmt.where(SecurityIncident.organization_id == organization_id)
    if severity:
        stmt = stmt.where(SecurityIncident.severity == severity)
    if status:
        stmt = stmt.where(SecurityIncident.status == status)
    if incident_type:
        stmt = stmt.where(SecurityIncident.incident_type == incident_type)
    stmt = stmt.order_by(SecurityIncident.created_at.desc()).offset(skip).limit(limit)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_incident_by_id(
    db: AsyncSession, incident_id: UUID, organization_id: UUID | None = None
) -> SecurityIncident | None:
    """Look up an incident; ``organization_id`` restricts it to one org (``None``: admin, any org)."""
    stmt = select(SecurityIncident).where(SecurityIncident.id == incident_id)
    if organization_id is not None:
        stmt = stmt.where(SecurityIncident.organization_id == organization_id)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def update_incident(
    db: AsyncSession,
    incident_id: UUID,
    organization_id: UUID | None = None,
    status: str | None = None,
    severity: str | None = None,
    assigned_to: UUID | None = None,
    resolution: str | None = None,
) -> SecurityIncident | None:
    incident = await get_incident_by_id(db, incident_id, organization_id)
    if not incident:
        return None
    if status is not None:
        incident.status = status
    if severity is not None:
        incident.severity = severity
    if assigned_to is not None:
        incident.assigned_to = assigned_to
    if resolution is not None:
        incident.resolution = resolution
        incident.resolved_at = _utcnow() if status in ("resolved", "closed") else None
    incident.updated_at = _utcnow()
    await db.flush()
    return incident


async def add_incident_update(
    db: AsyncSession,
    incident_id: UUID,
    user_id: UUID,
    update_type: str,
    content: str,
    organization_id: UUID | None = None,
) -> IncidentUpdate | None:
    incident = await get_incident_by_id(db, incident_id, organization_id)
    if not incident:
        return None
    update = IncidentUpdate(
        incident_id=incident_id,
        user_id=user_id,
        update_type=update_type,
        content=content,
    )
    db.add(update)
    await db.flush()
    return update


async def get_active_incident_count(
    db: AsyncSession, organization_id: UUID | None = None
) -> int:
    stmt = select(func.count()).select_from(SecurityIncident).where(
        SecurityIncident.status.notin_(["closed", "resolved"])
    )
    if organization_id is not None:
        stmt = stmt.where(SecurityIncident.organization_id == organization_id)
    result = await db.execute(stmt)
    return result.scalar() or 0


async def get_incident_count_by_severity(
    db: AsyncSession, organization_id: UUID | None = None
) -> dict[str, int]:
    stmt = (
        select(SecurityIncident.severity, func.count())
        .select_from(SecurityIncident)
        .where(SecurityIncident.status.notin_(["closed", "resolved"]))
    )
    if organization_id is not None:
        stmt = stmt.where(SecurityIncident.organization_id == organization_id)
    stmt = stmt.group_by(SecurityIncident.severity)
    result = await db.execute(stmt)
    rows = result.all()
    severity_map = {"critical": 0, "high": 0, "medium": 0, "low": 0, "info": 0}
    for severity, count in rows:
        if severity in severity_map:
            severity_map[severity] = count
    return severity_map
