"""Analyticsサービス テスト"""

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from src.main import create_app
from src.middleware.auth import TokenData, get_current_user
from src.models.base import get_db


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
            sub="test-user-id", type="user", org="test-org", roles=["admin"]
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
        assert data["service"] == "analytics-service"


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

    def test_create_datasource_requires_auth(self, client_no_auth):
        response = client_no_auth.post("/api/v1/analytics/datasources", json={})
        assert response.status_code == 401

    def test_list_datasources_requires_auth(self, client_no_auth):
        response = client_no_auth.get("/api/v1/analytics/datasources")
        assert response.status_code == 401

    def test_create_pipeline_requires_auth(self, client_no_auth):
        response = client_no_auth.post("/api/v1/analytics/pipelines", json={})
        assert response.status_code == 401

    def test_list_reports_requires_auth(self, client_no_auth):
        response = client_no_auth.get("/api/v1/analytics/reports")
        assert response.status_code == 401


# ============================================
# DataSource CRUD
# ============================================
class TestDataSourceCRUD:
    def test_create_datasource(self, client, mock_db):
        org_id = uuid.uuid4()

        response = client.post(
            "/api/v1/analytics/datasources",
            json={
                "organization_id": str(org_id),
                "name": "建設現場センサーDB",
                "source_type": "timescaledb",
                "connection_config": {
                    "host": "localhost",
                    "port": 5432,
                    "database": "sensors",
                },
                "status": "active",
                "description": "現場IoTセンサーの時系列データ",
            },
            headers=_auth_headers(),
        )
        assert response.status_code == 201
        assert mock_db.add.called
        called = mock_db.add.call_args[0][0]
        assert called.name == "建設現場センサーDB"
        assert called.source_type == "timescaledb"
        assert called.connection_config["host"] == "localhost"

    def test_list_datasources(self, client, mock_db):
        from src.models import DataSource

        org_id = uuid.uuid4()
        ds = DataSource(
            id=uuid.uuid4(),
            organization_id=org_id,
            name="テストDS",
            source_type="postgresql",
            connection_config={"host": "localhost"},
            status="active",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        mock_db.execute = AsyncMock(
            return_value=MockScalarResult(items=[ds], total=1)
        )

        response = client.get(
            f"/api/v1/analytics/datasources?organization_id={org_id}",
            headers=_auth_headers(),
        )
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert len(data["items"]) == 1
        assert data["items"][0]["name"] == "テストDS"

    def test_get_datasource(self, client, mock_db):
        from src.models import DataSource

        ds_id = uuid.uuid4()
        ds = DataSource(
            id=ds_id,
            organization_id=uuid.uuid4(),
            name="テストDS",
            source_type="postgresql",
            connection_config={"host": "localhost"},
            status="active",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        mock_db.get = AsyncMock(return_value=ds)

        response = client.get(
            f"/api/v1/analytics/datasources/{ds_id}",
            headers=_auth_headers(),
        )
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "テストDS"
        assert data["source_type"] == "postgresql"

    def test_datasource_not_found(self, client, mock_db):
        mock_db.get = AsyncMock(return_value=None)
        response = client.get(
            f"/api/v1/analytics/datasources/{uuid.uuid4()}",
            headers=_auth_headers(),
        )
        assert response.status_code == 404

    def test_update_datasource(self, client, mock_db):
        from src.models import DataSource

        ds_id = uuid.uuid4()
        ds = DataSource(
            id=ds_id,
            organization_id=uuid.uuid4(),
            name="古い名前",
            source_type="postgresql",
            connection_config={"host": "localhost"},
            status="active",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        mock_db.get = AsyncMock(return_value=ds)

        response = client.put(
            f"/api/v1/analytics/datasources/{ds_id}",
            json={"name": "新しい名前", "status": "inactive"},
            headers=_auth_headers(),
        )
        assert response.status_code == 200
        assert ds.name == "新しい名前"
        assert ds.status == "inactive"

    def test_delete_datasource(self, client, mock_db):
        from src.models import DataSource

        ds_id = uuid.uuid4()
        ds = DataSource(
            id=ds_id,
            organization_id=uuid.uuid4(),
            name="削除予定",
            source_type="kafka",
            connection_config={"bootstrap_servers": "localhost:9092"},
            status="active",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        mock_db.get = AsyncMock(return_value=ds)

        response = client.delete(
            f"/api/v1/analytics/datasources/{ds_id}",
            headers=_auth_headers(),
        )
        assert response.status_code == 204
        mock_db.delete.assert_called_once_with(ds)

    def test_test_datasource_connection(self, client, mock_db):
        from src.models import DataSource

        ds_id = uuid.uuid4()
        ds = DataSource(
            id=ds_id,
            organization_id=uuid.uuid4(),
            name="接続テストDS",
            source_type="postgresql",
            connection_config={"host": "db.example.com", "port": 5432},
            status="active",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        mock_db.get = AsyncMock(return_value=ds)

        response = client.post(
            f"/api/v1/analytics/datasources/{ds_id}/test",
            headers=_auth_headers(),
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["source_type"] == "postgresql"
        assert "接続テストDS" in data["message"]


# ============================================
# DataPipeline CRUD
# ============================================
class TestPipelineCRUD:
    def test_create_pipeline(self, client, mock_db):
        from src.models import DataSource

        org_id = uuid.uuid4()
        source_id = uuid.uuid4()
        target_id = uuid.uuid4()
        # Referenced datasources must exist in the pipeline's organization (ADR-0004).
        mock_db.get = AsyncMock(
            side_effect=lambda _model, ds_id: DataSource(
                id=ds_id, organization_id=org_id, name="ds", source_type="postgresql"
            )
        )

        response = client.post(
            "/api/v1/analytics/pipelines",
            json={
                "organization_id": str(org_id),
                "name": "センサーデータ→DWHパイプライン",
                "source_id": str(source_id),
                "target_id": str(target_id),
                "transform_logic": {
                    "operations": ["clean", "aggregate"],
                    "aggregation_window": "1h",
                },
                "schedule": "0 * * * *",
                "status": "draft",
            },
            headers=_auth_headers(),
        )
        assert response.status_code == 201
        called = mock_db.add.call_args[0][0]
        assert called.name == "センサーデータ→DWHパイプライン"
        assert called.transform_logic["operations"] == ["clean", "aggregate"]
        assert called.schedule == "0 * * * *"

    def test_list_pipelines(self, client, mock_db):
        from src.models import DataPipeline

        org_id = uuid.uuid4()
        pipeline = DataPipeline(
            id=uuid.uuid4(),
            organization_id=org_id,
            name="テストパイプライン",
            source_id=uuid.uuid4(),
            target_id=uuid.uuid4(),
            transform_logic={"op": "filter"},
            status="draft",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        mock_db.execute = AsyncMock(
            return_value=MockScalarResult(items=[pipeline], total=1)
        )

        response = client.get(
            f"/api/v1/analytics/pipelines?organization_id={org_id}",
            headers=_auth_headers(),
        )
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert len(data["items"]) == 1
        assert data["items"][0]["name"] == "テストパイプライン"

    def test_get_pipeline(self, client, mock_db):
        from src.models import DataPipeline

        pipe_id = uuid.uuid4()
        pipeline = DataPipeline(
            id=pipe_id,
            organization_id=uuid.uuid4(),
            name="取得テストパイプライン",
            source_id=uuid.uuid4(),
            target_id=uuid.uuid4(),
            transform_logic={"op": "map"},
            status="active",
            last_run=datetime.now(timezone.utc),
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        mock_db.get = AsyncMock(return_value=pipeline)

        response = client.get(
            f"/api/v1/analytics/pipelines/{pipe_id}",
            headers=_auth_headers(),
        )
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "取得テストパイプライン"
        assert data["status"] == "active"

    def test_trigger_pipeline_run(self, client, mock_db):
        from src.models import DataPipeline, DataSource

        pipe_id = uuid.uuid4()
        pipeline = DataPipeline(
            id=pipe_id,
            organization_id=uuid.uuid4(),
            name="実行テストパイプライン",
            source_id=uuid.uuid4(),
            target_id=uuid.uuid4(),
            transform_logic={"op": "copy"},
            status="draft",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        mock_db.get = AsyncMock(return_value=pipeline)
        # Source/target datasources are looked up within the pipeline's organization.
        mock_db.execute = AsyncMock(
            return_value=MockScalarResult(
                value=DataSource(
                    id=pipeline.source_id,
                    organization_id=pipeline.organization_id,
                    name="ds",
                    source_type="postgresql",
                )
            )
        )

        response = client.post(
            f"/api/v1/analytics/pipelines/{pipe_id}/run",
            headers=_auth_headers(),
        )
        assert response.status_code == 200
        data = response.json()
        assert data["pipeline_id"] == str(pipe_id)
        assert data["status"] == "running"
        assert pipeline.status == "running"
        assert pipeline.last_run is not None

    def test_trigger_pipeline_already_running(self, client, mock_db):
        from src.models import DataPipeline

        pipe_id = uuid.uuid4()
        pipeline = DataPipeline(
            id=pipe_id,
            organization_id=uuid.uuid4(),
            name="実行中パイプライン",
            source_id=uuid.uuid4(),
            target_id=uuid.uuid4(),
            transform_logic={"op": "copy"},
            status="running",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        mock_db.get = AsyncMock(return_value=pipeline)

        response = client.post(
            f"/api/v1/analytics/pipelines/{pipe_id}/run",
            headers=_auth_headers(),
        )
        assert response.status_code == 400

    def test_delete_pipeline(self, client, mock_db):
        from src.models import DataPipeline

        pipe_id = uuid.uuid4()
        pipeline = DataPipeline(
            id=pipe_id,
            organization_id=uuid.uuid4(),
            name="削除予定パイプライン",
            source_id=uuid.uuid4(),
            target_id=uuid.uuid4(),
            transform_logic={"op": "copy"},
            status="draft",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        mock_db.get = AsyncMock(return_value=pipeline)

        response = client.delete(
            f"/api/v1/analytics/pipelines/{pipe_id}",
            headers=_auth_headers(),
        )
        assert response.status_code == 204
        mock_db.delete.assert_called_once_with(pipeline)


# ============================================
# AnalyticsReport CRUD
# ============================================
class TestReportCRUD:
    def test_create_report(self, client, mock_db):
        org_id = uuid.uuid4()

        response = client.post(
            "/api/v1/analytics/reports",
            json={
                "organization_id": str(org_id),
                "name": "月次進捗レポート",
                "report_type": "dashboard",
                "query_config": {
                    "metrics": ["contract_amount", "actual_cost"],
                    "group_by": "month",
                },
                "schedule": "0 8 1 * *",
                "status": "draft",
            },
            headers=_auth_headers(),
        )
        assert response.status_code == 201
        called = mock_db.add.call_args[0][0]
        assert called.name == "月次進捗レポート"
        assert called.report_type == "dashboard"
        assert called.query_config["metrics"] == ["contract_amount", "actual_cost"]

    def test_list_reports(self, client, mock_db):
        from src.models import AnalyticsReport

        org_id = uuid.uuid4()
        report = AnalyticsReport(
            id=uuid.uuid4(),
            organization_id=org_id,
            name="テストレポート",
            report_type="chart",
            query_config={"metrics": ["count"]},
            status="active",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        mock_db.execute = AsyncMock(
            return_value=MockScalarResult(items=[report], total=1)
        )

        response = client.get(
            f"/api/v1/analytics/reports?organization_id={org_id}",
            headers=_auth_headers(),
        )
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert len(data["items"]) == 1
        assert data["items"][0]["name"] == "テストレポート"

    def test_get_report(self, client, mock_db):
        from src.models import AnalyticsReport

        report_id = uuid.uuid4()
        report = AnalyticsReport(
            id=report_id,
            organization_id=uuid.uuid4(),
            name="取得テストレポート",
            report_type="table",
            query_config={"metrics": ["sum"]},
            status="active",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        mock_db.get = AsyncMock(return_value=report)

        response = client.get(
            f"/api/v1/analytics/reports/{report_id}",
            headers=_auth_headers(),
        )
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "取得テストレポート"
        assert data["report_type"] == "table"

    def test_update_report(self, client, mock_db):
        from src.models import AnalyticsReport

        report_id = uuid.uuid4()
        report = AnalyticsReport(
            id=report_id,
            organization_id=uuid.uuid4(),
            name="古いレポート名",
            report_type="chart",
            query_config={"metrics": ["avg"]},
            status="draft",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        mock_db.get = AsyncMock(return_value=report)

        response = client.put(
            f"/api/v1/analytics/reports/{report_id}",
            json={"name": "更新後レポート名", "status": "active"},
            headers=_auth_headers(),
        )
        assert response.status_code == 200
        assert report.name == "更新後レポート名"
        assert report.status == "active"

    def test_generate_report(self, client, mock_db):
        from src.models import AnalyticsReport

        report_id = uuid.uuid4()
        report = AnalyticsReport(
            id=report_id,
            organization_id=uuid.uuid4(),
            name="生成テストレポート",
            report_type="export",
            query_config={"metrics": ["all"]},
            status="active",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        mock_db.get = AsyncMock(return_value=report)

        response = client.post(
            f"/api/v1/analytics/reports/{report_id}/generate",
            headers=_auth_headers(),
        )
        assert response.status_code == 200
        data = response.json()
        assert data["report_id"] == str(report_id)
        assert len(data["data"]) == 2
        assert data["data"][0]["metric"] == "sample_value_1"
        assert data["summary"]["total_records"] == 2

    def test_export_report_json(self, client, mock_db):
        from src.models import AnalyticsReport

        report_id = uuid.uuid4()
        report = AnalyticsReport(
            id=report_id,
            organization_id=uuid.uuid4(),
            name="エクスポートテストレポート",
            report_type="export",
            query_config={"metrics": ["all"]},
            status="active",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        mock_db.get = AsyncMock(return_value=report)

        response = client.post(
            f"/api/v1/analytics/reports/{report_id}/export?format=json",
            headers=_auth_headers(),
        )
        assert response.status_code == 200
        data = response.json()
        assert data["format"] == "json"
        assert data["report_id"] == str(report_id)
        assert "sample_value_1" in data["content"]

    def test_export_report_csv(self, client, mock_db):
        from src.models import AnalyticsReport

        report_id = uuid.uuid4()
        report = AnalyticsReport(
            id=report_id,
            organization_id=uuid.uuid4(),
            name="CSVエクスポートテストレポート",
            report_type="export",
            query_config={"metrics": ["all"]},
            status="active",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        mock_db.get = AsyncMock(return_value=report)

        response = client.post(
            f"/api/v1/analytics/reports/{report_id}/export?format=csv",
            headers=_auth_headers(),
        )
        assert response.status_code == 200
        data = response.json()
        assert data["format"] == "csv"
        assert data["report_id"] == str(report_id)
        assert "metric,value" in data["content"]
        assert "sample_value_1,100" in data["content"]

    def test_report_not_found(self, client, mock_db):
        mock_db.get = AsyncMock(return_value=None)
        response = client.get(
            f"/api/v1/analytics/reports/{uuid.uuid4()}",
            headers=_auth_headers(),
        )
        assert response.status_code == 404

    def test_delete_report(self, client, mock_db):
        from src.models import AnalyticsReport

        report_id = uuid.uuid4()
        report = AnalyticsReport(
            id=report_id,
            organization_id=uuid.uuid4(),
            name="削除予定レポート",
            report_type="table",
            query_config={"metrics": ["count"]},
            status="draft",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        mock_db.get = AsyncMock(return_value=report)

        response = client.delete(
            f"/api/v1/analytics/reports/{report_id}",
            headers=_auth_headers(),
        )
        assert response.status_code == 204
        mock_db.delete.assert_called_once_with(report)
