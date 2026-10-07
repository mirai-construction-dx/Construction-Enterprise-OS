"""通知サービス テスト"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from src.main import create_app
from src.models.base import get_db


class MockScalarResult:
    def scalar_one_or_none(self):
        return None

    def scalar(self):
        return 0

    def scalars(self):
        return self

    def all(self):
        return []

    def first(self):
        return None


@pytest.fixture
def app():
    _app = create_app()
    mock_db = AsyncMock()

    async def mock_execute(*args, **kwargs):
        return MockScalarResult()

    mock_db.execute = mock_execute
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


class TestHealthCheck:
    def test_health_returns_200(self, client):
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["service"] == "notification-service"
        assert data["integrations"]["neo"] == "disabled"

    def test_health_reports_misconfigured_enabled_neo(self, client):
        from types import SimpleNamespace
        from unittest.mock import patch

        settings = SimpleNamespace(NEO_ENABLED=True, NEO_API_URL="", NEO_API_KEY="")
        with patch("src.api.health.get_settings", return_value=settings):
            response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "degraded"
        assert response.json()["integrations"]["neo"] == "misconfigured"


class TestAuthRequired:
    def test_notifications_list_requires_auth(self, client):
        response = client.get("/api/v1/notifications")
        assert response.status_code == 401

    def test_notifications_unread_count_requires_auth(self, client):
        response = client.get("/api/v1/notifications/unread-count")
        assert response.status_code == 401

    def test_notifications_mark_read_requires_auth(self, client):
        response = client.patch("/api/v1/notifications/1/read")
        assert response.status_code == 401

    def test_notifications_mark_all_read_requires_auth(self, client):
        response = client.patch("/api/v1/notifications/read-all")
        assert response.status_code == 401

    def test_internal_send_requires_internal_api_key(self, client):
        response = client.post(
            "/api/v1/notifications/send",
            json={
                "recipient_id": "00000000-0000-0000-0000-000000000001",
                "template_code": "workflow.approved",
                "idempotency_key": "workflow-1-approved",
            },
        )
        assert response.status_code == 403

    def test_neo_callback_requires_webhook_signature(self, client):
        response = client.post(
            "/api/v1/notification/webhooks/neo/callback",
            json={
                "notification_id": 1,
                "idempotency_key": "event-1",
                "event": "opened",
            },
        )
        assert response.status_code == 403

    def test_templates_list_requires_auth(self, client):
        response = client.get("/api/v1/notification-templates")
        assert response.status_code == 401

    def test_templates_create_requires_auth(self, client):
        response = client.post("/api/v1/notification-templates", json={})
        assert response.status_code == 401

    def test_templates_get_by_code_requires_auth(self, client):
        response = client.get("/api/v1/notification-templates/test.code")
        assert response.status_code == 401


class TestTemplateRendering:
    def test_render_template_with_variables(self):
        from src.services.template_service import render_template

        title_template = "【要承認】{{ document_name }}の承認依頼"
        body_template = (
            "{{ document_name }}の承認依頼が{{ requester_name }}さんから届いています。"
        )

        variables = {
            "document_name": "作業計画書",
            "requester_name": "田中太郎",
        }

        title = render_template(title_template, variables)
        body = render_template(body_template, variables)

        assert title == "【要承認】作業計画書の承認依頼"
        assert body == "作業計画書の承認依頼が田中太郎さんから届いています。"

    def test_render_template_missing_variable(self):
        from src.services.template_service import render_template

        result = render_template("Hello {{ name }}", {})
        assert result == "Hello "

    def test_render_template_with_conditional(self):
        from src.services.template_service import render_template

        template = "{% if comment %}{{ comment }}{% else %}コメントなし{% endif %}"
        assert render_template(template, {"comment": "テスト"}) == "テスト"
        assert render_template(template, {}) == "コメントなし"


class TestNotificationCreation:
    @pytest.mark.asyncio
    async def test_create_notification_from_template(self, app):
        from uuid import uuid4
        from datetime import datetime, timezone

        from src.models import NotificationTemplate
        from src.services.notification_service import create_notification

        template = NotificationTemplate(
            id=uuid4(),
            code="test.event",
            name="Test Event",
            channels=["in_app"],
            title_template="Title: {{msg}}",
            body_template="Body: {{msg}}",
            priority="normal",
            category="test",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        mock_db = AsyncMock()
        mock_db.add = MagicMock()
        mock_db.execute = AsyncMock()

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = template
        mock_db.execute.return_value = mock_result

        async def mock_refresh(obj):
            obj.id = 1
            obj.created_at = datetime.now(timezone.utc)

        mock_db.refresh = mock_refresh
        mock_db.flush = AsyncMock()

        notification = await create_notification(
            mock_db,
            recipient_id=uuid4(),
            template_code="test.event",
            template_vars={"msg": "Hello World"},
            metadata={"source": "test"},
        )

        assert notification is not None
        assert notification.title == "Title: Hello World"
        assert notification.body == "Body: Hello World"
        assert notification.status == "pending"
        assert notification.channels == ["in_app"]

        mock_db.add.assert_called_once()
        assert mock_db.add.call_args[0][0].title == "Title: Hello World"

    @pytest.mark.asyncio
    async def test_create_notification_template_not_found(self):
        from uuid import uuid4
        from unittest.mock import AsyncMock, MagicMock

        from src.services.notification_service import create_notification

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        notification = await create_notification(
            mock_db,
            recipient_id=uuid4(),
            template_code="nonexistent.code",
            template_vars={},
        )

        assert notification is None

    @pytest.mark.asyncio
    async def test_create_notification_idempotent_returns_existing(self):
        from uuid import uuid4

        from src.services.notification_service import create_notification_idempotent

        existing = MagicMock()
        mock_db = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = existing
        mock_db.execute.return_value = result

        notification, created = await create_notification_idempotent(
            mock_db,
            recipient_id=uuid4(),
            template_code="workflow.approved",
            template_vars={},
            metadata={},
            idempotency_key="workflow-1-approved",
        )

        assert notification is existing
        assert created is False
        mock_db.add.assert_not_called()


def test_delete_template_requires_management_role():
    """テンプレート削除には管理ロール（admin/site_manager）が必要（RBAC）。"""
    from types import SimpleNamespace
    from uuid import uuid4

    from src.middleware.auth import TokenData, get_current_user

    app = create_app()
    template_id = uuid4()

    mock_db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = SimpleNamespace(id=template_id)
    mock_db.execute.return_value = result
    mock_db.delete = AsyncMock()
    mock_db.flush = AsyncMock()

    async def _get_db():
        yield mock_db

    async def _get_user():
        return TokenData(
            sub=str(uuid4()), type="user", org=str(uuid4()), roles=["site_worker"]
        )

    app.dependency_overrides[get_db] = _get_db
    app.dependency_overrides[get_current_user] = _get_user

    client = TestClient(app)
    resp = client.delete(f"/api/v1/notification-templates/{template_id}")

    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "FORBIDDEN"
    mock_db.delete.assert_not_awaited()
