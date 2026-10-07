"""アラートサービス"""

from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import AlertRule as AlertRuleModel
from ..models import AlertHistory as AlertHistoryModel
from ..models import Device as DeviceModel


class AlertStateError(Exception):
    """アラートの状態遷移違反。"""


_CONDITION_MAP = {
    "gt": lambda a, b: a > b,
    "lt": lambda a, b: a < b,
    "gte": lambda a, b: a >= b,
    "lte": lambda a, b: a <= b,
    "eq": lambda a, b: a == b,
}


def _evaluate_condition(condition: str, value: float, threshold: float) -> bool:
    op = _CONDITION_MAP.get(condition)
    if op is None:
        return False
    return op(value, threshold)


def _build_alert_message(rule, value: float) -> str:
    condition_str = {
        "gt": "超えました",
        "lt": "下回りました",
        "gte": "以上になりました",
        "lte": "以下になりました",
        "eq": "と一致しました",
    }.get(rule.condition, "トリガーされました")
    return f"{rule.name}: {rule.metric_name} が {value} となり、しきい値 {rule.threshold} を{condition_str}"


async def check_alert_rules(
    db: AsyncSession,
    device_id: UUID,
    metric_name: str,
    value: float,
    sensor_id: UUID | None = None,
    organization_id: UUID | None = None,
) -> list[AlertHistoryModel]:
    """テレメトリ投入後、アラートルールの閾値チェックを行う。

    organization_id が与えられた場合はその組織のルールに限定する。
    他テナントのグローバルルール（device_id が NULL）が自組織のデバイスへ
    適用されるのを防ぐ。
    """
    query = select(AlertRuleModel).where(
        AlertRuleModel.is_active.is_(True),
        AlertRuleModel.metric_name == metric_name,
        (AlertRuleModel.device_id == device_id)
        | (AlertRuleModel.device_id.is_(None)),
    )
    if organization_id is not None:
        query = query.where(AlertRuleModel.organization_id == organization_id)
    result = await db.execute(query)
    rules = list(result.scalars().all())

    created_alerts = []
    now = datetime.now(timezone.utc)

    for rule in rules:
        # SQL で絞り込みつつ、万一の漏れに備えて明示的にも組織を検査する。
        if organization_id is not None and rule.organization_id != organization_id:
            continue
        if not _evaluate_condition(rule.condition, value, rule.threshold):
            continue

        cooldown_threshold = now - timedelta(minutes=rule.cooldown_minutes)

        recent_result = await db.execute(
            select(AlertHistoryModel).where(
                AlertHistoryModel.rule_id == rule.id,
                AlertHistoryModel.device_id == device_id,
                AlertHistoryModel.metric_name == metric_name,
                AlertHistoryModel.created_at >= cooldown_threshold,
            )
        )
        if recent_result.scalar_one_or_none():
            continue

        alert = AlertHistoryModel(
            rule_id=rule.id,
            device_id=device_id,
            sensor_id=sensor_id,
            metric_name=metric_name,
            current_value=value,
            threshold=rule.threshold,
            severity=rule.severity,
            message=_build_alert_message(rule, value),
        )
        db.add(alert)
        created_alerts.append(alert)

    if created_alerts:
        await db.flush()
    return created_alerts


async def acknowledge_alert(
    db: AsyncSession, alert_id: int, user_id: UUID
) -> AlertHistoryModel | None:
    result = await db.execute(
        select(AlertHistoryModel).where(AlertHistoryModel.id == alert_id)
    )
    alert = result.scalar_one_or_none()
    if not alert:
        return None

    # DEF-08d: 解決済みアラートを後から確認する（逆行遷移）は許さない。
    if alert.resolved_at is not None:
        raise AlertStateError("解決済みのアラートは確認できません。")

    # DEF-08b: 既に確認済みなら先の確認者を上書きしない（冪等）。
    if alert.acknowledged_at is not None:
        return alert

    now = datetime.now(timezone.utc)
    alert.acknowledged_by = user_id
    alert.acknowledged_at = now
    await db.flush()
    return alert


async def resolve_alert(db: AsyncSession, alert_id: int) -> AlertHistoryModel | None:
    result = await db.execute(
        select(AlertHistoryModel).where(AlertHistoryModel.id == alert_id)
    )
    alert = result.scalar_one_or_none()
    if not alert:
        return None

    # DEF-08c: 解決済みへの再 resolve は resolved_at を上書きしない（冪等）。
    if alert.resolved_at is not None:
        return alert

    # DEF-08a: 未確認のアラートは resolve できない（状態遷移順序の強制）。
    if alert.acknowledged_at is None:
        raise AlertStateError("確認されていないアラートは解決できません。")

    now = datetime.now(timezone.utc)
    alert.resolved_at = now
    await db.flush()
    return alert


async def get_alert_rules(
    db: AsyncSession,
    organization_id: UUID,
    device_id: UUID | None = None,
) -> list[AlertRuleModel]:
    query = select(AlertRuleModel)
    if organization_id:
        query = query.where(AlertRuleModel.organization_id == organization_id)
    if device_id:
        query = query.where(AlertRuleModel.device_id == device_id)
    query = query.order_by(AlertRuleModel.created_at.desc())
    result = await db.execute(query)
    return list(result.scalars().all())


async def get_alert_history(
    db: AsyncSession,
    page: int = 1,
    per_page: int = 20,
    severity: str | None = None,
    device_id: UUID | None = None,
    acknowledged: bool | None = None,
    organization_id: UUID | None = None,
) -> tuple[list[AlertHistoryModel], int]:
    # alert_history 自体に組織列が無いため、devices へ JOIN して org 境界を守る。
    query = select(AlertHistoryModel).join(
        DeviceModel, AlertHistoryModel.device_id == DeviceModel.id
    )
    count_query = select(func.count(AlertHistoryModel.id)).join(
        DeviceModel, AlertHistoryModel.device_id == DeviceModel.id
    )

    if organization_id is not None:
        query = query.where(DeviceModel.organization_id == organization_id)
        count_query = count_query.where(
            DeviceModel.organization_id == organization_id
        )
    if severity:
        query = query.where(AlertHistoryModel.severity == severity)
        count_query = count_query.where(AlertHistoryModel.severity == severity)
    if device_id:
        query = query.where(AlertHistoryModel.device_id == device_id)
        count_query = count_query.where(AlertHistoryModel.device_id == device_id)
    if acknowledged is True:
        query = query.where(AlertHistoryModel.acknowledged_at.isnot(None))
        count_query = count_query.where(AlertHistoryModel.acknowledged_at.isnot(None))
    elif acknowledged is False:
        query = query.where(AlertHistoryModel.acknowledged_at.is_(None))
        count_query = count_query.where(AlertHistoryModel.acknowledged_at.is_(None))

    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    query = query.order_by(AlertHistoryModel.created_at.desc())
    query = query.offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(query)
    alerts = list(result.scalars().all())

    return alerts, total
