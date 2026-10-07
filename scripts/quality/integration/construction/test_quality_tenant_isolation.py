"""施工管理フロー: 実 PostgreSQL におけるテナント分離・承認・計算再現性の仕様テスト（Lead 所有）。

このファイルは「あるべき仕様（＝セキュアな挙動）」を assert する。
修正前は RED（＝欠陥の再現）、最小修正後に GREEN（＝是正の証拠）となることを意図している。

根拠となる仕様:
- docs/api/overview.md: 全 API は Authorization: Bearer <access_token> で認可し、
  権限はロール/パーミッションで制御する。
- docs/architecture/01-auth-platform.md / ADR-0001: organization 単位のデータ分離。
- services/construction/src/api/wbs.py の `_org_id(user)`: 組織はトークン由来が正。
"""

from __future__ import annotations

import asyncio
import uuid

import _shared
from conftest import (
    METHOD_B,
    ORG_A,
    ORG_B,
    PROJECT_B,
    RESOURCE_B,
    SCHEDULE_B,
    headers_for_org_a,
)

import asyncpg
import pytest

OWN_RESOURCE = uuid.UUID("00000000-0000-0000-0000-0000000a0001")
OWN_METHOD_REVIEW = uuid.UUID("00000000-0000-0000-0000-0000000a0002")
WBS_ROOT_A = uuid.UUID("00000000-0000-0000-0000-0000000a0003")
WBS_CHILD_B = uuid.UUID("00000000-0000-0000-0000-0000000a0004")
PROJECT_A = uuid.UUID("00000000-0000-0000-0000-00000000aa01")

BASE = "/api/v1/construction"


async def _exec(sql: str, *args) -> None:
    conn = await asyncpg.connect(_shared.raw_dsn())
    try:
        await conn.execute(sql, *args)
    finally:
        await conn.close()


async def _fetchval(sql: str, *args):
    conn = await asyncpg.connect(_shared.raw_dsn())
    try:
        return await conn.fetchval(sql, *args)
    finally:
        await conn.close()


def _seed_own_rows() -> None:
    """毎テスト前に 4 テーブルを初期化し、ORG_A / ORG_B の既知データを再投入する。

    テスト間の相互汚染（例: 削除系テストが ORG_B の資源を実際に消してしまい、
    後続の集計テストが空振りで「合格」する）を防ぐため、必ず全件作り直す。
    """
    asyncio.run(
        _exec(
            "TRUNCATE construction.wbs_items, construction.method_statements, "
            "construction.resources, construction.schedules CASCADE"
        )
    )
    # --- ORG_B（他テナント）のデータ ---
    asyncio.run(
        _exec(
            """
            INSERT INTO construction.resources
              (id, organization_id, project_id, resource_type, name, unit,
               planned_quantity, actual_quantity, unit_cost, total_cost, status)
            VALUES ($1,$2,$3,'labor','テスト要員B','人日',10,0,20000,0,'planned')
            """,
            RESOURCE_B,
            ORG_B,
            PROJECT_B,
        )
    )
    asyncio.run(
        _exec(
            """
            INSERT INTO construction.schedules
              (id, organization_id, project_id, name, schedule_type,
               planned_start, planned_end, predecessor_ids, successor_ids,
               critical_path, status, progress_percent)
            VALUES ($1,$2,$3,'テスト工程B','construction', DATE '2026-01-01',
                    DATE '2026-02-01', '{}', '{}', true, 'planned', 0)
            """,
            SCHEDULE_B,
            ORG_B,
            PROJECT_B,
        )
    )
    asyncio.run(
        _exec(
            """
            INSERT INTO construction.method_statements
              (id, organization_id, project_id, title, document_type, attachments, status)
            VALUES ($1,$2,$3,'テスト施工計画B','method_statement','{}','review')
            """,
            METHOD_B,
            ORG_B,
            PROJECT_B,
        )
    )
    # --- ORG_A（自テナント）のデータ ---
    asyncio.run(
        _exec(
            """
            INSERT INTO construction.resources
              (id, organization_id, project_id, resource_type, name, unit,
               planned_quantity, actual_quantity, unit_cost, total_cost, status)
            VALUES ($1,$2,$3,'labor','テスト自社要員A','人日',5,0,10000,0,'planned')
            """,
            OWN_RESOURCE,
            ORG_A,
            PROJECT_A,
        )
    )
    asyncio.run(
        _exec(
            """
            INSERT INTO construction.method_statements
              (id, organization_id, project_id, title, document_type, attachments, status)
            VALUES ($1,$2,$3,'テスト自社施工計画A','method_statement','{}','review')
            """,
            OWN_METHOD_REVIEW,
            ORG_A,
            PROJECT_A,
        )
    )
    # 意図的に「親=ORG_A の WBS、子=ORG_B の WBS」というクロステナント参照を作る。
    # API 経由でも POST /wbs は parent_id を検証しないため再現可能。
    asyncio.run(
        _exec(
            """
            INSERT INTO construction.wbs_items
              (id, organization_id, project_id, wbs_code, name, level,
               progress_percent, status)
            VALUES ($1,$2,$3,'1','テスト親WBS(A)',1,0,'pending')
            """,
            WBS_ROOT_A,
            ORG_A,
            PROJECT_A,
        )
    )
    asyncio.run(
        _exec(
            """
            INSERT INTO construction.wbs_items
              (id, organization_id, project_id, parent_id, wbs_code, name, level,
               progress_percent, status)
            VALUES ($1,$2,$3,$4,'1.1','テスト子WBS(Bの機密)',2,0,'pending')
            """,
            WBS_CHILD_B,
            ORG_B,
            PROJECT_A,
            WBS_ROOT_A,
        )
    )


@pytest.fixture(autouse=True)
def _own_rows():
    _seed_own_rows()
    yield


# ============================================================
# Q2: テナント分離 — 一覧
# ============================================================
class TestListTenantIsolation:
    def test_list_resources_does_not_leak_other_tenant(self, client):
        r = client.get(f"{BASE}/resources", headers=headers_for_org_a())
        assert r.status_code == 200, r.text
        ids = {item["id"] for item in r.json()["items"]}
        assert str(RESOURCE_B) not in ids, "他テナントの資源が一覧に漏えいしている"

    def test_list_resources_ignores_foreign_organization_query(self, client):
        r = client.get(
            f"{BASE}/resources",
            params={"organization_id": str(ORG_B)},
            headers=headers_for_org_a(),
        )
        assert r.status_code == 200, r.text
        ids = {item["id"] for item in r.json()["items"]}
        assert str(RESOURCE_B) not in ids, "クエリの organization_id で他テナントを指定できてしまう"

    def test_list_schedules_does_not_leak_other_tenant(self, client):
        r = client.get(f"{BASE}/schedules", headers=headers_for_org_a())
        assert r.status_code == 200, r.text
        ids = {item["id"] for item in r.json()["items"]}
        assert str(SCHEDULE_B) not in ids, "他テナントの工程が一覧に漏えいしている"

    def test_list_methods_does_not_leak_other_tenant(self, client):
        r = client.get(f"{BASE}/methods", headers=headers_for_org_a())
        assert r.status_code == 200, r.text
        ids = {item["id"] for item in r.json()["items"]}
        assert str(METHOD_B) not in ids, "他テナントの施工計画書が一覧に漏えいしている"


# ============================================================
# Q2: テナント分離 — ID 直指定
# ============================================================
class TestIdTenantIsolation:
    def test_get_resource_by_id_blocks_other_tenant(self, client):
        r = client.get(f"{BASE}/resources/{RESOURCE_B}", headers=headers_for_org_a())
        assert r.status_code in (403, 404), f"他テナント資源を取得できた: {r.status_code}"

    def test_update_resource_by_id_blocks_other_tenant(self, client):
        r = client.put(
            f"{BASE}/resources/{RESOURCE_B}",
            json={"name": "改ざん"},
            headers=headers_for_org_a(),
        )
        assert r.status_code in (403, 404), f"他テナント資源を更新できた: {r.status_code}"

    def test_delete_resource_by_id_blocks_other_tenant(self, client):
        r = client.delete(f"{BASE}/resources/{RESOURCE_B}", headers=headers_for_org_a())
        assert r.status_code in (403, 404), f"他テナント資源を削除できた: {r.status_code}"

    def test_get_schedule_by_id_blocks_other_tenant(self, client):
        r = client.get(f"{BASE}/schedules/{SCHEDULE_B}", headers=headers_for_org_a())
        assert r.status_code in (403, 404), f"他テナント工程を取得できた: {r.status_code}"

    def test_get_method_by_id_blocks_other_tenant(self, client):
        r = client.get(f"{BASE}/methods/{METHOD_B}", headers=headers_for_org_a())
        assert r.status_code in (403, 404), f"他テナント施工計画書を取得できた: {r.status_code}"


# ============================================================
# Q2: テナント分離 — 集計系
# ============================================================
class TestAggregateTenantIsolation:
    def test_resource_cost_summary_does_not_leak_other_tenant(self, client):
        r = client.get(
            f"{BASE}/projects/{PROJECT_B}/resource-cost-summary",
            headers=headers_for_org_a(),
        )
        assert r.status_code in (200, 403, 404)
        if r.status_code == 200:
            assert r.json() == [], "他テナントの原価集計が漏えいしている"

    def test_critical_path_does_not_leak_other_tenant(self, client):
        r = client.get(
            f"{BASE}/projects/{PROJECT_B}/critical-path", headers=headers_for_org_a()
        )
        assert r.status_code in (200, 403, 404)
        if r.status_code == 200:
            assert r.json() == [], "他テナントのクリティカルパスが漏えいしている"

    def test_gantt_does_not_leak_other_tenant(self, client):
        r = client.get(
            f"{BASE}/projects/{PROJECT_B}/gantt", headers=headers_for_org_a()
        )
        assert r.status_code in (200, 403, 404)
        if r.status_code == 200:
            assert r.json() == [], "他テナントのガントデータが漏えいしている"


# ============================================================
# Q2: テナント分離 — 作成時の組織偽装
# ============================================================
class TestCreateTenantSpoofing:
    def test_create_resource_cannot_spoof_organization(self, client):
        r = client.post(
            f"{BASE}/resources",
            json={
                "organization_id": str(ORG_B),
                "project_id": str(PROJECT_B),
                "resource_type": "labor",
                "name": "テスト偽装資源",
                "unit": "人日",
                "planned_quantity": "1",
                "unit_cost": "1000",
            },
            headers=headers_for_org_a(),
        )
        assert r.status_code == 201, r.text
        assert r.json()["organization_id"] == str(ORG_A), (
            "リクエストボディの organization_id で他テナント領域へ作成できてしまう"
        )


# ============================================================
# Q6: 承認 — 他テナント承認の遮断と承認者の同定
# ============================================================
class TestApproval:
    def test_approve_method_of_other_tenant_is_blocked(self, client):
        r = client.post(
            f"{BASE}/methods/{METHOD_B}/approve",
            json={"approved_by": str(_shared.USER_A)},
            headers=headers_for_org_a(),
        )
        assert r.status_code in (403, 404), f"他テナントの施工計画書を承認できた: {r.status_code}"

    def test_approver_is_derived_from_token_not_body(self, client):
        """承認者 approved_by は認証済みユーザーでなければならない（否認防止）。"""
        forged = uuid.UUID("00000000-0000-0000-0000-00000000dead")
        r = client.post(
            f"{BASE}/methods/{OWN_METHOD_REVIEW}/approve",
            json={"approved_by": str(forged)},
            headers=headers_for_org_a(),
        )
        assert r.status_code == 200, r.text
        assert r.json()["approved_by"] != str(forged), (
            "リクエストボディの approved_by がそのまま承認者として記録される（承認者偽装）"
        )
        assert r.json()["approved_by"] == str(_shared.USER_A)


# ============================================================
# Q3: 数量・原価の計算再現性
# ============================================================
class TestCostCalculation:
    def test_actual_quantity_zero_does_not_fall_back_to_planned(self, client):
        """実績数量 0 は 0 として扱う（planned へのフォールバックは誤り）。"""
        r = client.put(
            f"{BASE}/resources/{OWN_RESOURCE}",
            json={"planned_quantity": "10", "actual_quantity": "0", "unit_cost": "20000"},
            headers=headers_for_org_a(),
        )
        assert r.status_code == 200, r.text
        total = r.json()["total_cost"]
        assert float(total) == 0.0, f"実績数量0で planned にフォールバックしている: total_cost={total}"

    def test_total_cost_is_reproducible(self, client):
        """同一入力なら同一結果（決定性）。"""
        payload = {
            "planned_quantity": "3",
            "actual_quantity": "2",
            "unit_cost": "12345.67",
        }
        totals = []
        for _ in range(3):
            r = client.put(
                f"{BASE}/resources/{OWN_RESOURCE}",
                json=payload,
                headers=headers_for_org_a(),
            )
            assert r.status_code == 200, r.text
            totals.append(str(r.json()["total_cost"]))
        assert len(set(totals)) == 1, f"同一入力で結果が変動する: {totals}"
        # 2 * 12345.67 = 24691.34 （Numeric(15,2) の量子化を期待）
        assert float(totals[0]) == pytest.approx(24691.34, abs=0.005)


# ============================================================
# Q2: WBS ツリーのテナント混入
# ============================================================
class TestWbsTreeIsolation:
    def test_tree_does_not_include_other_tenant_child(self, client):
        r = client.get(
            f"{BASE}/wbs/tree",
            params={"project_id": str(PROJECT_A)},
            headers=headers_for_org_a(),
        )
        assert r.status_code == 200, r.text
        flat: list[str] = []

        def walk(nodes):
            for n in nodes:
                flat.append(n["id"])
                walk(n.get("children") or [])

        walk(r.json())
        assert str(WBS_CHILD_B) not in flat, (
            "他テナントの WBS 子ノードがツリーに混入している（親子の組織整合が未検証）"
        )
