"""ワークフロー自動化・スケジュールタスク・イベントトリガー管理サービス"""

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import AutomationRule, ScheduledTask, ScheduledTaskRun, Trigger


def _by_id(model: Any, record_id: UUID, organization_id: UUID | None) -> Select:
    """By-id lookup, restricted to one organization unless ``None`` (cross-org admin, ADR-0004)."""
    stmt = select(model).where(model.id == record_id)
    if organization_id is not None:
        stmt = stmt.where(model.organization_id == organization_id)
    return stmt


# ============================================
# Automation Rule CRUD
# ============================================
async def create_rule(db: AsyncSession, data: dict) -> AutomationRule:
    action = data.get("action", {})
    if hasattr(action, "model_dump"):
        action = action.model_dump()
    rule = AutomationRule(
        organization_id=data["organization_id"],
        name=data["name"],
        description=data.get("description"),
        trigger_type=data["trigger_type"],
        condition=data.get("condition", {}),
        action=action,
        is_active=data.get("is_active", True),
    )
    db.add(rule)
    await db.flush()
    return rule


async def get_rule_by_id(
    db: AsyncSession, rule_id: UUID, organization_id: UUID | None = None
) -> AutomationRule | None:
    result = await db.execute(_by_id(AutomationRule, rule_id, organization_id))
    return result.scalar_one_or_none()


async def get_rules_paginated(
    db: AsyncSession,
    page: int = 1,
    per_page: int = 20,
    trigger_type: str | None = None,
    is_active: bool | None = None,
    organization_id: UUID | None = None,
) -> tuple[list[AutomationRule], int]:
    query = select(AutomationRule)
    count_query = select(func.count(AutomationRule.id))

    if trigger_type:
        query = query.where(AutomationRule.trigger_type == trigger_type)
        count_query = count_query.where(AutomationRule.trigger_type == trigger_type)
    if is_active is not None:
        query = query.where(AutomationRule.is_active == is_active)
        count_query = count_query.where(AutomationRule.is_active == is_active)
    if organization_id is not None:
        query = query.where(AutomationRule.organization_id == organization_id)
        count_query = count_query.where(
            AutomationRule.organization_id == organization_id
        )

    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    query = query.order_by(AutomationRule.created_at.desc())
    query = query.offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(query)
    rules = list(result.scalars().all())

    return rules, total


async def update_rule(
    db: AsyncSession, rule_id: UUID, data: dict, organization_id: UUID | None = None
) -> AutomationRule | None:
    result = await db.execute(_by_id(AutomationRule, rule_id, organization_id))
    rule = result.scalar_one_or_none()
    if not rule:
        return None

    for key, value in data.items():
        if key == "action" and hasattr(value, "model_dump"):
            value = value.model_dump()
        if hasattr(rule, key) and value is not None:
            setattr(rule, key, value)

    await db.flush()
    return rule


async def delete_rule(
    db: AsyncSession, rule_id: UUID, organization_id: UUID | None = None
) -> bool:
    result = await db.execute(_by_id(AutomationRule, rule_id, organization_id))
    rule = result.scalar_one_or_none()
    if not rule:
        return False
    await db.delete(rule)
    await db.flush()
    return True


async def enable_rule(
    db: AsyncSession, rule_id: UUID, organization_id: UUID | None = None
) -> AutomationRule | None:
    result = await db.execute(_by_id(AutomationRule, rule_id, organization_id))
    rule = result.scalar_one_or_none()
    if not rule:
        return None
    rule.is_active = True
    await db.flush()
    return rule


async def disable_rule(
    db: AsyncSession, rule_id: UUID, organization_id: UUID | None = None
) -> AutomationRule | None:
    result = await db.execute(_by_id(AutomationRule, rule_id, organization_id))
    rule = result.scalar_one_or_none()
    if not rule:
        return None
    rule.is_active = False
    await db.flush()
    return rule


async def test_rule_execution(
    db: AsyncSession,
    rule_id: UUID,
    test_data: dict,
    organization_id: UUID | None = None,
) -> dict | None:
    result = await db.execute(_by_id(AutomationRule, rule_id, organization_id))
    rule = result.scalar_one_or_none()
    if not rule:
        return None

    input_data = test_data.get("input_data", {})
    matched = _evaluate_condition(rule.condition, input_data)

    action_result = {"executed": False}
    if matched:
        action_result = {
            "executed": True,
            "action_type": rule.action.get("type", "unknown"),
            "config": rule.action.get("config", {}),
            "simulated": True,
        }

    return {
        "rule_id": rule.id,
        "rule_name": rule.name,
        "matched": matched,
        "action_type": rule.action.get("type", "unknown"),
        "action_result": action_result,
    }


def _evaluate_condition(condition: dict, input_data: dict) -> bool:
    if not condition:
        return True
    field = condition.get("field")
    operator = condition.get("operator", "eq")
    value = condition.get("value")

    if field is None:
        return True

    actual = input_data.get(field)
    if operator == "eq":
        return actual == value
    elif operator == "neq":
        return actual != value
    elif operator == "gt":
        return actual is not None and actual > value
    elif operator == "lt":
        return actual is not None and actual < value
    elif operator == "gte":
        return actual is not None and actual >= value
    elif operator == "lte":
        return actual is not None and actual <= value
    elif operator == "contains":
        return str(value) in str(actual) if actual is not None else False
    return False


# ============================================
# Scheduled Task CRUD
# ============================================
async def create_task(db: AsyncSession, data: dict) -> ScheduledTask:
    task = ScheduledTask(
        organization_id=data["organization_id"],
        name=data["name"],
        description=data.get("description"),
        cron_expression=data["cron_expression"],
        action_type=data["action_type"],
        action_config=data.get("action_config", {}),
        is_active=data.get("is_active", True),
    )
    db.add(task)
    await db.flush()
    return task


async def get_task_by_id(
    db: AsyncSession, task_id: UUID, organization_id: UUID | None = None
) -> ScheduledTask | None:
    result = await db.execute(_by_id(ScheduledTask, task_id, organization_id))
    return result.scalar_one_or_none()


async def get_tasks_paginated(
    db: AsyncSession,
    page: int = 1,
    per_page: int = 20,
    action_type: str | None = None,
    is_active: bool | None = None,
    organization_id: UUID | None = None,
) -> tuple[list[ScheduledTask], int]:
    query = select(ScheduledTask)
    count_query = select(func.count(ScheduledTask.id))

    if action_type:
        query = query.where(ScheduledTask.action_type == action_type)
        count_query = count_query.where(ScheduledTask.action_type == action_type)
    if is_active is not None:
        query = query.where(ScheduledTask.is_active == is_active)
        count_query = count_query.where(ScheduledTask.is_active == is_active)
    if organization_id is not None:
        query = query.where(ScheduledTask.organization_id == organization_id)
        count_query = count_query.where(
            ScheduledTask.organization_id == organization_id
        )

    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    query = query.order_by(ScheduledTask.created_at.desc())
    query = query.offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(query)
    tasks = list(result.scalars().all())

    return tasks, total


async def update_task(
    db: AsyncSession, task_id: UUID, data: dict, organization_id: UUID | None = None
) -> ScheduledTask | None:
    result = await db.execute(_by_id(ScheduledTask, task_id, organization_id))
    task = result.scalar_one_or_none()
    if not task:
        return None

    for key, value in data.items():
        if hasattr(task, key) and value is not None:
            setattr(task, key, value)

    await db.flush()
    return task


async def delete_task(
    db: AsyncSession, task_id: UUID, organization_id: UUID | None = None
) -> bool:
    result = await db.execute(_by_id(ScheduledTask, task_id, organization_id))
    task = result.scalar_one_or_none()
    if not task:
        return False
    await db.delete(task)
    await db.flush()
    return True


async def trigger_task_now(
    db: AsyncSession, task_id: UUID, organization_id: UUID | None = None
) -> ScheduledTaskRun | None:
    result = await db.execute(_by_id(ScheduledTask, task_id, organization_id))
    task = result.scalar_one_or_none()
    if not task:
        return None

    now = datetime.now(timezone.utc)
    run = ScheduledTaskRun(
        task_id=task.id,
        organization_id=task.organization_id,
        status="running",
        started_at=now,
    )
    db.add(run)

    task.last_run = now
    task.last_status = "completed"

    run.status = "completed"
    run.completed_at = datetime.now(timezone.utc)
    run.output_data = {
        "message": f"Task '{task.name}' executed successfully",
        "action_type": task.action_type,
        "executed_at": now.isoformat(),
    }

    await db.flush()
    return run


async def get_task_run_history(
    db: AsyncSession,
    task_id: UUID,
    limit: int = 20,
    organization_id: UUID | None = None,
) -> list[ScheduledTaskRun]:
    query = select(ScheduledTaskRun).where(ScheduledTaskRun.task_id == task_id)
    if organization_id is not None:
        query = query.where(ScheduledTaskRun.organization_id == organization_id)
    query = query.order_by(ScheduledTaskRun.created_at.desc()).limit(limit)
    result = await db.execute(query)
    return list(result.scalars().all())


# ============================================
# Trigger CRUD
# ============================================
async def create_trigger(db: AsyncSession, data: dict) -> Trigger:
    trigger = Trigger(
        organization_id=data["organization_id"],
        name=data["name"],
        description=data.get("description"),
        event_type=data["event_type"],
        filter_conditions=data.get("filter_conditions", {}),
        action_config=data.get("action_config", {}),
        is_active=data.get("is_active", True),
    )
    db.add(trigger)
    await db.flush()
    return trigger


async def get_trigger_by_id(
    db: AsyncSession, trigger_id: UUID, organization_id: UUID | None = None
) -> Trigger | None:
    result = await db.execute(_by_id(Trigger, trigger_id, organization_id))
    return result.scalar_one_or_none()


async def get_triggers_paginated(
    db: AsyncSession,
    page: int = 1,
    per_page: int = 20,
    event_type: str | None = None,
    is_active: bool | None = None,
    organization_id: UUID | None = None,
) -> tuple[list[Trigger], int]:
    query = select(Trigger)
    count_query = select(func.count(Trigger.id))

    if event_type:
        query = query.where(Trigger.event_type == event_type)
        count_query = count_query.where(Trigger.event_type == event_type)
    if is_active is not None:
        query = query.where(Trigger.is_active == is_active)
        count_query = count_query.where(Trigger.is_active == is_active)
    if organization_id is not None:
        query = query.where(Trigger.organization_id == organization_id)
        count_query = count_query.where(Trigger.organization_id == organization_id)

    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    query = query.order_by(Trigger.created_at.desc())
    query = query.offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(query)
    triggers = list(result.scalars().all())

    return triggers, total


async def update_trigger(
    db: AsyncSession, trigger_id: UUID, data: dict, organization_id: UUID | None = None
) -> Trigger | None:
    result = await db.execute(_by_id(Trigger, trigger_id, organization_id))
    trigger = result.scalar_one_or_none()
    if not trigger:
        return None

    for key, value in data.items():
        if hasattr(trigger, key) and value is not None:
            setattr(trigger, key, value)

    await db.flush()
    return trigger


async def delete_trigger(
    db: AsyncSession, trigger_id: UUID, organization_id: UUID | None = None
) -> bool:
    result = await db.execute(_by_id(Trigger, trigger_id, organization_id))
    trigger = result.scalar_one_or_none()
    if not trigger:
        return False
    await db.delete(trigger)
    await db.flush()
    return True


async def enable_trigger(
    db: AsyncSession, trigger_id: UUID, organization_id: UUID | None = None
) -> Trigger | None:
    result = await db.execute(_by_id(Trigger, trigger_id, organization_id))
    trigger = result.scalar_one_or_none()
    if not trigger:
        return None
    trigger.is_active = True
    await db.flush()
    return trigger


async def disable_trigger(
    db: AsyncSession, trigger_id: UUID, organization_id: UUID | None = None
) -> Trigger | None:
    result = await db.execute(_by_id(Trigger, trigger_id, organization_id))
    trigger = result.scalar_one_or_none()
    if not trigger:
        return None
    trigger.is_active = False
    await db.flush()
    return trigger
