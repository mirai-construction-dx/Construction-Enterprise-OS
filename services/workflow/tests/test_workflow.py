"""ワークフローAPI テスト"""

import asyncio
import uuid
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from src.main import create_app
from src.models.base import get_db
from src.schemas import WorkflowDefinitionCreate
from src.services import approval_service
from src.services import workflow_service


def _utcnow():
    return datetime.now(timezone.utc)


TEST_USER_ID = uuid.uuid4()
TEST_ORG_ID = uuid.uuid4()
TEST_DEF_ID = uuid.uuid4()
TEST_INST_ID = uuid.uuid4()

VALID_TOKEN_PAYLOAD = {
    "sub": str(TEST_USER_ID),
    "type": "user",
    "org": str(TEST_ORG_ID),
    "roles": ["site_manager", "department_head"],
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


# ——— Health Check ———


def test_health_check(client):
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"


# ——— Auth Required ———


def test_definitions_require_auth(client):
    response = client.get("/api/v1/workflow/definitions")
    assert response.status_code == 401


def test_workflow_definition_requires_valid_unique_steps():
    with pytest.raises(ValueError):
        WorkflowDefinitionCreate(
            organization_id=TEST_ORG_ID,
            name="invalid",
            category="approval",
            steps=[],
        )
    with pytest.raises(ValueError, match="unique"):
        WorkflowDefinitionCreate(
            organization_id=TEST_ORG_ID,
            name="invalid",
            category="approval",
            steps=[
                {"order": 1, "role": "manager"},
                {"order": 1, "role": "director"},
            ],
        )


def test_workflow_definition_supports_parallel_roles_at_one_step():
    definition = WorkflowDefinitionCreate(
        organization_id=TEST_ORG_ID,
        name="並列回付",
        category="monthly_report",
        steps=[
            {"order": 1, "roles": ["accounting", "hr", "accounting"]},
            {"order": 2, "role": "department_head"},
        ],
    )

    assert definition.steps[0].role == "accounting"
    assert definition.steps[0].roles == ["accounting", "hr"]


def test_instances_require_auth(client):
    response = client.get("/api/v1/workflow/instances")
    assert response.status_code == 401


def test_create_definition_requires_auth(client):
    response = client.post("/api/v1/workflow/definitions", json={})
    assert response.status_code == 401


def test_create_instance_requires_auth(client):
    response = client.post("/api/v1/workflow/instances", json={})
    assert response.status_code == 401


@patch("src.middleware.auth.jwt")
def test_signed_token_with_invalid_subject_fails_closed(mock_jwt, client):
    mock_jwt.decode.return_value = {**VALID_TOKEN_PAYLOAD, "sub": "not-a-uuid"}

    response = client.get("/api/v1/workflow/definitions", headers=_make_auth_header())

    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "INVALID_TOKEN"


# ——— Workflow Definition CRUD ———


class MockScalarResult:
    def __init__(self, items):
        self._items = items

    def all(self):
        return self._items

    def first(self):
        return self._items[0] if self._items else None

    def scalar_one_or_none(self):
        return self._items[0] if self._items else None

    def scalar_one(self):
        return self._items[0]

    def scalars(self):
        return self


class MockDefinition:
    def __init__(self, **kwargs):
        self.id = kwargs.get("id", TEST_DEF_ID)
        self.organization_id = kwargs.get("organization_id", TEST_ORG_ID)
        self.name = kwargs.get("name", "テスト定義")
        self.description = kwargs.get("description", None)
        self.category = kwargs.get("category", "ringi")
        self.steps = kwargs.get(
            "steps", [{"order": 1, "role": "site_manager", "required": True}]
        )
        self.check_rules = kwargs.get("check_rules", {})
        self.is_active = kwargs.get("is_active", True)
        self.created_by = kwargs.get("created_by", TEST_USER_ID)
        self.created_at = kwargs.get("created_at", _utcnow())
        self.updated_at = kwargs.get("updated_at", _utcnow())


class MockInstance:
    def __init__(self, **kwargs):
        self.id = kwargs.get("id", TEST_INST_ID)
        self.receipt_no = kwargs.get("receipt_no", "SAW-2026-000001")
        self.definition_id = kwargs.get("definition_id", TEST_DEF_ID)
        self.organization_id = kwargs.get("organization_id", TEST_ORG_ID)
        self.title = kwargs.get("title", "テスト稟議")
        self.description = kwargs.get("description", None)
        self.category = kwargs.get("category", "ringi")
        self.status = kwargs.get("status", "draft")
        self.priority = kwargs.get("priority", "normal")
        self.reference_type = kwargs.get("reference_type", None)
        self.reference_id = kwargs.get("reference_id", None)
        self.metadata_ = kwargs.get("metadata_", {})
        self.definition = kwargs.get("definition", None)
        self.submitted_by = kwargs.get("submitted_by", TEST_USER_ID)
        self.submitted_at = kwargs.get("submitted_at", None)
        self.completed_at = kwargs.get("completed_at", None)
        self.duplicate_flag = kwargs.get("duplicate_flag", False)
        self.created_at = kwargs.get("created_at", _utcnow())
        self.updated_at = kwargs.get("updated_at", _utcnow())
        self.approvals = kwargs.get("approvals", [])


class MockApproval:
    def __init__(self, **kwargs):
        self.id = kwargs.get("id", uuid.uuid4())
        self.instance_id = kwargs.get("instance_id", TEST_INST_ID)
        self.step_order = kwargs.get("step_order", 1)
        self.approver_id = kwargs.get("approver_id", None)
        self.approver_role = kwargs.get("approver_role", "site_manager")
        self.status = kwargs.get("status", "pending")
        self.comment = kwargs.get("comment", None)
        self.approved_at = kwargs.get("approved_at", None)
        self.created_at = kwargs.get("created_at", _utcnow())


def test_case_visibility_is_limited_by_owner_assignment_or_management_role():
    other_user = uuid.uuid4()
    instance = MockInstance(
        submitted_by=TEST_USER_ID,
        approvals=[MockApproval(approver_id=other_user, status="pending")],
        status="pending_approval",
    )

    assert workflow_service.can_view_instance(instance, TEST_USER_ID, ["site_worker"])
    assert workflow_service.can_view_instance(instance, other_user, ["department_head"])
    assert workflow_service.can_view_instance(instance, uuid.uuid4(), ["management"])
    assert not workflow_service.can_view_instance(
        instance, uuid.uuid4(), ["site_worker"]
    )


def test_draft_response_does_not_expose_a_fake_receipt_number():
    instance = MockInstance(receipt_no=None)

    from src.api.workflows import _instance_to_response

    assert _instance_to_response(instance)["receipt_no"] is None


class MockStatusHistory:
    def __init__(self, **kwargs):
        self.id = kwargs.get("id", uuid.uuid4())
        self.instance_id = kwargs.get("instance_id", TEST_INST_ID)
        self.from_status = kwargs.get("from_status", "draft")
        self.to_status = kwargs.get("to_status", "in_progress")
        self.changed_by = kwargs.get("changed_by", TEST_USER_ID)
        self.comment = kwargs.get("comment", None)
        self.created_at = kwargs.get("created_at", _utcnow())


@patch("src.middleware.auth.jwt")
def test_list_definitions_filtered(mock_jwt, app):
    mock_jwt.decode.return_value = VALID_TOKEN_PAYLOAD

    mock_def1 = MockDefinition(
        id=uuid.uuid4(),
        name="一般稟議",
        category="ringi",
        steps=[{"order": 1, "role": "site_manager", "required": True}],
    )
    mock_def2 = MockDefinition(
        id=uuid.uuid4(),
        name="安全許可",
        category="safety_approval",
        steps=[{"order": 1, "role": "safety_officer", "required": True}],
    )

    db_mock = AsyncMock()
    db_mock.execute = AsyncMock(return_value=MockScalarResult([mock_def1, mock_def2]))
    db_mock.commit = AsyncMock()
    db_mock.rollback = AsyncMock()
    db_mock.close = AsyncMock()

    async def get_mock_db():
        yield db_mock

    app.dependency_overrides[get_db] = get_mock_db

    client = TestClient(app)
    response = client.get(
        "/api/v1/workflow/definitions?category=ringi",
        headers=_make_auth_header(),
    )
    assert response.status_code == 200
    assert len(response.json()["data"]) == 2


# Patch-based tests for full workflow flow
@patch("src.middleware.auth.jwt")
def test_health_check_with_mock(mock_jwt, client):
    mock_jwt.decode.return_value = VALID_TOKEN_PAYLOAD
    response = client.get("/health")
    assert response.status_code == 200


@patch("src.middleware.auth.jwt")
def test_list_definitions_empty(mock_jwt, app):
    mock_jwt.decode.return_value = VALID_TOKEN_PAYLOAD

    db_mock = AsyncMock()
    db_mock.execute = AsyncMock(return_value=MockScalarResult([]))
    db_mock.commit = AsyncMock()
    db_mock.rollback = AsyncMock()
    db_mock.close = AsyncMock()

    app.dependency_overrides[get_db] = lambda: db_mock

    client = TestClient(app)
    response = client.get("/api/v1/workflow/definitions", headers=_make_auth_header())
    assert response.status_code == 200
    assert response.json()["data"] == []


@patch("src.middleware.auth.jwt")
def test_create_definition_success(mock_jwt, app):
    mock_jwt.decode.return_value = {**VALID_TOKEN_PAYLOAD, "roles": ["admin"]}

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

    client = TestClient(app)
    response = client.post(
        "/api/v1/workflow/definitions",
        json={
            "organization_id": str(TEST_ORG_ID),
            "name": "一般稟議",
            "category": "ringi",
            "steps": [{"order": 1, "role": "site_manager", "required": True}],
        },
        headers=_make_auth_header(),
    )
    assert response.status_code == 201
    data = response.json()
    assert data["data"]["name"] == "一般稟議"
    db_mock.commit.assert_awaited_once()


@patch("src.middleware.auth.jwt")
def test_delete_definition_without_management_role_is_403(mock_jwt, app):
    mock_jwt.decode.return_value = {**VALID_TOKEN_PAYLOAD, "roles": ["site_worker"]}

    client = TestClient(app)
    response = client.delete(
        f"/api/v1/workflow/definitions/{TEST_DEF_ID}", headers=_make_auth_header()
    )

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "FORBIDDEN"


@patch("src.middleware.auth.jwt")
def test_create_instance_auto_creates_approvals(mock_jwt, app):
    mock_jwt.decode.return_value = VALID_TOKEN_PAYLOAD

    mock_def = MockDefinition(
        id=TEST_DEF_ID,
        category="ringi",
        steps=[
            {"order": 1, "role": "site_manager", "required": True},
            {"order": 2, "role": "department_head", "required": True},
        ],
    )
    mock_instance = MockInstance(
        id=TEST_INST_ID,
        category="ringi",
        status="draft",
    )
    mock_approval1 = MockApproval(
        instance_id=TEST_INST_ID, step_order=1, approver_role="site_manager"
    )
    mock_approval2 = MockApproval(
        instance_id=TEST_INST_ID, step_order=2, approver_role="department_head"
    )
    mock_instance.approvals = [mock_approval1, mock_approval2]

    db_mock = AsyncMock()
    db_mock.add = MagicMock()
    db_mock.flush = AsyncMock()
    db_mock.execute = AsyncMock(return_value=MockScalarResult([mock_instance]))
    db_mock.commit = AsyncMock()
    db_mock.rollback = AsyncMock()
    db_mock.close = AsyncMock()

    call_count = 0

    async def mock_execute_side_effect(statement):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return MockScalarResult([mock_def])
        return MockScalarResult([mock_instance])

    db_mock.execute = AsyncMock(side_effect=mock_execute_side_effect)

    async def get_mock_db():
        yield db_mock

    app.dependency_overrides[get_db] = get_mock_db

    client = TestClient(app)
    response = client.post(
        "/api/v1/workflow/instances",
        json={
            "definition_id": str(TEST_DEF_ID),
            "organization_id": str(TEST_ORG_ID),
            "title": "テスト稟議",
        },
        headers=_make_auth_header(),
    )
    assert response.status_code == 201
    data = response.json()
    assert data["data"]["status"] == "draft"
    assert len(data["data"]["approvals"]) == 2


@patch("src.middleware.auth.jwt")
def test_submit_instance(mock_jwt, app):
    mock_jwt.decode.return_value = VALID_TOKEN_PAYLOAD

    mock_instance = MockInstance(
        id=TEST_INST_ID,
        category="ringi",
        status="draft",
    )
    mock_instance.approvals = []

    mock_submitted = MockInstance(
        id=TEST_INST_ID,
        category="ringi",
        status="in_progress",
    )
    mock_submitted.submitted_at = _utcnow()

    db_mock = AsyncMock()
    db_mock.add = MagicMock()
    db_mock.execute = AsyncMock(return_value=MockScalarResult([mock_instance]))
    db_mock.flush = AsyncMock()
    db_mock.commit = AsyncMock()
    db_mock.rollback = AsyncMock()
    db_mock.close = AsyncMock()

    async def get_mock_db():
        yield db_mock

    app.dependency_overrides[get_db] = get_mock_db

    client = TestClient(app)
    response = client.post(
        f"/api/v1/workflow/instances/{TEST_INST_ID}/submit",
        headers=_make_auth_header(),
    )
    assert response.status_code == 200
    data = response.json()
    assert data["data"]["status"] == "in_progress"


@patch("src.middleware.auth.jwt")
def test_submit_instance_returns_validation_details(mock_jwt, app):
    mock_jwt.decode.return_value = VALID_TOKEN_PAYLOAD
    mock_instance = MockInstance(
        id=TEST_INST_ID,
        status="draft",
        definition=MockDefinition(
            check_rules={"required_fields": ["construction_code"]}
        ),
    )
    db_mock = AsyncMock()
    db_mock.execute = AsyncMock(return_value=MockScalarResult([mock_instance]))
    db_mock.flush = AsyncMock()
    db_mock.commit = AsyncMock()
    db_mock.rollback = AsyncMock()
    db_mock.close = AsyncMock()

    async def get_mock_db():
        yield db_mock

    app.dependency_overrides[get_db] = get_mock_db
    response = TestClient(app).post(
        f"/api/v1/workflow/instances/{TEST_INST_ID}/submit",
        headers=_make_auth_header(),
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "VALIDATION_ERROR"
    assert response.json()["detail"]["errors"][0]["field"] == "construction_code"


@patch("src.middleware.auth.jwt")
def test_approve_step(mock_jwt, app):
    mock_jwt.decode.return_value = VALID_TOKEN_PAYLOAD

    mock_approval = MockApproval(
        instance_id=TEST_INST_ID,
        step_order=1,
        approver_role="site_manager",
        status="pending",
    )
    mock_instance = MockInstance(
        id=TEST_INST_ID,
        category="ringi",
        status="in_progress",
    )
    mock_instance.approvals = [mock_approval]

    mock_post_approve = MockInstance(
        id=TEST_INST_ID,
        category="ringi",
        status="approved",
    )
    mock_post_approve.completed_at = _utcnow()
    mock_post_approve.approvals = [
        MockApproval(
            instance_id=TEST_INST_ID,
            step_order=1,
            approver_role="site_manager",
            status="approved",
            approver_id=TEST_USER_ID,
        )
    ]

    db_mock = AsyncMock()
    db_mock.add = MagicMock()
    db_mock.flush = AsyncMock()
    db_mock.commit = AsyncMock()
    db_mock.rollback = AsyncMock()
    db_mock.close = AsyncMock()

    call_count = 0

    async def mock_execute_side_effect(statement):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return MockScalarResult([mock_instance])
        if call_count == 2:
            return MockScalarResult([mock_approval])
        return MockScalarResult([])

    db_mock.execute = AsyncMock(side_effect=mock_execute_side_effect)

    async def get_mock_db():
        yield db_mock

    app.dependency_overrides[get_db] = get_mock_db

    client = TestClient(app)
    response = client.post(
        f"/api/v1/workflow/instances/{TEST_INST_ID}/approve?step_order=1",
        headers=_make_auth_header(),
    )
    assert response.status_code == 200


def test_approve_step_rejects_skipping_current_step():
    first = MockApproval(
        instance_id=TEST_INST_ID,
        step_order=1,
        approver_role="site_manager",
        status="pending",
    )
    second = MockApproval(
        instance_id=TEST_INST_ID,
        step_order=2,
        approver_role="department_head",
        status="pending",
    )
    instance = MockInstance(
        id=TEST_INST_ID, status="in_progress", approvals=[first, second]
    )
    db_mock = AsyncMock()
    db_mock.add = MagicMock()
    db_mock.execute = AsyncMock(
        side_effect=[
            MockScalarResult([instance]),
            MockScalarResult([second]),
        ]
    )

    with pytest.raises(ValueError, match="not the current step"):
        asyncio.run(
            approval_service.approve_step(
                db_mock,
                instance_id=TEST_INST_ID,
                step_order=2,
                user_id=TEST_USER_ID,
                user_roles=["department_head"],
                organization_id=TEST_ORG_ID,
            )
        )


def test_approve_step_rejects_user_without_required_role():
    approval = MockApproval(
        instance_id=TEST_INST_ID,
        step_order=1,
        approver_role="department_head",
        status="pending",
    )
    instance = MockInstance(
        id=TEST_INST_ID,
        status="in_progress",
        approvals=[approval],
    )
    db_mock = AsyncMock()
    db_mock.add = MagicMock()
    db_mock.execute = AsyncMock(
        side_effect=[
            MockScalarResult([instance]),
            MockScalarResult([]),
        ]
    )

    with pytest.raises(ValueError, match="not found for instance"):
        asyncio.run(
            approval_service.approve_step(
                db_mock,
                instance_id=TEST_INST_ID,
                step_order=1,
                user_id=TEST_USER_ID,
                user_roles=[],
            )
        )


def test_resubmit_rejected_workflow_resets_approvals_and_records_comment():
    rejected_approval = MockApproval(
        instance_id=TEST_INST_ID,
        step_order=1,
        approver_role="site_manager",
        status="rejected",
        comment="見積書を更新してください",
    )
    pending_approval = MockApproval(
        instance_id=TEST_INST_ID,
        step_order=2,
        approver_role="department_head",
        status="approved",
        approver_id=TEST_USER_ID,
    )
    instance = MockInstance(
        id=TEST_INST_ID,
        status="rejected",
        submitted_by=TEST_USER_ID,
        approvals=[rejected_approval, pending_approval],
    )
    db_mock = AsyncMock()
    db_mock.add = MagicMock()
    db_mock.execute = AsyncMock(return_value=MockScalarResult([instance]))
    db_mock.flush = AsyncMock()

    result = asyncio.run(
        workflow_service.resubmit_workflow(db_mock, TEST_INST_ID, TEST_USER_ID)
    )

    assert result.status == "in_progress"
    assert all(approval.status == "pending" for approval in instance.approvals)
    assert all(approval.approver_id is None for approval in instance.approvals)
    assert all(approval.comment is None for approval in instance.approvals)
    db_mock.flush.assert_awaited_once()


def test_submit_blocks_failed_definition_checks():
    definition = MockDefinition(check_rules={"required_fields": ["construction_code"]})
    instance = MockInstance(
        status="draft", submitted_by=TEST_USER_ID, definition=definition
    )
    db_mock = AsyncMock()
    db_mock.execute = AsyncMock(return_value=MockScalarResult([instance]))
    db_mock.flush = AsyncMock()

    with pytest.raises(ValueError, match="提出時チェックに失敗"):
        asyncio.run(
            workflow_service.submit_workflow(db_mock, TEST_INST_ID, TEST_USER_ID)
        )

    assert instance.status == "draft"
    db_mock.flush.assert_not_awaited()


def test_submit_marks_duplicate_candidate_without_blocking_submission():
    submitted_at = _utcnow()
    metadata = {
        "construction_code": "C-001",
        "doc_type_code": "monthly-report",
        "target_year_month": "2026-08",
        "amount": 100000,
        "attachments": ["monthly-report.pdf"],
    }
    instance = MockInstance(
        status="draft",
        receipt_no="SAW-2026-000002",
        metadata_=metadata,
        created_at=submitted_at,
    )
    candidate = MockInstance(
        id=uuid.uuid4(),
        status="in_progress",
        receipt_no="SAW-2026-000001",
        metadata_=metadata,
        submitted_by=TEST_USER_ID,
        created_at=submitted_at,
    )
    db_mock = AsyncMock()
    db_mock.add = MagicMock()
    db_mock.execute = AsyncMock(
        side_effect=[MockScalarResult([instance]), MockScalarResult([candidate])]
    )
    db_mock.flush = AsyncMock()

    result = asyncio.run(
        workflow_service.submit_workflow(db_mock, TEST_INST_ID, TEST_USER_ID)
    )

    assert result.status == "in_progress"
    assert result.duplicate_flag is True
    assert result.metadata_["duplicate_candidate_receipt_no"] == "SAW-2026-000001"
    assert any(
        warning["field"] == "duplicate"
        for warning in result.metadata_["check_warnings"]
    )
    db_mock.flush.assert_awaited_once()


def test_update_workflow_draft_only_changes_submitter_owned_draft():
    instance = MockInstance(status="draft", submitted_by=TEST_USER_ID)
    db_mock = AsyncMock()
    db_mock.execute = AsyncMock(return_value=MockScalarResult([instance]))
    db_mock.flush = AsyncMock()

    result = asyncio.run(
        workflow_service.update_workflow_draft(
            db_mock,
            TEST_INST_ID,
            TEST_USER_ID,
            title="更新後の件名",
            description="更新後の詳細",
            metadata={"construction_code": "C-001"},
        )
    )

    assert result.title == "更新後の件名"
    assert result.description == "更新後の詳細"
    assert result.metadata_ == {"construction_code": "C-001"}
    db_mock.flush.assert_awaited_once()


def test_due_date_prefers_instance_override_and_supports_master_rules():
    assert workflow_service._calculate_due_date(
        {"deadline": "2026-09-15"}, {"deadline_rule": "DAYS:30"}, date(2026, 8, 31)
    ) == date(2026, 9, 15)
    assert workflow_service._calculate_due_date(
        {}, {"deadline_rule": "DAYS:30"}, date(2026, 8, 31)
    ) == date(2026, 9, 30)
    assert workflow_service._calculate_due_date(
        {}, {"deadline_rule": "MONTHLY_DAY:5"}, date(2026, 8, 31)
    ) == date(2026, 9, 5)


def test_start_workflow_rejects_definition_from_another_organization():
    definition = MockDefinition(organization_id=uuid.uuid4())
    db_mock = AsyncMock()
    db_mock.execute = AsyncMock(return_value=MockScalarResult([definition]))

    with pytest.raises(ValueError, match="not in the organization"):
        asyncio.run(
            workflow_service.start_workflow(
                db_mock,
                definition_id=TEST_DEF_ID,
                submitted_by=TEST_USER_ID,
                organization_id=TEST_ORG_ID,
                title="組織境界テスト",
            )
        )


@patch("src.middleware.auth.jwt")
def test_reject_step(mock_jwt, app):
    mock_jwt.decode.return_value = VALID_TOKEN_PAYLOAD

    mock_approval = MockApproval(
        instance_id=TEST_INST_ID,
        step_order=1,
        approver_role="site_manager",
        status="pending",
    )
    mock_instance = MockInstance(
        id=TEST_INST_ID,
        category="ringi",
        status="in_progress",
    )
    mock_instance.approvals = [mock_approval]

    db_mock = AsyncMock()
    db_mock.add = MagicMock()
    db_mock.flush = AsyncMock()
    db_mock.commit = AsyncMock()
    db_mock.rollback = AsyncMock()
    db_mock.close = AsyncMock()

    call_count = 0

    async def mock_execute_side_effect(statement):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return MockScalarResult([mock_instance])
        if call_count == 2:
            return MockScalarResult([mock_approval])
        return MockScalarResult([])

    db_mock.execute = AsyncMock(side_effect=mock_execute_side_effect)

    async def get_mock_db():
        yield db_mock

    app.dependency_overrides[get_db] = get_mock_db

    client = TestClient(app)
    response = client.post(
        f"/api/v1/workflow/instances/{TEST_INST_ID}/reject?step_order=1",
        json={"comment": "不備あり"},
        headers=_make_auth_header(),
    )
    assert response.status_code == 200


@patch("src.middleware.auth.jwt")
def test_cancel_instance(mock_jwt, app):
    mock_jwt.decode.return_value = VALID_TOKEN_PAYLOAD

    mock_instance = MockInstance(
        id=TEST_INST_ID,
        category="ringi",
        status="in_progress",
    )
    mock_instance.approvals = []

    db_mock = AsyncMock()
    db_mock.add = MagicMock()
    db_mock.execute = AsyncMock(return_value=MockScalarResult([mock_instance]))
    db_mock.flush = AsyncMock()
    db_mock.commit = AsyncMock()
    db_mock.rollback = AsyncMock()
    db_mock.close = AsyncMock()

    async def get_mock_db():
        yield db_mock

    app.dependency_overrides[get_db] = get_mock_db

    client = TestClient(app)
    response = client.post(
        f"/api/v1/workflow/instances/{TEST_INST_ID}/cancel",
        headers=_make_auth_header(),
    )
    assert response.status_code == 200


@patch("src.middleware.auth.jwt")
def test_get_pending_approvals(mock_jwt, app):
    mock_jwt.decode.return_value = VALID_TOKEN_PAYLOAD

    mock_approval = MockApproval(
        instance_id=TEST_INST_ID,
        step_order=1,
        approver_role="site_manager",
        status="pending",
    )
    mock_instance = MockInstance(
        id=TEST_INST_ID,
        category="ringi",
        status="in_progress",
    )
    mock_instance.approvals = [mock_approval]

    db_mock = AsyncMock()
    db_mock.execute = AsyncMock(return_value=MockScalarResult([mock_instance]))
    db_mock.commit = AsyncMock()
    db_mock.rollback = AsyncMock()
    db_mock.close = AsyncMock()

    async def get_mock_db():
        yield db_mock

    app.dependency_overrides[get_db] = get_mock_db

    client = TestClient(app)
    response = client.get(
        "/api/v1/workflow/instances/pending",
        headers=_make_auth_header(),
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data["data"]) == 1


@patch("src.middleware.auth.jwt")
def test_get_instance_not_found(mock_jwt, app):
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
        f"/api/v1/workflow/instances/{uuid.uuid4()}",
        headers=_make_auth_header(),
    )
    assert response.status_code == 404


@patch("src.middleware.auth.jwt")
def test_get_history(mock_jwt, app):
    mock_jwt.decode.return_value = VALID_TOKEN_PAYLOAD

    mock_approval1 = MockApproval(
        instance_id=TEST_INST_ID,
        step_order=1,
        approver_role="site_manager",
        status="approved",
        approver_id=TEST_USER_ID,
    )
    mock_approval2 = MockApproval(
        instance_id=TEST_INST_ID,
        step_order=2,
        approver_role="department_head",
        status="pending",
    )
    mock_instance = MockInstance(
        id=TEST_INST_ID,
        category="ringi",
        status="in_progress",
    )
    mock_instance.approvals = [mock_approval1, mock_approval2]
    mock_instance.status_history = [
        MockStatusHistory(from_status=None, to_status="draft"),
        MockStatusHistory(from_status="draft", to_status="in_progress"),
    ]

    db_mock = AsyncMock()
    db_mock.execute = AsyncMock(return_value=MockScalarResult([mock_instance]))
    db_mock.commit = AsyncMock()
    db_mock.rollback = AsyncMock()
    db_mock.close = AsyncMock()

    async def get_mock_db():
        yield db_mock

    app.dependency_overrides[get_db] = get_mock_db

    client = TestClient(app)
    response = client.get(
        f"/api/v1/workflow/instances/{TEST_INST_ID}/history",
        headers=_make_auth_header(),
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data["data"]) == 2


def _collect_routes(app) -> set[tuple[str, tuple[str, ...]]]:
    """app に登録された (path, methods) を FastAPI のバージョン差に依存せず収集する。

    FastAPI 0.141 以降 ``app.routes`` は ``include_router`` の結果を
    フラット展開せず ``_IncludedRouter`` として保持するため、
    ``route.path`` を直接参照すると AttributeError になる。
    旧バージョン(0.115 系)では従来どおり APIRoute が並ぶ。

    本テストの目的は「ルートが登録されていること」の検証であり、
    個別 APIRoute の内部構造に依存しないことが望ましいため、
    公開 API である ``app.openapi()`` の paths を正本として検証する。
    """
    spec = app.openapi()
    routes: set[tuple[str, tuple[str, ...]]] = set()
    for path, operations in spec.get("paths", {}).items():
        for method in operations:
            if method.lower() in {
                "get",
                "post",
                "put",
                "patch",
                "delete",
                "head",
                "options",
            }:
                routes.add((path, (method.upper(),)))
    return routes


def test_spec_compatible_case_routes_are_registered(app):
    routes = _collect_routes(app)
    assert ("/api/v1/cases", ("GET",)) in routes
    assert ("/api/v1/cases", ("POST",)) in routes
    assert ("/api/v1/cases/{receipt_no}", ("GET",)) in routes
    assert ("/api/v1/cases/{receipt_no}/submit", ("POST",)) in routes
    for action in (
        "confirm",
        "return",
        "resubmit",
        "forward",
        "approve",
        "judge-duplicate",
        "store",
    ):
        assert (f"/api/v1/cases/{{receipt_no}}/{action}", ("POST",)) in routes
