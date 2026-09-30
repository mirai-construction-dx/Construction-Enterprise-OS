"""Constructionサービス テスト"""

import uuid
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from src.main import create_app
from src.middleware.auth import TokenData, get_current_user
from src.models.base import get_db

ORG_ID = uuid.UUID("00000000-0000-0000-0000-0000000000aa")


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
    if hasattr(obj, "status") and getattr(obj, "status", None) is None:
        cls_name = type(obj).__name__
        defaults = {
            "WBSItem": "pending",
            "Resource": "planned",
            "Schedule": "planned",
            "MethodStatement": "draft",
        }
        setattr(obj, "status", defaults.get(cls_name, "active"))
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
        return TokenData(
            sub="test-user-id", type="user", org=str(ORG_ID), roles=["admin"]
        )

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
        assert data["service"] == "construction-service"


# ============================================
# Auth Required
# ============================================
class TestAuthRequired:
    @pytest.fixture
    def app_no_auth(self):
        return create_app()

    @pytest.fixture
    def client_no_auth(self, app_no_auth):
        return TestClient(app_no_auth)

    def test_create_wbs_requires_auth(self, client_no_auth):
        response = client_no_auth.post("/api/v1/construction/wbs", json={})
        assert response.status_code == 401

    def test_list_wbs_requires_auth(self, client_no_auth):
        response = client_no_auth.get("/api/v1/construction/wbs")
        assert response.status_code == 401


# ============================================
# WBS CRUD + Tree
# ============================================
class TestWBSCRUD:
    def test_create_wbs(self, client, mock_db):
        org_id = uuid.uuid4()
        project_id = uuid.uuid4()

        response = client.post(
            "/api/v1/construction/wbs",
            json={
                "organization_id": str(org_id),
                "project_id": str(project_id),
                "wbs_code": "1.1",
                "name": "基礎工事",
                "description": "基礎工事一式",
                "level": 2,
                "planned_start": "2026-05-01",
                "planned_end": "2026-06-30",
                "planned_cost": "5000000",
                "weight_percent": "20.0",
            },
            headers=_auth_headers(),
        )
        assert response.status_code == 201
        assert mock_db.add.called
        called = mock_db.add.call_args[0][0]
        assert called.wbs_code == "1.1"
        assert called.name == "基礎工事"
        assert called.level == 2

    def test_list_wbs(self, client, mock_db):
        from src.models import WBSItem

        org_id = uuid.uuid4()
        project_id = uuid.uuid4()
        wbs = WBSItem(
            id=uuid.uuid4(),
            organization_id=org_id,
            project_id=project_id,
            wbs_code="1.1",
            name="基礎工事",
            level=2,
            status="pending",
            progress_percent=0,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        mock_db.execute = AsyncMock(return_value=MockScalarResult(items=[wbs], total=1))

        response = client.get(
            f"/api/v1/construction/wbs?project_id={project_id}",
            headers=_auth_headers(),
        )
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert len(data["items"]) == 1
        assert data["items"][0]["wbs_code"] == "1.1"

    def test_get_wbs(self, client, mock_db):
        from src.models import WBSItem

        wbs_id = uuid.uuid4()
        wbs = WBSItem(
            id=wbs_id,
            organization_id=ORG_ID,
            project_id=uuid.uuid4(),
            wbs_code="1.1",
            name="基礎工事",
            level=2,
            planned_cost=5000000,
            progress_percent=25.5,
            status="in_progress",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        mock_db.get = AsyncMock(return_value=wbs)

        response = client.get(
            f"/api/v1/construction/wbs/{wbs_id}",
            headers=_auth_headers(),
        )
        assert response.status_code == 200
        data = response.json()
        assert data["wbs_code"] == "1.1"
        assert data["status"] == "in_progress"

    def test_wbs_not_found(self, client, mock_db):
        mock_db.get = AsyncMock(return_value=None)
        response = client.get(
            f"/api/v1/construction/wbs/{uuid.uuid4()}",
            headers=_auth_headers(),
        )
        assert response.status_code == 404

    def test_get_wbs_rejects_other_organization(self, app, client, mock_db):
        from src.models import WBSItem

        # ADR-0004: admin crosses organizations, so use a regular (non-admin) user here.
        async def regular_user():
            return TokenData(sub="u", type="user", org=str(ORG_ID), roles=["user"])

        app.dependency_overrides[get_current_user] = regular_user

        other = WBSItem(
            id=uuid.uuid4(),
            organization_id=uuid.uuid4(),
            project_id=uuid.uuid4(),
            wbs_code="9",
            name="他組織のWBS",
            level=1,
            progress_percent=0,
            status="pending",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        mock_db.get = AsyncMock(return_value=other)

        response = client.get(
            f"/api/v1/construction/wbs/{other.id}",
            headers=_auth_headers(),
        )
        assert response.status_code == 404

    def test_wbs_children(self, client, mock_db):
        from src.models import WBSItem

        parent_id = uuid.uuid4()
        child1 = WBSItem(
            id=uuid.uuid4(),
            organization_id=ORG_ID,
            project_id=uuid.uuid4(),
            parent_id=parent_id,
            wbs_code="1.1.1",
            name="型枠工事",
            level=3,
            progress_percent=0,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        child2 = WBSItem(
            id=uuid.uuid4(),
            organization_id=ORG_ID,
            project_id=uuid.uuid4(),
            parent_id=parent_id,
            wbs_code="1.1.2",
            name="鉄筋工事",
            level=3,
            progress_percent=0,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        parent = WBSItem(
            id=parent_id,
            organization_id=ORG_ID,
            project_id=uuid.uuid4(),
            wbs_code="1.1",
            name="基礎工事",
            level=2,
            progress_percent=0,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        mock_db.get = AsyncMock(return_value=parent)
        mock_db.execute = AsyncMock(
            return_value=MockScalarResult(items=[child1, child2])
        )

        response = client.get(
            f"/api/v1/construction/wbs/{parent_id}/children",
            headers=_auth_headers(),
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2
        assert data[0]["wbs_code"] == "1.1.1"

    def test_wbs_progress_update(self, client, mock_db):
        from src.models import WBSItem

        wbs_id = uuid.uuid4()
        wbs = WBSItem(
            id=wbs_id,
            organization_id=ORG_ID,
            project_id=uuid.uuid4(),
            wbs_code="1.1",
            name="基礎工事",
            level=2,
            progress_percent=0,
            status="pending",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        mock_db.get = AsyncMock(return_value=wbs)

        response = client.patch(
            f"/api/v1/construction/wbs/{wbs_id}/progress",
            json={"progress_percent": "45.0", "status": "in_progress"},
            headers=_auth_headers(),
        )
        assert response.status_code == 200
        assert float(wbs.progress_percent) == 45.0
        assert wbs.status == "in_progress"

    def test_wbs_tree_route_not_shadowed_by_wbs_id(self, client, mock_db):
        from src.models import WBSItem

        root = WBSItem(
            id=uuid.uuid4(),
            organization_id=ORG_ID,
            project_id=uuid.uuid4(),
            wbs_code="1",
            name="工事一式",
            level=1,
            progress_percent=0,
            status="pending",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        mock_db.execute = AsyncMock(
            side_effect=[
                MockScalarResult(items=[root]),
                MockScalarResult(items=[]),
            ]
        )

        response = client.get(
            f"/api/v1/construction/wbs/tree?project_id={root.project_id}",
            headers=_auth_headers(),
        )
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["wbs_code"] == "1"
        assert data[0]["children"] == []

    def test_wbs_tree_requires_project_id(self, client):
        response = client.get(
            "/api/v1/construction/wbs/tree",
            headers=_auth_headers(),
        )
        assert response.status_code == 422


# ============================================
# Resource CRUD + Allocation
# ============================================
class TestResourceCRUD:
    def test_create_resource(self, client, mock_db):
        org_id = uuid.uuid4()
        project_id = uuid.uuid4()

        response = client.post(
            "/api/v1/construction/resources",
            json={
                "organization_id": str(org_id),
                "project_id": str(project_id),
                "resource_type": "labor",
                "name": "型枠大工",
                "specification": "1級技能士",
                "unit": "人日",
                "planned_quantity": "30",
                "unit_cost": "25000",
                "allocation_start": "2026-05-01",
                "allocation_end": "2026-06-30",
            },
            headers=_auth_headers(),
        )
        assert response.status_code == 201
        called = mock_db.add.call_args[0][0]
        assert called.resource_type == "labor"
        assert called.name == "型枠大工"
        assert float(called.unit_cost) == 25000

    def test_list_resources(self, client, mock_db):
        from src.models import Resource

        org_id = uuid.uuid4()
        resource = Resource(
            id=uuid.uuid4(),
            organization_id=org_id,
            project_id=uuid.uuid4(),
            resource_type="equipment",
            name="クローラクレーン",
            unit="台",
            planned_quantity=1,
            unit_cost=500000,
            status="planned",
            created_at=datetime.now(timezone.utc),
        )

        mock_db.execute = AsyncMock(
            return_value=MockScalarResult(items=[resource], total=1)
        )

        response = client.get(
            "/api/v1/construction/resources?resource_type=equipment",
            headers=_auth_headers(),
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data["items"]) == 1
        assert data["items"][0]["name"] == "クローラクレーン"

    def test_resource_allocation(self, client, mock_db):
        from src.models import Resource

        resource_id = uuid.uuid4()
        resource = Resource(
            id=resource_id,
            organization_id=ORG_ID,
            project_id=uuid.uuid4(),
            resource_type="labor",
            name="型枠大工",
            planned_quantity=30,
            unit_cost=25000,
            status="planned",
            created_at=datetime.now(timezone.utc),
        )
        mock_db.get = AsyncMock(return_value=resource)

        response = client.patch(
            f"/api/v1/construction/resources/{resource_id}/allocation",
            json={"status": "allocated"},
            headers=_auth_headers(),
        )
        assert response.status_code == 200
        assert resource.status == "allocated"


# ============================================
# Schedule CRUD + Critical Path
# ============================================
class TestScheduleCRUD:
    def test_create_schedule(self, client, mock_db):
        org_id = uuid.uuid4()
        project_id = uuid.uuid4()

        response = client.post(
            "/api/v1/construction/schedules",
            json={
                "organization_id": str(org_id),
                "project_id": str(project_id),
                "name": "基礎工事スケジュール",
                "schedule_type": "master",
                "planned_start": "2026-05-01",
                "planned_end": "2026-06-30",
                "duration_days": 61,
                "critical_path": True,
                "predecessor_ids": [],
                "successor_ids": [],
            },
            headers=_auth_headers(),
        )
        assert response.status_code == 201
        called = mock_db.add.call_args[0][0]
        assert called.name == "基礎工事スケジュール"
        assert called.schedule_type == "master"
        assert called.critical_path is True

    def test_critical_path_query(self, client, mock_db):
        from src.models import Schedule

        project_id = uuid.uuid4()
        org_id = uuid.uuid4()
        s1 = Schedule(
            id=uuid.uuid4(),
            organization_id=org_id,
            project_id=project_id,
            name="クリティカル工程A",
            schedule_type="master",
            planned_start=date(2026, 5, 1),
            planned_end=date(2026, 6, 30),
            critical_path=True,
            progress_percent=0,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        s2 = Schedule(
            id=uuid.uuid4(),
            organization_id=org_id,
            project_id=project_id,
            name="クリティカル工程B",
            schedule_type="master",
            planned_start=date(2026, 7, 1),
            planned_end=date(2026, 8, 31),
            critical_path=True,
            progress_percent=0,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        mock_db.execute = AsyncMock(return_value=MockScalarResult(items=[s1, s2]))

        response = client.get(
            f"/api/v1/construction/projects/{project_id}/critical-path",
            headers=_auth_headers(),
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2
        assert data[0]["critical_path"] is True

    def test_gantt_data(self, client, mock_db):
        from src.models import Schedule

        project_id = uuid.uuid4()
        s1 = Schedule(
            id=uuid.uuid4(),
            organization_id=ORG_ID,
            project_id=project_id,
            name="基礎工事",
            schedule_type="master",
            planned_start=date(2026, 5, 1),
            planned_end=date(2026, 6, 30),
            critical_path=True,
            progress_percent=30,
            status="in_progress",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        mock_db.execute = AsyncMock(return_value=MockScalarResult(items=[s1]))

        response = client.get(
            f"/api/v1/construction/projects/{project_id}/gantt",
            headers=_auth_headers(),
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["name"] == "基礎工事"
        assert data[0]["critical_path"] is True


# ============================================
# Method Statement CRUD + Approval
# ============================================
class TestMethodStatement:
    def test_create_method(self, client, mock_db):
        org_id = uuid.uuid4()
        project_id = uuid.uuid4()

        response = client.post(
            "/api/v1/construction/methods",
            json={
                "organization_id": str(org_id),
                "project_id": str(project_id),
                "title": "基礎工事施工計画書",
                "document_type": "method_statement",
                "content": "施工手順の詳細...",
                "safety_measures": "安全対策の詳細...",
                "environmental_measures": "環境対策の詳細...",
                "quality_control_points": "品質管理ポイント...",
                "required_equipment": ["クローラクレーン", "バイブロハンマ"],
                "required_materials": ["生コンクリート", "鉄筋"],
                "required_labor": "型枠大工 4名, 鉄筋工 3名",
            },
            headers=_auth_headers(),
        )
        assert response.status_code == 201
        called = mock_db.add.call_args[0][0]
        assert called.title == "基礎工事施工計画書"
        assert called.document_type == "method_statement"
        assert called.status == "draft"

    def test_submit_for_approval(self, client, mock_db):
        from src.models import MethodStatement

        method_id = uuid.uuid4()
        method = MethodStatement(
            id=method_id,
            organization_id=ORG_ID,
            project_id=uuid.uuid4(),
            title="基礎工事施工計画書",
            document_type="method_statement",
            status="draft",
            attachments=[],
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        mock_db.get = AsyncMock(return_value=method)

        response = client.post(
            f"/api/v1/construction/methods/{method_id}/submit",
            headers=_auth_headers(),
        )
        assert response.status_code == 200
        assert method.status == "review"

    def test_approve_method(self, client, mock_db):
        from src.models import MethodStatement

        method_id = uuid.uuid4()
        method = MethodStatement(
            id=method_id,
            organization_id=ORG_ID,
            project_id=uuid.uuid4(),
            title="基礎工事施工計画書",
            document_type="method_statement",
            status="review",
            attachments=[],
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        approver_id = uuid.uuid4()
        mock_db.get = AsyncMock(return_value=method)

        response = client.post(
            f"/api/v1/construction/methods/{method_id}/approve",
            json={"approved_by": str(approver_id)},
            headers=_auth_headers(),
        )
        assert response.status_code == 200
        assert method.status == "approved"
        assert method.approved_by == approver_id
        assert method.approved_at is not None

    def test_reject_method(self, client, mock_db):
        from src.models import MethodStatement

        method_id = uuid.uuid4()
        method = MethodStatement(
            id=method_id,
            organization_id=ORG_ID,
            project_id=uuid.uuid4(),
            title="基礎工事施工計画書",
            document_type="method_statement",
            status="review",
            attachments=[],
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        mock_db.get = AsyncMock(return_value=method)

        response = client.post(
            f"/api/v1/construction/methods/{method_id}/reject",
            headers=_auth_headers(),
        )
        assert response.status_code == 200
        assert method.status == "draft"

    def test_list_methods(self, client, mock_db):
        from src.models import MethodStatement

        method = MethodStatement(
            id=uuid.uuid4(),
            organization_id=ORG_ID,
            project_id=uuid.uuid4(),
            title="基礎工事施工計画書",
            document_type="method_statement",
            status="approved",
            attachments=[],
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        mock_db.execute = AsyncMock(
            return_value=MockScalarResult(items=[method], total=1)
        )

        response = client.get(
            "/api/v1/construction/methods?status=approved",
            headers=_auth_headers(),
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data["items"]) == 1
        assert data["items"][0]["title"] == "基礎工事施工計画書"
