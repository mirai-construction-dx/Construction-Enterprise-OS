"""Organization checks for references to parent WBS items (ADR-0004)."""

from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from ..middleware.auth import TokenData
from ..middleware.tenant import is_cross_org_admin
from ..services import construction_service


async def ensure_wbs_in_org(
    db: AsyncSession, user: TokenData, wbs_id: UUID | None, target_org: UUID
) -> None:
    """Ensure a referenced WBS item exists and belongs to ``target_org``.

    - Regular user: lookup is scoped to ``target_org`` (== token org); other org -> 404.
    - Admin: the item must exist (404) and belong to the record's organization (400 mismatch).
    """
    if wbs_id is None:
        return
    admin = is_cross_org_admin(user)
    wbs = await construction_service.get_wbs(db, wbs_id, None if admin else target_org)
    if wbs is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "WBS_NOT_FOUND",
                "message": "参照先のWBSアイテムが見つかりません。",
            },
        )
    if wbs.organization_id != target_org:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "WBS_ORG_MISMATCH",
                "message": "参照先のWBSアイテムの組織が一致しません。",
            },
        )
