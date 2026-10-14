"""Field DXサービス テスト"""

import uuid
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from src.main import create_app
from src.middleware.auth import TokenData, get_current_user
from src.models.base import get_db


TEST_ORG = uuid.UUID("00000000-0000-0000-0000-0000000000aa")
TEST_USER = uuid.UUID("00000000-0000-0000-0000-0000000000dd")


class MockScalarResult:
    def __init__(self, value=None, items=None, total=0):
        self._value = value
        self._items = items or []
        self._total = total

    def scalar_one_or_none(self):
        return self._value

    def scalar(self):
        return self._total if self._total else self._value

    def scalars(self):
        return self

    def all(self):
        return self._items

    def first(self):
        return self._items[0] if self._items else None


def _auto_refresh(obj):
    if obj.id is None:
        obj.id = uuid.uuid4()
    if not hasattr(obj, "created_at") or obj.created_at is None:
        obj.created_at = datetime.now(timezone.utc)
    if hasattr(obj, "updated_at") and obj.updated_at is None:
        obj.updated_at = datetime.now(timezone.utc)
    if not hasattr(obj, "recorded_at") or obj.recorded_at is None:
        if hasattr(obj, "recorded_at"):
            obj.recorded_at = datetime.now(timezone.utc)
    if hasattr(obj, "status") and getattr(obj, "status", None) is None:
        cls_name = type(obj).__name__
        defaults = {
            "DailyReport": "draft",
            "ProgressRecord": "pending",
            "QualityCheck": "pending",
        }
        setattr(obj, "status", defaults.get(cls_name, "pending"))
    return obj


@pytest.fixture
def mock_db():
    db = AsyncMock()
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    db.close = AsyncMock()
    db.flush = AsyncMock()
    db.delete = AsyncMock()
    db.execute = AsyncMock(return_value=MockScalarResult())
    db.get = AsyncMock(return_value=None)

    async def mock_refresh(obj):
        _auto_refresh(obj)

    db.refresh = mock_refresh
    return db


@pytest.fixture
def app(mock_db):
    _app = create_app()

    async def mock_get_db():
        yield mock_db

    async def mock_get_current_user():
        return TokenData(sub=str(TEST_USER), type="user", org=str(TEST_ORG), roles=["site_manager"])

    _app.dependency_overrides[get_db] = mock_get_db
    _app.dependency_overrides[get_current_user] = mock_get_current_user
    return _app


@pytest.fixture
def client(app):
    return TestClient(app)


def _auth_headers():
    return {"Authorization": "Bearer test-token"}


# ============================================
# Health Check
# ============================================
class TestHealthCheck:
    def test_health_returns_200(self, client):
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["service"] == "field-dx-service"


# ============================================
# Auth Required
# ============================================
class TestAuthRequired:
    @pytest.fixture
    def app_no_auth(self):
        _app = create_app()
        return _app

    @pytest.fixture
    def client_no_auth(self, app_no_auth):
        return TestClient(app_no_auth)

    def test_create_report_requires_auth(self, client_no_auth):
        response = client_no_auth.post("/api/v1/field/reports", json={})
        assert response.status_code == 401

    def test_list_reports_requires_auth(self, client_no_auth):
        response = client_no_auth.get("/api/v1/field/reports")
        assert response.status_code == 401

    def test_create_progress_requires_auth(self, client_no_auth):
        response = client_no_auth.post("/api/v1/field/progress", json={})
        assert response.status_code == 401

    def test_create_quality_requires_auth(self, client_no_auth):
        response = client_no_auth.post("/api/v1/field/quality", json={})
        assert response.status_code == 401


# ============================================
# Daily Report CRUD + Submit/Approve
# ============================================
class TestDailyReportCRUD:
    def test_create_daily_report(self, client, mock_db):
        org_id = TEST_ORG
        project_id = uuid.uuid4()
        created_by = uuid.uuid4()

        response = client.post(
            "/api/v1/field/reports",
            json={
                "organization_id": str(org_id),
                "project_id": str(project_id),
                "report_date": "2026-05-24",
                "weather": "sunny",
                "temperature": 25.5,
                "work_description": "基礎コンクリート打設",
                "work_results": "予定通り完了",
                "worker_count": 8,
                "equipment_used": ["ポンプ車", "バイブレーター"],
                "materials_used": ["生コン 50m3"],
                "issues": "特になし",
                "next_plan": "型枠解体作業",
                "created_by": str(created_by),
            },
            headers=_auth_headers(),
        )
        assert response.status_code == 201
        assert mock_db.add.called
        called = mock_db.add.call_args[0][0]
        assert called.work_description == "基礎コンクリート打設"
        assert called.weather == "sunny"
        assert called.temperature == 25.5
        assert called.status == "draft"

    def test_list_daily_reports(self, client, mock_db):
        from src.models import DailyReport

        org_id = uuid.uuid4()
        project_id = uuid.uuid4()
        report = DailyReport(
            id=uuid.uuid4(),
            organization_id=org_id,
            project_id=project_id,
            report_date=date(2026, 5, 24),
            weather="sunny",
            temperature=25.5,
            work_description="基礎コンクリート打設",
            worker_count=8,
            status="draft",
            created_by=uuid.uuid4(),
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        mock_db.execute = AsyncMock(
            return_value=MockScalarResult(items=[report], total=1)
        )

        response = client.get(
            f"/api/v1/field/reports?project_id={project_id}",
            headers=_auth_headers(),
        )
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert len(data["items"]) == 1
        assert data["items"][0]["work_description"] == "基礎コンクリート打設"

    def test_get_daily_report(self, client, mock_db):
        from src.models import DailyReport

        report_id = uuid.uuid4()
        report = DailyReport(
            id=report_id,
            organization_id=TEST_ORG,
            project_id=uuid.uuid4(),
            report_date=date(2026, 5, 24),
            weather="sunny",
            temperature=25.5,
            work_description="基礎コンクリート打設",
            worker_count=8,
            status="draft",
            created_by=uuid.uuid4(),
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        mock_db.get = AsyncMock(return_value=report)

        response = client.get(
            f"/api/v1/field/reports/{report_id}",
            headers=_auth_headers(),
        )
        assert response.status_code == 200
        data = response.json()
        assert data["weather"] == "sunny"
        assert data["status"] == "draft"

    def test_report_not_found(self, client, mock_db):
        mock_db.get = AsyncMock(return_value=None)
        response = client.get(
            f"/api/v1/field/reports/{uuid.uuid4()}",
            headers=_auth_headers(),
        )
        assert response.status_code == 404

    def test_update_daily_report(self, client, mock_db):
        from src.models import DailyReport

        report_id = uuid.uuid4()
        report = DailyReport(
            id=report_id,
            organization_id=TEST_ORG,
            project_id=uuid.uuid4(),
            report_date=date(2026, 5, 24),
            weather="sunny",
            temperature=25.5,
            work_description="基礎コンクリート打設",
            worker_count=8,
            status="draft",
            created_by=uuid.uuid4(),
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        mock_db.get = AsyncMock(return_value=report)

        response = client.put(
            f"/api/v1/field/reports/{report_id}",
            json={"weather": "cloudy", "worker_count": 10},
            headers=_auth_headers(),
        )
        assert response.status_code == 200
        assert report.weather == "cloudy"
        assert report.worker_count == 10

    def test_submit_report(self, client, mock_db):
        from src.models import DailyReport

        report_id = uuid.uuid4()
        report = DailyReport(
            id=report_id,
            organization_id=TEST_ORG,
            project_id=uuid.uuid4(),
            report_date=date(2026, 5, 24),
            weather="sunny",
            temperature=25.5,
            work_description="基礎コンクリート打設",
            worker_count=8,
            status="draft",
            created_by=uuid.uuid4(),
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        mock_db.get = AsyncMock(return_value=report)

        response = client.post(
            f"/api/v1/field/reports/{report_id}/submit",
            headers=_auth_headers(),
        )
        assert response.status_code == 200
        assert report.status == "submitted"

    def test_submit_already_submitted_fails(self, client, mock_db):
        from src.models import DailyReport

        report_id = uuid.uuid4()
        report = DailyReport(
            id=report_id,
            organization_id=TEST_ORG,
            project_id=uuid.uuid4(),
            report_date=date(2026, 5, 24),
            weather="sunny",
            temperature=25.5,
            work_description="基礎コンクリート打設",
            worker_count=8,
            status="submitted",
            created_by=uuid.uuid4(),
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        mock_db.get = AsyncMock(return_value=report)

        response = client.post(
            f"/api/v1/field/reports/{report_id}/submit",
            headers=_auth_headers(),
        )
        assert response.status_code == 400

    def test_approve_report(self, client, mock_db):
        from src.models import DailyReport

        report_id = uuid.uuid4()
        report = DailyReport(
            id=report_id,
            organization_id=TEST_ORG,
            project_id=uuid.uuid4(),
            report_date=date(2026, 5, 24),
            weather="sunny",
            temperature=25.5,
            work_description="基礎コンクリート打設",
            worker_count=8,
            status="submitted",
            created_by=uuid.uuid4(),
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        mock_db.get = AsyncMock(return_value=report)

        response = client.post(
            f"/api/v1/field/reports/{report_id}/approve",
            headers=_auth_headers(),
        )
        assert response.status_code == 200
        assert report.status == "approved"
        assert report.approved_by == TEST_USER

    def test_approve_draft_fails(self, client, mock_db):
        from src.models import DailyReport

        report_id = uuid.uuid4()
        report = DailyReport(
            id=report_id,
            organization_id=TEST_ORG,
            project_id=uuid.uuid4(),
            report_date=date(2026, 5, 24),
            weather="sunny",
            temperature=25.5,
            work_description="基礎コンクリート打設",
            worker_count=8,
            status="draft",
            created_by=uuid.uuid4(),
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        mock_db.get = AsyncMock(return_value=report)

        response = client.post(
            f"/api/v1/field/reports/{report_id}/approve",
            headers=_auth_headers(),
        )
        assert response.status_code == 400


# ============================================
# Progress Tracking
# ============================================
class TestProgressTracking:
    def test_create_progress_record(self, client, mock_db):
        org_id = TEST_ORG
        project_id = uuid.uuid4()
        recorded_by = uuid.uuid4()

        response = client.post(
            "/api/v1/field/progress",
            json={
                "organization_id": str(org_id),
                "project_id": str(project_id),
                "activity_name": "基礎掘削工",
                "activity_code": "EXC-001",
                "planned_quantity": 500.0,
                "actual_quantity": 200.0,
                "unit": "m3",
                "planned_start": "2026-05-01",
                "planned_end": "2026-05-15",
                "actual_start": "2026-05-02",
                "progress_percent": 40.0,
                "status": "in_progress",
                "recorded_by": str(recorded_by),
            },
            headers=_auth_headers(),
        )
        assert response.status_code == 201
        called = mock_db.add.call_args[0][0]
        assert called.activity_name == "基礎掘削工"
        assert called.progress_percent == 40.0
        assert called.status == "in_progress"

    def test_list_progress_records(self, client, mock_db):
        from src.models import ProgressRecord

        org_id = uuid.uuid4()
        project_id = uuid.uuid4()
        record = ProgressRecord(
            id=uuid.uuid4(),
            organization_id=org_id,
            project_id=project_id,
            activity_name="基礎掘削工",
            planned_quantity=500.0,
            actual_quantity=200.0,
            unit="m3",
            progress_percent=40.0,
            status="in_progress",
            recorded_by=uuid.uuid4(),
            recorded_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        mock_db.execute = AsyncMock(
            return_value=MockScalarResult(items=[record], total=1)
        )

        response = client.get(
            f"/api/v1/field/progress?project_id={project_id}",
            headers=_auth_headers(),
        )
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["items"][0]["activity_name"] == "基礎掘削工"

    def test_progress_summary(self, client, mock_db):
        from src.models import ProgressRecord

        project_id = uuid.uuid4()
        org_id = uuid.uuid4()

        r1 = ProgressRecord(
            id=uuid.uuid4(),
            organization_id=org_id,
            project_id=project_id,
            activity_name="基礎掘削工",
            progress_percent=100.0,
            status="completed",
            recorded_by=uuid.uuid4(),
            recorded_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        r2 = ProgressRecord(
            id=uuid.uuid4(),
            organization_id=org_id,
            project_id=project_id,
            activity_name="型枠工",
            progress_percent=50.0,
            status="in_progress",
            recorded_by=uuid.uuid4(),
            recorded_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        r3 = ProgressRecord(
            id=uuid.uuid4(),
            organization_id=org_id,
            project_id=project_id,
            activity_name="鉄筋工",
            progress_percent=0.0,
            status="pending",
            recorded_by=uuid.uuid4(),
            recorded_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        mock_db.execute = AsyncMock(
            return_value=MockScalarResult(items=[r1, r2, r3])
        )

        response = client.get(
            f"/api/v1/field/progress/{project_id}/summary",
            headers=_auth_headers(),
        )
        assert response.status_code == 200
        data = response.json()
        assert data["total_activities"] == 3
        assert data["completed"] == 1
        assert data["in_progress"] == 1
        assert data["pending"] == 1
        assert data["overall_progress"] == 50.0


# ============================================
# Quality Check
# ============================================
class TestQualityCheck:
    def test_create_quality_check(self, client, mock_db):
        org_id = TEST_ORG
        project_id = uuid.uuid4()
        inspector_id = uuid.uuid4()

        response = client.post(
            "/api/v1/field/quality",
            json={
                "organization_id": str(org_id),
                "project_id": str(project_id),
                "check_item": "コンクリート圧縮強度試験",
                "check_type": "strength_test",
                "standard_value": "18.0 N/mm2以上",
                "measured_value": "21.5 N/mm2",
                "is_conforming": True,
                "check_date": "2026-05-24",
                "location": "3号棟基礎",
                "inspector_id": str(inspector_id),
                "status": "passed",
            },
            headers=_auth_headers(),
        )
        assert response.status_code == 201
        called = mock_db.add.call_args[0][0]
        assert called.check_item == "コンクリート圧縮強度試験"
        assert called.check_type == "strength_test"
        assert called.is_conforming is True

    def test_list_quality_checks(self, client, mock_db):
        from src.models import QualityCheck

        org_id = uuid.uuid4()
        project_id = uuid.uuid4()
        check = QualityCheck(
            id=uuid.uuid4(),
            organization_id=org_id,
            project_id=project_id,
            check_item="コンクリート圧縮強度試験",
            check_type="strength_test",
            standard_value="18.0 N/mm2以上",
            measured_value="21.5 N/mm2",
            is_conforming=True,
            check_date=date(2026, 5, 24),
            inspector_id=uuid.uuid4(),
            status="passed",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        mock_db.execute = AsyncMock(
            return_value=MockScalarResult(items=[check], total=1)
        )

        response = client.get(
            f"/api/v1/field/quality?project_id={project_id}",
            headers=_auth_headers(),
        )
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["items"][0]["check_item"] == "コンクリート圧縮強度試験"

    def test_quality_stats(self, client, mock_db):
        from src.models import QualityCheck

        project_id = uuid.uuid4()
        org_id = uuid.uuid4()

        c1 = QualityCheck(
            id=uuid.uuid4(),
            organization_id=org_id,
            project_id=project_id,
            check_item="圧縮強度",
            check_type="strength_test",
            is_conforming=True,
            check_date=date(2026, 5, 24),
            inspector_id=uuid.uuid4(),
            status="passed",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        c2 = QualityCheck(
            id=uuid.uuid4(),
            organization_id=org_id,
            project_id=project_id,
            check_item="寸法検査",
            check_type="dimension_check",
            is_conforming=False,
            check_date=date(2026, 5, 24),
            inspector_id=uuid.uuid4(),
            status="failed",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        c3 = QualityCheck(
            id=uuid.uuid4(),
            organization_id=org_id,
            project_id=project_id,
            check_item="鉄筋検査",
            check_type="reinforcement_check",
            is_conforming=True,
            check_date=date(2026, 5, 24),
            inspector_id=uuid.uuid4(),
            status="passed",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        mock_db.execute = AsyncMock(
            return_value=MockScalarResult(items=[c1, c2, c3])
        )

        response = client.get(
            f"/api/v1/field/quality/{project_id}/stats",
            headers=_auth_headers(),
        )
        assert response.status_code == 200
        data = response.json()
        assert data["total_checks"] == 3
        assert data["passed"] == 2
        assert data["failed"] == 1
        assert data["conformance_rate"] == pytest.approx(66.67, 0.1)
