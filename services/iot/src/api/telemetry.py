"""テレメトリデータ投入・クエリエンドポイント"""

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from ..middleware.auth import TokenData, get_current_client, get_current_user
from ..middleware.tenant import scope_org
from ..models.base import get_db
from ..schemas import (
    APIResponse,
    LatestTelemetryValue,
    TelemetryIngestRequest,
)
from ..services.telemetry_service import (
    ingest_telemetry,
    query_telemetry,
    get_latest_telemetry,
)
from ..services.alert_service import check_alert_rules
from ..services.device_service import get_device_by_id, get_visible_device_ids

router = APIRouter()


async def _ensure_device_visible(db: AsyncSession, device_id: UUID, user: TokenData) -> None:
    """Telemetry belongs to a device; another organization's device is 404 (no existence leak)."""
    if not await get_device_by_id(db, device_id, scope_org(user)):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "DEVICE_NOT_FOUND", "message": "デバイスが見つかりません。"},
        )


@router.post(
    "/ingest", response_model=APIResponse, status_code=status.HTTP_202_ACCEPTED
)
async def ingest(
    request: Request,
    body: TelemetryIngestRequest,
    db: AsyncSession = Depends(get_db),
    current_client: TokenData = Depends(get_current_client),
):
    # ADR-0004 (#132): every device in the batch must exist and belong to the caller's
    # organization (user and client tokens alike; admin crosses orgs). Otherwise the whole batch
    # is rejected with 404 before any telemetry is written or alert rule evaluated. Alert rules
    # are further limited to the device's own organization (see check_alert_rules).
    requested = {point.device_id for point in body.data}
    visible = await get_visible_device_ids(db, requested, scope_org(current_client))
    if requested - visible:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "DEVICE_NOT_FOUND", "message": "デバイスが見つかりません。"},
        )

    count = await ingest_telemetry(db, body.data)

    for point in body.data:
        await check_alert_rules(
            db,
            device_id=point.device_id,
            metric_name=point.metric_name,
            value=point.value,
            sensor_id=point.sensor_id,
        )

    return APIResponse(
        data={
            "ingested": count,
            "message": f"{count}件のテレメトリデータを投入しました。",
        }
    )


@router.get("/{device_id}", response_model=APIResponse)
async def query_device_telemetry(
    request: Request,
    device_id: UUID,
    start_time: datetime = Query(...),
    end_time: datetime = Query(...),
    metric_name: str | None = Query(None),
    limit: int = Query(100, ge=1, le=10000),
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    await _ensure_device_visible(db, device_id, current_user)
    rows = await query_telemetry(
        db,
        device_id=device_id,
        start_time=start_time,
        end_time=end_time,
        metric_name=metric_name,
        limit=limit,
    )
    return APIResponse(
        data=[
            {
                "id": r.id,
                "device_id": str(r.device_id),
                "sensor_id": str(r.sensor_id) if r.sensor_id else None,
                "metric_name": r.metric_name,
                "value": r.value,
                "unit": r.unit,
                "timestamp": r.timestamp.isoformat(),
            }
            for r in rows
        ]
    )


@router.get(
    "/{device_id}/latest", response_model=APIResponse[list[LatestTelemetryValue]]
)
async def latest_telemetry(
    request: Request,
    device_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    await _ensure_device_visible(db, device_id, current_user)
    rows = await get_latest_telemetry(db, device_id)
    return APIResponse(data=[LatestTelemetryValue(**r) for r in rows])
