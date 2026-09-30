"""Vulnerability tracking API endpoints."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from ..middleware.auth import TokenData, get_current_user
from ..middleware.tenant import create_org, scope_org
from ..models.base import get_db
from ..schemas import APIResponse, VulnerabilityCreate, VulnerabilityUpdate
from ..services import vulnerability_service

router = APIRouter()


def _vuln_to_response(v) -> dict:
    return {
        "id": str(v.id),
        "organization_id": str(v.organization_id),
        "title": v.title,
        "description": v.description,
        "severity": v.severity,
        "cve_id": v.cve_id,
        "cvss_score": v.cvss_score,
        "affected_component": v.affected_component,
        "status": v.status,
        "remediation": v.remediation,
        "discovered_at": v.discovered_at.isoformat() if v.discovered_at else None,
        "fixed_at": v.fixed_at.isoformat() if v.fixed_at else None,
        "created_at": v.created_at.isoformat() if v.created_at else None,
        "updated_at": v.updated_at.isoformat() if v.updated_at else None,
    }


@router.post("/vulnerabilities", status_code=status.HTTP_201_CREATED)
async def create_vulnerability(
    body: VulnerabilityCreate,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    vuln = await vulnerability_service.create_vulnerability(
        db,
        organization_id=create_org(current_user, body.organization_id),
        title=body.title,
        severity=body.severity,
        description=body.description,
        cve_id=body.cve_id,
        cvss_score=body.cvss_score,
        affected_component=body.affected_component,
        remediation=body.remediation,
    )
    return APIResponse(data=_vuln_to_response(vuln))


@router.get("/vulnerabilities")
async def list_vulnerabilities(
    organization_id: UUID | None = Query(None),
    severity: str | None = Query(None),
    status: str | None = Query(None),
    cve_id: str | None = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    vulns = await vulnerability_service.get_vulnerabilities(
        db,
        organization_id=scope_org(current_user, organization_id),
        severity=severity,
        status=status,
        cve_id=cve_id,
        skip=skip,
        limit=limit,
    )
    return APIResponse(data=[_vuln_to_response(v) for v in vulns])


@router.put("/vulnerabilities/{vuln_id}")
async def update_vulnerability(
    vuln_id: UUID,
    body: VulnerabilityUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    vuln = await vulnerability_service.update_vulnerability(
        db,
        vuln_id,
        organization_id=scope_org(current_user),
        status=body.status,
        severity=body.severity,
        remediation=body.remediation,
        cvss_score=body.cvss_score,
    )
    if not vuln:
        raise HTTPException(
            status_code=404,
            detail={"code": "NOT_FOUND", "message": "Vulnerability not found."},
        )
    return APIResponse(data=_vuln_to_response(vuln))


@router.get("/vulnerabilities/open")
async def get_open_vulnerabilities(
    organization_id: UUID | None = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    counts = await vulnerability_service.get_open_vulnerability_count_by_severity(
        db, scope_org(current_user, organization_id)
    )
    return APIResponse(data={"open_vulnerabilities": counts})
