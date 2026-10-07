"""品質テスト: テナント分離・認可境界（工事台帳→原価明細→承認→請求→支払）。

対象: ``services/erp`` の原価管理フロー。
DB 不要（``CaptureDB`` + ``TestClient``）。実行 SQL を捕捉し WHERE 句を検査する。

判定の読み方:
- 欠陥テスト = **仕様どおりの期待**を assert する。修正後は PASS になる。
- 実装は修正済み。詳細は ``reports/quality-tests/qa-erp.md``。
"""

import uuid

try:  # pytest の import 形態差を吸収
    from ._quality_support import (
        ORG_A,
        ORG_B,
        SPOOFED_APPROVER,
        USER_A,
        CaptureDB,
        has_org_filter,
        make_budget,
        make_client,
        make_cost,
        make_invoice,
        make_ledger,
        statement_wheres,
        unauthenticated_client,
    )
except ImportError:  # pragma: no cover
    from _quality_support import (  # type: ignore[no-redef]
        ORG_A,
        ORG_B,
        SPOOFED_APPROVER,
        USER_A,
        CaptureDB,
        has_org_filter,
        make_budget,
        make_client,
        make_cost,
        make_invoice,
        make_ledger,
        statement_wheres,
        unauthenticated_client,
    )


# ============================================================
# Q1 positive control: 未認証は 401（既存実装で成立していることの確認）
# ============================================================
class TestAuthRequiredControl:
    def test_financial_write_endpoints_require_authentication(self):
        client = unauthenticated_client()
        ledger_id = uuid.uuid4()
        cost_id = uuid.uuid4()

        assert client.get("/api/v1/erp/ledger").status_code == 401
        assert client.get(f"/api/v1/erp/ledger/{ledger_id}").status_code == 401
        assert (
            client.post(
                f"/api/v1/erp/ledger/{ledger_id}/costs", json={}
            ).status_code
            == 401
        )
        assert (
            client.post(f"/api/v1/erp/costs/{cost_id}/approve", json={}).status_code
            == 401
        )
        assert client.put(f"/api/v1/erp/costs/{cost_id}", json={}).status_code == 401
        assert client.delete(f"/api/v1/erp/costs/{cost_id}").status_code == 401
        assert client.get("/api/v1/erp/ledger/summary").status_code == 401


# ============================================================
# D1: GET /ledger の organization_id がクエリ由来（省略時は全テナント）
# ============================================================
class TestD1ListLedgerTenantScope:
    def test_list_ledger_filters_by_token_org_when_query_omitted(self):
        db = CaptureDB()
        client = make_client(db, org=ORG_A)

        response = client.get("/api/v1/erp/ledger")

        assert response.status_code == 200
        assert has_org_filter(db, ORG_A), statement_wheres(db)

    def test_list_ledger_ignores_foreign_org_query(self):
        db = CaptureDB()
        client = make_client(db, org=ORG_A)

        response = client.get(f"/api/v1/erp/ledger?organization_id={ORG_B}")

        assert response.status_code == 200
        assert has_org_filter(db, ORG_A)
        assert not has_org_filter(db, ORG_B)

    def test_list_invoices_filters_by_token_org(self):
        db = CaptureDB()
        client = make_client(db, org=ORG_A)

        response = client.get("/api/v1/erp/invoices")

        assert response.status_code == 200
        assert has_org_filter(db, ORG_A), statement_wheres(db)


# ============================================================
# D2: get_ledger / get_cost に組織検査が無い（他テナントの閲覧・改変・削除）
# ============================================================
class TestD2LedgerTenantBoundary:
    def test_get_ledger_other_tenant_should_be_404(self):
        ledger_id = uuid.uuid4()
        db = CaptureDB()
        db.put(make_ledger(ORG_B, lid=ledger_id))
        client = make_client(db, org=ORG_A)

        assert client.get(f"/api/v1/erp/ledger/{ledger_id}").status_code == 404


class TestD2CostTenantBoundary:
    def test_list_costs_other_tenant_should_be_404(self):
        ledger_id = uuid.uuid4()
        db = CaptureDB()
        db.put(make_ledger(ORG_B, lid=ledger_id))
        client = make_client(db, org=ORG_A)

        assert client.get(f"/api/v1/erp/ledger/{ledger_id}/costs").status_code == 404

    def test_create_cost_other_tenant_should_be_404(self):
        ledger_id = uuid.uuid4()
        db = CaptureDB()
        db.put(make_ledger(ORG_B, lid=ledger_id))
        client = make_client(db, org=ORG_A)

        response = client.post(
            f"/api/v1/erp/ledger/{ledger_id}/costs",
            json={
                "category": "materials",
                "description": "テスト他社原価",
                "amount": "100",
                "cost_date": "2026-05-01",
            },
        )
        assert response.status_code == 404

    def test_update_cost_other_tenant_should_be_404(self):
        cost = make_cost(ORG_B, amount="100")
        db = CaptureDB()
        db.put(cost)
        client = make_client(db, org=ORG_A)

        response = client.put(
            f"/api/v1/erp/costs/{cost.id}", json={"amount": "999999"}
        )
        assert response.status_code == 404

    def test_delete_cost_other_tenant_should_be_404(self):
        cost = make_cost(ORG_B, amount="100")
        db = CaptureDB()
        db.put(cost)
        client = make_client(db, org=ORG_A)

        assert client.delete(f"/api/v1/erp/costs/{cost.id}").status_code == 404

    def test_approve_cost_other_tenant_should_be_404(self):
        cost = make_cost(ORG_B)
        db = CaptureDB()
        db.put(cost)
        client = make_client(db, org=ORG_A)

        response = client.post(
            f"/api/v1/erp/costs/{cost.id}/approve",
            json={"approved_by": str(USER_A)},
        )
        assert response.status_code == 404


class TestD2InvoiceTenantBoundary:
    def test_invoice_cross_tenant_should_be_404(self):
        invoice = make_invoice(ORG_B, status="issued")
        db = CaptureDB()
        db.put(invoice)
        client = make_client(db, org=ORG_A)

        assert client.get(f"/api/v1/erp/invoices/{invoice.id}").status_code == 404
        assert (
            client.put(
                f"/api/v1/erp/invoices/{invoice.id}", json={"amount": "55"}
            ).status_code
            == 404
        )
        assert (
            client.post(
                f"/api/v1/erp/invoices/{invoice.id}/pay", json={}
            ).status_code
            == 404
        )


# ============================================================
# D3: approved_by がリクエストボディ由来（承認者偽装）
# ============================================================
class TestD3ApproverSpoofing:
    def test_approve_should_use_token_subject(self):
        cost = make_cost(ORG_A)
        db = CaptureDB()
        db.put(cost)
        client = make_client(db, org=ORG_A, sub=USER_A)

        response = client.post(
            f"/api/v1/erp/costs/{cost.id}/approve",
            json={"approved_by": str(SPOOFED_APPROVER)},
        )
        assert response.status_code == 200
        assert str(cost.approved_by) == str(USER_A)


# ============================================================
# D4: POST の organization_id がボディ由来（テナント偽装）
# ============================================================
class TestD4CreateTenantFromBody:
    def test_create_ledger_should_force_token_org(self):
        db = CaptureDB()
        client = make_client(db, org=ORG_A)

        response = client.post(
            "/api/v1/erp/ledger",
            json={
                "organization_id": str(ORG_B),
                "project_id": str(uuid.uuid4()),
                "project_code": "PJ-QA-B",
                "project_name": "テスト工事B",
                "project_type": "building",
                "contract_amount": "1000",
            },
        )
        assert response.status_code == 201
        assert str(db.added[0].organization_id) == str(ORG_A)

    def test_create_cost_should_force_token_org(self):
        """自テナント台帳への作成では、ボディの organization_id ではなくトークン org を保存する。

        (D2 の「他テナント台帳へは 404」とは別の関心事。混同すると恒久的に xfail のまま残るため、
         台帳は自テナント ORG_A を使う)
        """
        ledger_id = uuid.uuid4()
        db = CaptureDB()
        db.put(make_ledger(ORG_A, lid=ledger_id))
        client = make_client(db, org=ORG_A)

        response = client.post(
            f"/api/v1/erp/ledger/{ledger_id}/costs",
            json={
                "organization_id": str(ORG_B),
                "category": "materials",
                "description": "テスト自社原価",
                "amount": "100",
                "cost_date": "2026-05-01",
            },
        )
        assert response.status_code == 201, response.text
        assert str(db.added[0].organization_id) == str(ORG_A)


# ============================================================
# D7: 財務操作にロール / スコープ要件が無い
# ============================================================
class TestD7NoRbacOnFinancialWrites:
    def test_approve_requires_finance_role(self):
        cost = make_cost(ORG_A)
        db = CaptureDB()
        db.put(cost)
        client = make_client(db, org=ORG_A, roles=[], scopes=[])

        response = client.post(
            f"/api/v1/erp/costs/{cost.id}/approve",
            json={"approved_by": str(USER_A)},
        )
        assert response.status_code == 403


# ============================================================
# D9: cost.budget_id と ledger の整合検査が無い（budget の誤帰属）
# ============================================================
class TestD9BudgetLedgerConsistency:
    def test_create_cost_rejects_budget_of_other_ledger(self):
        ledger_id = uuid.uuid4()
        other_ledger_id = uuid.uuid4()
        budget_id = uuid.uuid4()
        db = CaptureDB()
        db.put(make_ledger(ORG_A, lid=ledger_id))
        db.put(make_budget(ORG_A, lid=other_ledger_id, bid=budget_id))
        client = make_client(db, org=ORG_A)

        response = client.post(
            f"/api/v1/erp/ledger/{ledger_id}/costs",
            json={
                "budget_id": str(budget_id),
                "category": "materials",
                "description": "テスト原価A",
                "amount": "500",
                "cost_date": "2026-05-01",
            },
        )
        assert response.status_code in (400, 422)
