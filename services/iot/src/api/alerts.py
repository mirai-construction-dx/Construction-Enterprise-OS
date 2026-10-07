"""アラートルール・履歴管理エンドポイント"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from ..middleware.auth import TokenData, get_current_user, require_any_role
from ..middleware.tenant import create_org, is_cross_org_admin, scope_org
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
    AlertStateError,
    get_alert_rules,
    get_alert_history,
    acknowledge_alert,
    resolve_alert,
)
from ..services.device_service import get_device_by_id, get_sensor_by_id

router = APIRouter()


def _not_found(code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND, detail={"code": code, "message": message}
    )


def _org_mismatch(code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST, detail={"code": code, "message": message}
    )


def _actor_id(user: TokenData) -> UUID:
    """トークンの sub を操作者として同定する（非 UUID は 403、500 にしない）。"""
    try:
        return UUID(user.sub)
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "INVALID_IDENTITY",
                "message": "Authenticated user id is invalid.",
            },
        ) from exc


async def _validate_rule_targets(
    db: AsyncSession, body: AlertRuleCreateRequest, org: UUID, user: TokenData
) -> None:
    """Referenced device / sensor must belong to the rule's organization.

    Regular users look them up within their token org only, so another org's record is 404.
    A cross-org admin can see every record, so a record of a different org than the rule is
    rejected as an invalid request (400) instead of being hidden.
    """
    lookup_org = None if is_cross_org_admin(user) else org
    if body.device_id is not None:
        device = await get_device_by_id(db, body.device_id, lookup_org)
        if not device:
            raise _not_found("DEVICE_NOT_FOUND", "デバイスが見つかりません。")
        if device.organization_id != org:
            raise _org_mismatch(
                "DEVICE_ORG_MISMATCH", "ルールと異なる組織のデバイスは指定できません。"
            )
    if body.sensor_id is not None:
        sensor = await get_sensor_by_id(db, body.sensor_id, lookup_org)
        if not sensor:
            raise _not_found("SENSOR_NOT_FOUND", "センサーが見つかりません。")
        if sensor.device.organization_id != org:
            raise _org_mismatch(
                "SENSOR_ORG_MISMATCH", "ルールと異なる組織のセンサーは指定できません。"
            )


@router.post("/alert-rules", response_model=APIResponse[AlertRuleResponse], status_code=status.HTTP_201_CREATED)
async def create_alert_rule(
    request: Request,
    body: AlertRuleCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    org = create_org(current_user, body.organization_id)
    await _validate_rule_targets(db, body, org, current_user)
    rule = AlertRuleModel(
        organization_id=org,
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
    current_user: TokenData = Depends(get_current_user),
):
    rules = await get_alert_rules(
        db, organization_id=scope_org(current_user, organization_id), device_id=device_id
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
    organization_id: UUID | None = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    org_filter = scope_org(current_user, organization_id)
    alerts, total = await get_alert_history(
        db,
        page=page,
        per_page=per_page,
        severity=severity,
        device_id=device_id,
        acknowledged=acknowledged,
        organization_id=org_filter,
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
    current_user: TokenData = Depends(get_current_user),
):
    require_any_role(current_user)
    org = scope_org(current_user)
    user_id = _actor_id(current_user)
    try:
        alert = await acknowledge_alert(db, alert_id, user_id, org)
    except AlertStateError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "INVALID_TRANSITION", "message": str(exc)},
        ) from exc
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
    current_user: TokenData = Depends(get_current_user),
):
    require_any_role(current_user)
    try:
        alert = await resolve_alert(db, alert_id, scope_org(current_user))
    except AlertStateError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "INVALID_TRANSITION", "message": str(exc)},
        ) from exc
    if not alert:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "ALERT_NOT_FOUND", "message": "アラートが見つかりません。"},
        )
    return APIResponse(data=AlertHistoryResponse.model_validate(alert))
