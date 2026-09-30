"""Autonomous Service 結合テスト"""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from src.main import create_app
from src.models.base import get_db
from src.middleware.auth import get_current_user, get_current_client


class MockRow:
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


class MockResult:
    def __init__(self, return_value=None):
        self._return_value = return_value

    def scalar_one_or_none(self):
        return self._return_value

    def scalars(self):
        return self

    def all(self):
        if isinstance(self._return_value, list):
            return self._return_value
        return [self._return_value] if self._return_value else []

    def scalar(self):
        return self._return_value


def _make_mock_user(sub="00000000-0000-0000-0000-000000000001"):
    user = MagicMock()
    user.sub = sub
    user.type = "user"
    user.org = "00000000-0000-0000-0000-000000000001"
    user.roles = ["admin"]
    user.scopes = []
    return user


def _make_mock_agent(agent_id=None):
    from datetime import datetime, timezone
    a = MagicMock()
    a.id = agent_id or uuid4()
    a.organization_id = uuid4()
    a.name = "Mock Agent"
    a.agent_type = "scheduler"
    a.status = "idle"
    a.target_resource = None
    a.config = {}
    a.last_run_at = None
    a.run_count = 0
    a.error_count = 0
    a.is_enabled = True
    a.created_at = datetime.now(timezone.utc)
    return a


def _make_mock_twin(twin_id=None):
    from datetime import datetime, timezone

    class MockTwin:
        def __init__(self):
            self.id = twin_id or uuid4()
            self.organization_id = uuid4()
            self.project_id = None
            self.name = "Mock Twin"
            self.twin_type = "construction_site"
            self.status = "active"
            self.bim_model_id = None
            self.iot_device_ids = []
            self.last_sync_at = datetime.now(timezone.utc)
            self.sync_interval_seconds = 60
            self.data_sources = {}
            self.current_state = {}
            self.metadata = {}
            self.metadata_ = {}
            self.created_at = datetime.now(timezone.utc)
            self.updated_at = datetime.now(timezone.utc)
    return MockTwin()


def _make_mock_task(task_id=None):
    from datetime import datetime, timezone
    t = MagicMock()
    t.id = task_id or uuid4()
    t.organization_id = uuid4()
    t.agent_id = None
    t.digital_twin_id = None
    t.title = "Mock Task"
    t.task_type = "optimize_schedule"
    t.priority = "normal"
    t.status = "pending"
    t.input_data = None
    t.output_data = None
    t.error_message = None
    t.started_at = None
    t.completed_at = None
    t.duration_ms = None
    t.created_at = datetime.now(timezone.utc)
    return t


def _make_mock_simulation(sim_id=None):
    from datetime import datetime, timezone
    s = MagicMock()
    s.id = sim_id or uuid4()
    s.organization_id = uuid4()
    s.project_id = None
    s.digital_twin_id = None
    s.name = "Mock Simulation"
    s.simulation_type = "schedule"
    s.status = "draft"
    s.parameters = {}
    s.results = {}
    s.progress_percent = 0
    s.started_at = None
    s.completed_at = None
    s.created_by = None
    s.created_at = datetime.now(timezone.utc)
    return s


def _make_mock_operation(op_id=None):
    op = MockRow(
        id=op_id or uuid4(),
        organization_id=uuid4(),
        project_id=None,
        digital_twin_id=None,
        name="Mock Excavation",
        operation_type="excavation",
        equipment_id=None,
        status="planned",
        plan_data={},
        execution_log=[],
        progress_percent=0,
        safety_status="normal",
        area=None,
        start_time=None,
        end_time=None,
        operator_id=None,
        created_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
    )
    return op


def _make_mock_robot(robot_id=None):
    robot = MockRow(
        id=robot_id or uuid4(),
        organization_id=uuid4(),
        project_id=None,
        robot_name="Mock AUV-7",
        robot_type="auv",
        status="docked",
        mission_type="survey",
        location={"type": "Point", "coordinates": [139.76, 35.68]},
        depth_meters=12.5,
        battery_level=95,
        mission_plan={},
        telemetry={},
        last_contact=None,
        deployed_at=None,
        recovered_at=None,
        created_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
    )
    return robot


def _make_mock_control(ctrl_id=None):
    ctrl = MockRow(
        id=ctrl_id or uuid4(),
        organization_id=uuid4(),
        target_id=uuid4(),
        target_type="operation",
        command_type="start",
        parameters={},
        status="pending",
        issued_by=uuid4(),
        executed_at=None,
        result=None,
        error_message=None,
        created_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
    )
    return ctrl


async def _mock_get_current_user():
    return _make_mock_user()


async def _mock_get_current_client():
    client = MagicMock()
    client.sub = "00000000-0000-0000-0000-000000000002"
    client.type = "client"
    client.org = "00000000-0000-0000-0000-000000000001"
    client.roles = []
    client.scopes = ["autonomous:agent"]
    return client


@pytest.fixture
def app():
    _app = create_app()
    mock_db = AsyncMock()

    async def mock_execute(*args, **kwargs):
        return MockResult()

    async def mock_commit():
        pass

    async def mock_rollback():
        pass

    async def mock_close():
        pass

    async def mock_flush():
        pass

    mock_db.execute = mock_execute
    mock_db.commit = mock_commit
    mock_db.rollback = mock_rollback
    mock_db.close = mock_close
    mock_db.flush = mock_flush
    mock_db.add = MagicMock()
    mock_db.delete = MagicMock()

    async def mock_get_db():
        yield mock_db

    _app.dependency_overrides[get_db] = mock_get_db
    _app.dependency_overrides[get_current_user] = _mock_get_current_user
    _app.dependency_overrides[get_current_client] = _mock_get_current_client
    return _app


@pytest.fixture
def client(app):
    return TestClient(app)


@pytest.fixture
def auth_headers():
    return {"Authorization": "Bearer mock-user-token"}


# ============================================
# Test 1: Health Check
# ============================================
def test_health_check(client):
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["service"] == "autonomous-service"


# ============================================
# Test 2: Auth Required - Agent endpoint
# ============================================
def test_agents_list_requires_auth():
    _app = create_app()
    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=MockResult())
    mock_db.commit = AsyncMock()
    mock_db.rollback = AsyncMock()
    mock_db.close = AsyncMock()
    mock_db.flush = AsyncMock()
    mock_db.add = MagicMock()
    mock_db.delete = MagicMock()

    async def mock_get_db():
        yield mock_db

    _app.dependency_overrides[get_db] = mock_get_db
    c = TestClient(_app)
    response = c.get("/api/v1/autonomous/agents")
    assert response.status_code == 401


# ============================================
# Test 3: Agent CRUD - Create
# ============================================
def test_create_agent(client, auth_headers):
    mock_agent = _make_mock_agent()

    import src.api.agents as agents_module
    agents_module.create_agent = AsyncMock(return_value=mock_agent)

    response = client.post(
        "/api/v1/autonomous/agents",
        json={
            "organization_id": "00000000-0000-0000-0000-000000000001",
            "name": "Test Scheduler",
            "agent_type": "scheduler",
        },
        headers=auth_headers,
    )
    assert response.status_code == 201
    data = response.json()
    assert data["success"] is True
    assert data["data"]["name"] == "Mock Agent"


# ============================================
# Test 4: Agent CRUD - Get
# ============================================
def test_get_agent(client, auth_headers):
    agent_id = uuid4()
    mock_agent = _make_mock_agent(agent_id=agent_id)

    import src.api.agents as agents_module
    agents_module.get_agent_by_id = AsyncMock(return_value=mock_agent)

    response = client.get(
        f"/api/v1/autonomous/agents/{agent_id}",
        headers=auth_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True


# ============================================
# Test 5: Agent CRUD - Update
# ============================================
def test_update_agent(client, auth_headers):
    agent_id = uuid4()
    mock_agent = _make_mock_agent(agent_id=agent_id)

    import src.api.agents as agents_module
    agents_module.update_agent = AsyncMock(return_value=mock_agent)

    response = client.put(
        f"/api/v1/autonomous/agents/{agent_id}",
        json={"name": "Updated Agent"},
        headers=auth_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True


# ============================================
# Test 6: Agent CRUD - Delete
# ============================================
def test_delete_agent(client, auth_headers):
    agent_id = uuid4()

    import src.api.agents as agents_module
    agents_module.delete_agent = AsyncMock(return_value=True)

    response = client.delete(
        f"/api/v1/autonomous/agents/{agent_id}",
        headers=auth_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True


# ============================================
# Test 7: Agent Start/Stop
# ============================================
def test_start_agent(client, auth_headers):
    agent_id = uuid4()
    mock_agent = _make_mock_agent(agent_id=agent_id)

    import src.api.agents as agents_module
    agents_module.start_agent = AsyncMock(return_value=mock_agent)

    response = client.post(
        f"/api/v1/autonomous/agents/{agent_id}/start",
        headers=auth_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True


# ============================================
# Test 8: Digital Twin CRUD - Create
# ============================================
def test_create_twin(client, auth_headers):
    mock_twin = _make_mock_twin()

    import src.api.digital_twins as twin_module
    twin_module.create_twin = AsyncMock(return_value=mock_twin)

    response = client.post(
        "/api/v1/autonomous/digital-twins",
        json={
            "organization_id": "00000000-0000-0000-0000-000000000001",
            "name": "Test Construction Site",
            "twin_type": "construction_site",
        },
        headers=auth_headers,
    )
    assert response.status_code == 201
    data = response.json()
    assert data["success"] is True
    assert data["data"]["name"] == "Mock Twin"


# ============================================
# Test 9: Digital Twin CRUD - Get
# ============================================
def test_get_twin(client, auth_headers):
    twin_id = uuid4()
    mock_twin = _make_mock_twin(twin_id=twin_id)

    import src.api.digital_twins as twin_module
    twin_module.get_twin_by_id = AsyncMock(return_value=mock_twin)

    response = client.get(
        f"/api/v1/autonomous/digital-twins/{twin_id}",
        headers=auth_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True


# ============================================
# Test 10: Digital Twin Sync State
# ============================================
def test_sync_twin(client, auth_headers):
    twin_id = uuid4()
    mock_twin = _make_mock_twin(twin_id=twin_id)

    import src.api.digital_twins as twin_module
    twin_module.sync_twin = AsyncMock(return_value=mock_twin)

    response = client.post(
        f"/api/v1/autonomous/digital-twins/{twin_id}/sync",
        json={"current_state": {"status": "active"}},
        headers=auth_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True


# ============================================
# Test 11: Task Creation
# ============================================
def test_create_task(client, auth_headers):
    mock_task = _make_mock_task()

    import src.api.tasks as tasks_module
    tasks_module.create_task = AsyncMock(return_value=mock_task)

    response = client.post(
        "/api/v1/autonomous/tasks",
        json={
            "organization_id": "00000000-0000-0000-0000-000000000001",
            "title": "Optimize Construction Schedule",
            "task_type": "optimize_schedule",
        },
        headers=auth_headers,
    )
    assert response.status_code == 201
    data = response.json()
    assert data["success"] is True
    assert data["data"]["title"] == "Mock Task"


# ============================================
# Test 12: Task Get Result
# ============================================
def test_get_task(client, auth_headers):
    task_id = uuid4()
    mock_task = _make_mock_task(task_id=task_id)

    import src.api.tasks as tasks_module
    tasks_module.get_task_by_id = AsyncMock(return_value=mock_task)

    response = client.get(
        f"/api/v1/autonomous/tasks/{task_id}",
        headers=auth_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True


# ============================================
# Test 13: Simulation Create
# ============================================
def test_create_simulation(client, auth_headers):
    mock_sim = _make_mock_simulation()

    import src.api.simulations as sim_module
    sim_module.create_simulation = AsyncMock(return_value=mock_sim)

    response = client.post(
        "/api/v1/autonomous/simulations",
        json={
            "organization_id": "00000000-0000-0000-0000-000000000001",
            "name": "Schedule Simulation",
            "simulation_type": "schedule",
        },
        headers=auth_headers,
    )
    assert response.status_code == 201
    data = response.json()
    assert data["success"] is True
    assert data["data"]["name"] == "Mock Simulation"


# ============================================
# Test 14: Simulation Run
# ============================================
def test_run_simulation(client, auth_headers):
    sim_id = uuid4()
    mock_sim = _make_mock_simulation(sim_id=sim_id)

    import src.api.simulations as sim_module
    sim_module.run_simulation = AsyncMock(return_value=mock_sim)

    response = client.post(
        f"/api/v1/autonomous/simulations/{sim_id}/run",
        headers=auth_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True


# ============================================
# Test 15: Agent List Pagination
# ============================================
def test_list_agents(client, auth_headers):
    mock_agent = _make_mock_agent()

    import src.api.agents as agents_module
    agents_module.get_agents_paginated = AsyncMock(return_value=([mock_agent], 1))

    response = client.get(
        "/api/v1/autonomous/agents?page=1&per_page=10",
        headers=auth_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["data"]["total"] == 1


# ============================================
# Test 18: Operation CRUD - Create
# ============================================
def test_create_operation(client, auth_headers):
    mock_op = _make_mock_operation()

    import src.api.operations as ops_module
    ops_module.create_operation = AsyncMock(return_value=mock_op)

    response = client.post(
        "/api/v1/autonomous/operations",
        json={
            "organization_id": "00000000-0000-0000-0000-000000000001",
            "name": "Test Excavation",
            "operation_type": "excavation",
        },
        headers=auth_headers,
    )
    assert response.status_code == 201
    data = response.json()
    assert data["success"] is True
    assert data["data"]["name"] == "Mock Excavation"


# ============================================
# Test 19: Operation CRUD - Get
# ============================================
def test_get_operation(client, auth_headers):
    op_id = uuid4()
    mock_op = _make_mock_operation(op_id=op_id)

    import src.api.operations as ops_module
    ops_module.get_operation_by_id = AsyncMock(return_value=mock_op)

    response = client.get(
        f"/api/v1/autonomous/operations/{op_id}",
        headers=auth_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True


# ============================================
# Test 20: Operation CRUD - Update
# ============================================
def test_update_operation(client, auth_headers):
    op_id = uuid4()
    mock_op = _make_mock_operation(op_id=op_id)

    import src.api.operations as ops_module
    ops_module.update_operation = AsyncMock(return_value=mock_op)

    response = client.put(
        f"/api/v1/autonomous/operations/{op_id}",
        json={"name": "Updated Excavation"},
        headers=auth_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True


# ============================================
# Test 21: Operation CRUD - Delete
# ============================================
def test_delete_operation(client, auth_headers):
    op_id = uuid4()

    import src.api.operations as ops_module
    ops_module.delete_operation = AsyncMock(return_value=True)

    response = client.delete(
        f"/api/v1/autonomous/operations/{op_id}",
        headers=auth_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True


# ============================================
# Test 22: Operation Start
# ============================================
def test_start_operation(client, auth_headers):
    op_id = uuid4()
    mock_op = _make_mock_operation(op_id=op_id)

    import src.api.operations as ops_module
    ops_module.start_operation = AsyncMock(return_value=mock_op)

    response = client.post(
        f"/api/v1/autonomous/operations/{op_id}/start",
        headers=auth_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True


# ============================================
# Test 23: Operation Emergency Stop
# ============================================
def test_emergency_stop_operation(client, auth_headers):
    op_id = uuid4()
    mock_op = _make_mock_operation(op_id=op_id)

    import src.api.operations as ops_module
    ops_module.emergency_stop_operation = AsyncMock(return_value=mock_op)

    response = client.post(
        f"/api/v1/autonomous/operations/{op_id}/emergency-stop",
        headers=auth_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True


# ============================================
# Test 24: Operation Progress
# ============================================
def test_get_operation_progress(client, auth_headers):
    op_id = uuid4()

    import src.api.operations as ops_module
    ops_module.get_operation_progress = AsyncMock(return_value={
        "operation_id": str(op_id),
        "name": "Excavation Job",
        "status": "in_progress",
        "progress_percent": 45.5,
        "safety_status": "normal",
        "execution_log": [],
    })

    response = client.get(
        f"/api/v1/autonomous/operations/{op_id}/progress",
        headers=auth_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["data"]["progress_percent"] == 45.5


# ============================================
# Test 25: Operation List
# ============================================
def test_list_operations(client, auth_headers):
    mock_op = _make_mock_operation()

    import src.api.operations as ops_module
    ops_module.get_operations_paginated = AsyncMock(return_value=([mock_op], 1))

    response = client.get(
        "/api/v1/autonomous/operations?page=1&per_page=10",
        headers=auth_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["data"]["total"] == 1


# ============================================
# Test 26: Marine Robot CRUD - Create
# ============================================
def test_create_marine_robot(client, auth_headers):
    mock_robot = _make_mock_robot()

    import src.api.marine_robots as robots_module
    robots_module.create_marine_robot = AsyncMock(return_value=mock_robot)

    response = client.post(
        "/api/v1/autonomous/marine-robots",
        json={
            "organization_id": "00000000-0000-0000-0000-000000000001",
            "robot_name": "Test AUV",
            "robot_type": "auv",
        },
        headers=auth_headers,
    )
    assert response.status_code == 201
    data = response.json()
    assert data["success"] is True
    assert data["data"]["robot_name"] == "Mock AUV-7"


# ============================================
# Test 27: Marine Robot CRUD - Get
# ============================================
def test_get_marine_robot(client, auth_headers):
    robot_id = uuid4()
    mock_robot = _make_mock_robot(robot_id=robot_id)

    import src.api.marine_robots as robots_module
    robots_module.get_marine_robot_by_id = AsyncMock(return_value=mock_robot)

    response = client.get(
        f"/api/v1/autonomous/marine-robots/{robot_id}",
        headers=auth_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True


# ============================================
# Test 28: Marine Robot Deploy
# ============================================
def test_deploy_marine_robot(client, auth_headers):
    robot_id = uuid4()
    mock_robot = _make_mock_robot(robot_id=robot_id)

    import src.api.marine_robots as robots_module
    robots_module.deploy_marine_robot = AsyncMock(return_value=mock_robot)

    response = client.post(
        f"/api/v1/autonomous/marine-robots/{robot_id}/deploy",
        headers=auth_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True


# ============================================
# Test 29: Marine Robot Telemetry
# ============================================
def test_get_marine_robot_telemetry(client, auth_headers):
    robot_id = uuid4()

    import src.api.marine_robots as robots_module
    robots_module.get_marine_robot_telemetry = AsyncMock(return_value={
        "robot_id": str(robot_id),
        "robot_name": "Test AUV",
        "status": "operating",
        "telemetry": {"speed": 1.5, "heading": 270},
        "battery_level": 78,
        "location": {"type": "Point", "coordinates": [139.76, 35.68]},
        "last_contact": None,
    })

    response = client.get(
        f"/api/v1/autonomous/marine-robots/{robot_id}/telemetry",
        headers=auth_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["data"]["battery_level"] == 78


# ============================================
# Test 30: Marine Robot List
# ============================================
def test_list_marine_robots(client, auth_headers):
    mock_robot = _make_mock_robot()

    import src.api.marine_robots as robots_module
    robots_module.get_marine_robots_paginated = AsyncMock(return_value=([mock_robot], 1))

    response = client.get(
        "/api/v1/autonomous/marine-robots?page=1&per_page=10",
        headers=auth_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["data"]["total"] == 1


# ============================================
# Test 31: Control - Send Command
# ============================================
def test_send_control_command(client, auth_headers, monkeypatch):
    from uuid import UUID

    mock_ctrl = _make_mock_control()
    # The command target must exist in the command's organization (ADR-0004).
    target_op = _make_mock_operation(op_id=UUID("00000000-0000-0000-0000-000000000010"))
    target_op.organization_id = UUID("00000000-0000-0000-0000-000000000001")

    import src.api.controls as ctrl_module
    ctrl_module.send_control_command = AsyncMock(return_value=mock_ctrl)
    monkeypatch.setattr(ctrl_module, "get_control_target", AsyncMock(return_value=target_op))

    response = client.post(
        "/api/v1/autonomous/controls",
        json={
            "organization_id": "00000000-0000-0000-0000-000000000001",
            "target_id": "00000000-0000-0000-0000-000000000010",
            "target_type": "operation",
            "command_type": "start",
            "parameters": {"speed": "medium"},
            "issued_by": "00000000-0000-0000-0000-000000000001",
        },
        headers=auth_headers,
    )
    assert response.status_code == 201
    data = response.json()
    assert data["success"] is True


# ============================================
# Test 32: Control - Get Pending Commands
# ============================================
def test_get_pending_commands(client, auth_headers):
    mock_ctrl = _make_mock_control()

    import src.api.controls as ctrl_module
    ctrl_module.get_pending_controls = AsyncMock(return_value=([mock_ctrl], 1))

    response = client.get(
        "/api/v1/autonomous/controls?page=1&per_page=10",
        headers=auth_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["data"]["total"] == 1


# ============================================
# Test 33: Control - Get Command History for Target
# ============================================
def test_get_target_command_history(client, auth_headers):
    target_id = uuid4()
    mock_ctrl = _make_mock_control()

    import src.api.controls as ctrl_module
    ctrl_module.get_controls_for_target = AsyncMock(return_value=([mock_ctrl], 1))

    response = client.get(
        f"/api/v1/autonomous/controls/target/operation/{target_id}?page=1&per_page=10",
        headers=auth_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["data"]["total"] == 1


# ============================================
# Test 34: Control - Get Single Command
# ============================================
def test_get_control_command(client, auth_headers):
    ctrl_id = uuid4()
    mock_ctrl = _make_mock_control(ctrl_id=ctrl_id)

    import src.api.controls as ctrl_module
    ctrl_module.get_control_by_id = AsyncMock(return_value=mock_ctrl)

    response = client.get(
        f"/api/v1/autonomous/controls/{ctrl_id}",
        headers=auth_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True


# ============================================
# Test 16: Twin List
# ============================================
def test_list_twins(client, auth_headers):
    mock_twin = _make_mock_twin()

    import src.api.digital_twins as twin_module
    twin_module.get_twins_paginated = AsyncMock(return_value=([mock_twin], 1))

    response = client.get(
        "/api/v1/autonomous/digital-twins?page=1&per_page=10",
        headers=auth_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["data"]["total"] == 1


# ============================================
# Test 17: Simulation List
# ============================================
def test_list_simulations(client, auth_headers):
    mock_sim = _make_mock_simulation()

    import src.api.simulations as sim_module
    sim_module.get_simulations_paginated = AsyncMock(return_value=([mock_sim], 1))

    response = client.get(
        "/api/v1/autonomous/simulations?page=1&per_page=10",
        headers=auth_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["data"]["total"] == 1
