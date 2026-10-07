"""Q6(承認・証跡) / Q8(異常・復旧) 承認状態遷移の品質テスト。

対象仮説:
  H6 submit → approve / reject の状態遷移の正当性
  H7 二重承認 / 二重却下、並行実行での競合
  H8 承認操作に必要なロール(_require_management の適用範囲)

方針:
  services/workflow/tests の既存方式 (`create_app()` + `dependency_overrides` +
  TestClient、`src.middleware.auth.jwt` の patch) を踏襲。実 DB / 通知実送信なし。
  `@pytest.mark.xfail(strict=True)` は未修正の欠陥の証跡(成功ではない)。
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from src.main import create_app
from src.models.base import get_db
from src.models import WorkflowAuditLog, WorkflowStatusHistory
from src.services import approval_service, workflow_service

UTC = timezone.utc

ORG_A = UUID("00000000-0000-0000-0000-0000000000aa")
ORG_B = UUID("00000000-0000-0000-0000-0000000000bb")
USER_A = UUID("00000000-0000-0000-0000-0000000000cc")
USER_B = UUID("00000000-0000-0000-0000-0000000000cd")
DEF_ID = UUID("00000000-0000-0000-0000-0000000000ee")
INST_ID = UUID("00000000-0000-0000-0000-0000000000ff")

TOKEN_DEPT = {
    "sub": str(USER_A),
    "type": "user",
    "org": str(ORG_A),
    "roles": ["department_head"],
    "scopes": [],
}
TOKEN_ADMIN = {
    "sub": str(USER_A),
    "type": "user",
    "org": str(ORG_A),
    "roles": ["admin"],
    "scopes": [],
}


def _utcnow():
    return datetime.now(UTC)


def _auth_header() -> dict:
    # 実際の署名検証は patch した jwt.decode が担うため、形式のみ満たせばよい。
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
        self.definition_id = kwargs.get("definition_id", DEF_ID)
        self.organization_id = kwargs.get("organization_id", ORG_A)
        self.title = kwargs.get("title", "テスト稟議")
        self.description = kwargs.get("description", None)
        self.category = kwargs.get("category", "ringi")
        self.status = kwargs.get("status", "in_progress")
        self.priority = kwargs.get("priority", "normal")
        self.reference_type = kwargs.get("reference_type", None)
        self.reference_id = kwargs.get("reference_id", None)
        self.metadata_ = kwargs.get("metadata_", {})
        self.definition = kwargs.get("definition", None)
        self.submitted_by = kwargs.get("submitted_by", USER_A)
        self.submitted_at = kwargs.get("submitted_at", _utcnow())
        self.completed_at = kwargs.get("completed_at", None)
        self.duplicate_flag = kwargs.get("duplicate_flag", False)
        self.created_at = kwargs.get("created_at", _utcnow())
        self.updated_at = kwargs.get("updated_at", _utcnow())
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


def _db_for_approval(instance, approval):
    """approve_step/reject_step の execute 2 回 (instance, approval) を模す。"""
    db = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.execute = AsyncMock(
        side_effect=[_result_one(instance), _result_scalars_first(approval)]
    )
    return db


# ——— H6: 状態遷移の正当性 (service 層) ———


class TestApprovalTransitions:
    @pytest.mark.asyncio
    async def test_approve_first_of_two_steps_keeps_instance_in_progress(self):
        step1 = MockApproval(step_order=1, approver_role="department_head")
        step2 = MockApproval(step_order=2, approver_role="director")
        instance = MockInstance(approvals=[step1, step2])
        db = _db_for_approval(instance, step1)

        result = await approval_service.approve_step(
            db,
            instance_id=INST_ID,
            step_order=1,
            user_id=USER_A,
            user_roles=["department_head"],
            organization_id=ORG_A,
        )

        assert step1.status == "approved"
        assert step1.approver_id == USER_A
        assert step1.approved_at is not None
        assert result.status == "in_progress"
        assert result.completed_at is None
        assert instance.status_history == []

    @pytest.mark.asyncio
    async def test_approve_final_pending_step_marks_instance_approved_with_history(self):
        step1 = MockApproval(step_order=1, approver_role="department_head", status="approved")
        step2 = MockApproval(step_order=2, approver_role="director")
        instance = MockInstance(approvals=[step1, step2])
        db = _db_for_approval(instance, step2)

        result = await approval_service.approve_step(
            db,
            instance_id=INST_ID,
            step_order=2,
            user_id=USER_A,
            user_roles=["director"],
            organization_id=ORG_A,
        )

        assert result.status == "approved"
        assert result.completed_at is not None
        assert len(instance.status_history) == 1
        history = instance.status_history[0]
        assert history.to_status == "approved"
        assert history.from_status == "in_progress"
        assert history.changed_by == USER_A

    @pytest.mark.asyncio
    async def test_double_approve_same_step_is_rejected(self):
        """[H7] 同じ instance / step を 2 回承認できないこと。"""
        step1 = MockApproval(step_order=1, approver_role="department_head", status="approved")
        instance = MockInstance(approvals=[step1], status="approved")
        # 2 回目: instance は既に approved なので not in progress で拒否
        db = _db_for_approval(instance, step1)

        with pytest.raises(ValueError):
            await approval_service.approve_step(
                db,
                instance_id=INST_ID,
                step_order=1,
                user_id=USER_A,
                user_roles=["department_head"],
                organization_id=ORG_A,
            )
        assert step1.status == "approved"

    @pytest.mark.asyncio
    async def test_double_approve_when_step_no_longer_pending_is_rejected(self):
        """pending フィルタにより 2 回目は承認対象が見つからず拒否される。"""
        step1 = MockApproval(step_order=1, approver_role="department_head", status="approved")
        instance = MockInstance(approvals=[step1])
        db = AsyncMock()
        db.add = MagicMock()
        db.flush = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[_result_one(instance), _result_scalars_first(None)]
        )

        with pytest.raises(ValueError):
            await approval_service.approve_step(
                db,
                instance_id=INST_ID,
                step_order=1,
                user_id=USER_A,
                user_roles=["department_head"],
                organization_id=ORG_A,
            )

    @pytest.mark.asyncio
    async def test_approve_then_reject_on_same_step_is_rejected(self):
        step1 = MockApproval(step_order=1, approver_role="department_head", status="approved")
        instance = MockInstance(approvals=[step1], status="approved")
        db = _db_for_approval(instance, step1)

        with pytest.raises(ValueError):
            await approval_service.reject_step(
                db,
                instance_id=INST_ID,
                step_order=1,
                user_id=USER_A,
                user_roles=["department_head"],
                organization_id=ORG_A,
            )
        assert step1.status == "approved"

    @pytest.mark.asyncio
    async def test_reject_sets_instance_rejected_and_records_comment(self):
        step1 = MockApproval(step_order=1, approver_role="department_head")
        instance = MockInstance(approvals=[step1])
        db = _db_for_approval(instance, step1)

        result = await approval_service.reject_step(
            db,
            instance_id=INST_ID,
            step_order=1,
            user_id=USER_A,
            comment="記載不備",
            user_roles=["department_head"],
            organization_id=ORG_A,
        )

        assert result.status == "rejected"
        assert result.completed_at is not None
        assert step1.status == "rejected"
        assert step1.comment == "記載不備" and step1.approver_id == USER_A
        assert instance.status_history[-1].to_status == "rejected"
        assert instance.status_history[-1].comment == "記載不備"

    @pytest.mark.asyncio
    async def test_approve_non_current_step_is_rejected(self):
        step1 = MockApproval(step_order=1, approver_role="department_head")
        step2 = MockApproval(step_order=2, approver_role="director")
        instance = MockInstance(approvals=[step1, step2])
        db = _db_for_approval(instance, step2)

        with pytest.raises(ValueError, match="not the current step"):
            await approval_service.approve_step(
                db,
                instance_id=INST_ID,
                step_order=2,
                user_id=USER_A,
                user_roles=["director"],
                organization_id=ORG_A,
            )
        assert step2.status == "pending"

    @pytest.mark.asyncio
    async def test_approve_without_required_role_is_rejected(self):
        step1 = MockApproval(step_order=1, approver_role="department_head")
        instance = MockInstance(approvals=[step1])
        db = AsyncMock()
        db.add = MagicMock()
        db.flush = AsyncMock()
        # ロール不一致のため SQL 側で pending 承認がヒットしない
        db.execute = AsyncMock(
            side_effect=[_result_one(instance), _result_scalars_first(None)]
        )

        with pytest.raises(ValueError):
            await approval_service.approve_step(
                db,
                instance_id=INST_ID,
                step_order=1,
                user_id=USER_A,
                user_roles=["site_worker"],
                organization_id=ORG_A,
            )
        assert step1.status == "pending"

    @pytest.mark.asyncio
    async def test_approve_without_any_role_is_rejected(self):
        step1 = MockApproval(step_order=1, approver_role="department_head")
        instance = MockInstance(approvals=[step1])
        db = AsyncMock()
        db.add = MagicMock()
        db.flush = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[_result_one(instance), _result_scalars_first(None)]
        )

        with pytest.raises(ValueError):
            await approval_service.approve_step(
                db,
                instance_id=INST_ID,
                step_order=1,
                user_id=USER_A,
                user_roles=[],
                organization_id=ORG_A,
            )

    @pytest.mark.asyncio
    async def test_approve_finalized_instance_is_rejected(self):
        instance = MockInstance(status="rejected", approvals=[])
        db = _db_for_approval(instance, None)

        with pytest.raises(ValueError, match="not in progress"):
            await approval_service.approve_step(
                db,
                instance_id=INST_ID,
                step_order=1,
                user_id=USER_A,
                user_roles=["department_head"],
                organization_id=ORG_A,
            )

    @pytest.mark.asyncio
    async def test_reject_finalized_instance_is_rejected(self):
        instance = MockInstance(status="approved", approvals=[])
        db = _db_for_approval(instance, None)

        with pytest.raises(ValueError, match="not in progress"):
            await approval_service.reject_step(
                db,
                instance_id=INST_ID,
                step_order=1,
                user_id=USER_A,
                user_roles=["department_head"],
                organization_id=ORG_A,
            )

    @pytest.mark.asyncio
    async def test_approve_is_scoped_to_organization(self):
        """他組織の instance_id では承認できない(スコープ不一致 → not found)。"""
        db = AsyncMock()
        db.add = MagicMock()
        db.flush = AsyncMock()
        captured = {}

        async def _execute(stmt):
            captured.setdefault("stmt", stmt)
            return _result_one(None)

        db.execute = _execute

        with pytest.raises(ValueError, match="not found"):
            await approval_service.approve_step(
                db,
                instance_id=INST_ID,
                step_order=1,
                user_id=USER_A,
                user_roles=["department_head"],
                organization_id=ORG_B,
            )
        where = str(captured["stmt"]).split("WHERE", 1)[-1]
        assert "organization_id" in where

    def test_can_user_approve_requires_matching_role(self):
        approval = MockApproval(approver_role="director")
        assert approval_service.can_user_approve(approval, ["director"]) is True
        assert approval_service.can_user_approve(approval, ["department_head"]) is False
        assert approval_service.can_user_approve(approval, []) is False


# ——— H7: 並行実行(二重承認)の競合 — 静的根拠 ———


class TestConcurrencyGap:
    def test_defect_no_row_lock_on_approval_read(self):
        """[欠陥・静的根拠] 承認読み取りに SELECT ... FOR UPDATE が無い。

        `_get_approval` / `_get_scoped_instance` は行ロックを取らないため、
        同一 step への同時 approve が両方とも status='pending' を読んで
        双方成功しうる(二重承認・approved_at/approver_id の上書き)。
        ここでは行ロックが存在しないことをソース上で確認する。
        実行時(timing 依存)の再現は未確認であり、成功として扱わない。
        """
        from pathlib import Path

        src = (
            Path(__file__).resolve().parents[1]
            / "src"
            / "services"
            / "approval_service.py"
        ).read_text(encoding="utf-8")
        assert "with_for_update" not in src, (
            "行ロックが導入された: 欠陥が修正された可能性があるためマーカーを見直すこと"
        )

    @pytest.mark.asyncio
    @pytest.mark.xfail(
        strict=True,
        reason="DEFECT-WF-1: 行ロック/楽観的排他が無く同時 approve が双方成功しうる",
    )
    async def test_defect_concurrent_approve_both_succeed(self):
        """[欠陥] 先行トランザクションが未コミットの間、同一 step を二重承認できる。

        2 セッションが同じ pending 承認行を別スナップショットとして読む状況を
        モデル化する(SQL は status='pending' で絞るがロックも条件付き UPDATE も無い)。
        実行時(timing 依存)の再現ではなく、排他制御が存在しないことの白箱根拠。
        """
        snapshot_a = MockApproval(step_order=1, approver_role="department_head")
        snapshot_b = MockApproval(step_order=1, approver_role="department_head")
        db_a = _db_for_approval(MockInstance(approvals=[snapshot_a]), snapshot_a)
        db_b = _db_for_approval(MockInstance(approvals=[snapshot_b]), snapshot_b)

        first = await approval_service.approve_step(
            db_a,
            instance_id=INST_ID,
            step_order=1,
            user_id=USER_A,
            user_roles=["department_head"],
            organization_id=ORG_A,
        )
        with pytest.raises(ValueError):
            await approval_service.approve_step(
                db_b,
                instance_id=INST_ID,
                step_order=1,
                user_id=USER_B,
                user_roles=["department_head"],
                organization_id=ORG_A,
            )
        assert first.status == "approved"


# ——— H6 / H8: API 経由の状態遷移とロール ———


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


class TestApprovalApi:
    @pytest.mark.parametrize(
        "method,path,body",
        [
            ("post", f"/api/v1/workflow/instances/{INST_ID}/submit", None),
            ("post", f"/api/v1/workflow/instances/{INST_ID}/approve?step_order=1", None),
            ("post", f"/api/v1/workflow/instances/{INST_ID}/reject?step_order=1", None),
            ("post", f"/api/v1/workflow/instances/{INST_ID}/resubmit", None),
            ("post", f"/api/v1/workflow/instances/{INST_ID}/cancel", None),
        ],
    )
    def test_action_endpoints_require_auth(self, client, method, path, body):
        response = client.request(method.upper(), path, json=body)
        assert response.status_code == 401

    @patch("src.middleware.auth.jwt")
    def test_submit_non_draft_is_rejected(self, mock_jwt, app):
        mock_jwt.decode.return_value = TOKEN_DEPT
        instance = MockInstance(status="in_progress")
        with patch.object(
            workflow_service, "get_instance_with_chain", AsyncMock(return_value=instance)
        ):
            response = TestClient(app).post(
                f"/api/v1/workflow/instances/{INST_ID}/submit",
                headers=_auth_header(),
            )
        assert response.status_code == 400
        assert response.json()["detail"]["code"] == "BAD_REQUEST"

    @patch("src.middleware.auth.jwt")
    def test_submit_by_non_submitter_is_rejected(self, mock_jwt, app):
        mock_jwt.decode.return_value = {**TOKEN_DEPT, "sub": str(USER_B)}
        instance = MockInstance(status="draft", submitted_by=USER_A)
        with patch.object(
            workflow_service, "get_instance_with_chain", AsyncMock(return_value=instance)
        ):
            response = TestClient(app).post(
                f"/api/v1/workflow/instances/{INST_ID}/submit",
                headers=_auth_header(),
            )
        assert response.status_code == 400

    @patch("src.middleware.auth.jwt")
    def test_admin_without_step_role_cannot_approve(self, mock_jwt, app):
        """[H8] admin ロールだけでは承認ステップを飛ばせない(権限昇格不可)。"""
        mock_jwt.decode.return_value = TOKEN_ADMIN
        app.state.mock_db.execute = AsyncMock(
            side_effect=[_result_one(MockInstance(approvals=[])), _result_scalars_first(None)]
        )
        response = TestClient(app).post(
            f"/api/v1/workflow/instances/{INST_ID}/approve?step_order=1",
            headers=_auth_header(),
        )
        assert response.status_code == 400

    @patch("src.middleware.auth.jwt")
    def test_approve_is_role_based_not_management_gated(self, mock_jwt, app):
        """[H8] 承認は _require_management ではなくステップの approver_role で判定される。

        設計確認: department_head を持つトークンは admin/management 無しで承認できる。
        """
        mock_jwt.decode.return_value = TOKEN_DEPT
        step1 = MockApproval(step_order=1, approver_role="department_head")
        instance = MockInstance(approvals=[step1])
        app.state.mock_db.execute = AsyncMock(
            side_effect=[_result_one(instance), _result_scalars_first(step1)]
        )
        response = TestClient(app).post(
            f"/api/v1/workflow/instances/{INST_ID}/approve?step_order=1",
            headers=_auth_header(),
        )
        assert response.status_code == 200
        assert step1.status == "approved"

    @patch("src.middleware.auth.jwt")
    def test_approve_duplicate_step_returns_400(self, mock_jwt, app):
        """[H7] 同じ step への 2 回目の approve は 400 で拒否される。"""
        mock_jwt.decode.return_value = TOKEN_DEPT
        instance = MockInstance(approvals=[])
        app.state.mock_db.execute = AsyncMock(
            side_effect=[_result_one(instance), _result_scalars_first(None)]
        )
        response = TestClient(app).post(
            f"/api/v1/workflow/instances/{INST_ID}/approve?step_order=1",
            headers=_auth_header(),
        )
        assert response.status_code == 400

    @patch("src.middleware.auth.jwt")
    def test_reject_non_current_step_returns_400(self, mock_jwt, app):
        mock_jwt.decode.return_value = TOKEN_DEPT
        step1 = MockApproval(step_order=1, approver_role="department_head")
        step2 = MockApproval(step_order=2, approver_role="department_head")
        instance = MockInstance(approvals=[step1, step2])
        app.state.mock_db.execute = AsyncMock(
            side_effect=[_result_one(instance), _result_scalars_first(step2)]
        )
        response = TestClient(app).post(
            f"/api/v1/workflow/instances/{INST_ID}/reject?step_order=2",
            headers=_auth_header(),
        )
        assert response.status_code == 400
        assert step2.status == "pending"

    @patch("src.middleware.auth.jwt")
    def test_cancel_after_approval_is_rejected(self, mock_jwt, app):
        mock_jwt.decode.return_value = TOKEN_DEPT
        instance = MockInstance(status="approved")
        with patch.object(
            workflow_service, "get_instance_with_chain", AsyncMock(return_value=instance)
        ):
            response = TestClient(app).post(
                f"/api/v1/workflow/instances/{INST_ID}/cancel",
                headers=_auth_header(),
            )
        assert response.status_code == 400

    @patch("src.middleware.auth.jwt")
    def test_resubmit_only_from_rejected(self, mock_jwt, app):
        mock_jwt.decode.return_value = TOKEN_DEPT
        instance = MockInstance(status="in_progress")
        with patch.object(
            workflow_service, "get_instance_with_chain", AsyncMock(return_value=instance)
        ):
            response = TestClient(app).post(
                f"/api/v1/workflow/instances/{INST_ID}/resubmit",
                headers=_auth_header(),
            )
        assert response.status_code == 400

    @patch("src.middleware.auth.jwt")
    def test_resubmit_from_rejected_resets_approvals(self, mock_jwt, app):
        """却下 → 再提出で承認が pending に戻り、却下コメントが履歴へ残る。"""
        mock_jwt.decode.return_value = TOKEN_DEPT
        step1 = MockApproval(
            step_order=1,
            approver_role="department_head",
            status="rejected",
            approver_id=USER_B,
            comment="不備",
        )
        instance = MockInstance(status="rejected", approvals=[step1], completed_at=_utcnow())
        with patch.object(
            workflow_service, "get_instance_with_chain", AsyncMock(return_value=instance)
        ):
            response = TestClient(app).post(
                f"/api/v1/workflow/instances/{INST_ID}/resubmit",
                headers=_auth_header(),
            )
        assert response.status_code == 200
        assert instance.status == "in_progress"
        assert instance.completed_at is None
        assert step1.status == "pending" and step1.approver_id is None
        assert instance.status_history[-1].to_status == "in_progress"
        assert instance.status_history[-1].comment == "不備"

    @patch("src.middleware.auth.jwt")
    def test_missing_org_claim_is_forbidden(self, mock_jwt, app):
        mock_jwt.decode.return_value = {**TOKEN_DEPT, "org": None}
        response = TestClient(app).post(
            f"/api/v1/workflow/instances/{INST_ID}/approve?step_order=1",
            headers=_auth_header(),
        )
        assert response.status_code == 403
        assert response.json()["detail"]["code"] == "ORG_REQUIRED"

    def test_approval_records_status_history_object(self):
        """_record_status_change が WorkflowStatusHistory を db.add すること。"""
        instance = MockInstance()
        db = AsyncMock()
        db.add = MagicMock()
        workflow_service._record_status_change(
            db, instance, "in_progress", "approved", USER_A, "ok"
        )
        added = db.add.call_args.args[0]
        assert isinstance(added, WorkflowStatusHistory)
        assert added.to_status == "approved"
        assert added.changed_by == USER_A
        assert added.comment == "ok"
