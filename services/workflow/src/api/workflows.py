"""ワークフローAPI エンドポイント"""

import secrets
from typing import Literal
from uuid import UUID

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    Header,
    HTTPException,
    Query,
    status,
)
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..middleware.auth import (
    MANAGEMENT_ROLES,
    TokenData,
    get_current_user,
    require_any_role,
)
from ..models import WorkflowAuditLog
from ..models.base import get_db
from ..schemas import (
    APIResponse,
    ApprovalAction,
    WorkflowDefinitionCreate,
    WorkflowDefinitionUpdate,
    WorkflowInstanceCreate,
    WorkflowInstanceUpdate,
    WorkflowInquiryAnswer,
    WorkflowInquiryCreate,
)
from ..services import approval_service, workflow_service
from ..services.check_service import SubmissionValidationError
from ..services.notification_adapter import (
    resolve_notification_recipients,
    send_workflow_notification,
    send_workflow_notifications,
)
from ..services.document_adapter import (
    store_workflow_documents,
    store_workflow_work_area,
)
from ..config import get_settings
from ..jobs.deadline_notifications import notify_deadlines
from ..jobs.workload_notifications import notify_workload_alerts

router = APIRouter()

_LEGACY_MANAGEMENT_ROLES = {"admin", "management"}


def _require_management(current_user: TokenData) -> None:
    if not _LEGACY_MANAGEMENT_ROLES.intersection(current_user.roles):
        raise HTTPException(
            status_code=403,
            detail={"code": "FORBIDDEN", "message": "管理部権限が必要です。"},
        )


class NotificationCallback(BaseModel):
    workflow_instance_id: UUID
    notification_id: int
    idempotency_key: str
    event: Literal["opened", "read", "responded", "acknowledged"]
    response: str | None = None
    occurred_at: str | None = None


def _deadline_value(instance) -> str:
    due_date = getattr(instance, "due_date", None)
    return due_date.isoformat() if due_date is not None else ""


async def require_internal_job_key(
    x_internal_api_key: str | None = Header(default=None),
) -> None:
    configured_key = get_settings().INTERNAL_JOB_API_KEY
    if (
        not configured_key
        or not x_internal_api_key
        or not secrets.compare_digest(x_internal_api_key, configured_key)
    ):
        raise HTTPException(
            status_code=403,
            detail={
                "code": "INTERNAL_AUTH_REQUIRED",
                "message": "内部認証が必要です。",
            },
        )


def _organization_id(current_user: TokenData) -> UUID:
    if not current_user.org:
        raise HTTPException(
            status_code=403,
            detail={
                "code": "ORG_REQUIRED",
                "message": "組織情報がないトークンは利用できません。",
            },
        )
    try:
        return UUID(current_user.org)
    except ValueError as exc:
        raise HTTPException(
            status_code=403,
            detail={"code": "ORG_INVALID", "message": "トークンの組織情報が無効です。"},
        ) from exc


@router.post(
    "/internal/jobs/deadline-notifications",
    dependencies=[Depends(require_internal_job_key)],
)
async def run_deadline_notifications(db: AsyncSession = Depends(get_db)):
    sent, skipped, failed = await notify_deadlines(db)
    return APIResponse(data={"sent": sent, "skipped": skipped, "failed": failed})


@router.post(
    "/internal/jobs/workload-notifications",
    dependencies=[Depends(require_internal_job_key)],
)
async def run_workload_notifications(db: AsyncSession = Depends(get_db)):
    sent, skipped = await notify_workload_alerts(db)
    return APIResponse(data={"sent": sent, "skipped": skipped})


@router.post(
    "/internal/notification-callback",
    dependencies=[Depends(require_internal_job_key)],
)
async def receive_notification_callback(
    body: NotificationCallback,
    db: AsyncSession = Depends(get_db),
):
    existing = await db.execute(
        select(WorkflowAuditLog).where(
            WorkflowAuditLog.event_type == "workflow.notification.callback",
            WorkflowAuditLog.event_data.contains(
                {"idempotency_key": body.idempotency_key}
            ),
        )
    )
    if existing.scalar_one_or_none() is not None:
        return APIResponse(data={"recorded": False, "duplicate": True})
    workflow_service.record_audit_log(
        db,
        user_id=None,
        event_type="workflow.notification.callback",
        event_data=body.model_dump(mode="json"),
    )
    await db.commit()
    return APIResponse(data={"recorded": True, "duplicate": False})


def _definition_to_response(d) -> dict:
    return {
        "id": str(d.id),
        "organization_id": str(d.organization_id),
        "name": d.name,
        "description": d.description,
        "category": d.category,
        "steps": d.steps if isinstance(d.steps, list) else [],
        "check_rules": d.check_rules if isinstance(d.check_rules, dict) else {},
        "is_active": d.is_active,
        "created_by": str(d.created_by) if d.created_by else None,
        "created_at": d.created_at.isoformat() if d.created_at else None,
        "updated_at": d.updated_at.isoformat() if d.updated_at else None,
    }


def _instance_to_response(instance) -> dict:
    result = {
        "id": str(instance.id),
        "receipt_no": getattr(instance, "receipt_no", None),
        "definition_id": str(instance.definition_id)
        if instance.definition_id
        else None,
        "organization_id": str(instance.organization_id),
        "title": instance.title,
        "description": instance.description,
        "category": instance.category,
        "status": instance.status,
        "priority": instance.priority,
        "reference_type": instance.reference_type,
        "reference_id": str(instance.reference_id) if instance.reference_id else None,
        "metadata": instance.metadata_ if isinstance(instance.metadata_, dict) else {},
        "submitted_by": str(instance.submitted_by),
        "due_date": (
            instance.due_date.isoformat()
            if getattr(instance, "due_date", None)
            else None
        ),
        "submitted_at": instance.submitted_at.isoformat()
        if instance.submitted_at
        else None,
        "completed_at": instance.completed_at.isoformat()
        if instance.completed_at
        else None,
        "duplicate_flag": getattr(instance, "duplicate_flag", False),
        "canonical_stored_at": (
            instance.canonical_stored_at.isoformat()
            if getattr(instance, "canonical_stored_at", None)
            else None
        ),
        "canonical_error": getattr(instance, "canonical_error", None),
        "created_at": instance.created_at.isoformat() if instance.created_at else None,
        "updated_at": instance.updated_at.isoformat() if instance.updated_at else None,
    }
    if hasattr(instance, "approvals"):
        result["approvals"] = [_approval_to_response(a) for a in instance.approvals]
    if hasattr(instance, "status_history"):
        result["status_history"] = [
            _history_to_response(h) for h in instance.status_history
        ]
    return result


def _approval_to_response(a) -> dict:
    return {
        "id": str(a.id),
        "instance_id": str(a.instance_id),
        "step_order": a.step_order,
        "approver_id": str(a.approver_id) if a.approver_id else None,
        "approver_role": a.approver_role,
        "status": a.status,
        "comment": a.comment,
        "approved_at": a.approved_at.isoformat() if a.approved_at else None,
        "created_at": a.created_at.isoformat() if a.created_at else None,
    }


def _history_to_response(h) -> dict:
    return {
        "id": str(h.id),
        "instance_id": str(h.instance_id),
        "from_status": h.from_status,
        "to_status": h.to_status,
        "changed_by": str(h.changed_by),
        "comment": h.comment,
        "created_at": h.created_at.isoformat() if h.created_at else None,
    }


def _inquiry_to_response(inquiry) -> dict:
    return {
        "id": str(inquiry.id),
        "instance_id": str(inquiry.instance_id),
        "organization_id": str(inquiry.organization_id),
        "question": inquiry.question,
        "answer": inquiry.answer,
        "channel": inquiry.channel,
        "status": inquiry.status,
        "asked_by": str(inquiry.asked_by),
        "answered_by": str(inquiry.answered_by) if inquiry.answered_by else None,
        "created_at": inquiry.created_at.isoformat() if inquiry.created_at else None,
        "answered_at": inquiry.answered_at.isoformat() if inquiry.answered_at else None,
    }


# ——— Workflow Definitions ———


@router.post("/definitions", status_code=status.HTTP_201_CREATED)
async def create_definition(
    body: WorkflowDefinitionCreate,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    organization_id = _organization_id(current_user)
    _require_management(current_user)
    if body.organization_id != organization_id:
        raise HTTPException(
            status_code=403,
            detail={"code": "ORG_FORBIDDEN", "message": "組織が一致しません。"},
        )
    steps = [s.model_dump() for s in body.steps]
    definition = await workflow_service.create_definition(
        db,
        organization_id=body.organization_id,
        name=body.name,
        description=body.description,
        category=body.category,
        steps=steps,
        check_rules=body.check_rules,
        created_by=UUID(current_user.sub),
    )
    workflow_service.record_audit_log(
        db,
        user_id=UUID(current_user.sub),
        event_type="workflow.definition.create",
        event_data={"definition_id": str(definition.id)},
    )
    await db.commit()
    return APIResponse(data=_definition_to_response(definition))


@router.get("/definitions")
async def list_definitions(
    organization_id: UUID | None = Query(None),
    category: str | None = Query(None),
    is_active: bool | None = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    authenticated_org = _organization_id(current_user)
    if organization_id is not None and organization_id != authenticated_org:
        raise HTTPException(
            status_code=403,
            detail={"code": "ORG_FORBIDDEN", "message": "組織が一致しません。"},
        )
    definitions = await workflow_service.get_definitions(
        db,
        organization_id=authenticated_org,
        category=category,
        is_active=is_active,
    )
    return APIResponse(data=[_definition_to_response(d) for d in definitions])


@router.patch("/definitions/{definition_id}")
async def update_definition(
    definition_id: UUID,
    body: WorkflowDefinitionUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    organization_id = _organization_id(current_user)
    _require_management(current_user)
    try:
        definition = await workflow_service.update_definition(
            db,
            definition_id,
            organization_id,
            {
                **body.model_dump(exclude_unset=True),
                "steps": (
                    [step.model_dump() for step in body.steps]
                    if body.steps is not None
                    else None
                ),
            },
        )
        workflow_service.record_audit_log(
            db,
            user_id=UUID(current_user.sub),
            event_type="workflow.definition.update",
            event_data={"definition_id": str(definition_id)},
        )
        await db.commit()
        return APIResponse(data=_definition_to_response(definition))
    except ValueError as e:
        raise HTTPException(
            status_code=400, detail={"code": "BAD_REQUEST", "message": str(e)}
        )


@router.delete("/definitions/{definition_id}")
async def deactivate_definition(
    definition_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    organization_id = _organization_id(current_user)
    require_any_role(current_user, MANAGEMENT_ROLES)  # 削除には管理ロールを要求する
    try:
        definition = await workflow_service.update_definition(
            db, definition_id, organization_id, {"is_active": False}
        )
        workflow_service.record_audit_log(
            db,
            user_id=UUID(current_user.sub),
            event_type="workflow.definition.deactivate",
            event_data={"definition_id": str(definition_id)},
        )
        await db.commit()
        return APIResponse(data=_definition_to_response(definition))
    except ValueError as e:
        raise HTTPException(
            status_code=400, detail={"code": "BAD_REQUEST", "message": str(e)}
        )


# ——— Workflow Instances ———


@router.post("/instances", status_code=status.HTTP_201_CREATED)
async def create_instance(
    body: WorkflowInstanceCreate,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    organization_id = _organization_id(current_user)
    if body.organization_id != organization_id:
        raise HTTPException(
            status_code=403,
            detail={"code": "ORG_FORBIDDEN", "message": "組織が一致しません。"},
        )
    try:
        instance = await workflow_service.start_workflow(
            db,
            definition_id=body.definition_id,
            submitted_by=UUID(current_user.sub),
            organization_id=body.organization_id,
            title=body.title,
            description=body.description,
            priority=body.priority,
            reference_type=body.reference_type,
            reference_id=body.reference_id,
            metadata=body.metadata,
        )
        instance_full = await workflow_service.get_instance_with_chain(
            db, instance.id, organization_id
        )
        workflow_service.record_audit_log(
            db,
            user_id=UUID(current_user.sub),
            event_type="workflow.instance.create",
            event_data={
                "instance_id": str(instance.id),
                "receipt_no": instance.receipt_no,
            },
        )
        await db.commit()
        data = _instance_to_response(instance_full)
        return APIResponse(data=data)
    except ValueError as e:
        raise HTTPException(
            status_code=400, detail={"code": "BAD_REQUEST", "message": str(e)}
        )


@router.get("/instances")
async def list_instances(
    organization_id: UUID | None = Query(None),
    status: str | None = Query(None),
    category: str | None = Query(None),
    submitted_by: UUID | None = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    authenticated_org = _organization_id(current_user)
    if organization_id is not None and organization_id != authenticated_org:
        raise HTTPException(
            status_code=403,
            detail={"code": "ORG_FORBIDDEN", "message": "組織が一致しません。"},
        )
    instances = await workflow_service.get_instances(
        db,
        organization_id=authenticated_org,
        status=status,
        category=category,
        submitted_by=submitted_by,
    )
    instances = [
        instance
        for instance in instances
        if workflow_service.can_view_instance(
            instance, UUID(current_user.sub), current_user.roles
        )
    ]
    return APIResponse(data=[_instance_to_response(i) for i in instances])


@router.get("/instances/pending")
async def get_pending_approvals(
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    organization_id = _organization_id(current_user)
    instances = await workflow_service.get_pending_approvals(
        db, user_roles=current_user.roles, organization_id=organization_id
    )
    return APIResponse(data=[_instance_to_response(i) for i in instances])


@router.get("/instances/{instance_id}")
async def get_instance(
    instance_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    organization_id = _organization_id(current_user)
    instance = await workflow_service.get_instance_with_chain(
        db, instance_id, organization_id
    )
    if not instance:
        raise HTTPException(
            status_code=404,
            detail={"code": "NOT_FOUND", "message": "ワークフローが見つかりません。"},
        )
    if not workflow_service.can_view_instance(
        instance, UUID(current_user.sub), current_user.roles
    ):
        raise HTTPException(
            status_code=404,
            detail={"code": "NOT_FOUND", "message": "ワークフローが見つかりません。"},
        )
    data = _instance_to_response(instance)
    data["approvals"] = [_approval_to_response(a) for a in instance.approvals]
    return APIResponse(data=data)


@router.patch("/instances/{instance_id}")
async def update_instance(
    instance_id: UUID,
    body: WorkflowInstanceUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    organization_id = _organization_id(current_user)
    try:
        instance = await workflow_service.get_instance_with_chain(
            db, instance_id, organization_id
        )
        if not instance:
            raise ValueError(f"Workflow instance {instance_id} not found")
        if not workflow_service.can_view_instance(
            instance, UUID(current_user.sub), current_user.roles
        ):
            raise ValueError(f"Workflow instance {instance_id} not found")
        instance = await workflow_service.update_workflow_draft(
            db,
            instance_id,
            UUID(current_user.sub),
            title=body.title,
            description=body.description,
            metadata=body.metadata,
        )
        workflow_service.record_audit_log(
            db,
            user_id=UUID(current_user.sub),
            event_type="workflow.instance.update",
            event_data={"instance_id": str(instance_id)},
        )
        await db.commit()
        return APIResponse(data=_instance_to_response(instance))
    except ValueError as e:
        raise HTTPException(
            status_code=400, detail={"code": "BAD_REQUEST", "message": str(e)}
        )


@router.get("/instances/{instance_id}/history")
async def get_history(
    instance_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    organization_id = _organization_id(current_user)
    instance = await workflow_service.get_instance_with_chain(
        db, instance_id, organization_id
    )
    if not instance:
        raise HTTPException(
            status_code=404,
            detail={"code": "NOT_FOUND", "message": "ワークフローが見つかりません。"},
        )
    if not workflow_service.can_view_instance(
        instance, UUID(current_user.sub), current_user.roles
    ):
        raise HTTPException(
            status_code=404,
            detail={"code": "NOT_FOUND", "message": "ワークフローが見つかりません。"},
        )
    return APIResponse(
        data=[_history_to_response(h) for h in getattr(instance, "status_history", [])]
    )


@router.post("/instances/{instance_id}/inquiries", status_code=status.HTTP_201_CREATED)
async def create_instance_inquiry(
    instance_id: UUID,
    body: WorkflowInquiryCreate,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    organization_id = _organization_id(current_user)
    instance = await workflow_service.get_instance_with_chain(
        db, instance_id, _organization_id(current_user)
    )
    if not instance or not workflow_service.can_view_instance(
        instance, UUID(current_user.sub), current_user.roles
    ):
        raise HTTPException(
            status_code=404,
            detail={"code": "NOT_FOUND", "message": "ワークフローが見つかりません。"},
        )
    try:
        inquiry = await workflow_service.create_inquiry(
            db,
            instance_id,
            _organization_id(current_user),
            UUID(current_user.sub),
            body.question,
            body.channel,
        )
        workflow_service.record_audit_log(
            db,
            user_id=UUID(current_user.sub),
            event_type="workflow.inquiry.create",
            event_data={"instance_id": str(instance_id)},
        )
        await db.commit()
        recipients = await resolve_notification_recipients(
            organization_id=organization_id,
            roles={"management", "admin"},
        )
        background_tasks.add_task(
            send_workflow_notifications,
            recipient_ids=recipients,
            template_code="workflow.inquiry",
            instance_id=instance.id,
            transition="inquiry",
            actor_id=UUID(current_user.sub),
            template_vars={
                "document_name": instance.title,
                "requester_name": str(current_user.sub),
                "deadline": _deadline_value(instance),
                "comment": body.question,
            },
        )
        return APIResponse(data=_inquiry_to_response(inquiry))
    except ValueError as e:
        raise HTTPException(
            status_code=404, detail={"code": "NOT_FOUND", "message": str(e)}
        )


@router.get("/instances/{instance_id}/inquiries")
async def list_instance_inquiries(
    instance_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    instance = await workflow_service.get_instance_with_chain(
        db, instance_id, _organization_id(current_user)
    )
    if not instance or not workflow_service.can_view_instance(
        instance, UUID(current_user.sub), current_user.roles
    ):
        raise HTTPException(
            status_code=404,
            detail={"code": "NOT_FOUND", "message": "ワークフローが見つかりません。"},
        )
    try:
        inquiries = await workflow_service.get_inquiries(
            db, instance_id, _organization_id(current_user)
        )
        return APIResponse(data=[_inquiry_to_response(i) for i in inquiries])
    except ValueError as e:
        raise HTTPException(
            status_code=404, detail={"code": "NOT_FOUND", "message": str(e)}
        )


@router.post("/instances/{instance_id}/inquiries/{inquiry_id}/answer")
async def answer_instance_inquiry(
    instance_id: UUID,
    inquiry_id: UUID,
    body: WorkflowInquiryAnswer,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    if not {"admin", "management"}.intersection(current_user.roles):
        raise HTTPException(
            status_code=403,
            detail={"code": "FORBIDDEN", "message": "管理部権限が必要です。"},
        )
    try:
        inquiry = await workflow_service.answer_inquiry(
            db,
            inquiry_id,
            instance_id,
            _organization_id(current_user),
            UUID(current_user.sub),
            body.answer,
        )
        workflow_service.record_audit_log(
            db,
            user_id=UUID(current_user.sub),
            event_type="workflow.inquiry.answer",
            event_data={"instance_id": str(instance_id), "inquiry_id": str(inquiry_id)},
        )
        await db.commit()
        return APIResponse(data=_inquiry_to_response(inquiry))
    except ValueError as e:
        raise HTTPException(
            status_code=400, detail={"code": "BAD_REQUEST", "message": str(e)}
        )


# ——— Workflow Actions ———


@router.post("/instances/{instance_id}/submit")
async def submit_instance(
    instance_id: UUID,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    organization_id = _organization_id(current_user)
    try:
        instance = await workflow_service.get_instance_with_chain(
            db, instance_id, organization_id
        )
        if not instance:
            raise ValueError(f"Workflow instance {instance_id} not found")
        instance = await workflow_service.submit_workflow(
            db, instance_id, UUID(current_user.sub)
        )
        workflow_service.record_audit_log(
            db,
            user_id=UUID(current_user.sub),
            event_type="workflow.instance.submit",
            event_data={
                "instance_id": str(instance_id),
                "receipt_no": instance.receipt_no,
            },
        )
        await db.commit()
        document_ids = (
            instance.metadata_.get("attachment_document_ids", [])
            if isinstance(instance.metadata_, dict)
            else []
        )
        if isinstance(document_ids, list) and document_ids and instance.receipt_no:
            background_tasks.add_task(
                store_workflow_work_area,
                document_ids=document_ids,
                organization_id=organization_id,
                receipt_no=instance.receipt_no,
            )
        approval_roles = {
            approval.approver_role
            for approval in getattr(instance, "approvals", [])
            if getattr(approval, "status", "pending") == "pending"
        }
        recipients = await resolve_notification_recipients(
            organization_id=organization_id, roles=approval_roles
        )
        background_tasks.add_task(
            send_workflow_notifications,
            recipient_ids=recipients,
            template_code="workflow.approval_requested",
            instance_id=instance.id,
            transition="submitted",
            actor_id=UUID(current_user.sub),
            template_vars={
                "document_name": instance.title,
                "requester_name": str(current_user.sub),
                "deadline": _deadline_value(instance),
                "comment": "",
            },
        )
        return APIResponse(data=_instance_to_response(instance))
    except SubmissionValidationError as e:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "VALIDATION_ERROR",
                "message": str(e),
                "errors": e.errors,
                "warnings": e.warnings,
            },
        )
    except ValueError as e:
        raise HTTPException(
            status_code=400, detail={"code": "BAD_REQUEST", "message": str(e)}
        )


@router.post("/instances/{instance_id}/resubmit")
async def resubmit_instance(
    instance_id: UUID,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    organization_id = _organization_id(current_user)
    try:
        instance = await workflow_service.get_instance_with_chain(
            db, instance_id, organization_id
        )
        if not instance:
            raise ValueError(f"Workflow instance {instance_id} not found")
        instance = await workflow_service.resubmit_workflow(
            db, instance_id, UUID(current_user.sub)
        )
        workflow_service.record_audit_log(
            db,
            user_id=UUID(current_user.sub),
            event_type="workflow.instance.resubmit",
            event_data={
                "instance_id": str(instance_id),
                "receipt_no": instance.receipt_no,
            },
        )
        await db.commit()
        recipients = await resolve_notification_recipients(
            organization_id=organization_id,
            roles={"management", "admin"},
        )
        background_tasks.add_task(
            send_workflow_notifications,
            recipient_ids=recipients,
            template_code="workflow.resubmitted",
            instance_id=instance.id,
            transition="resubmitted",
            actor_id=UUID(current_user.sub),
            template_vars={
                "document_name": instance.title,
                "requester_name": str(current_user.sub),
                "deadline": _deadline_value(instance),
                "comment": "",
            },
        )
        return APIResponse(data=_instance_to_response(instance))
    except ValueError as e:
        raise HTTPException(
            status_code=400, detail={"code": "BAD_REQUEST", "message": str(e)}
        )


@router.post("/instances/{instance_id}/approve")
async def approve_step(
    instance_id: UUID,
    background_tasks: BackgroundTasks,
    step_order: int = Query(..., description="Approval step order to approve"),
    body: ApprovalAction | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    organization_id = _organization_id(current_user)
    try:
        comment = body.comment if body else None
        instance = await approval_service.approve_step(
            db,
            instance_id=instance_id,
            step_order=step_order,
            user_id=UUID(current_user.sub),
            comment=comment,
            user_roles=current_user.roles,
            organization_id=organization_id,
        )
        workflow_service.record_audit_log(
            db,
            user_id=UUID(current_user.sub),
            event_type="workflow.approval.approve",
            event_data={"instance_id": str(instance_id), "step_order": step_order},
        )
        await db.commit()
        background_tasks.add_task(
            send_workflow_notification,
            recipient_id=instance.submitted_by,
            template_code="workflow.approved",
            instance_id=instance.id,
            transition="approved",
            actor_id=UUID(current_user.sub),
            template_vars={
                "document_name": instance.title,
                "comment": comment or "",
            },
        )
        document_ids = (
            instance.metadata_.get("attachment_document_ids", [])
            if isinstance(instance.metadata_, dict)
            else []
        )
        if instance.status == "approved" and isinstance(document_ids, list):
            background_tasks.add_task(
                store_workflow_documents,
                document_ids=document_ids,
                organization_id=organization_id,
            )
        return APIResponse(data=_instance_to_response(instance))
    except ValueError as e:
        raise HTTPException(
            status_code=400, detail={"code": "BAD_REQUEST", "message": str(e)}
        )


@router.post("/instances/{instance_id}/reject")
async def reject_step(
    instance_id: UUID,
    background_tasks: BackgroundTasks,
    step_order: int = Query(..., description="Approval step order to reject"),
    body: ApprovalAction | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    organization_id = _organization_id(current_user)
    try:
        comment = body.comment if body else None
        instance = await approval_service.reject_step(
            db,
            instance_id=instance_id,
            step_order=step_order,
            user_id=UUID(current_user.sub),
            comment=comment,
            user_roles=current_user.roles,
            organization_id=organization_id,
        )
        workflow_service.record_audit_log(
            db,
            user_id=UUID(current_user.sub),
            event_type="workflow.approval.reject",
            event_data={"instance_id": str(instance_id), "step_order": step_order},
        )
        await db.commit()
        background_tasks.add_task(
            send_workflow_notification,
            recipient_id=instance.submitted_by,
            template_code="workflow.rejected",
            instance_id=instance.id,
            transition="rejected",
            actor_id=UUID(current_user.sub),
            template_vars={
                "document_name": instance.title,
                "comment": comment or "",
            },
        )
        return APIResponse(data=_instance_to_response(instance))
    except ValueError as e:
        raise HTTPException(
            status_code=400, detail={"code": "BAD_REQUEST", "message": str(e)}
        )


@router.post("/instances/{instance_id}/cancel")
async def cancel_instance(
    instance_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    organization_id = _organization_id(current_user)
    try:
        instance = await workflow_service.get_instance_with_chain(
            db, instance_id, organization_id
        )
        if not instance:
            raise ValueError(f"Workflow instance {instance_id} not found")
        instance = await workflow_service.cancel_workflow(
            db, instance_id, UUID(current_user.sub)
        )
        workflow_service.record_audit_log(
            db,
            user_id=UUID(current_user.sub),
            event_type="workflow.instance.cancel",
            event_data={"instance_id": str(instance_id)},
        )
        await db.commit()
        return APIResponse(data=_instance_to_response(instance))
    except ValueError as e:
        raise HTTPException(
            status_code=400, detail={"code": "BAD_REQUEST", "message": str(e)}
        )
