"""Q1(権限境界) / Q2(データ分離) / Q6(承認・証跡) 監査ログと内部ジョブの品質テスト。

対象仮説:
  H9  _organization_id(トークン由来)が一覧・取得のテナント境界として機能すること
  H10 WorkflowAuditLog に承認者・アクションが記録され、改ざん・削除APIが無いこと
  H11 内部ジョブエンドポイントが無認証で叩けないこと(fail-closed)
  H12 通知の冪等性(idempotency_key)で重複通知が抑止されること

方針:
  実 DB / 実通知送信なし(httpx は mock)。`@pytest.mark.xfail(strict=True)` は
  未修正の欠陥の証跡(成功ではない)。
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from src.main import create_app
from src.models.base import get_db
from src.models import WorkflowAuditLog
from src.services import notification_adapter, workflow_service

UTC = timezone.utc

ORG_A = UUID("00000000-0000-0000-0000-0000000000aa")
ORG_B = UUID("00000000-0000-0000-0000-0000000000bb")
USER_A = UUID("00000000-0000-0000-0000-0000000000cc")
USER_B = UUID("00000000-0000-0000-0000-0000000000cd")
INST_ID = UUID("00000000-0000-0000-0000-0000000000ff")

JOB_KEY = "test-internal-job-key-local-only"

TOKEN_USER = {
    "sub": str(USER_A),
    "type": "user",
    "org": str(ORG_A),
    "roles": ["site_worker"],
    "scopes": [],
}
TOKEN_MGMT = {**TOKEN_USER, "roles": ["management"]}


def _utcnow():
    return datetime.now(UTC)


def _auth_header() -> dict:
    return {"Authorization": "Bearer test.token.value"}


class MockApproval:
    def __init__(self, **kwargs):
        self.id = kwargs.get("id", uuid4())
        self.instance_id = kwargs.get("instance_id", INST_ID)
        self.step_order = kwargs.get("step_order", 1)
        self.approver_id = kwargs.get("approver_id", None)
        self.approver_role = kwargs.get("approver_role", "department_head")
        self.status = kwargs.get("status", "pending")
        self.comment = kwargs.get("comment", None)
        self.approved_at = kwargs.get("approved_at", None)
        self.created_at = kwargs.get("created_at", _utcnow())


class MockInstance:
    def __init__(self, **kwargs):
        self.id = kwargs.get("id", INST_ID)
        self.receipt_no = kwargs.get("receipt_no", "SAW-2026-000001")
        self.definition_id = kwargs.get("definition_id", uuid4())
        self.organization_id = kwargs.get("organization_id", ORG_A)
        self.title = kwargs.get("title", "テスト稟議")
        self.description = None
        self.category = "ringi"
        self.status = kwargs.get("status", "in_progress")
        self.priority = "normal"
        self.reference_type = None
        self.reference_id = None
        self.metadata_ = kwargs.get("metadata_", {})
        self.definition = None
        self.submitted_by = kwargs.get("submitted_by", USER_A)
        self.submitted_at = _utcnow()
        self.completed_at = None
        self.duplicate_flag = False
        self.created_at = _utcnow()
        self.updated_at = _utcnow()
        self.approvals = kwargs.get("approvals", [])
        self.status_history = kwargs.get("status_history", [])


def _result_one(obj):
    result = MagicMock()
    result.scalar_one_or_none.return_value = obj
    return result


def _result_scalars_first(obj):
    result = MagicMock()
    result.scalars.return_value.first.return_value = obj
    return result


def _result_rowcount(rowcount: int):
    result = MagicMock()
    result.rowcount = rowcount
    return result


@pytest.fixture
def app():
    _app = create_app()
    mock_db = AsyncMock()
    mock_db.add = MagicMock()
    mock_db.flush = AsyncMock()
    mock_db.commit = AsyncMock()
    mock_db.rollback = AsyncMock()
    mock_db.close = AsyncMock()
    mock_db.execute = AsyncMock()

    async def _get_db():
        yield mock_db

    _app.dependency_overrides[get_db] = _get_db
    _app.state.mock_db = mock_db
    return _app


@pytest.fixture
def client(app):
    return TestClient(app)


# ——— H9: テナント境界 ———


class TestOrganizationIsolation:
    @patch("src.middleware.auth.jwt")
    def test_list_instances_other_org_query_is_forbidden(self, mock_jwt, app):
        mock_jwt.decode.return_value = TOKEN_USER
        response = TestClient(app).get(
            f"/api/v1/workflow/instances?organization_id={ORG_B}",
            headers=_auth_header(),
        )
        assert response.status_code == 403
        assert response.json()["detail"]["code"] == "ORG_FORBIDDEN"

    @patch("src.middleware.auth.jwt")
    def test_list_definitions_other_org_query_is_forbidden(self, mock_jwt, app):
        mock_jwt.decode.return_value = TOKEN_USER
        response = TestClient(app).get(
            f"/api/v1/workflow/definitions?organization_id={ORG_B}",
            headers=_auth_header(),
        )
        assert response.status_code == 403

    @patch("src.middleware.auth.jwt")
    def test_list_instances_uses_token_org_when_param_absent(self, mock_jwt, app):
        mock_jwt.decode.return_value = TOKEN_USER
        get_instances = AsyncMock(return_value=[])
        with patch.object(workflow_service, "get_instances", get_instances):
            response = TestClient(app).get(
                "/api/v1/workflow/instances", headers=_auth_header()
            )
        assert response.status_code == 200
        assert get_instances.call_args.kwargs["organization_id"] == ORG_A

    @patch("src.middleware.auth.jwt")
    def test_missing_org_claim_is_forbidden(self, mock_jwt, app):
        mock_jwt.decode.return_value = {**TOKEN_USER, "org": None}
        response = TestClient(app).get(
            "/api/v1/workflow/instances", headers=_auth_header()
        )
        assert response.status_code == 403
        assert response.json()["detail"]["code"] == "ORG_REQUIRED"

    @patch("src.middleware.auth.jwt")
    def test_invalid_org_claim_is_forbidden(self, mock_jwt, app):
        mock_jwt.decode.return_value = {**TOKEN_USER, "org": "not-a-uuid"}
        response = TestClient(app).get(
            "/api/v1/workflow/instances", headers=_auth_header()
        )
        assert response.status_code == 403
        assert response.json()["detail"]["code"] == "ORG_INVALID"

    @patch("src.middleware.auth.jwt")
    def test_get_instance_other_org_returns_404(self, mock_jwt, app):
        mock_jwt.decode.return_value = TOKEN_USER
        with patch.object(
            workflow_service, "get_instance_with_chain", AsyncMock(return_value=None)
        ):
            response = TestClient(app).get(
                f"/api/v1/workflow/instances/{INST_ID}", headers=_auth_header()
            )
        assert response.status_code == 404

    @patch("src.middleware.auth.jwt")
    def test_unrelated_user_cannot_view_instance(self, mock_jwt, app):
        """所有者・承認者・管理ロール以外には存在自体を隠す(404)。"""
        mock_jwt.decode.return_value = TOKEN_USER
        instance = MockInstance(
            submitted_by=USER_B,
            approvals=[MockApproval(approver_id=USER_B, approver_role="manager")],
            status="in_progress",
        )
        assert workflow_service.can_view_instance(instance, USER_A, ["site_worker"]) is False
        with patch.object(
            workflow_service, "get_instance_with_chain", AsyncMock(return_value=instance)
        ):
            response = TestClient(app).get(
                f"/api/v1/workflow/instances/{INST_ID}", headers=_auth_header()
            )
        assert response.status_code == 404

    @patch("src.middleware.auth.jwt")
    def test_management_role_can_view_any_instance_in_org(self, mock_jwt, app):
        mock_jwt.decode.return_value = TOKEN_MGMT
        instance = MockInstance(submitted_by=USER_B, approvals=[])
        with patch.object(
            workflow_service, "get_instance_with_chain", AsyncMock(return_value=instance)
        ):
            response = TestClient(app).get(
                f"/api/v1/workflow/instances/{INST_ID}", headers=_auth_header()
            )
        assert response.status_code == 200


# ——— H10: 監査ログの記録と不変性 ———


class TestAuditTrail:
    @patch("src.middleware.auth.jwt")
    def test_approve_records_audit_log_with_token_actor(self, mock_jwt, app):
        mock_jwt.decode.return_value = TOKEN_MGMT
        step1 = MockApproval(step_order=1, approver_role="management")
        instance = MockInstance(approvals=[step1])
        app.state.mock_db.execute = AsyncMock(
            side_effect=[
                _result_one(instance),
                _result_scalars_first(step1),
                _result_rowcount(1),
            ]
        )

        response = TestClient(app).post(
            f"/api/v1/workflow/instances/{INST_ID}/approve?step_order=1",
            headers=_auth_header(),
        )
        assert response.status_code == 200

        logs = [
            call.args[0]
            for call in app.state.mock_db.add.call_args_list
            if call.args and isinstance(call.args[0], WorkflowAuditLog)
        ]
        assert logs, "承認時に WorkflowAuditLog が追記されていない"
        entry = logs[-1]
        assert entry.event_type == "workflow.approval.approve"
        assert entry.user_id == USER_A, "承認者がトークン由来で記録されていない"
        assert entry.event_data["instance_id"] == str(INST_ID)
        assert entry.event_data["step_order"] == 1
        assert entry.success is True

    @patch("src.middleware.auth.jwt")
    def test_reject_records_audit_log_with_token_actor(self, mock_jwt, app):
        mock_jwt.decode.return_value = TOKEN_MGMT
        step1 = MockApproval(step_order=1, approver_role="management")
        instance = MockInstance(approvals=[step1])
        app.state.mock_db.execute = AsyncMock(
            side_effect=[_result_one(instance), _result_scalars_first(step1)]
        )

        response = TestClient(app).post(
            f"/api/v1/workflow/instances/{INST_ID}/reject?step_order=1",
            headers=_auth_header(),
        )
        assert response.status_code == 200

        logs = [
            call.args[0]
            for call in app.state.mock_db.add.call_args_list
            if call.args and isinstance(call.args[0], WorkflowAuditLog)
        ]
        assert logs
        assert logs[-1].event_type == "workflow.approval.reject"
        assert logs[-1].user_id == USER_A

    def test_record_audit_log_only_appends(self):
        """record_audit_log が追記(add)のみで更新・削除を行わないこと。"""
        db = AsyncMock()
        db.add = MagicMock()
        db.delete = MagicMock()
        workflow_service.record_audit_log(
            db, user_id=USER_A, event_type="workflow.instance.submit", event_data={}
        )
        assert db.add.call_count == 1
        assert db.delete.call_count == 0
        added = db.add.call_args.args[0]
        assert isinstance(added, WorkflowAuditLog)
        assert added.user_id == USER_A

    def test_no_audit_log_mutation_route_exists(self, app):
        """監査ログを改変・削除する HTTP ルートが公開されていないこと。"""
        offenders = []
        for route in app.routes:
            path = getattr(route, "path", "")
            methods = getattr(route, "methods", set()) or set()
            if "audit" in path.lower():
                mutating = methods & {"POST", "PUT", "PATCH", "DELETE"}
                if mutating:
                    offenders.append((path, sorted(mutating)))
        assert offenders == [], f"監査ログを変更しうるルート: {offenders}"


# ——— H11: 内部ジョブの認証 (fail-closed) ———


JOB_PATHS = [
    "/api/v1/workflow/internal/jobs/deadline-notifications",
    "/api/v1/workflow/internal/jobs/workload-notifications",
]
CALLBACK_PATH = "/api/v1/workflow/internal/notification-callback"


@pytest.fixture
def job_key(monkeypatch):
    from src.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("INTERNAL_JOB_API_KEY", JOB_KEY)
    yield JOB_KEY
    get_settings.cache_clear()


class TestInternalJobAuth:
    def test_job_endpoints_reject_missing_key(self, client, job_key):
        for path in JOB_PATHS:
            response = client.post(path)
            assert response.status_code == 403, path
            assert response.json()["detail"]["code"] == "INTERNAL_AUTH_REQUIRED"

    def test_job_endpoints_reject_wrong_key(self, client, job_key):
        for path in JOB_PATHS:
            response = client.post(path, headers={"X-Internal-API-Key": "wrong"})
            assert response.status_code == 403, path

    def test_job_endpoints_fail_closed_when_key_unset(self, client, monkeypatch):
        from src.config import get_settings

        get_settings.cache_clear()
        monkeypatch.delenv("INTERNAL_JOB_API_KEY", raising=False)
        try:
            for path in JOB_PATHS:
                response = client.post(path, headers={"X-Internal-API-Key": JOB_KEY})
                assert response.status_code == 403, path
        finally:
            get_settings.cache_clear()

    def test_notification_callback_requires_internal_key(self, client, job_key):
        response = client.post(
            CALLBACK_PATH,
            json={
                "workflow_instance_id": str(INST_ID),
                "notification_id": 1,
                "idempotency_key": "k1",
                "event": "opened",
            },
        )
        assert response.status_code == 403


# ——— H12: 通知の冪等性 ———


class TestNotificationIdempotency:
    def _configured(self):
        return MagicMock(
            NOTIFICATION_SERVICE_URL="http://notification.invalid",
            NOTIFICATION_INTERNAL_API_KEY="internal-key",
            NOTIFICATION_TIMEOUT_SECONDS=1.0,
        )

    def test_notification_callback_records_once_and_dedupes(self, client, job_key):
        body = {
            "workflow_instance_id": str(INST_ID),
            "notification_id": 1,
            "idempotency_key": "idem-abc",
            "event": "acknowledged",
        }
        client.app.state.mock_db.execute = AsyncMock(return_value=_result_one(None))
        first = client.post(
            CALLBACK_PATH, json=body, headers={"X-Internal-API-Key": JOB_KEY}
        )
        assert first.status_code == 200
        assert first.json()["data"] == {"recorded": True, "duplicate": False}

        client.app.state.mock_db.execute = AsyncMock(
            return_value=_result_one(WorkflowAuditLog())
        )
        second = client.post(
            CALLBACK_PATH, json=body, headers={"X-Internal-API-Key": JOB_KEY}
        )
        assert second.status_code == 200
        assert second.json()["data"] == {"recorded": False, "duplicate": True}

    @pytest.mark.asyncio
    async def test_notification_idempotency_key_is_deterministic(self):
        """同一(instance, transition, actor, recipient)は同一 idempotency_key になる。"""
        recipient = uuid4()
        fake_client = MagicMock()
        fake_client.__aenter__ = AsyncMock(return_value=fake_client)
        fake_client.__aexit__ = AsyncMock(return_value=False)
        fake_client.post = AsyncMock(return_value=MagicMock(raise_for_status=MagicMock()))

        with (
            patch.object(
                notification_adapter, "get_settings", return_value=self._configured()
            ),
            patch.object(
                notification_adapter.httpx, "AsyncClient", MagicMock(return_value=fake_client)
            ),
        ):
            for _ in range(2):
                ok = await notification_adapter.send_workflow_notification(
                    recipient_id=recipient,
                    template_code="workflow.approved",
                    instance_id=INST_ID,
                    transition="approved",
                    actor_id=USER_A,
                    template_vars={"document_name": "x"},
                )
                assert ok is True

        keys = [
            call.kwargs["json"]["idempotency_key"]
            for call in fake_client.post.call_args_list
        ]
        assert keys[0] == keys[1], "同一操作で冪等キーが変わっている"
        assert keys[0] == f"workflow:{INST_ID}:approved:{USER_A}:{recipient}"

    @pytest.mark.asyncio
    async def test_notification_is_not_sent_when_service_unconfigured(self):
        settings = MagicMock(
            NOTIFICATION_SERVICE_URL="", NOTIFICATION_INTERNAL_API_KEY=""
        )
        with (
            patch.object(
                notification_adapter, "get_settings", return_value=settings
            ),
            patch.object(notification_adapter.httpx, "AsyncClient") as client_cls,
        ):
            ok = await notification_adapter.send_workflow_notification(
                recipient_id=uuid4(),
                template_code="workflow.approved",
                instance_id=INST_ID,
                transition="approved",
                actor_id=USER_A,
                template_vars={},
            )
        assert ok is False
        client_cls.assert_not_called()

    @pytest.mark.asyncio
    async def test_notification_delivery_failure_does_not_raise(self):
        """通知失敗が業務トランザクションを壊さない(False を返して継続)。"""
        import httpx

        fake_client = MagicMock()
        fake_client.__aenter__ = AsyncMock(return_value=fake_client)
        fake_client.__aexit__ = AsyncMock(return_value=False)
        fake_client.post = AsyncMock(side_effect=httpx.ConnectError("boom"))

        with (
            patch.object(
                notification_adapter, "get_settings", return_value=self._configured()
            ),
            patch.object(
                notification_adapter.httpx, "AsyncClient", MagicMock(return_value=fake_client)
            ),
        ):
            ok = await notification_adapter.send_workflow_notification(
                recipient_id=uuid4(),
                template_code="workflow.approved",
                instance_id=INST_ID,
                transition="approved",
                actor_id=USER_A,
                template_vars={},
            )
        assert ok is False
