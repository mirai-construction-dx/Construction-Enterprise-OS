"""品質テスト: テナント分離・認可境界（工事台帳→原価明細→承認→請求→支払）。

対象: ``services/erp`` の原価管理フロー。
DB 不要（``CaptureDB`` + ``TestClient``）。実行 SQL を捕捉し WHERE 句を検査する。

判定の読み方:
- ``xfail(strict=True)`` のテスト = **仕様どおりの期待**を assert している。
  現状は失敗する（= 欠陥が実在する）。reason の ``DEFECT-xx`` が欠陥 ID。
  修正されると ``XPASS(strict)`` となり失敗に変わるので、マーカー除去を強制できる。
- ``*_current_behavior*`` のテスト = **現状の（脆弱な）挙動**を固定して PASS する。
  欠陥が実在することの積極的な証拠。
- 実装は変更していない。詳細と重大度は ``reports/quality-tests/qa-erp.md``。
"""

import uuid
from decimal import Decimal

import pytest

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
    def test_list_ledger_current_behavior_no_tenant_filter(self):
        """クエリ省略時、WHERE に organization_id 条件が一切付かない。"""
        db = CaptureDB()
        client = make_client(db, org=ORG_A)

        response = client.get("/api/v1/erp/ledger")

        assert response.status_code == 200
        assert not has_org_filter(db, ORG_A)
        assert not has_org_filter(db, ORG_B)
        assert all("organization_id" not in where for where in statement_wheres(db))

    @pytest.mark.xfail(
        strict=True,
        reason="DEFECT-D1: GET /ledger がクエリ省略時にトークン org で絞らない（全テナント返却）",
    )
    def test_list_ledger_filters_by_token_org_when_query_omitted(self):
        db = CaptureDB()
        client = make_client(db, org=ORG_A)

        response = client.get("/api/v1/erp/ledger")

        assert response.status_code == 200
        assert has_org_filter(db, ORG_A), statement_wheres(db)

    def test_list_ledger_current_behavior_trusts_foreign_org_query(self):
        """他テナントの organization_id をクエリで指定でき、そのまま WHERE に使われる。"""
        db = CaptureDB()
        client = make_client(db, org=ORG_A)

        response = client.get(f"/api/v1/erp/ledger?organization_id={ORG_B}")

        assert response.status_code == 200
        assert has_org_filter(db, ORG_B)
        assert not has_org_filter(db, ORG_A)

    @pytest.mark.xfail(
        strict=True,
        reason="DEFECT-D1: クエリの organization_id を信頼している（トークン org を使うべき）",
    )
    def test_list_ledger_ignores_foreign_org_query(self):
        db = CaptureDB()
        client = make_client(db, org=ORG_A)

        response = client.get(f"/api/v1/erp/ledger?organization_id={ORG_B}")

        assert response.status_code == 200
        assert has_org_filter(db, ORG_A)
        assert not has_org_filter(db, ORG_B)

    def test_list_invoices_current_behavior_no_tenant_filter(self):
        db = CaptureDB()
        client = make_client(db, org=ORG_A)

        response = client.get("/api/v1/erp/invoices")

        assert response.status_code == 200
        assert not has_org_filter(db, ORG_A)
        assert not has_org_filter(db, ORG_B)

    @pytest.mark.xfail(
        strict=True,
        reason="DEFECT-D1: GET /invoices がクエリ省略時にトークン org で絞らない",
    )
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
    def test_get_ledger_other_tenant_current_behavior_200(self):
        ledger_id = uuid.uuid4()
        db = CaptureDB()
        db.put(make_ledger(ORG_B, lid=ledger_id))
        client = make_client(db, org=ORG_A)

        response = client.get(f"/api/v1/erp/ledger/{ledger_id}")

        assert response.status_code == 200
        assert response.json()["organization_id"] == str(ORG_B)

    @pytest.mark.xfail(
        strict=True, reason="DEFECT-D2: GET /ledger/{id} にテナント境界が無い（404 になるべき）"
    )
    def test_get_ledger_other_tenant_should_be_404(self):
        ledger_id = uuid.uuid4()
        db = CaptureDB()
        db.put(make_ledger(ORG_B, lid=ledger_id))
        client = make_client(db, org=ORG_A)

        assert client.get(f"/api/v1/erp/ledger/{ledger_id}").status_code == 404


class TestD2CostTenantBoundary:
    def test_list_costs_other_tenant_current_behavior_200(self):
        ledger_id = uuid.uuid4()
        db = CaptureDB()
        db.put(make_ledger(ORG_B, lid=ledger_id))
        client = make_client(db, org=ORG_A)

        response = client.get(f"/api/v1/erp/ledger/{ledger_id}/costs")

        assert response.status_code == 200

    def test_list_costs_where_is_scoped_only_by_ledger_id(self):
        """cost_items の WHERE は ledger_id のみ。organization_id 条件が無い。"""
        ledger_id = uuid.uuid4()
        db = CaptureDB()
        db.put(make_ledger(ORG_B, lid=ledger_id))
        client = make_client(db, org=ORG_A)

        response = client.get(f"/api/v1/erp/ledger/{ledger_id}/costs")

        assert response.status_code == 200
        cost_wheres = [w for w in statement_wheres(db) if "cost_items" in w]
        assert cost_wheres, statement_wheres(db)
        assert all("ledger_id" in w for w in cost_wheres)
        assert all("organization_id" not in w for w in cost_wheres)

    @pytest.mark.xfail(
        strict=True,
        reason="DEFECT-D2: GET /ledger/{id}/costs が他テナント台帳を 404 にしない",
    )
    def test_list_costs_other_tenant_should_be_404(self):
        ledger_id = uuid.uuid4()
        db = CaptureDB()
        db.put(make_ledger(ORG_B, lid=ledger_id))
        client = make_client(db, org=ORG_A)

        assert client.get(f"/api/v1/erp/ledger/{ledger_id}/costs").status_code == 404

    def test_create_cost_other_tenant_current_behavior_201(self):
        ledger_id = uuid.uuid4()
        db = CaptureDB()
        db.put(make_ledger(ORG_B, lid=ledger_id))
        client = make_client(db, org=ORG_A)

        response = client.post(
            f"/api/v1/erp/ledger/{ledger_id}/costs",
            json={
                "organization_id": str(ORG_B),
                "category": "materials",
                "description": "テスト他社原価",
                "amount": "100",
                "cost_date": "2026-05-01",
            },
        )

        assert response.status_code == 201
        assert db.added and str(db.added[0].organization_id) == str(ORG_B)

    @pytest.mark.xfail(
        strict=True,
        reason="DEFECT-D2: POST /ledger/{id}/costs が他テナント台帳へ原価を追加できる",
    )
    def test_create_cost_other_tenant_should_be_404(self):
        ledger_id = uuid.uuid4()
        db = CaptureDB()
        db.put(make_ledger(ORG_B, lid=ledger_id))
        client = make_client(db, org=ORG_A)

        response = client.post(
            f"/api/v1/erp/ledger/{ledger_id}/costs",
            json={
                "organization_id": str(ORG_B),
                "category": "materials",
                "description": "テスト他社原価",
                "amount": "100",
                "cost_date": "2026-05-01",
            },
        )
        assert response.status_code == 404

    def test_update_cost_other_tenant_current_behavior_mutates(self):
        cost = make_cost(ORG_B, amount="100")
        db = CaptureDB()
        db.put(cost)
        client = make_client(db, org=ORG_A)

        response = client.put(
            f"/api/v1/erp/costs/{cost.id}", json={"amount": "999999"}
        )

        assert response.status_code == 200
        assert Decimal(str(cost.amount)) == Decimal("999999")

    @pytest.mark.xfail(
        strict=True, reason="DEFECT-D2: PUT /costs/{id} が他テナント原価を改変できる"
    )
    def test_update_cost_other_tenant_should_be_404(self):
        cost = make_cost(ORG_B, amount="100")
        db = CaptureDB()
        db.put(cost)
        client = make_client(db, org=ORG_A)

        response = client.put(
            f"/api/v1/erp/costs/{cost.id}", json={"amount": "999999"}
        )
        assert response.status_code == 404

    def test_delete_cost_other_tenant_current_behavior_deletes(self):
        cost = make_cost(ORG_B, amount="100")
        db = CaptureDB()
        db.put(cost)
        client = make_client(db, org=ORG_A)

        response = client.delete(f"/api/v1/erp/costs/{cost.id}")

        assert response.status_code == 204
        assert db.deleted == [cost]

    @pytest.mark.xfail(
        strict=True, reason="DEFECT-D2: DELETE /costs/{id} が他テナント原価を削除できる"
    )
    def test_delete_cost_other_tenant_should_be_404(self):
        cost = make_cost(ORG_B, amount="100")
        db = CaptureDB()
        db.put(cost)
        client = make_client(db, org=ORG_A)

        assert client.delete(f"/api/v1/erp/costs/{cost.id}").status_code == 404

    def test_approve_cost_other_tenant_current_behavior_200(self):
        cost = make_cost(ORG_B)
        db = CaptureDB()
        db.put(cost)
        client = make_client(db, org=ORG_A)

        response = client.post(
            f"/api/v1/erp/costs/{cost.id}/approve",
            json={"approved_by": str(USER_A)},
        )

        assert response.status_code == 200
        assert cost.status == "approved"

    @pytest.mark.xfail(
        strict=True,
        reason="DEFECT-D2: POST /costs/{id}/approve が他テナント原価を承認できる",
    )
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
    def test_invoice_cross_tenant_current_behavior_get_put_pay(self):
        invoice = make_invoice(ORG_B, status="issued")
        db = CaptureDB()
        db.put(invoice)
        client = make_client(db, org=ORG_A)

        assert client.get(f"/api/v1/erp/invoices/{invoice.id}").status_code == 200
        assert (
            client.put(
                f"/api/v1/erp/invoices/{invoice.id}", json={"amount": "55"}
            ).status_code
            == 200
        )
        assert (
            client.post(
                f"/api/v1/erp/invoices/{invoice.id}/pay", json={}
            ).status_code
            == 200
        )
        assert invoice.status == "paid"

    @pytest.mark.xfail(
        strict=True,
        reason="DEFECT-D2: 請求書の GET/PUT/PAY にテナント境界が無い（404 になるべき）",
    )
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
    def test_approve_current_behavior_approved_by_from_body(self):
        cost = make_cost(ORG_A)
        db = CaptureDB()
        db.put(cost)
        client = make_client(db, org=ORG_A, sub=USER_A)

        response = client.post(
            f"/api/v1/erp/costs/{cost.id}/approve",
            json={"approved_by": str(SPOOFED_APPROVER)},
        )

        assert response.status_code == 200
        assert str(cost.approved_by) == str(SPOOFED_APPROVER)
        assert str(cost.approved_by) != str(USER_A)

    @pytest.mark.xfail(
        strict=True,
        reason="DEFECT-D3: approved_by がボディ由来でトークン主体(sub)と一致しない（承認者偽装）",
    )
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
    def test_create_ledger_current_behavior_stores_body_org(self):
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
        assert db.added and str(db.added[0].organization_id) == str(ORG_B)

    @pytest.mark.xfail(
        strict=True,
        reason="DEFECT-D4: POST /ledger の organization_id がボディ由来（トークン org を使うべき）",
    )
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

    def test_create_cost_current_behavior_stores_body_org(self):
        ledger_id = uuid.uuid4()
        db = CaptureDB()
        db.put(make_ledger(ORG_B, lid=ledger_id))
        client = make_client(db, org=ORG_A)

        response = client.post(
            f"/api/v1/erp/ledger/{ledger_id}/costs",
            json={
                "organization_id": str(ORG_B),
                "category": "materials",
                "description": "テスト他社原価",
                "amount": "100",
                "cost_date": "2026-05-01",
            },
        )

        assert response.status_code == 201
        assert str(db.added[0].organization_id) == str(ORG_B)

    @pytest.mark.xfail(
        strict=True,
        reason="DEFECT-D4: POST /ledger/{id}/costs の organization_id がボディ由来",
    )
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
    def test_approve_without_roles_or_scopes_current_behavior_200(self):
        cost = make_cost(ORG_A)
        db = CaptureDB()
        db.put(cost)
        client = make_client(db, org=ORG_A, roles=[], scopes=[])

        response = client.post(
            f"/api/v1/erp/costs/{cost.id}/approve",
            json={"approved_by": str(USER_A)},
        )

        assert response.status_code == 200

    @pytest.mark.xfail(
        strict=True,
        reason="DEFECT-D7: 財務書込にロール/スコープ検証が無い（roles=[] でも承認できる）",
    )
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
    def test_create_cost_current_behavior_accepts_budget_of_other_ledger(self):
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
                "organization_id": str(ORG_A),
                "budget_id": str(budget_id),
                "category": "materials",
                "description": "テスト原価A",
                "amount": "500",
                "cost_date": "2026-05-01",
            },
        )

        assert response.status_code == 201
        assert str(db.added[0].budget_id) == str(budget_id)

    @pytest.mark.xfail(
        strict=True,
        reason="DEFECT-D9: 他台帳の budget_id を指定した原価作成が拒否されない",
    )
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
                "organization_id": str(ORG_A),
                "budget_id": str(budget_id),
                "category": "materials",
                "description": "テスト原価A",
                "amount": "500",
                "cost_date": "2026-05-01",
            },
        )
        assert response.status_code in (400, 422)
