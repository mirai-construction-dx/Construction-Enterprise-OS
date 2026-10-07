"""アラートルール・履歴管理エンドポイント"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from ..middleware.auth import get_current_user, require_organization_id
from ..models.base import get_db
from ..schemas import (
    APIResponse,
    AlertHistoryListResponse,
    AlertHistoryResponse,
    AlertRuleCreateRequest,
    AlertRuleResponse,
    MetaInfo,
)
from ..models import AlertRule as AlertRuleModel
from ..services.alert_service import (
    get_alert_rules,
    get_alert_history,
    acknowledge_alert,
    resolve_alert,
)

router = APIRouter()


@router.post("/alert-rules", response_model=APIResponse[AlertRuleResponse], status_code=status.HTTP_201_CREATED)
async def create_alert_rule(
    request: Request,
    body: AlertRuleCreateRequest,
    db: AsyncSession = Depends(get_db),
    _current_user=Depends(get_current_user),
):
    rule = AlertRuleModel(
        organization_id=body.organization_id,
        device_id=body.device_id,
        sensor_id=body.sensor_id,
        name=body.name,
        metric_name=body.metric_name,
        condition=body.condition,
        threshold=body.threshold,
        severity=body.severity,
        is_active=body.is_active,
        cooldown_minutes=body.cooldown_minutes,
        notification_channels=body.notification_channels,
    )
    db.add(rule)
    await db.flush()
    return APIResponse(data=AlertRuleResponse.model_validate(rule))


@router.get("/alert-rules", response_model=APIResponse[list[AlertRuleResponse]])
async def list_alert_rules(
    request: Request,
    organization_id: UUID | None = Query(None),
    device_id: UUID | None = Query(None),
    db: AsyncSession = Depends(get_db),
    _current_user=Depends(get_current_user),
):
    rules = await get_alert_rules(
        db,
        organization_id=require_organization_id(_current_user),
        device_id=device_id,
    )
    return APIResponse(data=[AlertRuleResponse.model_validate(r) for r in rules])


@router.get("/alerts", response_model=APIResponse[AlertHistoryListResponse])
async def list_alerts(
    request: Request,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    severity: str | None = Query(None),
    device_id: UUID | None = Query(None),
    acknowledged: bool | None = Query(None),
    db: AsyncSession = Depends(get_db),
    _current_user=Depends(get_current_user),
):
    alerts, total = await get_alert_history(
        db,
        page=page,
        per_page=per_page,
        severity=severity,
        device_id=device_id,
        acknowledged=acknowledged,
    )
    total_pages = max((total + per_page - 1) // per_page, 1) if total > 0 else 0

    return APIResponse(
        data=AlertHistoryListResponse(
            alerts=[AlertHistoryResponse.model_validate(a) for a in alerts],
            total=total,
        ),
        meta=MetaInfo(
            page=page,
            per_page=per_page,
            total=total,
            total_pages=total_pages,
        ),
    )


@router.post("/alerts/{alert_id}/acknowledge", response_model=APIResponse[AlertHistoryResponse])
async def acknowledge(
    request: Request,
    alert_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    from uuid import UUID as UUIDType
    user_id = UUIDType(current_user.sub)
    alert = await acknowledge_alert(db, alert_id, user_id)
    if not alert:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "ALERT_NOT_FOUND", "message": "アラートが見つかりません。"},
        )
    return APIResponse(data=AlertHistoryResponse.model_validate(alert))


@router.post("/alerts/{alert_id}/resolve", response_model=APIResponse[AlertHistoryResponse])
async def resolve(
    request: Request,
    alert_id: int,
    db: AsyncSession = Depends(get_db),
    _current_user=Depends(get_current_user),
):
    alert = await resolve_alert(db, alert_id)
    if not alert:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "ALERT_NOT_FOUND", "message": "アラートが見つかりません。"},
        )
    return APIResponse(data=AlertHistoryResponse.model_validate(alert))
