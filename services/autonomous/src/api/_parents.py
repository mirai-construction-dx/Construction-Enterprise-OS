"""Parent-reference checks for create endpoints (ADR-0004).

A new record may only reference parent records (agent, digital twin, ...) of its own organization.
- Regular users look parents up within their token organization: another org's parent is 404.
- A cross-org admin can see every parent; a parent of a different organization than the new
  record is rejected with 400 ``<PARENT>_ORG_MISMATCH``.
"""

from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from ..middleware.auth import TokenData
from ..middleware.tenant import scope_org

Lookup = Callable[..., Awaitable[Any]]


async def ensure_parent_in_org(
    db: AsyncSession,
    lookup: Lookup,
    parent_id: UUID | None,
    record_org: UUID,
    user: TokenData,
    *,
    code: str,
    label: str,
) -> None:
    """Verify ``parent_id`` (if given) exists, is visible to ``user`` and belongs to ``record_org``."""
    if parent_id is None:
        return
    parent = await lookup(db, parent_id, organization_id=scope_org(user))
    if parent is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": f"{code}_NOT_FOUND",
                "message": f"{label}が見つかりません。",
            },
        )
    if parent.organization_id != record_org:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": f"{code}_ORG_MISMATCH",
                "message": f"登録先と異なる組織の{label}は指定できません。",
            },
        )
