"""Organization (tenant) scoping helpers (ADR-0004).

Rules:
- Regular users only access data of their own organization (token ``org`` claim, exact match).
  A token without a valid ``org`` is rejected (fail-closed).
- The ``admin`` role may access data across organizations.
"""

from uuid import UUID

from fastapi import HTTPException

from .auth import TokenData

CROSS_ORG_ROLE = "admin"


def is_cross_org_admin(user: TokenData) -> bool:
    # bim's TokenData.roles is Optional; a missing claim means "no roles"
    return CROSS_ORG_ROLE in (user.roles or [])


def token_org(user: TokenData) -> UUID:
    """Return the caller's organization from the token, or reject with 403."""
    if not user.org:
        raise HTTPException(
            status_code=403,
            detail={
                "code": "ORG_REQUIRED",
                "message": "組織情報がないトークンは利用できません。",
            },
        )
    try:
        return UUID(user.org)
    except ValueError as exc:
        raise HTTPException(
            status_code=403,
            detail={"code": "ORG_INVALID", "message": "トークンの組織情報が無効です。"},
        ) from exc


def _forbidden_org() -> HTTPException:
    return HTTPException(
        status_code=403,
        detail={
            "code": "ORG_FORBIDDEN",
            "message": "他組織のデータにはアクセスできません。",
        },
    )


def scope_org(user: TokenData, requested: UUID | None = None) -> UUID | None:
    """Organization filter for list / aggregate / by-id queries.

    Returns ``None`` (no filter) only for a cross-org admin who did not request an organization.
    A regular user requesting another organization gets 403.
    """
    if is_cross_org_admin(user):
        return requested
    org = token_org(user)
    if requested is not None and requested != org:
        raise _forbidden_org()
    return org


def create_org(user: TokenData, body_org: UUID) -> UUID:
    """Organization to store on a new record; regular users may only create in their own org."""
    if is_cross_org_admin(user):
        return body_org
    org = token_org(user)
    if body_org != org:
        raise _forbidden_org()
    return org
