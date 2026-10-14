"""原価管理フロー: 実 PostgreSQL におけるテナント分離・承認者同定・金額再現性の仕様テスト。

修正前は RED（＝欠陥の再現）、修正後に GREEN（＝是正の証拠）となることを意図する。

根拠となる仕様:
- docs/api/overview.md: 全 API は Authorization: Bearer で認可。ロール/パーミッションで制御。
- docs/architecture/01-auth-platform.md: organization 単位のデータ分離。
"""

from __future__ import annotations

import asyncio
import uuid

import _shared
from conftest import (
    COST_B,
    INVOICE_B,
    LEDGER_A,
    LEDGER_B,
    ORG_A,
    ORG_B,
    PROJECT_A,
    PROJECT_B,
    headers_for_org_a,
)

import asyncpg
import pytest

BASE = "/api/v1/erp"


async def _exec(sql: str, *args) -> None:
    conn = await asyncpg.connect(_shared.raw_dsn())
    try:
        await conn.execute(sql, *args)
    finally:
        await conn.close()


def _seed() -> None:
    """毎テスト前に既知データのみで再構築する（テスト間の相互汚染を防ぐ）。"""
    asyncio.run(_exec("TRUNCATE erp.invoices, erp.cost_items, erp.budgets, erp.project_ledger CASCADE"))
    # 他テナント (ORG_B) の工事台帳・原価・請求
    asyncio.run(
        _exec(
            """
            INSERT INTO erp.project_ledger
              (id, organization_id, project_id, project_code, project_name,
               project_type, contract_amount, budget_amount, actual_cost,
               progress_rate, status)
            VALUES ($1,$2,$3,'B-001','テスト工事B','civil',1000000,800000,0,0,'in_progress')
            """,
            LEDGER_B,
            ORG_B,
            PROJECT_B,
        )
    )
    asyncio.run(
        _exec(
            """
            INSERT INTO erp.cost_items
              (id, organization_id, ledger_id, category, description, amount,
               cost_date, status)
            VALUES ($1,$2,$3,'materials','テスト資材B',150000, DATE '2026-05-01','pending')
            """,
            COST_B,
            ORG_B,
            LEDGER_B,
        )
    )
    asyncio.run(
        _exec(
            """
            INSERT INTO erp.invoices
              (id, organization_id, ledger_id, invoice_number, invoice_type,
               vendor_name, amount, tax_amount, total_amount, issue_date, status)
            VALUES ($1,$2,$3,'INV-B-0001','payable','テスト取引先B',150000,15000,165000,
                    DATE '2026-05-02','draft')
            """,
            INVOICE_B,
            ORG_B,
            LEDGER_B,
        )
    )
    # 自テナント (ORG_A)
    asyncio.run(
        _exec(
            """
            INSERT INTO erp.project_ledger
              (id, organization_id, project_id, project_code, project_name,
               project_type, contract_amount, budget_amount, actual_cost,
               progress_rate, status)
            VALUES ($1,$2,$3,'A-001','テスト工事A','civil',500000,400000,0,0,'in_progress')
            """,
            LEDGER_A,
            ORG_A,
            PROJECT_A,
        )
    )


@pytest.fixture(autouse=True)
def _rows():
    _seed()
    yield


class TestLedgerTenantIsolation:
    def test_list_ledgers_does_not_leak_other_tenant(self, client):
        r = client.get(f"{BASE}/ledger", headers=headers_for_org_a())
        assert r.status_code == 200, r.text
        ids = {i["id"] for i in r.json()["items"]}
        assert str(LEDGER_B) not in ids, "他テナントの工事台帳が一覧に漏えいしている"

    def test_list_ledgers_ignores_foreign_organization_query(self, client):
        r = client.get(
            f"{BASE}/ledger",
            params={"organization_id": str(ORG_B)},
            headers=headers_for_org_a(),
        )
        assert r.status_code == 200, r.text
        ids = {i["id"] for i in r.json()["items"]}
        assert str(LEDGER_B) not in ids, "クエリの organization_id で他テナントを指定できてしまう"

    def test_get_ledger_by_id_blocks_other_tenant(self, client):
        r = client.get(f"{BASE}/ledger/{LEDGER_B}", headers=headers_for_org_a())
        assert r.status_code in (403, 404), f"他テナントの台帳を取得できた: {r.status_code}"


class TestCostTenantIsolation:
    def test_list_costs_of_other_tenant_ledger_is_blocked(self, client):
        r = client.get(
            f"{BASE}/ledger/{LEDGER_B}/costs", headers=headers_for_org_a()
        )
        assert r.status_code in (403, 404), f"他テナント台帳の原価を一覧できた: {r.status_code}"

    def test_create_cost_in_other_tenant_ledger_is_blocked(self, client):
        r = client.post(
            f"{BASE}/ledger/{LEDGER_B}/costs",
            json={
                "organization_id": str(ORG_B),
                "category": "materials",
                "description": "テスト越境原価",
                "amount": "1000",
                "cost_date": "2026-06-01",
            },
            headers=headers_for_org_a(),
        )
        assert r.status_code in (403, 404), f"他テナント台帳へ原価を作成できた: {r.status_code}"

    def test_update_cost_of_other_tenant_is_blocked(self, client):
        r = client.put(
            f"{BASE}/costs/{COST_B}",
            json={"description": "改ざん"},
            headers=headers_for_org_a(),
        )
        assert r.status_code in (403, 404), f"他テナント原価を更新できた: {r.status_code}"

    def test_delete_cost_of_other_tenant_is_blocked(self, client):
        r = client.delete(f"{BASE}/costs/{COST_B}", headers=headers_for_org_a())
        assert r.status_code in (403, 404), f"他テナント原価を削除できた: {r.status_code}"

    def test_approve_cost_of_other_tenant_is_blocked(self, client):
        r = client.post(
            f"{BASE}/costs/{COST_B}/approve",
            json={"approved_by": str(_shared.USER_A)},
            headers=headers_for_org_a(),
        )
        assert r.status_code in (403, 404), f"他テナント原価を承認できた: {r.status_code}"


class TestInvoiceTenantIsolation:
    def test_list_invoices_does_not_leak_other_tenant(self, client):
        r = client.get(f"{BASE}/invoices", headers=headers_for_org_a())
        assert r.status_code == 200, r.text
        ids = {i["id"] for i in r.json()["items"]}
        assert str(INVOICE_B) not in ids, "他テナントの請求書が一覧に漏えいしている"

    def test_get_invoice_by_id_blocks_other_tenant(self, client):
        r = client.get(f"{BASE}/invoices/{INVOICE_B}", headers=headers_for_org_a())
        assert r.status_code in (403, 404), f"他テナントの請求書を取得できた: {r.status_code}"


class TestCreationSpoofing:
    def test_create_ledger_cannot_spoof_organization(self, client):
        r = client.post(
            f"{BASE}/ledger",
            json={
                "organization_id": str(ORG_B),
                "project_id": str(PROJECT_B),
                "project_code": "X-001",
                "project_name": "テスト偽装工事",
                "project_type": "civil",
                "contract_amount": "1000",
            },
            headers=headers_for_org_a(),
        )
        assert r.status_code == 201, r.text
        assert r.json()["organization_id"] == str(ORG_A), (
            "ボディの organization_id で他テナント領域へ台帳を作成できてしまう"
        )


class TestApproverIdentity:
    def test_approver_is_derived_from_token_not_body(self, client):
        """承認者は認証済みユーザーでなければならない（否認防止）。"""
        forged = uuid.UUID("00000000-0000-0000-0000-00000000dead")
        r = client.post(
            f"{BASE}/ledger/{LEDGER_A}/costs",
            json={
                "organization_id": str(ORG_A),
                "category": "materials",
                "description": "テスト自社原価",
                "amount": "50000",
                "cost_date": "2026-06-01",
            },
            headers=headers_for_org_a(),
        )
        assert r.status_code == 201, r.text
        cost_id = r.json()["id"]
        a = client.post(
            f"{BASE}/costs/{cost_id}/approve",
            json={"approved_by": str(forged)},
            headers=headers_for_org_a(),
        )
        assert a.status_code == 200, a.text
        assert a.json()["approved_by"] != str(forged), (
            "ボディの approved_by がそのまま承認者として記録される（承認者偽装）"
        )
        assert a.json()["approved_by"] == str(_shared.USER_A)


class TestAmountReproducibility:
    def test_amount_is_quantized_to_two_decimals_deterministically(self, client):
        """Numeric(15,2) の量子化が決定的であること（同一入力→同一結果）。"""
        seen = set()
        for _ in range(3):
            r = client.post(
                f"{BASE}/ledger/{LEDGER_A}/costs",
                json={
                    "organization_id": str(ORG_A),
                    "category": "materials",
                    "description": "テスト端数",
                    "amount": "0.005",
                    "cost_date": "2026-06-02",
                },
                headers=headers_for_org_a(),
            )
            assert r.status_code == 201, r.text
            seen.add(str(r.json()["amount"]))
        assert len(seen) == 1, f"同一入力で金額が変動する: {seen}"
        assert seen.pop() in {"0.00", "0.01"}, f"量子化されていない: {seen}"
