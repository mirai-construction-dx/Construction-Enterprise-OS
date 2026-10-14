"""承認ワークフロー: 実 PostgreSQL における同時承認（競合状態）の仕様テスト。

teammate (qa-docs-approval) は WF-1 を「静的根拠＋stale-snapshot 白箱モデル」として報告し、
**実 DB 同時実行での再現は未実施**と明記した。本テストはその未確認事項を Lead が独立に検証する。

期待（仕様）: 同一ステップに対する並行 approve は 1 件だけが成功し、
承認者・承認時刻・ステータス履歴が一意に確定すること（否認防止）。
"""

from __future__ import annotations

import asyncio
import threading
import uuid

import _shared
from conftest import APPROVAL_ID, INSTANCE_ID, ORG_A, USER_A, headers_org_a

import asyncpg
import pytest

BASE = "/api/v1/workflow"


async def _exec(sql: str, *args) -> None:
    conn = await asyncpg.connect(_shared.raw_dsn())
    try:
        await conn.execute(sql, *args)
    finally:
        await conn.close()


async def _fetch(sql: str, *args):
    conn = await asyncpg.connect(_shared.raw_dsn())
    try:
        return await conn.fetch(sql, *args)
    finally:
        await conn.close()


def _seed() -> None:
    asyncio.run(
        _exec(
            "TRUNCATE auth.audit_logs, workflow.workflow_status_history, "
            "workflow.workflow_inquiries, workflow.workflow_approvals, "
            "workflow.workflow_instances CASCADE"
        )
    )
    asyncio.run(
        _exec(
            """
            INSERT INTO workflow.workflow_instances
              (id, organization_id, title, category, status, priority,
               submitted_by, duplicate_flag, metadata, created_at, updated_at)
            VALUES ($1,$2,'テスト稟議','approval','in_progress','normal',$3,false,
                    '{}'::jsonb, now(), now())
            """,
            INSTANCE_ID,
            ORG_A,
            USER_A,
        )
    )
    asyncio.run(
        _exec(
            """
            INSERT INTO workflow.workflow_approvals
              (id, instance_id, step_order, approver_role, status, created_at)
            VALUES ($1,$2,1,'admin','pending', now())
            """,
            APPROVAL_ID,
            INSTANCE_ID,
        )
    )


@pytest.fixture(autouse=True)
def _rows():
    _seed()
    yield


def test_concurrent_approve_only_one_succeeds(client):
    """2 スレッドから同時に approve し、成功が 1 件に限定されることを検証する。"""
    statuses: list[int] = []
    lock = threading.Lock()
    barrier = threading.Barrier(2)

    def worker() -> None:
        try:
            barrier.wait(timeout=10)
            r = client.post(
                f"{BASE}/instances/{INSTANCE_ID}/approve",
                params={"step_order": 1},
                json={"comment": "テスト承認"},
                headers=headers_org_a(["admin"]),
            )
            code = r.status_code
        except Exception:  # ネットワーク/クライアント例外も証跡として残す
            code = -1
        with lock:
            statuses.append(code)

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert len(statuses) == 2, f"並行リクエストが完了しなかった: {statuses}"
    successes = [s for s in statuses if s == 200]
    assert len(successes) == 1, (
        f"同一ステップの並行承認が {len(successes)} 件成功した（二重承認）: {statuses}"
    )

    # 承認者・履歴が一意に確定していること
    approvals = asyncio.run(
        _fetch(
            "SELECT status, approver_id, approved_at FROM workflow.workflow_approvals "
            "WHERE id = $1",
            APPROVAL_ID,
        )
    )
    assert approvals[0]["status"] == "approved"
    assert str(approvals[0]["approver_id"]) == str(USER_A)

    history = asyncio.run(
        _fetch(
            "SELECT to_status FROM workflow.workflow_status_history "
            "WHERE instance_id = $1 AND to_status = 'approved'",
            INSTANCE_ID,
        )
    )
    assert len(history) == 1, (
        f"承認のステータス履歴が {len(history)} 件記録された（証跡の重複／不定）"
    )

    instance = asyncio.run(
        _fetch(
            "SELECT status, completed_at FROM workflow.workflow_instances WHERE id = $1",
            INSTANCE_ID,
        )
    )
    assert instance[0]["status"] == "approved"
    assert instance[0]["completed_at"] is not None


def test_sequential_double_approve_is_rejected(client):
    """逐次実行では 2 回目が拒否されること（既存の正しい挙動の回帰）。"""
    first = client.post(
        f"{BASE}/instances/{INSTANCE_ID}/approve",
        params={"step_order": 1},
        json={"comment": "1回目"},
        headers=headers_org_a(["admin"]),
    )
    assert first.status_code == 200, first.text
    second = client.post(
        f"{BASE}/instances/{INSTANCE_ID}/approve",
        params={"step_order": 1},
        json={"comment": "2回目"},
        headers=headers_org_a(["admin"]),
    )
    assert second.status_code >= 400, (
        f"逐次での二重承認が成功した: {second.status_code}"
    )


def test_approve_without_required_role_is_forbidden(client):
    """ステップの approver_role を持たないトークンでは承認できないこと。"""
    r = client.post(
        f"{BASE}/instances/{INSTANCE_ID}/approve",
        params={"step_order": 1},
        json={"comment": "ロール不足"},
        headers=headers_org_a(["site_worker"]),
    )
    assert r.status_code >= 400, f"必要ロールなしで承認できた: {r.status_code}"


def test_approve_unknown_step_is_rejected(client):
    r = client.post(
        f"{BASE}/instances/{INSTANCE_ID}/approve",
        params={"step_order": 99},
        json={"comment": "存在しないステップ"},
        headers=headers_org_a(["admin"]),
    )
    assert r.status_code >= 400, f"存在しないステップを承認できた: {r.status_code}"


def test_other_tenant_cannot_approve(client):
    other_org = uuid.UUID("00000000-0000-0000-0000-0000000000bb")
    token = _shared.make_token(other_org, _shared.USER_B, ["admin"])
    r = client.post(
        f"{BASE}/instances/{INSTANCE_ID}/approve",
        params={"step_order": 1},
        json={"comment": "他テナント"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code >= 400, f"他テナントから承認できた: {r.status_code}"
