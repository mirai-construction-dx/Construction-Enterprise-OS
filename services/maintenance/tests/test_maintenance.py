"""Maintenance service API tests."""

import uuid
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from src.main import create_app
from src.models.base import get_db


def _utcnow():
    return datetime.now(timezone.utc)


TEST_USER_ID = uuid.uuid4()
TEST_ORG_ID = uuid.uuid4()
TEST_DISASTER_ID = uuid.uuid4()
TEST_PLAN_ID = uuid.uuid4()
TEST_RECORD_ID = uuid.uuid4()
TEST_INSPECTION_ID = uuid.uuid4()

VALID_TOKEN_PAYLOAD = {
    "sub": str(TEST_USER_ID),
    "type": "user",
    "org": str(TEST_ORG_ID),
    "roles": ["maintenance_admin", "admin"],
    "scopes": [],
}


def _make_auth_header() -> dict:
    import base64
    import json

    payload_b64 = (
        base64.urlsafe_b64encode(json.dumps(VALID_TOKEN_PAYLOAD).encode())
        .decode()
        .rstrip("=")
    )
    header_b64 = (
        base64.urlsafe_b64encode(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
        .decode()
        .rstrip("=")
    )
    signature = "fake_signature"
    token = f"{header_b64}.{payload_b64}.{signature}"
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def app():
    _app = create_app()
    mock_db = AsyncMock()
    mock_db.execute = AsyncMock()
    mock_db.add = MagicMock()
    mock_db.commit = AsyncMock()
    mock_db.rollback = AsyncMock()
    mock_db.close = AsyncMock()
    mock_db.flush = AsyncMock()

    async def mock_get_db():
        yield mock_db

    _app.dependency_overrides[get_db] = mock_get_db
    return _app


@pytest.fixture
def client(app):
    return TestClient(app)


class MockScalarResult:
    def __init__(self, items):
        self._items = items

    def all(self):
        return self._items

    def first(self):
        return self._items[0] if self._items else None

    def scalar_one_or_none(self):
        return self._items[0] if self._items else None

    def scalar(self):
        return self._items[0] if self._items else None

    def scalars(self):
        return self


class MockDisaster:
    def __init__(self, **kwargs):
        self.id = kwargs.get("id", TEST_DISASTER_ID)
        self.organization_id = kwargs.get("organization_id", TEST_ORG_ID)
        self.project_id = kwargs.get("project_id", None)
        self.title = kwargs.get("title", "Test Disaster")
        self.disaster_type = kwargs.get("disaster_type", "earthquake")
        self.severity = kwargs.get("severity", "severe")
        self.status = kwargs.get("status", "reported")
        self.occurred_at = kwargs.get("occurred_at", _utcnow())
        self.location = kwargs.get("location", None)
        self.description = kwargs.get("description", "Disaster description")
        self.damage_assessment = kwargs.get("damage_assessment", None)
        self.estimated_cost = kwargs.get("estimated_cost", None)
        self.casualties = kwargs.get("casualties", 0)
        self.evacuation_required = kwargs.get("evacuation_required", False)
        self.reported_by = kwargs.get("reported_by", TEST_USER_ID)
        self.created_at = kwargs.get("created_at", _utcnow())
        self.updated_at = kwargs.get("updated_at", _utcnow())


class MockRecoveryPlan:
    def __init__(self, **kwargs):
        self.id = kwargs.get("id", TEST_PLAN_ID)
        self.organization_id = kwargs.get("organization_id", TEST_ORG_ID)
        self.disaster_report_id = kwargs.get("disaster_report_id", TEST_DISASTER_ID)
        self.title = kwargs.get("title", "Test Recovery Plan")
        self.description = kwargs.get("description", None)
        self.priority = kwargs.get("priority", "high")
        self.status = kwargs.get("status", "planned")
        self.estimated_duration_days = kwargs.get("estimated_duration_days", 30)
        self.estimated_cost = kwargs.get("estimated_cost", None)
        self.actual_cost = kwargs.get("actual_cost", None)
        self.start_date = kwargs.get("start_date", None)
        self.completed_date = kwargs.get("completed_date", None)
        self.contractor = kwargs.get("contractor", None)
        self.resources_needed = kwargs.get("resources_needed", None)
        self.progress_percent = kwargs.get("progress_percent", None)
        self.created_by = kwargs.get("created_by", TEST_USER_ID)
        self.created_at = kwargs.get("created_at", _utcnow())
        self.updated_at = kwargs.get("updated_at", _utcnow())


class MockMaintenanceRecord:
    def __init__(self, **kwargs):
        self.id = kwargs.get("id", TEST_RECORD_ID)
        self.organization_id = kwargs.get("organization_id", TEST_ORG_ID)
        self.project_id = kwargs.get("project_id", None)
        self.asset_name = kwargs.get("asset_name", "Bridge A")
        self.asset_type = kwargs.get("asset_type", "bridge")
        self.maintenance_type = kwargs.get("maintenance_type", "routine_inspection")
        self.status = kwargs.get("status", "scheduled")
        self.description = kwargs.get("description", "Routine bridge inspection")
        self.work_performed = kwargs.get("work_performed", None)
        self.cost = kwargs.get("cost", None)
        self.contractor = kwargs.get("contractor", None)
        self.scheduled_date = kwargs.get("scheduled_date", None)
        self.completed_date = kwargs.get("completed_date", None)
        self.next_maintenance_date = kwargs.get("next_maintenance_date", None)
        self.location = kwargs.get("location", None)
        self.performed_by = kwargs.get("performed_by", None)
        self.notes = kwargs.get("notes", None)
        self.created_at = kwargs.get("created_at", _utcnow())
        self.updated_at = kwargs.get("updated_at", _utcnow())


class MockInspectionSchedule:
    def __init__(self, **kwargs):
        self.id = kwargs.get("id", TEST_INSPECTION_ID)
        self.organization_id = kwargs.get("organization_id", TEST_ORG_ID)
        self.asset_name = kwargs.get("asset_name", "Dam Wall")
        self.asset_type = kwargs.get("asset_type", "dam")
        self.inspection_type = kwargs.get("inspection_type", "detailed")
        self.frequency = kwargs.get("frequency", "quarterly")
        self.last_inspection_date = kwargs.get("last_inspection_date", None)
        self.next_inspection_date = kwargs.get("next_inspection_date", date.today())
        self.status = kwargs.get("status", "scheduled")
        self.inspector = kwargs.get("inspector", None)
        self.checklist = kwargs.get("checklist", None)
        self.notes = kwargs.get("notes", None)
        self.created_at = kwargs.get("created_at", _utcnow())
        self.updated_at = kwargs.get("updated_at", _utcnow())


# ═══════════════════════════════════════════════
# Test 1: Health check
# ═══════════════════════════════════════════════


def test_health_check(client):
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["service"] == "maintenance-service"


# ═══════════════════════════════════════════════
# Test 2-4: Auth required
# ═══════════════════════════════════════════════


def test_disasters_require_auth(client):
    response = client.get("/api/v1/maintenance/disasters")
    assert response.status_code == 401


def test_maintenance_records_require_auth(client):
    response = client.get("/api/v1/maintenance/records")
    assert response.status_code == 401


def test_inspections_require_auth(client):
    response = client.get("/api/v1/maintenance/inspections")
    assert response.status_code == 401


# ═══════════════════════════════════════════════
# Test 5: Create disaster report
# ═══════════════════════════════════════════════


@patch("src.middleware.auth.jwt")
def test_create_disaster_success(mock_jwt, app):
    mock_jwt.decode.return_value = VALID_TOKEN_PAYLOAD

    db_mock = AsyncMock()
    db_mock.add = MagicMock()
    db_mock.flush = AsyncMock()
    db_mock.execute = AsyncMock()
    db_mock.commit = AsyncMock()
    db_mock.rollback = AsyncMock()
    db_mock.close = AsyncMock()

    async def get_mock_db():
        yield db_mock

    app.dependency_overrides[get_db] = get_mock_db

    test_date = datetime(2025, 1, 15, 14, 30, 0, tzinfo=timezone.utc)
    client = TestClient(app)
    response = client.post(
        "/api/v1/maintenance/disasters",
        json={
            "organization_id": str(TEST_ORG_ID),
            "title": "Earthquake damage at site C",
            "disaster_type": "earthquake",
            "severity": "severe",
            "occurred_at": test_date.isoformat(),
            "description": "Magnitude 7.1 earthquake caused structural damage",
            "casualties": 5,
            "evacuation_required": True,
            "reported_by": str(TEST_USER_ID),
        },
        headers=_make_auth_header(),
    )
    assert response.status_code == 201
    data = response.json()
    assert data["data"]["title"] == "Earthquake damage at site C"
    assert data["data"]["disaster_type"] == "earthquake"
    assert data["data"]["severity"] == "severe"
    assert data["data"]["casualties"] == 5
    assert data["data"]["evacuation_required"] is True


# ═══════════════════════════════════════════════
# Test 6: List disasters with filters
# ═══════════════════════════════════════════════


@patch("src.middleware.auth.jwt")
def test_list_disasters(mock_jwt, app):
    mock_jwt.decode.return_value = VALID_TOKEN_PAYLOAD

    dr1 = MockDisaster(
        id=uuid.uuid4(),
        title="Flood damage",
        disaster_type="flood",
        severity="moderate",
    )
    dr2 = MockDisaster(
        id=uuid.uuid4(), title="Landslide", disaster_type="landslide", severity="severe"
    )

    db_mock = AsyncMock()
    db_mock.execute = AsyncMock(return_value=MockScalarResult([dr1, dr2]))
    db_mock.commit = AsyncMock()
    db_mock.rollback = AsyncMock()
    db_mock.close = AsyncMock()

    async def get_mock_db():
        yield db_mock

    app.dependency_overrides[get_db] = get_mock_db

    client = TestClient(app)
    response = client.get(
        "/api/v1/maintenance/disasters?disaster_type=flood",
        headers=_make_auth_header(),
    )
    assert response.status_code == 200
    assert len(response.json()["data"]) == 2


# ═══════════════════════════════════════════════
# Test 7: Get disaster with recovery plans
# ═══════════════════════════════════════════════


@patch("src.middleware.auth.jwt")
def test_get_disaster_with_plans(mock_jwt, app):
    mock_jwt.decode.return_value = VALID_TOKEN_PAYLOAD

    disaster = MockDisaster(id=TEST_DISASTER_ID, title="Bridge collapse")
    plan = MockRecoveryPlan(id=uuid.uuid4(), title="Rebuild Bridge")

    db_mock = AsyncMock()
    db_mock.execute = AsyncMock(return_value=MockScalarResult([plan]))
    db_mock.commit = AsyncMock()
    db_mock.rollback = AsyncMock()
    db_mock.close = AsyncMock()

    async def get_mock_db():
        yield db_mock

    app.dependency_overrides[get_db] = get_mock_db

    # Override the execute to return disaster first for get_by_id, then plans
    call_count = 0

    async def mock_execute(stmt):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return MockScalarResult([disaster])
        return MockScalarResult([plan])

    db_mock.execute = mock_execute

    client = TestClient(app)
    response = client.get(
        f"/api/v1/maintenance/disasters/{TEST_DISASTER_ID}",
        headers=_make_auth_header(),
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["data"]["report"]["title"] == "Bridge collapse"
    assert len(payload["data"]["recovery_plans"]) == 1
    assert payload["data"]["recovery_plans"][0]["title"] == "Rebuild Bridge"


# ═══════════════════════════════════════════════
# Test 8: Update disaster assessment
# ═══════════════════════════════════════════════


@patch("src.middleware.auth.jwt")
def test_update_disaster_assessment(mock_jwt, app):
    mock_jwt.decode.return_value = VALID_TOKEN_PAYLOAD

    disaster = MockDisaster(id=TEST_DISASTER_ID, status="reported")

    db_mock = AsyncMock()
    db_mock.add = MagicMock()
    db_mock.flush = AsyncMock()
    db_mock.execute = AsyncMock(return_value=MockScalarResult([disaster]))
    db_mock.commit = AsyncMock()
    db_mock.rollback = AsyncMock()
    db_mock.close = AsyncMock()

    async def get_mock_db():
        yield db_mock

    app.dependency_overrides[get_db] = get_mock_db

    client = TestClient(app)
    response = client.put(
        f"/api/v1/maintenance/disasters/{TEST_DISASTER_ID}",
        json={
            "status": "assessing",
            "damage_assessment": "Significant structural damage to east wing",
            "severity": "catastrophic",
        },
        headers=_make_auth_header(),
    )
    assert response.status_code == 200
    assert disaster.status == "assessing"
    assert "east wing" in disaster.damage_assessment
    assert disaster.severity == "catastrophic"


# ═══════════════════════════════════════════════
# Test 9: Create recovery plan
# ═══════════════════════════════════════════════


@patch("src.middleware.auth.jwt")
def test_create_recovery_plan(mock_jwt, app):
    mock_jwt.decode.return_value = VALID_TOKEN_PAYLOAD

    disaster = MockDisaster(id=TEST_DISASTER_ID, title="Landslide damage")

    db_mock = AsyncMock()
    db_mock.add = MagicMock()
    db_mock.flush = AsyncMock()
    db_mock.execute = AsyncMock(return_value=MockScalarResult([disaster]))
    db_mock.commit = AsyncMock()
    db_mock.rollback = AsyncMock()
    db_mock.close = AsyncMock()

    async def get_mock_db():
        yield db_mock

    app.dependency_overrides[get_db] = get_mock_db

    client = TestClient(app)
    response = client.post(
        f"/api/v1/maintenance/disasters/{TEST_DISASTER_ID}/recovery-plans",
        json={
            "organization_id": str(TEST_ORG_ID),
            "title": "Slope stabilization plan",
            "description": "Install retaining walls and drainage",
            "priority": "critical",
            "estimated_duration_days": 45,
            "estimated_cost": "500000.00",
            "contractor": "ABC Construction",
            "created_by": str(TEST_USER_ID),
        },
        headers=_make_auth_header(),
    )
    assert response.status_code == 201
    data = response.json()
    assert data["data"]["title"] == "Slope stabilization plan"
    assert data["data"]["priority"] == "critical"
    assert data["data"]["status"] == "planned"


# ═══════════════════════════════════════════════
# Test 10: Update recovery plan progress
# ═══════════════════════════════════════════════


@patch("src.middleware.auth.jwt")
def test_update_recovery_plan_progress(mock_jwt, app):
    mock_jwt.decode.return_value = VALID_TOKEN_PAYLOAD

    plan = MockRecoveryPlan(id=TEST_PLAN_ID, status="mobilized", progress_percent=None)

    db_mock = AsyncMock()
    db_mock.add = MagicMock()
    db_mock.flush = AsyncMock()
    db_mock.execute = AsyncMock(return_value=MockScalarResult([plan]))
    db_mock.commit = AsyncMock()
    db_mock.rollback = AsyncMock()
    db_mock.close = AsyncMock()

    async def get_mock_db():
        yield db_mock

    app.dependency_overrides[get_db] = get_mock_db

    client = TestClient(app)
    response = client.put(
        f"/api/v1/maintenance/recovery-plans/{TEST_PLAN_ID}",
        json={
            "status": "in_progress",
            "progress_percent": "45.50",
        },
        headers=_make_auth_header(),
    )
    assert response.status_code == 200
    assert plan.status == "in_progress"


# ═══════════════════════════════════════════════
# Test 11: Create maintenance record
# ═══════════════════════════════════════════════


@patch("src.middleware.auth.jwt")
def test_create_maintenance_record(mock_jwt, app):
    mock_jwt.decode.return_value = VALID_TOKEN_PAYLOAD

    db_mock = AsyncMock()
    db_mock.add = MagicMock()
    db_mock.flush = AsyncMock()
    db_mock.execute = AsyncMock()
    db_mock.commit = AsyncMock()
    db_mock.rollback = AsyncMock()
    db_mock.close = AsyncMock()

    async def get_mock_db():
        yield db_mock

    app.dependency_overrides[get_db] = get_mock_db

    test_date = date(2025, 6, 1)
    client = TestClient(app)
    response = client.post(
        "/api/v1/maintenance/records",
        json={
            "organization_id": str(TEST_ORG_ID),
            "asset_name": "Highway Bridge #4",
            "asset_type": "bridge",
            "maintenance_type": "preventive",
            "description": "Preventive maintenance on bridge bearings",
            "cost": "250000.00",
            "contractor": "XYZ Infra",
            "scheduled_date": test_date.isoformat(),
            "location": "Route 50, KM 120",
            "notes": "Annual preventive check",
        },
        headers=_make_auth_header(),
    )
    assert response.status_code == 201
    data = response.json()
    assert data["data"]["asset_name"] == "Highway Bridge #4"
    assert data["data"]["asset_type"] == "bridge"
    assert data["data"]["maintenance_type"] == "preventive"
    assert data["data"]["status"] == "scheduled"


# ═══════════════════════════════════════════════
# Test 12: Complete maintenance record
# ═══════════════════════════════════════════════


@patch("src.middleware.auth.jwt")
def test_complete_maintenance_record(mock_jwt, app):
    mock_jwt.decode.return_value = VALID_TOKEN_PAYLOAD

    record = MockMaintenanceRecord(id=TEST_RECORD_ID, status="in_progress")

    db_mock = AsyncMock()
    db_mock.add = MagicMock()
    db_mock.flush = AsyncMock()
    db_mock.execute = AsyncMock(return_value=MockScalarResult([record]))
    db_mock.commit = AsyncMock()
    db_mock.rollback = AsyncMock()
    db_mock.close = AsyncMock()

    async def get_mock_db():
        yield db_mock

    app.dependency_overrides[get_db] = get_mock_db

    client = TestClient(app)
    response = client.put(
        f"/api/v1/maintenance/records/{TEST_RECORD_ID}",
        json={
            "status": "completed",
            "work_performed": "Replaced bridge bearings, sealed joints",
            "cost": "275000.00",
            "performed_by": str(TEST_USER_ID),
        },
        headers=_make_auth_header(),
    )
    assert response.status_code == 200
    assert record.status == "completed"
    assert "bridge bearings" in record.work_performed


# ═══════════════════════════════════════════════
# Test 13: List overdue maintenance records
# ═══════════════════════════════════════════════


@patch("src.middleware.auth.jwt")
def test_list_overdue_maintenance(mock_jwt, app):
    mock_jwt.decode.return_value = VALID_TOKEN_PAYLOAD

    rec1 = MockMaintenanceRecord(
        id=uuid.uuid4(), asset_name="Overdue Bridge", status="scheduled"
    )
    rec2 = MockMaintenanceRecord(
        id=uuid.uuid4(), asset_name="Overdue Road", status="scheduled"
    )

    db_mock = AsyncMock()
    db_mock.execute = AsyncMock(return_value=MockScalarResult([rec1, rec2]))
    db_mock.commit = AsyncMock()
    db_mock.rollback = AsyncMock()
    db_mock.close = AsyncMock()

    async def get_mock_db():
        yield db_mock

    app.dependency_overrides[get_db] = get_mock_db

    client = TestClient(app)
    response = client.get(
        "/api/v1/maintenance/records/overdue",
        headers=_make_auth_header(),
    )
    assert response.status_code == 200
    assert len(response.json()["data"]) == 2


# ═══════════════════════════════════════════════
# Test 14: Schedule inspection
# ═══════════════════════════════════════════════


@patch("src.middleware.auth.jwt")
def test_create_inspection_schedule(mock_jwt, app):
    mock_jwt.decode.return_value = VALID_TOKEN_PAYLOAD

    db_mock = AsyncMock()
    db_mock.add = MagicMock()
    db_mock.flush = AsyncMock()
    db_mock.execute = AsyncMock()
    db_mock.commit = AsyncMock()
    db_mock.rollback = AsyncMock()
    db_mock.close = AsyncMock()

    async def get_mock_db():
        yield db_mock

    app.dependency_overrides[get_db] = get_mock_db

    test_date = date(2025, 12, 1)
    client = TestClient(app)
    response = client.post(
        "/api/v1/maintenance/inspections",
        json={
            "organization_id": str(TEST_ORG_ID),
            "asset_name": "River Dam #2",
            "asset_type": "dam",
            "inspection_type": "detailed",
            "frequency": "yearly",
            "next_inspection_date": test_date.isoformat(),
            "inspector": "John Inspector",
            "notes": "Annual structural integrity check",
        },
        headers=_make_auth_header(),
    )
    assert response.status_code == 201
    data = response.json()
    assert data["data"]["asset_name"] == "River Dam #2"
    assert data["data"]["inspection_type"] == "detailed"
    assert data["data"]["frequency"] == "yearly"
    assert data["data"]["status"] == "scheduled"


# ═══════════════════════════════════════════════
# Test 15: Complete inspection with checklist
# ═══════════════════════════════════════════════


@patch("src.middleware.auth.jwt")
def test_complete_inspection_with_checklist(mock_jwt, app):
    mock_jwt.decode.return_value = VALID_TOKEN_PAYLOAD

    inspection = MockInspectionSchedule(id=TEST_INSPECTION_ID, status="scheduled")

    db_mock = AsyncMock()
    db_mock.add = MagicMock()
    db_mock.flush = AsyncMock()
    db_mock.execute = AsyncMock(return_value=MockScalarResult([inspection]))
    db_mock.commit = AsyncMock()
    db_mock.rollback = AsyncMock()
    db_mock.close = AsyncMock()

    async def get_mock_db():
        yield db_mock

    app.dependency_overrides[get_db] = get_mock_db

    checklist = [
        {"item": "Structural integrity", "pass": True, "note": "No cracks found"},
        {"item": "Water seals", "pass": True, "note": "All seals intact"},
        {"item": "Spillway gates", "pass": False, "note": "Minor rust on gate 3"},
    ]

    client = TestClient(app)
    response = client.put(
        f"/api/v1/maintenance/inspections/{TEST_INSPECTION_ID}",
        json={
            "status": "completed",
            "checklist": checklist,
            "notes": "Overall good condition. Schedule repair for gate 3.",
        },
        headers=_make_auth_header(),
    )
    assert response.status_code == 200
    assert inspection.status == "completed"
    assert inspection.last_inspection_date is not None


# ═══════════════════════════════════════════════
# Test 16: Get upcoming inspections
# ═══════════════════════════════════════════════


@patch("src.middleware.auth.jwt")
def test_get_upcoming_inspections(mock_jwt, app):
    mock_jwt.decode.return_value = VALID_TOKEN_PAYLOAD

    insp1 = MockInspectionSchedule(
        id=uuid.uuid4(), asset_name="Bridge X", status="scheduled"
    )
    insp2 = MockInspectionSchedule(
        id=uuid.uuid4(), asset_name="Tunnel Y", status="scheduled"
    )

    db_mock = AsyncMock()
    db_mock.execute = AsyncMock(return_value=MockScalarResult([insp1, insp2]))
    db_mock.commit = AsyncMock()
    db_mock.rollback = AsyncMock()
    db_mock.close = AsyncMock()

    async def get_mock_db():
        yield db_mock

    app.dependency_overrides[get_db] = get_mock_db

    client = TestClient(app)
    response = client.get(
        "/api/v1/maintenance/inspections/upcoming",
        headers=_make_auth_header(),
    )
    assert response.status_code == 200
    assert len(response.json()["data"]) == 2


# ═══════════════════════════════════════════════
# Test 17: Get overdue inspections
# ═══════════════════════════════════════════════


@patch("src.middleware.auth.jwt")
def test_get_overdue_inspections(mock_jwt, app):
    mock_jwt.decode.return_value = VALID_TOKEN_PAYLOAD

    insp1 = MockInspectionSchedule(
        id=uuid.uuid4(), asset_name="Overdue Dam", status="scheduled"
    )

    db_mock = AsyncMock()
    db_mock.execute = AsyncMock(return_value=MockScalarResult([insp1]))
    db_mock.commit = AsyncMock()
    db_mock.rollback = AsyncMock()
    db_mock.close = AsyncMock()

    async def get_mock_db():
        yield db_mock

    app.dependency_overrides[get_db] = get_mock_db

    client = TestClient(app)
    response = client.get(
        "/api/v1/maintenance/inspections/overdue",
        headers=_make_auth_header(),
    )
    assert response.status_code == 200
    assert len(response.json()["data"]) == 1


# ═══════════════════════════════════════════════
# Test 18: Not found - disaster
# ═══════════════════════════════════════════════


@patch("src.middleware.auth.jwt")
def test_disaster_not_found(mock_jwt, app):
    mock_jwt.decode.return_value = VALID_TOKEN_PAYLOAD

    db_mock = AsyncMock()
    db_mock.execute = AsyncMock(return_value=MockScalarResult([]))
    db_mock.commit = AsyncMock()
    db_mock.rollback = AsyncMock()
    db_mock.close = AsyncMock()

    async def get_mock_db():
        yield db_mock

    app.dependency_overrides[get_db] = get_mock_db

    client = TestClient(app)
    response = client.get(
        f"/api/v1/maintenance/disasters/{TEST_DISASTER_ID}",
        headers=_make_auth_header(),
    )
    assert response.status_code == 404


# ═══════════════════════════════════════════════
# Test 19: Update disaster - not found
# ═══════════════════════════════════════════════


@patch("src.middleware.auth.jwt")
def test_update_disaster_not_found(mock_jwt, app):
    mock_jwt.decode.return_value = VALID_TOKEN_PAYLOAD

    db_mock = AsyncMock()
    db_mock.execute = AsyncMock(return_value=MockScalarResult([]))
    db_mock.commit = AsyncMock()
    db_mock.rollback = AsyncMock()
    db_mock.close = AsyncMock()

    async def get_mock_db():
        yield db_mock

    app.dependency_overrides[get_db] = get_mock_db

    client = TestClient(app)
    response = client.put(
        f"/api/v1/maintenance/disasters/{TEST_DISASTER_ID}",
        json={"status": "contained"},
        headers=_make_auth_header(),
    )
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "NOT_FOUND"


# ═══════════════════════════════════════════════
# Test 20: List maintenance records
# ═══════════════════════════════════════════════


@patch("src.middleware.auth.jwt")
def test_list_maintenance_records(mock_jwt, app):
    mock_jwt.decode.return_value = VALID_TOKEN_PAYLOAD

    rec1 = MockMaintenanceRecord(
        id=uuid.uuid4(), asset_name="Bridge B", asset_type="bridge"
    )
    rec2 = MockMaintenanceRecord(
        id=uuid.uuid4(), asset_name="Road C", asset_type="road"
    )

    db_mock = AsyncMock()
    db_mock.execute = AsyncMock(return_value=MockScalarResult([rec1, rec2]))
    db_mock.commit = AsyncMock()
    db_mock.rollback = AsyncMock()
    db_mock.close = AsyncMock()

    async def get_mock_db():
        yield db_mock

    app.dependency_overrides[get_db] = get_mock_db

    client = TestClient(app)
    response = client.get(
        "/api/v1/maintenance/records?asset_type=bridge",
        headers=_make_auth_header(),
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert len(data) == 2
    assert data[0]["asset_name"] == "Bridge B"


# ═══════════════════════════════════════════════
# Test 21: Get maintenance record by ID
# ═══════════════════════════════════════════════


@patch("src.middleware.auth.jwt")
def test_get_maintenance_record(mock_jwt, app):
    mock_jwt.decode.return_value = VALID_TOKEN_PAYLOAD

    record = MockMaintenanceRecord(id=TEST_RECORD_ID, asset_name="Bridge A")

    db_mock = AsyncMock()
    db_mock.execute = AsyncMock(return_value=MockScalarResult([record]))
    db_mock.commit = AsyncMock()
    db_mock.rollback = AsyncMock()
    db_mock.close = AsyncMock()

    async def get_mock_db():
        yield db_mock

    app.dependency_overrides[get_db] = get_mock_db

    client = TestClient(app)
    response = client.get(
        f"/api/v1/maintenance/records/{TEST_RECORD_ID}",
        headers=_make_auth_header(),
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["id"] == str(TEST_RECORD_ID)
    assert data["asset_name"] == "Bridge A"


# ═══════════════════════════════════════════════
# Test 22: Get maintenance record - not found
# ═══════════════════════════════════════════════


@patch("src.middleware.auth.jwt")
def test_get_maintenance_record_not_found(mock_jwt, app):
    mock_jwt.decode.return_value = VALID_TOKEN_PAYLOAD

    db_mock = AsyncMock()
    db_mock.execute = AsyncMock(return_value=MockScalarResult([]))
    db_mock.commit = AsyncMock()
    db_mock.rollback = AsyncMock()
    db_mock.close = AsyncMock()

    async def get_mock_db():
        yield db_mock

    app.dependency_overrides[get_db] = get_mock_db

    client = TestClient(app)
    response = client.get(
        f"/api/v1/maintenance/records/{TEST_RECORD_ID}",
        headers=_make_auth_header(),
    )
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "NOT_FOUND"


# ═══════════════════════════════════════════════
# Test 23: Update maintenance record - not found
# ═══════════════════════════════════════════════


@patch("src.middleware.auth.jwt")
def test_update_maintenance_record_not_found(mock_jwt, app):
    mock_jwt.decode.return_value = VALID_TOKEN_PAYLOAD

    db_mock = AsyncMock()
    db_mock.execute = AsyncMock(return_value=MockScalarResult([]))
    db_mock.commit = AsyncMock()
    db_mock.rollback = AsyncMock()
    db_mock.close = AsyncMock()

    async def get_mock_db():
        yield db_mock

    app.dependency_overrides[get_db] = get_mock_db

    client = TestClient(app)
    response = client.put(
        f"/api/v1/maintenance/records/{TEST_RECORD_ID}",
        json={"status": "completed"},
        headers=_make_auth_header(),
    )
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "NOT_FOUND"


# ═══════════════════════════════════════════════
# Test 24: Get recovery plan by ID
# ═══════════════════════════════════════════════


@patch("src.middleware.auth.jwt")
def test_get_recovery_plan(mock_jwt, app):
    mock_jwt.decode.return_value = VALID_TOKEN_PAYLOAD

    plan = MockRecoveryPlan(id=TEST_PLAN_ID, title="Road Repair Plan")

    db_mock = AsyncMock()
    db_mock.execute = AsyncMock(return_value=MockScalarResult([plan]))
    db_mock.commit = AsyncMock()
    db_mock.rollback = AsyncMock()
    db_mock.close = AsyncMock()

    async def get_mock_db():
        yield db_mock

    app.dependency_overrides[get_db] = get_mock_db

    client = TestClient(app)
    response = client.get(
        f"/api/v1/maintenance/recovery-plans/{TEST_PLAN_ID}",
        headers=_make_auth_header(),
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["id"] == str(TEST_PLAN_ID)
    assert data["title"] == "Road Repair Plan"


# ═══════════════════════════════════════════════
# Test 25: Get recovery plan - not found
# ═══════════════════════════════════════════════


@patch("src.middleware.auth.jwt")
def test_get_recovery_plan_not_found(mock_jwt, app):
    mock_jwt.decode.return_value = VALID_TOKEN_PAYLOAD

    db_mock = AsyncMock()
    db_mock.execute = AsyncMock(return_value=MockScalarResult([]))
    db_mock.commit = AsyncMock()
    db_mock.rollback = AsyncMock()
    db_mock.close = AsyncMock()

    async def get_mock_db():
        yield db_mock

    app.dependency_overrides[get_db] = get_mock_db

    client = TestClient(app)
    response = client.get(
        f"/api/v1/maintenance/recovery-plans/{TEST_PLAN_ID}",
        headers=_make_auth_header(),
    )
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "NOT_FOUND"


# ═══════════════════════════════════════════════
# Test 26: Update recovery plan - not found
# ═══════════════════════════════════════════════


@patch("src.middleware.auth.jwt")
def test_update_recovery_plan_not_found(mock_jwt, app):
    mock_jwt.decode.return_value = VALID_TOKEN_PAYLOAD

    db_mock = AsyncMock()
    db_mock.execute = AsyncMock(return_value=MockScalarResult([]))
    db_mock.commit = AsyncMock()
    db_mock.rollback = AsyncMock()
    db_mock.close = AsyncMock()

    async def get_mock_db():
        yield db_mock

    app.dependency_overrides[get_db] = get_mock_db

    client = TestClient(app)
    response = client.put(
        f"/api/v1/maintenance/recovery-plans/{TEST_PLAN_ID}",
        json={"status": "in_progress", "progress_percent": "50.00"},
        headers=_make_auth_header(),
    )
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "NOT_FOUND"


# ═══════════════════════════════════════════════
# Test 27: List inspection schedules
# ═══════════════════════════════════════════════


@patch("src.middleware.auth.jwt")
def test_list_inspections(mock_jwt, app):
    mock_jwt.decode.return_value = VALID_TOKEN_PAYLOAD

    insp1 = MockInspectionSchedule(
        id=uuid.uuid4(), asset_name="Dam A", status="scheduled"
    )
    insp2 = MockInspectionSchedule(
        id=uuid.uuid4(), asset_name="Bridge B", status="scheduled"
    )

    db_mock = AsyncMock()
    db_mock.execute = AsyncMock(return_value=MockScalarResult([insp1, insp2]))
    db_mock.commit = AsyncMock()
    db_mock.rollback = AsyncMock()
    db_mock.close = AsyncMock()

    async def get_mock_db():
        yield db_mock

    app.dependency_overrides[get_db] = get_mock_db

    client = TestClient(app)
    response = client.get(
        "/api/v1/maintenance/inspections?status=scheduled",
        headers=_make_auth_header(),
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert len(data) == 2
    assert data[0]["asset_name"] == "Dam A"


# ═══════════════════════════════════════════════
# Test 28: Get inspection by ID
# ═══════════════════════════════════════════════


@patch("src.middleware.auth.jwt")
def test_get_inspection(mock_jwt, app):
    mock_jwt.decode.return_value = VALID_TOKEN_PAYLOAD

    inspection = MockInspectionSchedule(id=TEST_INSPECTION_ID, asset_name="Dam Wall")

    db_mock = AsyncMock()
    db_mock.execute = AsyncMock(return_value=MockScalarResult([inspection]))
    db_mock.commit = AsyncMock()
    db_mock.rollback = AsyncMock()
    db_mock.close = AsyncMock()

    async def get_mock_db():
        yield db_mock

    app.dependency_overrides[get_db] = get_mock_db

    client = TestClient(app)
    response = client.get(
        f"/api/v1/maintenance/inspections/{TEST_INSPECTION_ID}",
        headers=_make_auth_header(),
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["id"] == str(TEST_INSPECTION_ID)
    assert data["asset_name"] == "Dam Wall"


# ═══════════════════════════════════════════════
# Test 29: Get inspection - not found
# ═══════════════════════════════════════════════


@patch("src.middleware.auth.jwt")
def test_get_inspection_not_found(mock_jwt, app):
    mock_jwt.decode.return_value = VALID_TOKEN_PAYLOAD

    db_mock = AsyncMock()
    db_mock.execute = AsyncMock(return_value=MockScalarResult([]))
    db_mock.commit = AsyncMock()
    db_mock.rollback = AsyncMock()
    db_mock.close = AsyncMock()

    async def get_mock_db():
        yield db_mock

    app.dependency_overrides[get_db] = get_mock_db

    client = TestClient(app)
    response = client.get(
        f"/api/v1/maintenance/inspections/{TEST_INSPECTION_ID}",
        headers=_make_auth_header(),
    )
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "NOT_FOUND"


# ═══════════════════════════════════════════════
# Test 30: Update inspection - not found
# ═══════════════════════════════════════════════


@patch("src.middleware.auth.jwt")
def test_update_inspection_not_found(mock_jwt, app):
    mock_jwt.decode.return_value = VALID_TOKEN_PAYLOAD

    db_mock = AsyncMock()
    db_mock.execute = AsyncMock(return_value=MockScalarResult([]))
    db_mock.commit = AsyncMock()
    db_mock.rollback = AsyncMock()
    db_mock.close = AsyncMock()

    async def get_mock_db():
        yield db_mock

    app.dependency_overrides[get_db] = get_mock_db

    client = TestClient(app)
    response = client.put(
        f"/api/v1/maintenance/inspections/{TEST_INSPECTION_ID}",
        json={"status": "completed", "notes": "All checks passed"},
        headers=_make_auth_header(),
    )
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "NOT_FOUND"


# ═══════════════════════════════════════════════
# Issue #139: 作成者の偽装防止・状態遷移の検証
# ═══════════════════════════════════════════════


def _hardening_db(items=None):
    db_mock = AsyncMock()
    db_mock.add = MagicMock()
    db_mock.flush = AsyncMock()
    db_mock.execute = AsyncMock(return_value=MockScalarResult(items or []))
    db_mock.commit = AsyncMock()
    db_mock.rollback = AsyncMock()
    db_mock.close = AsyncMock()
    return db_mock


def _use_db(app, db_mock):
    async def get_mock_db():
        yield db_mock

    app.dependency_overrides[get_db] = get_mock_db


@patch("src.middleware.auth.jwt")
def test_create_disaster_uses_token_sub_for_reported_by(mock_jwt, app):
    """#139: 本文の reported_by ではなくトークンの sub を作成者に使う。"""
    mock_jwt.decode.return_value = VALID_TOKEN_PAYLOAD
    spoofed = uuid.uuid4()
    db_mock = _hardening_db()
    _use_db(app, db_mock)
    client = TestClient(app)

    response = client.post(
        "/api/v1/maintenance/disasters",
        json={
            "organization_id": str(TEST_ORG_ID),
            "title": "偽装テスト",
            "disaster_type": "earthquake",
            "severity": "severe",
            "occurred_at": datetime(2025, 1, 15, tzinfo=timezone.utc).isoformat(),
            "description": "偽装された reported_by は無視される",
            "reported_by": str(spoofed),
        },
        headers=_make_auth_header(),
    )

    assert response.status_code == 201
    created = db_mock.add.call_args[0][0]
    assert created.reported_by == TEST_USER_ID
    assert response.json()["data"]["reported_by"] == str(TEST_USER_ID)


@patch("src.middleware.auth.jwt")
def test_create_recovery_plan_uses_token_sub_for_created_by(mock_jwt, app):
    """#139: 本文の created_by ではなくトークンの sub を作成者に使う。"""
    mock_jwt.decode.return_value = VALID_TOKEN_PAYLOAD
    spoofed = uuid.uuid4()
    disaster = MockDisaster(id=TEST_DISASTER_ID)
    db_mock = _hardening_db([disaster])
    _use_db(app, db_mock)
    client = TestClient(app)

    response = client.post(
        f"/api/v1/maintenance/disasters/{TEST_DISASTER_ID}/recovery-plans",
        json={
            "organization_id": str(TEST_ORG_ID),
            "title": "偽装された復旧計画",
            "created_by": str(spoofed),
        },
        headers=_make_auth_header(),
    )

    assert response.status_code == 201
    created = db_mock.add.call_args[0][0]
    assert created.created_by == TEST_USER_ID
    assert response.json()["data"]["created_by"] == str(TEST_USER_ID)


@patch("src.middleware.auth.jwt")
def test_create_maintenance_record_uses_token_sub_for_performed_by(mock_jwt, app):
    """#139: 本文の performed_by ではなくトークンの sub を作業者に使う。"""
    mock_jwt.decode.return_value = VALID_TOKEN_PAYLOAD
    spoofed = uuid.uuid4()
    db_mock = _hardening_db()
    _use_db(app, db_mock)
    client = TestClient(app)

    response = client.post(
        "/api/v1/maintenance/records",
        json={
            "organization_id": str(TEST_ORG_ID),
            "asset_name": "Bridge #1",
            "asset_type": "bridge",
            "maintenance_type": "preventive",
            "description": "点検",
            "performed_by": str(spoofed),
        },
        headers=_make_auth_header(),
    )

    assert response.status_code == 201
    created = db_mock.add.call_args[0][0]
    assert created.performed_by == TEST_USER_ID
    assert response.json()["data"]["performed_by"] == str(TEST_USER_ID)


@patch("src.middleware.auth.jwt")
def test_update_maintenance_record_uses_token_sub_for_performed_by(mock_jwt, app):
    """#139: PUT 本文の performed_by も無視し、更新したユーザーを記録する。"""
    mock_jwt.decode.return_value = VALID_TOKEN_PAYLOAD
    spoofed = uuid.uuid4()
    record = MockMaintenanceRecord(id=TEST_RECORD_ID, status="scheduled")
    db_mock = _hardening_db([record])
    _use_db(app, db_mock)
    client = TestClient(app)

    response = client.put(
        f"/api/v1/maintenance/records/{TEST_RECORD_ID}",
        json={"performed_by": str(spoofed)},
        headers=_make_auth_header(),
    )

    assert response.status_code == 200
    assert record.performed_by == TEST_USER_ID


@patch("src.middleware.auth.jwt")
def test_update_maintenance_record_rejects_backward_status_transition(mock_jwt, app):
    """#139: 完了済み記録を PUT で差し戻せない。"""
    mock_jwt.decode.return_value = VALID_TOKEN_PAYLOAD
    record = MockMaintenanceRecord(id=TEST_RECORD_ID, status="completed")
    db_mock = _hardening_db([record])
    _use_db(app, db_mock)
    client = TestClient(app)

    response = client.put(
        f"/api/v1/maintenance/records/{TEST_RECORD_ID}",
        json={"status": "scheduled"},
        headers=_make_auth_header(),
    )

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "INVALID_STATUS_TRANSITION"
    assert record.status == "completed"


@patch("src.middleware.auth.jwt")
def test_update_disaster_rejects_backward_status_transition(mock_jwt, app):
    """#139: 解決済みの災害報告を PUT で差し戻せない。"""
    mock_jwt.decode.return_value = VALID_TOKEN_PAYLOAD
    disaster = MockDisaster(id=TEST_DISASTER_ID, status="resolved")
    db_mock = _hardening_db([disaster])
    _use_db(app, db_mock)
    client = TestClient(app)

    response = client.put(
        f"/api/v1/maintenance/disasters/{TEST_DISASTER_ID}",
        json={"status": "assessing"},
        headers=_make_auth_header(),
    )

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "INVALID_STATUS_TRANSITION"
    assert disaster.status == "resolved"


@patch("src.middleware.auth.jwt")
def test_update_recovery_plan_rejects_backward_status_transition(mock_jwt, app):
    """#139: 完了済み復旧計画を PUT で差し戻せない。"""
    mock_jwt.decode.return_value = VALID_TOKEN_PAYLOAD
    plan = MockRecoveryPlan(id=TEST_PLAN_ID, status="completed")
    db_mock = _hardening_db([plan])
    _use_db(app, db_mock)
    client = TestClient(app)

    response = client.put(
        f"/api/v1/maintenance/recovery-plans/{TEST_PLAN_ID}",
        json={"status": "in_progress"},
        headers=_make_auth_header(),
    )

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "INVALID_STATUS_TRANSITION"
    assert plan.status == "completed"
