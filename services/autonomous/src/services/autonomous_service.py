"""自律型AIエージェント・デジタルツイン管理サービス"""

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import AutonomousAgent, AutonomousControl, AutonomousOperation, AutonomousTask, ConstructionSimulation, DigitalTwin, MarineRobot


def _by_id(model: Any, record_id: UUID, organization_id: UUID | None) -> Select:
    """Select a record by id, restricted to ``organization_id`` unless it is None (admin, ADR-0004)."""
    stmt = select(model).where(model.id == record_id)
    if organization_id is not None:
        stmt = stmt.where(model.organization_id == organization_id)
    return stmt


# ============================================
# Autonomous Agent CRUD
# ============================================
async def create_agent(db: AsyncSession, data: dict) -> AutonomousAgent:
    agent = AutonomousAgent(
        organization_id=data["organization_id"],
        name=data["name"],
        agent_type=data["agent_type"],
        target_resource=data.get("target_resource"),
        config=data.get("config", {}),
        is_enabled=data.get("is_enabled", True),
        status="idle",
    )
    db.add(agent)
    await db.flush()
    return agent


async def get_agent_by_id(db: AsyncSession, agent_id: UUID, organization_id: UUID | None = None) -> AutonomousAgent | None:
    result = await db.execute(
        _by_id(AutonomousAgent, agent_id, organization_id)
    )
    return result.scalar_one_or_none()


async def get_agents_paginated(
    db: AsyncSession,
    page: int = 1,
    per_page: int = 20,
    agent_type: str | None = None,
    status: str | None = None,
    organization_id: UUID | None = None,
) -> tuple[list[AutonomousAgent], int]:
    query = select(AutonomousAgent)
    count_query = select(func.count(AutonomousAgent.id))

    if agent_type:
        query = query.where(AutonomousAgent.agent_type == agent_type)
        count_query = count_query.where(AutonomousAgent.agent_type == agent_type)
    if status:
        query = query.where(AutonomousAgent.status == status)
        count_query = count_query.where(AutonomousAgent.status == status)
    if organization_id is not None:
        query = query.where(AutonomousAgent.organization_id == organization_id)
        count_query = count_query.where(AutonomousAgent.organization_id == organization_id)

    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    query = query.order_by(AutonomousAgent.created_at.desc())
    query = query.offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(query)
    agents = list(result.scalars().all())

    return agents, total


async def update_agent(db: AsyncSession, agent_id: UUID, data: dict, organization_id: UUID | None = None) -> AutonomousAgent | None:
    result = await db.execute(_by_id(AutonomousAgent, agent_id, organization_id))
    agent = result.scalar_one_or_none()
    if not agent:
        return None

    for key, value in data.items():
        if hasattr(agent, key) and value is not None:
            setattr(agent, key, value)

    await db.flush()
    return agent


async def delete_agent(db: AsyncSession, agent_id: UUID, organization_id: UUID | None = None) -> bool:
    result = await db.execute(_by_id(AutonomousAgent, agent_id, organization_id))
    agent = result.scalar_one_or_none()
    if not agent:
        return False
    await db.delete(agent)
    await db.flush()
    return True


async def start_agent(db: AsyncSession, agent_id: UUID, organization_id: UUID | None = None) -> AutonomousAgent | None:
    result = await db.execute(_by_id(AutonomousAgent, agent_id, organization_id))
    agent = result.scalar_one_or_none()
    if not agent:
        return None
    agent.status = "active"
    agent.last_run_at = datetime.now(timezone.utc)
    agent.run_count += 1
    await db.flush()
    return agent


async def stop_agent(db: AsyncSession, agent_id: UUID, organization_id: UUID | None = None) -> AutonomousAgent | None:
    result = await db.execute(_by_id(AutonomousAgent, agent_id, organization_id))
    agent = result.scalar_one_or_none()
    if not agent:
        return None
    agent.status = "idle"
    await db.flush()
    return agent


async def pause_agent(db: AsyncSession, agent_id: UUID, organization_id: UUID | None = None) -> AutonomousAgent | None:
    result = await db.execute(_by_id(AutonomousAgent, agent_id, organization_id))
    agent = result.scalar_one_or_none()
    if not agent:
        return None
    agent.status = "paused"
    await db.flush()
    return agent


# ============================================
# Digital Twin CRUD
# ============================================
async def create_twin(db: AsyncSession, data: dict) -> DigitalTwin:
    twin = DigitalTwin(
        organization_id=data["organization_id"],
        project_id=data.get("project_id"),
        name=data["name"],
        twin_type=data["twin_type"],
        bim_model_id=data.get("bim_model_id"),
        iot_device_ids=data.get("iot_device_ids", []),
        sync_interval_seconds=data.get("sync_interval_seconds", 60),
        data_sources=data.get("data_sources", {}),
        metadata_=data.get("metadata", {}),
        status="initializing",
    )
    db.add(twin)
    await db.flush()
    return twin


async def get_twin_by_id(db: AsyncSession, twin_id: UUID, organization_id: UUID | None = None) -> DigitalTwin | None:
    result = await db.execute(
        _by_id(DigitalTwin, twin_id, organization_id)
    )
    return result.scalar_one_or_none()


async def get_twins_paginated(
    db: AsyncSession,
    page: int = 1,
    per_page: int = 20,
    twin_type: str | None = None,
    status: str | None = None,
    project_id: UUID | None = None,
    organization_id: UUID | None = None,
) -> tuple[list[DigitalTwin], int]:
    query = select(DigitalTwin)
    count_query = select(func.count(DigitalTwin.id))

    if twin_type:
        query = query.where(DigitalTwin.twin_type == twin_type)
        count_query = count_query.where(DigitalTwin.twin_type == twin_type)
    if status:
        query = query.where(DigitalTwin.status == status)
        count_query = count_query.where(DigitalTwin.status == status)
    if project_id:
        query = query.where(DigitalTwin.project_id == project_id)
        count_query = count_query.where(DigitalTwin.project_id == project_id)
    if organization_id is not None:
        query = query.where(DigitalTwin.organization_id == organization_id)
        count_query = count_query.where(DigitalTwin.organization_id == organization_id)

    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    query = query.order_by(DigitalTwin.created_at.desc())
    query = query.offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(query)
    twins = list(result.scalars().all())

    return twins, total


async def update_twin(db: AsyncSession, twin_id: UUID, data: dict, organization_id: UUID | None = None) -> DigitalTwin | None:
    result = await db.execute(_by_id(DigitalTwin, twin_id, organization_id))
    twin = result.scalar_one_or_none()
    if not twin:
        return None

    for key, value in data.items():
        if hasattr(twin, key) and value is not None:
            if key == "metadata":
                setattr(twin, "metadata_", value)
            else:
                setattr(twin, key, value)

    await db.flush()
    return twin


async def delete_twin(db: AsyncSession, twin_id: UUID, organization_id: UUID | None = None) -> bool:
    result = await db.execute(_by_id(DigitalTwin, twin_id, organization_id))
    twin = result.scalar_one_or_none()
    if not twin:
        return False
    await db.delete(twin)
    await db.flush()
    return True


async def sync_twin(
    db: AsyncSession, twin_id: UUID, current_state: dict,
    organization_id: UUID | None = None,
) -> DigitalTwin | None:
    result = await db.execute(_by_id(DigitalTwin, twin_id, organization_id))
    twin = result.scalar_one_or_none()
    if not twin:
        return None

    now = datetime.now(timezone.utc)
    twin.last_sync_at = now
    twin.current_state = current_state
    twin.status = "active"
    await db.flush()
    return twin


async def get_twin_current_state(db: AsyncSession, twin_id: UUID, organization_id: UUID | None = None) -> dict | None:
    result = await db.execute(_by_id(DigitalTwin, twin_id, organization_id))
    twin = result.scalar_one_or_none()
    if not twin:
        return None
    return {
        "twin_id": twin.id,
        "name": twin.name,
        "status": twin.status,
        "current_state": twin.current_state,
        "last_sync_at": twin.last_sync_at,
    }


# ============================================
# Autonomous Task CRUD
# ============================================
async def create_task(db: AsyncSession, data: dict) -> AutonomousTask:
    task = AutonomousTask(
        organization_id=data["organization_id"],
        agent_id=data.get("agent_id"),
        digital_twin_id=data.get("digital_twin_id"),
        title=data["title"],
        task_type=data["task_type"],
        priority=data.get("priority", "normal"),
        input_data=data.get("input_data"),
        status="pending",
    )
    db.add(task)
    await db.flush()
    return task


async def get_task_by_id(db: AsyncSession, task_id: UUID, organization_id: UUID | None = None) -> AutonomousTask | None:
    result = await db.execute(
        _by_id(AutonomousTask, task_id, organization_id)
    )
    return result.scalar_one_or_none()


async def get_tasks_paginated(
    db: AsyncSession,
    page: int = 1,
    per_page: int = 20,
    task_type: str | None = None,
    status: str | None = None,
    priority: str | None = None,
    agent_id: UUID | None = None,
    organization_id: UUID | None = None,
) -> tuple[list[AutonomousTask], int]:
    query = select(AutonomousTask)
    count_query = select(func.count(AutonomousTask.id))

    if task_type:
        query = query.where(AutonomousTask.task_type == task_type)
        count_query = count_query.where(AutonomousTask.task_type == task_type)
    if status:
        query = query.where(AutonomousTask.status == status)
        count_query = count_query.where(AutonomousTask.status == status)
    if priority:
        query = query.where(AutonomousTask.priority == priority)
        count_query = count_query.where(AutonomousTask.priority == priority)
    if agent_id:
        query = query.where(AutonomousTask.agent_id == agent_id)
        count_query = count_query.where(AutonomousTask.agent_id == agent_id)
    if organization_id is not None:
        query = query.where(AutonomousTask.organization_id == organization_id)
        count_query = count_query.where(AutonomousTask.organization_id == organization_id)

    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    query = query.order_by(AutonomousTask.created_at.desc())
    query = query.offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(query)
    tasks = list(result.scalars().all())

    return tasks, total


# ============================================
# Construction Simulation CRUD
# ============================================
async def create_simulation(db: AsyncSession, data: dict) -> ConstructionSimulation:
    sim = ConstructionSimulation(
        organization_id=data["organization_id"],
        project_id=data.get("project_id"),
        digital_twin_id=data.get("digital_twin_id"),
        name=data["name"],
        simulation_type=data["simulation_type"],
        parameters=data.get("parameters", {}),
        created_by=data.get("created_by"),
        status="draft",
    )
    db.add(sim)
    await db.flush()
    return sim


async def get_simulation_by_id(db: AsyncSession, sim_id: UUID, organization_id: UUID | None = None) -> ConstructionSimulation | None:
    result = await db.execute(
        _by_id(ConstructionSimulation, sim_id, organization_id)
    )
    return result.scalar_one_or_none()


async def get_simulations_paginated(
    db: AsyncSession,
    page: int = 1,
    per_page: int = 20,
    simulation_type: str | None = None,
    status: str | None = None,
    project_id: UUID | None = None,
    organization_id: UUID | None = None,
) -> tuple[list[ConstructionSimulation], int]:
    query = select(ConstructionSimulation)
    count_query = select(func.count(ConstructionSimulation.id))

    if simulation_type:
        query = query.where(ConstructionSimulation.simulation_type == simulation_type)
        count_query = count_query.where(ConstructionSimulation.simulation_type == simulation_type)
    if status:
        query = query.where(ConstructionSimulation.status == status)
        count_query = count_query.where(ConstructionSimulation.status == status)
    if project_id:
        query = query.where(ConstructionSimulation.project_id == project_id)
        count_query = count_query.where(ConstructionSimulation.project_id == project_id)
    if organization_id is not None:
        query = query.where(ConstructionSimulation.organization_id == organization_id)
        count_query = count_query.where(ConstructionSimulation.organization_id == organization_id)

    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    query = query.order_by(ConstructionSimulation.created_at.desc())
    query = query.offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(query)
    simulations = list(result.scalars().all())

    return simulations, total


async def update_simulation(
    db: AsyncSession, sim_id: UUID, data: dict,
    organization_id: UUID | None = None,
) -> ConstructionSimulation | None:
    result = await db.execute(
        _by_id(ConstructionSimulation, sim_id, organization_id)
    )
    sim = result.scalar_one_or_none()
    if not sim:
        return None

    for key, value in data.items():
        if hasattr(sim, key) and value is not None:
            setattr(sim, key, value)

    await db.flush()
    return sim


async def delete_simulation(db: AsyncSession, sim_id: UUID, organization_id: UUID | None = None) -> bool:
    result = await db.execute(
        _by_id(ConstructionSimulation, sim_id, organization_id)
    )
    sim = result.scalar_one_or_none()
    if not sim:
        return False
    await db.delete(sim)
    await db.flush()
    return True


async def run_simulation(db: AsyncSession, sim_id: UUID, organization_id: UUID | None = None) -> ConstructionSimulation | None:
    result = await db.execute(
        _by_id(ConstructionSimulation, sim_id, organization_id)
    )
    sim = result.scalar_one_or_none()
    if not sim:
        return None

    now = datetime.now(timezone.utc)
    sim.status = "running"
    sim.started_at = now
    sim.progress_percent = 0

    # シミュレーション完了を模擬
    sim.status = "completed"
    sim.completed_at = datetime.now(timezone.utc)
    sim.progress_percent = 100.00
    sim.results = {
        "summary": "Simulation completed successfully",
        "executed_at": now.isoformat(),
    }

    await db.flush()
    return sim


# ============================================
# Autonomous Operations CRUD
# ============================================
async def create_operation(db: AsyncSession, data: dict) -> AutonomousOperation:
    op = AutonomousOperation(
        organization_id=data["organization_id"],
        project_id=data.get("project_id"),
        digital_twin_id=data.get("digital_twin_id"),
        name=data["name"],
        operation_type=data["operation_type"],
        equipment_id=data.get("equipment_id"),
        plan_data=data.get("plan_data", {}),
        area=data.get("area"),
        operator_id=data.get("operator_id"),
        status="planned",
        execution_log=[],
        progress_percent=0,
        safety_status="normal",
    )
    db.add(op)
    await db.flush()
    return op


async def get_operation_by_id(db: AsyncSession, op_id: UUID, organization_id: UUID | None = None) -> AutonomousOperation | None:
    result = await db.execute(
        _by_id(AutonomousOperation, op_id, organization_id)
    )
    return result.scalar_one_or_none()


async def get_operations_paginated(
    db: AsyncSession,
    page: int = 1,
    per_page: int = 20,
    operation_type: str | None = None,
    status: str | None = None,
    project_id: UUID | None = None,
    organization_id: UUID | None = None,
) -> tuple[list[AutonomousOperation], int]:
    query = select(AutonomousOperation)
    count_query = select(func.count(AutonomousOperation.id))

    if operation_type:
        query = query.where(AutonomousOperation.operation_type == operation_type)
        count_query = count_query.where(AutonomousOperation.operation_type == operation_type)
    if status:
        query = query.where(AutonomousOperation.status == status)
        count_query = count_query.where(AutonomousOperation.status == status)
    if project_id:
        query = query.where(AutonomousOperation.project_id == project_id)
        count_query = count_query.where(AutonomousOperation.project_id == project_id)
    if organization_id is not None:
        query = query.where(AutonomousOperation.organization_id == organization_id)
        count_query = count_query.where(AutonomousOperation.organization_id == organization_id)

    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    query = query.order_by(AutonomousOperation.created_at.desc())
    query = query.offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(query)
    operations = list(result.scalars().all())

    return operations, total


async def update_operation(
    db: AsyncSession, op_id: UUID, data: dict,
    organization_id: UUID | None = None,
) -> AutonomousOperation | None:
    result = await db.execute(
        _by_id(AutonomousOperation, op_id, organization_id)
    )
    op = result.scalar_one_or_none()
    if not op:
        return None

    for key, value in data.items():
        if hasattr(op, key) and value is not None:
            setattr(op, key, value)

    await db.flush()
    return op


async def delete_operation(db: AsyncSession, op_id: UUID, organization_id: UUID | None = None) -> bool:
    result = await db.execute(
        _by_id(AutonomousOperation, op_id, organization_id)
    )
    op = result.scalar_one_or_none()
    if not op:
        return False
    await db.delete(op)
    await db.flush()
    return True


async def start_operation(db: AsyncSession, op_id: UUID, organization_id: UUID | None = None) -> AutonomousOperation | None:
    result = await db.execute(
        _by_id(AutonomousOperation, op_id, organization_id)
    )
    op = result.scalar_one_or_none()
    if not op:
        return None
    now = datetime.now(timezone.utc)
    op.status = "in_progress"
    op.start_time = now
    op.safety_status = "normal"
    await db.flush()
    return op


async def pause_operation(db: AsyncSession, op_id: UUID, organization_id: UUID | None = None) -> AutonomousOperation | None:
    result = await db.execute(
        _by_id(AutonomousOperation, op_id, organization_id)
    )
    op = result.scalar_one_or_none()
    if not op:
        return None
    op.status = "paused"
    await db.flush()
    return op


async def resume_operation(db: AsyncSession, op_id: UUID, organization_id: UUID | None = None) -> AutonomousOperation | None:
    result = await db.execute(
        _by_id(AutonomousOperation, op_id, organization_id)
    )
    op = result.scalar_one_or_none()
    if not op:
        return None
    op.status = "in_progress"
    await db.flush()
    return op


async def abort_operation(db: AsyncSession, op_id: UUID, organization_id: UUID | None = None) -> AutonomousOperation | None:
    result = await db.execute(
        _by_id(AutonomousOperation, op_id, organization_id)
    )
    op = result.scalar_one_or_none()
    if not op:
        return None
    op.status = "aborted"
    op.end_time = datetime.now(timezone.utc)
    await db.flush()
    return op


async def emergency_stop_operation(db: AsyncSession, op_id: UUID, organization_id: UUID | None = None) -> AutonomousOperation | None:
    result = await db.execute(
        _by_id(AutonomousOperation, op_id, organization_id)
    )
    op = result.scalar_one_or_none()
    if not op:
        return None
    op.status = "emergency_stop"
    op.safety_status = "emergency"
    op.end_time = datetime.now(timezone.utc)
    await db.flush()
    return op


async def get_operation_progress(db: AsyncSession, op_id: UUID, organization_id: UUID | None = None) -> dict | None:
    result = await db.execute(
        _by_id(AutonomousOperation, op_id, organization_id)
    )
    op = result.scalar_one_or_none()
    if not op:
        return None
    return {
        "operation_id": op.id,
        "name": op.name,
        "status": op.status,
        "progress_percent": float(op.progress_percent),
        "safety_status": op.safety_status,
        "execution_log": op.execution_log,
    }


# ============================================
# Marine Robotics CRUD
# ============================================
async def create_marine_robot(db: AsyncSession, data: dict) -> MarineRobot:
    robot = MarineRobot(
        organization_id=data["organization_id"],
        project_id=data.get("project_id"),
        robot_name=data["robot_name"],
        robot_type=data["robot_type"],
        mission_type=data.get("mission_type"),
        location=data.get("location"),
        depth_meters=data.get("depth_meters"),
        battery_level=data.get("battery_level"),
        mission_plan=data.get("mission_plan", {}),
        telemetry={},
        status="docked",
    )
    db.add(robot)
    await db.flush()
    return robot


async def get_marine_robot_by_id(db: AsyncSession, robot_id: UUID, organization_id: UUID | None = None) -> MarineRobot | None:
    result = await db.execute(
        _by_id(MarineRobot, robot_id, organization_id)
    )
    return result.scalar_one_or_none()


async def get_marine_robots_paginated(
    db: AsyncSession,
    page: int = 1,
    per_page: int = 20,
    robot_type: str | None = None,
    status: str | None = None,
    mission_type: str | None = None,
    organization_id: UUID | None = None,
) -> tuple[list[MarineRobot], int]:
    query = select(MarineRobot)
    count_query = select(func.count(MarineRobot.id))

    if robot_type:
        query = query.where(MarineRobot.robot_type == robot_type)
        count_query = count_query.where(MarineRobot.robot_type == robot_type)
    if status:
        query = query.where(MarineRobot.status == status)
        count_query = count_query.where(MarineRobot.status == status)
    if mission_type:
        query = query.where(MarineRobot.mission_type == mission_type)
        count_query = count_query.where(MarineRobot.mission_type == mission_type)
    if organization_id is not None:
        query = query.where(MarineRobot.organization_id == organization_id)
        count_query = count_query.where(MarineRobot.organization_id == organization_id)

    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    query = query.order_by(MarineRobot.created_at.desc())
    query = query.offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(query)
    robots = list(result.scalars().all())

    return robots, total


async def update_marine_robot(
    db: AsyncSession, robot_id: UUID, data: dict,
    organization_id: UUID | None = None,
) -> MarineRobot | None:
    result = await db.execute(
        _by_id(MarineRobot, robot_id, organization_id)
    )
    robot = result.scalar_one_or_none()
    if not robot:
        return None

    for key, value in data.items():
        if hasattr(robot, key) and value is not None:
            setattr(robot, key, value)

    await db.flush()
    return robot


async def delete_marine_robot(db: AsyncSession, robot_id: UUID, organization_id: UUID | None = None) -> bool:
    result = await db.execute(
        _by_id(MarineRobot, robot_id, organization_id)
    )
    robot = result.scalar_one_or_none()
    if not robot:
        return False
    await db.delete(robot)
    await db.flush()
    return True


async def deploy_marine_robot(db: AsyncSession, robot_id: UUID, organization_id: UUID | None = None) -> MarineRobot | None:
    result = await db.execute(
        _by_id(MarineRobot, robot_id, organization_id)
    )
    robot = result.scalar_one_or_none()
    if not robot:
        return None
    now = datetime.now(timezone.utc)
    robot.status = "deploying"
    robot.deployed_at = now
    robot.last_contact = now
    await db.flush()
    return robot


async def recover_marine_robot(db: AsyncSession, robot_id: UUID, organization_id: UUID | None = None) -> MarineRobot | None:
    result = await db.execute(
        _by_id(MarineRobot, robot_id, organization_id)
    )
    robot = result.scalar_one_or_none()
    if not robot:
        return None
    now = datetime.now(timezone.utc)
    robot.status = "docked"
    robot.recovered_at = now
    robot.last_contact = now
    await db.flush()
    return robot


async def get_marine_robot_telemetry(db: AsyncSession, robot_id: UUID, organization_id: UUID | None = None) -> dict | None:
    result = await db.execute(
        _by_id(MarineRobot, robot_id, organization_id)
    )
    robot = result.scalar_one_or_none()
    if not robot:
        return None
    return {
        "robot_id": robot.id,
        "robot_name": robot.robot_name,
        "status": robot.status,
        "telemetry": robot.telemetry,
        "battery_level": robot.battery_level,
        "location": robot.location,
        "last_contact": robot.last_contact,
    }


async def set_marine_robot_mission(
    db: AsyncSession, robot_id: UUID, mission_plan: dict,
    organization_id: UUID | None = None,
) -> MarineRobot | None:
    result = await db.execute(
        _by_id(MarineRobot, robot_id, organization_id)
    )
    robot = result.scalar_one_or_none()
    if not robot:
        return None
    robot.mission_plan = mission_plan
    await db.flush()
    return robot


# ============================================
# Autonomous Controls CRUD
# ============================================
# Control targets that are stored (and organization-owned) in this service.
# Commands for any other target_type cannot be checked for ownership and are rejected (fail-closed).
CONTROL_TARGET_MODELS: dict[str, Any] = {
    "operation": AutonomousOperation,
    "marine_robot": MarineRobot,
    "agent": AutonomousAgent,
    "digital_twin": DigitalTwin,
    "simulation": ConstructionSimulation,
}


async def get_control_target(
    db: AsyncSession,
    target_type: str,
    target_id: UUID,
    organization_id: UUID | None = None,
) -> Any | None:
    """Return the command target (organization-scoped), or None if absent / not visible.

    Raises ``KeyError`` for an unsupported ``target_type``.
    """
    model = CONTROL_TARGET_MODELS[target_type]
    result = await db.execute(_by_id(model, target_id, organization_id))
    return result.scalar_one_or_none()


async def send_control_command(db: AsyncSession, data: dict) -> AutonomousControl:
    ctrl = AutonomousControl(
        organization_id=data["organization_id"],
        target_id=data["target_id"],
        target_type=data["target_type"],
        command_type=data["command_type"],
        parameters=data.get("parameters", {}),
        issued_by=data["issued_by"],
        status="pending",
    )
    db.add(ctrl)
    await db.flush()
    return ctrl


async def get_control_by_id(db: AsyncSession, control_id: UUID, organization_id: UUID | None = None) -> AutonomousControl | None:
    result = await db.execute(
        _by_id(AutonomousControl, control_id, organization_id)
    )
    return result.scalar_one_or_none()


async def get_controls_for_target(
    db: AsyncSession,
    target_id: UUID,
    target_type: str,
    page: int = 1,
    per_page: int = 20,
    organization_id: UUID | None = None,
) -> tuple[list[AutonomousControl], int]:
    query = select(AutonomousControl).where(
        AutonomousControl.target_id == target_id,
        AutonomousControl.target_type == target_type,
    )
    count_query = select(func.count(AutonomousControl.id)).where(
        AutonomousControl.target_id == target_id,
        AutonomousControl.target_type == target_type,
    )
    if organization_id is not None:
        query = query.where(AutonomousControl.organization_id == organization_id)
        count_query = count_query.where(AutonomousControl.organization_id == organization_id)

    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    query = query.order_by(AutonomousControl.created_at.desc())
    query = query.offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(query)
    controls = list(result.scalars().all())

    return controls, total


async def get_pending_controls(
    db: AsyncSession,
    organization_id: UUID | None = None,
    page: int = 1,
    per_page: int = 20,
) -> tuple[list[AutonomousControl], int]:
    query = select(AutonomousControl).where(
        AutonomousControl.status == "pending"
    )
    count_query = select(func.count(AutonomousControl.id)).where(
        AutonomousControl.status == "pending"
    )

    if organization_id is not None:
        query = query.where(AutonomousControl.organization_id == organization_id)
        count_query = count_query.where(AutonomousControl.organization_id == organization_id)

    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    query = query.order_by(AutonomousControl.created_at.desc())
    query = query.offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(query)
    controls = list(result.scalars().all())

    return controls, total
