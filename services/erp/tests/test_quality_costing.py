"""品質テスト: 原価計算・承認・金額精度（工事台帳→原価明細→承認→請求→支払）。

対象: ``services/erp`` の原価管理フロー。DB 不要（``CaptureDB`` + ``TestClient``）。

判定の読み方:
- 欠陥テスト = 仕様どおりの期待を assert（修正後は PASS）。
- H4（承認済み削除禁止）は **仕様どおり機能している**ことを PASS で確認する。
- 実装は修正済み。詳細は ``reports/quality-tests/qa-erp.md``。
"""

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import Numeric

try:  # pytest の import 形態差を吸収
    from ._quality_support import (
        ORG_A,
        ORG_B,
        USER_A,
        CaptureDB,
        make_budget,
        make_client,
        make_cost,
        make_ledger,
    )
except ImportError:  # pragma: no cover
    from _quality_support import (  # type: ignore[no-redef]
        ORG_A,
        ORG_B,
        USER_A,
        CaptureDB,
        make_budget,
        make_client,
        make_cost,
        make_ledger,
    )


# ============================================================
# H4: 承認済み原価の削除禁止（cost_service.delete_cost）の実効性
#     -> 仕様どおり機能している（欠陥ではない）
# ============================================================
class TestH4ApprovedCostDeleteGuard:
    def test_delete_pending_cost_allowed(self):
        cost = make_cost(ORG_A, status="pending")
        db = CaptureDB()
        db.put(cost)
        client = make_client(db, org=ORG_A)

        response = client.delete(f"/api/v1/erp/costs/{cost.id}")

        assert response.status_code == 204
        assert db.deleted == [cost]

    def test_delete_approved_cost_blocked(self):
        cost = make_cost(ORG_A, status="approved")
        db = CaptureDB()
        db.put(cost)
        client = make_client(db, org=ORG_A)

        response = client.delete(f"/api/v1/erp/costs/{cost.id}")

        assert response.status_code == 400
        assert db.deleted == []

    @pytest.mark.parametrize("status", ["rejected", "APPROVED", ""])
    def test_delete_cost_with_unexpected_status_blocked(self, status):
        """pending 以外はすべて拒否（fail-safe）。"""
        cost = make_cost(ORG_A, status=status)
        db = CaptureDB()
        db.put(cost)
        client = make_client(db, org=ORG_A)

        response = client.delete(f"/api/v1/erp/costs/{cost.id}")

        assert response.status_code == 400
        assert db.deleted == []

    def test_delete_after_approve_blocked(self):
        cost = make_cost(ORG_A, status="pending")
        db = CaptureDB()
        db.put(cost)
        client = make_client(db, org=ORG_A)

        approved = client.post(
            f"/api/v1/erp/costs/{cost.id}/approve",
            json={"approved_by": str(USER_A)},
        )
        assert approved.status_code == 200

        response = client.delete(f"/api/v1/erp/costs/{cost.id}")

        assert response.status_code == 400
        assert db.deleted == []


# ============================================================
# Q6: 承認の状態遷移と証跡
# ============================================================
class TestQ6ApprovalStateMachine:
    def test_approve_sets_status_timestamp_and_rolls_up_amounts(self):
        ledger_id = uuid.uuid4()
        budget_id = uuid.uuid4()
        ledger = make_ledger(ORG_A, lid=ledger_id, actual="0")
        budget = make_budget(ORG_A, lid=ledger_id, bid=budget_id, actual="0")
        cost = make_cost(
            ORG_A, lid=ledger_id, budget_id=budget_id, amount="150000"
        )
        db = CaptureDB()
        db.put(ledger)
        db.put(budget)
        db.put(cost)
        client = make_client(db, org=ORG_A)

        response = client.post(
            f"/api/v1/erp/costs/{cost.id}/approve",
            json={"approved_by": str(USER_A)},
        )

        assert response.status_code == 200
        assert cost.status == "approved"
        assert cost.approved_at is not None
        assert Decimal(str(budget.actual_amount)) == Decimal("150000")
        assert Decimal(str(ledger.actual_cost)) == Decimal("150000")
        assert Decimal(str(ledger.estimated_profit)) == Decimal("850000")

    def test_approve_twice_blocked(self):
        cost = make_cost(ORG_A, status="approved")
        db = CaptureDB()
        db.put(cost)
        client = make_client(db, org=ORG_A)

        response = client.post(
            f"/api/v1/erp/costs/{cost.id}/approve",
            json={"approved_by": str(USER_A)},
        )

        assert response.status_code == 400

    def test_update_approved_cost_blocked(self):
        cost = make_cost(ORG_A, status="approved", amount="100")
        db = CaptureDB()
        db.put(cost)
        client = make_client(db, org=ORG_A)

        response = client.put(
            f"/api/v1/erp/costs/{cost.id}", json={"amount": "200"}
        )

        assert response.status_code == 400
        assert Decimal(str(cost.amount)) == Decimal("100")

    def test_approve_unknown_cost_404(self):
        db = CaptureDB()
        client = make_client(db, org=ORG_A)

        response = client.post(
            f"/api/v1/erp/costs/{uuid.uuid4()}/approve",
            json={"approved_by": str(USER_A)},
        )

        assert response.status_code == 404


# ============================================================
# D9: budget の誤帰属（台帳・テナント整合検査なし）
# ============================================================
class TestD9BudgetAttribution:
    def test_approve_rejects_budget_of_other_ledger(self):
        ledger_id = uuid.uuid4()
        other_ledger_id = uuid.uuid4()
        budget_id = uuid.uuid4()
        ledger = make_ledger(ORG_A, lid=ledger_id, actual="0")
        foreign_budget = make_budget(
            ORG_A, lid=other_ledger_id, bid=budget_id, actual="0"
        )
        cost = make_cost(ORG_A, lid=ledger_id, budget_id=budget_id, amount="500")
        db = CaptureDB()
        db.put(ledger)
        db.put(foreign_budget)
        db.put(cost)
        client = make_client(db, org=ORG_A)

        response = client.post(
            f"/api/v1/erp/costs/{cost.id}/approve",
            json={"approved_by": str(USER_A)},
        )
        assert response.status_code in (400, 422)

    def test_approve_rejects_budget_of_other_tenant(self):
        ledger_id = uuid.uuid4()
        budget_id = uuid.uuid4()
        ledger = make_ledger(ORG_A, lid=ledger_id, actual="0")
        other_tenant_budget = make_budget(
            ORG_B, lid=ledger_id, bid=budget_id, actual="0"
        )
        cost = make_cost(ORG_A, lid=ledger_id, budget_id=budget_id, amount="700")
        db = CaptureDB()
        db.put(ledger)
        db.put(other_tenant_budget)
        db.put(cost)
        client = make_client(db, org=ORG_A)

        response = client.post(
            f"/api/v1/erp/costs/{cost.id}/approve",
            json={"approved_by": str(USER_A)},
        )
        assert response.status_code in (400, 422)


# ============================================================
# H5: 金額計算の Decimal/float と丸め・再現性
# ============================================================
class TestH5MoneyPrecision:
    def _summary(self, contract, actual, budget):
        ledger = make_ledger(
            ORG_A, contract=contract, actual=actual, budget=budget
        )
        db = CaptureDB()
        db.put(ledger)
        client = make_client(db, org=ORG_A)
        response = client.get(f"/api/v1/erp/ledger/{ledger.id}/summary")
        assert response.status_code == 200
        return response.json()

    def test_summary_estimated_profit_is_two_decimals(self):
        data = self._summary("0.30", "0.10", "0.30")

        assert Decimal(data["estimated_profit"]) == Decimal("0.20")

    def test_summary_rates_are_rounded(self):
        data = self._summary("0.30", "0.10", "0.30")
        quantum = Decimal("0.01")

        assert Decimal(data["profit_margin"]) == Decimal(
            data["profit_margin"]
        ).quantize(quantum)
        assert Decimal(data["budget_utilization"]) == Decimal(
            data["budget_utilization"]
        ).quantize(quantum)

    def test_summary_is_deterministic_for_same_input(self):
        """同一入力→同一出力（決定性は満たす）。"""
        first = self._summary("1000000.10", "500000.05", "800000")
        second = self._summary("1000000.10", "500000.05", "800000")

        assert first == second

    def test_summary_handles_zero_budget_and_contract_safely(self):
        """境界: budget=0 / contract=0 でもゼロ除算しない（0 を返す）。"""
        data = self._summary("0", "0", "0")

        assert Decimal(data["budget_utilization"]) == Decimal("0")
        assert Decimal(data["profit_margin"]) == Decimal("0")

    def test_approve_accumulation_is_decimal_exact(self):
        ledger_id = uuid.uuid4()
        budget_id = uuid.uuid4()
        ledger = make_ledger(ORG_A, lid=ledger_id, actual="0")
        budget = make_budget(ORG_A, lid=ledger_id, bid=budget_id, actual="0")
        first = make_cost(ORG_A, lid=ledger_id, budget_id=budget_id, amount="0.10")
        second = make_cost(ORG_A, lid=ledger_id, budget_id=budget_id, amount="0.20")
        db = CaptureDB()
        db.put(ledger)
        db.put(budget)
        db.put(first)
        db.put(second)
        client = make_client(db, org=ORG_A)

        for cost in (first, second):
            client.post(
                f"/api/v1/erp/costs/{cost.id}/approve",
                json={"approved_by": str(USER_A)},
            )

        assert Decimal(str(budget.actual_amount)) == Decimal("0.30")
        assert Decimal(str(ledger.actual_cost)) == Decimal("0.30")

    def test_create_invoice_total_is_exact(self):
        db = CaptureDB()
        client = make_client(db, org=ORG_A)

        response = client.post(
            "/api/v1/erp/invoices",
            json={
                "organization_id": str(ORG_A),
                "invoice_number": "INV-QA-Q1",
                "invoice_type": "payable",
                "vendor_name": "テスト商事",
                "amount": "0.10",
                "tax_amount": "0.20",
                "issue_date": "2026-05-20",
            },
        )
        assert response.status_code == 201
        assert Decimal(str(db.added[0].total_amount)) == Decimal("0.30")


class TestH5BoundaryValidation:
    def test_update_cost_rejects_non_positive_amount(self):
        cost = make_cost(ORG_A, amount="100")
        db = CaptureDB()
        db.put(cost)
        client = make_client(db, org=ORG_A)

        response = client.put(
            f"/api/v1/erp/costs/{cost.id}", json={"amount": "-100"}
        )
        assert response.status_code in (400, 422)

    def test_update_ledger_rejects_non_positive_contract(self):
        ledger = make_ledger(ORG_A, contract="1000000")
        db = CaptureDB()
        db.put(ledger)
        client = make_client(db, org=ORG_A)

        response = client.put(
            f"/api/v1/erp/ledger/{ledger.id}", json={"contract_amount": "-5"}
        )
        assert response.status_code in (400, 422)

    def test_update_ledger_rejects_out_of_range_progress(self):
        ledger = make_ledger(ORG_A)
        db = CaptureDB()
        db.put(ledger)
        client = make_client(db, org=ORG_A)

        response = client.put(
            f"/api/v1/erp/ledger/{ledger.id}", json={"progress_rate": "150"}
        )
        assert response.status_code in (400, 422)


# ============================================================
# H6: GET /ledger/summary が固定スタブ値
# ============================================================
class TestH6LedgerSummaryAggregation:
    """GET /ledger/summary は固定スタブではなく自組織の実データを集計する。"""

    def test_summary_is_zero_without_ledgers(self):
        db = CaptureDB()
        client = make_client(db, org=ORG_A)

        response = client.get("/api/v1/erp/ledger/summary")

        assert response.status_code == 200
        body = response.json()
        assert body["total_revenue"] == 0
        assert body["total_cost"] == 0
        assert body["projects_count"] == 0
        # 販管費は未モデル化のため営業利益は未算出（固定値を返さない）
        assert body["operating_profit"] is None

    def test_summary_reflects_persisted_ledger_data(self):
        db = CaptureDB()
        db.put(make_ledger(ORG_A, contract="1234", actual="999", budget="1"))
        client = make_client(db, org=ORG_A)

        response = client.get("/api/v1/erp/ledger/summary")

        assert response.status_code == 200
        body = response.json()
        assert Decimal(str(body["total_revenue"])) == Decimal("1234")
        assert Decimal(str(body["total_cost"])) == Decimal("999")
        assert Decimal(str(body["gross_profit"])) == Decimal("235")
        assert body["projects_count"] == 1


# ============================================================
# 型整合（Numeric(15,2) と Pydantic Decimal）— 参考情報
# ============================================================
class TestNumericSchemaConsistency:
    def test_db_columns_are_numeric_15_2_and_schema_uses_decimal(self):
        from src.models.models import CostItem, ProjectLedger
        from src.schemas.schemas import CostItemResponse, LedgerResponse

        contract_type = ProjectLedger.__table__.c.contract_amount.type
        amount_type = CostItem.__table__.c.amount.type

        assert isinstance(contract_type, Numeric)
        assert (contract_type.precision, contract_type.scale) == (15, 2)
        assert isinstance(amount_type, Numeric)
        assert (amount_type.precision, amount_type.scale) == (15, 2)
        assert LedgerResponse.model_fields["contract_amount"].annotation is Decimal
        assert CostItemResponse.model_fields["amount"].annotation is Decimal
