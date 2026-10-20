"""データソース API

`connection_config` は認証情報（パスワード・API キー等）を含み得るため write-only とし、
応答（DataSourceResponse）には含めない（#138）。
保存時の暗号化は未実装であり、DB には平文 JSONB として保存される。
暗号化を実装するまでは認証情報の登録を前提にせず、必要になった時点で
KMS/Secrets Manager 等の導入方針を別途決定する。
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from ..middleware.auth import (
    MANAGEMENT_ROLES,
    TokenData,
    get_current_user,
    require_any_role,
)
from ..middleware.tenant import create_org, scope_org
from ..models.base import get_db
from ..schemas import (
    DataSourceCreateRequest,
    DataSourceListResponse,
    DataSourceResponse,
    DataSourceTestResponse,
    DataSourceUpdateRequest,
)
from ..services import analytics_service as service

router = APIRouter()


@router.post(
    "/datasources",
    response_model=DataSourceResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_datasource(
    body: DataSourceCreateRequest,
    db: AsyncSession = Depends(get_db),
    user: TokenData = Depends(get_current_user),
):
    # #138: データソース（接続情報）の作成は管理ロールに限定する。
    # 組織の検証を先に行い、ORG_REQUIRED / ORG_FORBIDDEN を従来どおり返す
    # （delete と同じ順序）。ロール検証は DB アクセスより前に行う。
    data = body.model_dump()
    data["organization_id"] = create_org(user, body.organization_id)
    require_any_role(user, MANAGEMENT_ROLES)
    ds = await service.create_datasource(db, data)
    return ds


@router.get("/datasources", response_model=DataSourceListResponse)
async def list_datasources(
    organization_id: UUID | None = Query(None),
    source_type: str | None = Query(None),
    status: str | None = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    user: TokenData = Depends(get_current_user),
):
    items, total = await service.list_datasources(
        db,
        organization_id=scope_org(user, organization_id),
        source_type=source_type,
        status=status,
        page=page,
        per_page=per_page,
    )
    return DataSourceListResponse(
        items=items, total=total, page=page, per_page=per_page  # type: ignore[arg-type]
    )


@router.get("/datasources/{datasource_id}", response_model=DataSourceResponse)
async def get_datasource(
    datasource_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: TokenData = Depends(get_current_user),
):
    ds = await service.get_datasource(db, datasource_id, scope_org(user))
    if not ds:
        raise HTTPException(status_code=404, detail="データソースが見つかりません")
    return ds


@router.put("/datasources/{datasource_id}", response_model=DataSourceResponse)
async def update_datasource(
    datasource_id: UUID,
    body: DataSourceUpdateRequest,
    db: AsyncSession = Depends(get_db),
    user: TokenData = Depends(get_current_user),
):
    ds = await service.get_datasource(db, datasource_id, scope_org(user))
    if not ds:
        raise HTTPException(status_code=404, detail="データソースが見つかりません")
    return await service.update_datasource(db, ds, body.model_dump(exclude_none=True))


@router.delete("/datasources/{datasource_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_datasource(
    datasource_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: TokenData = Depends(get_current_user),
):
    org = scope_org(user)
    require_any_role(user, MANAGEMENT_ROLES)
    ds = await service.get_datasource(db, datasource_id, org)
    if not ds:
        raise HTTPException(status_code=404, detail="データソースが見つかりません")
    await service.delete_datasource(db, ds)


@router.post(
    "/datasources/{datasource_id}/test",
    response_model=DataSourceTestResponse,
)
async def test_datasource_connection(
    datasource_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: TokenData = Depends(get_current_user),
):
    ds = await service.get_datasource(db, datasource_id, scope_org(user))
    if not ds:
        raise HTTPException(status_code=404, detail="データソースが見つかりません")
    result = await service.test_datasource_connection(ds)
    return result
