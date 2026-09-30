"""ETLパイプライン API"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from ..middleware.auth import TokenData, get_current_user
from ..middleware.tenant import create_org, is_cross_org_admin, scope_org
from ..models.base import get_db
from ..schemas import (
    PipelineCreateRequest,
    PipelineListResponse,
    PipelineResponse,
    PipelineRunResponse,
    PipelineUpdateRequest,
)
from ..services import analytics_service as service

router = APIRouter()


def _datasource_not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={
            "code": "DATASOURCE_NOT_FOUND",
            "message": "データソースが見つかりません。",
        },
    )


def _datasource_org_mismatch() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail={
            "code": "DATASOURCE_ORG_MISMATCH",
            "message": "パイプラインと異なる組織のデータソースは指定できません。",
        },
    )


async def _ensure_datasources_in_org(
    db: AsyncSession,
    user: TokenData,
    pipeline_org: UUID,
    datasource_ids: list[UUID | None],
) -> None:
    """Require every referenced datasource to belong to the pipeline's organization.

    Regular users only see their own organization, so another org's datasource is
    simply not found (404, no existence leak). An admin can see every organization,
    so a cross-org reference is reported as an invalid request (400).
    """
    for ds_id in datasource_ids:
        if ds_id is None:
            continue
        if is_cross_org_admin(user):
            ds = await service.get_datasource(db, ds_id)
            if not ds:
                raise _datasource_not_found()
            if ds.organization_id != pipeline_org:
                raise _datasource_org_mismatch()
        elif not await service.get_datasource(db, ds_id, pipeline_org):
            raise _datasource_not_found()


@router.post(
    "/pipelines",
    response_model=PipelineResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_pipeline(
    body: PipelineCreateRequest,
    db: AsyncSession = Depends(get_db),
    user: TokenData = Depends(get_current_user),
):
    data = body.model_dump()
    org_id = create_org(user, body.organization_id)
    data["organization_id"] = org_id
    await _ensure_datasources_in_org(db, user, org_id, [body.source_id, body.target_id])
    pipeline = await service.create_pipeline(db, data)
    return pipeline


@router.get("/pipelines", response_model=PipelineListResponse)
async def list_pipelines(
    organization_id: UUID | None = Query(None),
    status: str | None = Query(None),
    source_id: UUID | None = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    user: TokenData = Depends(get_current_user),
):
    items, total = await service.list_pipelines(
        db,
        organization_id=scope_org(user, organization_id),
        status=status,
        source_id=source_id,
        page=page,
        per_page=per_page,
    )
    return PipelineListResponse(
        items=items, total=total, page=page, per_page=per_page  # type: ignore[arg-type]
    )


@router.get("/pipelines/{pipeline_id}", response_model=PipelineResponse)
async def get_pipeline(
    pipeline_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: TokenData = Depends(get_current_user),
):
    pipeline = await service.get_pipeline(db, pipeline_id, scope_org(user))
    if not pipeline:
        raise HTTPException(status_code=404, detail="パイプラインが見つかりません")
    return pipeline


@router.put("/pipelines/{pipeline_id}", response_model=PipelineResponse)
async def update_pipeline(
    pipeline_id: UUID,
    body: PipelineUpdateRequest,
    db: AsyncSession = Depends(get_db),
    user: TokenData = Depends(get_current_user),
):
    pipeline = await service.get_pipeline(db, pipeline_id, scope_org(user))
    if not pipeline:
        raise HTTPException(status_code=404, detail="パイプラインが見つかりません")
    data = body.model_dump(exclude_none=True)
    # Validate re-pointed datasources before any attribute is mutated.
    await _ensure_datasources_in_org(
        db, user, pipeline.organization_id, [data.get("source_id"), data.get("target_id")]
    )
    return await service.update_pipeline(db, pipeline, data)


@router.delete("/pipelines/{pipeline_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_pipeline(
    pipeline_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: TokenData = Depends(get_current_user),
):
    pipeline = await service.get_pipeline(db, pipeline_id, scope_org(user))
    if not pipeline:
        raise HTTPException(status_code=404, detail="パイプラインが見つかりません")
    await service.delete_pipeline(db, pipeline)


@router.post(
    "/pipelines/{pipeline_id}/run",
    response_model=PipelineRunResponse,
)
async def trigger_pipeline_run(
    pipeline_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: TokenData = Depends(get_current_user),
):
    pipeline = await service.get_pipeline(db, pipeline_id, scope_org(user))
    if not pipeline:
        raise HTTPException(status_code=404, detail="パイプラインが見つかりません")
    if pipeline.status == "running":
        raise HTTPException(status_code=400, detail="パイプラインはすでに実行中です")
    # A run reads/writes its datasources: both must belong to the pipeline's organization
    # (guards against legacy cross-org references). Checked before the status is changed.
    for ds_id in (pipeline.source_id, pipeline.target_id):
        if ds_id is not None and not await service.get_datasource(
            db, ds_id, pipeline.organization_id
        ):
            raise _datasource_not_found()
    result = await service.trigger_pipeline_run(db, pipeline)
    return result
