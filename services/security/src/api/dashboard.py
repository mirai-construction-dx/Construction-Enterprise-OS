"""Security dashboard API endpoint."""

from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..middleware.auth import TokenData, get_current_user
from ..middleware.tenant import scope_org
from ..models import SecurityAudit
from ..models.base import get_db
from ..schemas import APIResponse
from ..services import incident_service, policy_service, vulnerability_service

router = APIRouter()


def _incident_to_response(inc) -> dict:
    return {
        "id": str(inc.id),
        "organization_id": str(inc.organization_id),
        "title": inc.title,
        "description": inc.description,
        "severity": inc.severity,
        "incident_type": inc.incident_type,
        "status": inc.status,
        "source_ip": str(inc.source_ip) if inc.source_ip else None,
        "affected_systems": inc.affected_systems,
        "detected_by": inc.detected_by,
        "assigned_to": str(inc.assigned_to) if inc.assigned_to else None,
        "resolution": inc.resolution,
        "resolved_at": inc.resolved_at.isoformat() if inc.resolved_at else None,
        "created_at": inc.created_at.isoformat() if inc.created_at else None,
        "updated_at": inc.updated_at.isoformat() if inc.updated_at else None,
    }


@router.get("/dashboard")
async def get_dashboard(
    organization_id: UUID | None = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    # ADR-0004: regular users see only their own organization; admin may pick one or see all.
    org = scope_org(current_user, organization_id)
    inc_severity = await incident_service.get_incident_count_by_severity(db, org)
    vuln_severity = await vulnerability_service.get_open_vulnerability_count_by_severity(
        db, org
    )
    policies_due = await policy_service.count_policies_due_review(db, org)

    recent_incidents = await incident_service.get_incidents(
        db, organization_id=org, skip=0, limit=5
    )

    stmt = select(SecurityAudit)
    if org is not None:
        stmt = stmt.where(SecurityAudit.organization_id == org)
    stmt = stmt.order_by(SecurityAudit.created_at.desc()).limit(1)
    result = await db.execute(stmt)
    latest_audit = result.scalar_one_or_none()

    return APIResponse(
        data={
            "open_incidents": {
                "critical": inc_severity.get("critical", 0),
                "high": inc_severity.get("high", 0),
                "medium": inc_severity.get("medium", 0),
                "low": inc_severity.get("low", 0),
                "info": inc_severity.get("info", 0),
            },
            "open_vulnerabilities": {
                "critical": vuln_severity.get("critical", 0),
                "high": vuln_severity.get("high", 0),
                "medium": vuln_severity.get("medium", 0),
                "low": vuln_severity.get("low", 0),
                "info": vuln_severity.get("info", 0),
            },
            "recent_incidents": [_incident_to_response(i) for i in recent_incidents],
            "policies_due_review": policies_due,
            "latest_audit_status": latest_audit.status if latest_audit else None,
        }
    )
