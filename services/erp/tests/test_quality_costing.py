"""品質テスト: 原価計算・承認・金額精度（工事台帳→原価明細→承認→請求→支払）。

対象: ``services/erp`` の原価管理フロー。DB 不要（``CaptureDB`` + ``TestClient``）。

判定の読み方:
- ``xfail(strict=True)`` = 仕様どおりの期待を assert（現状は失敗 = 欠陥が実在）。
- ``*_current_behavior*`` = 現状の挙動を固定して PASS（欠陥の積極的証拠）。
- H4（承認済み削除禁止）は **仕様どおり機能している**ことを PASS で確認する。
- 実装は変更していない。詳細は ``reports/quality-tests/qa-erp.md``。
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
        statement_wheres,
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
        statement_wheres,
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
    def test_approve_current_behavior_credits_budget_of_other_ledger(self):
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

        assert response.status_code == 200
        assert Decimal(str(foreign_budget.actual_amount)) == Decimal("500")

    @pytest.mark.xfail(
        strict=True,
        reason="DEFECT-D9: 他台帳の予算へ実績が加算される（budget_id の整合検査なし）",
    )
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

    def test_approve_current_behavior_credits_other_tenant_budget(self):
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

        assert response.status_code == 200
        assert Decimal(str(other_tenant_budget.actual_amount)) == Decimal("700")

    @pytest.mark.xfail(
        strict=True,
        reason="DEFECT-D9: 他テナントの予算へ実績が加算される（予算の org 検査なし）",
    )
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

    def test_summary_current_behavior_float_artifacts(self):
        """0.30 - 0.10 が 0.19999999999999998 として API に漏れる。"""
        data = self._summary("0.30", "0.10", "0.30")

        assert data["estimated_profit"] == "0.19999999999999998"
        assert data["profit_margin"] == "66.66666666666666"
        assert data["budget_utilization"] == "33.333333333333336"

    @pytest.mark.xfail(
        strict=True,
        reason="DEFECT-D5: 金額が float 経由で計算され 2 桁に収まらない（0.20 になるべき）",
    )
    def test_summary_estimated_profit_is_two_decimals(self):
        data = self._summary("0.30", "0.10", "0.30")

        assert Decimal(data["estimated_profit"]) == Decimal("0.20")

    @pytest.mark.xfail(
        strict=True,
        reason="DEFECT-D5: 利益率/予算消化率が丸められない（無限小数が返る）",
    )
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

    def test_approve_current_behavior_float_accumulation(self):
        """0.10 と 0.20 の承認で実績が 0.30000000000000004 になる。"""
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
            response = client.post(
                f"/api/v1/erp/costs/{cost.id}/approve",
                json={"approved_by": str(USER_A)},
            )
            assert response.status_code == 200

        assert Decimal(str(budget.actual_amount)) == Decimal(
            "0.30000000000000004"
        )
        assert Decimal(str(ledger.actual_cost)) == Decimal("0.30000000000000004")

    @pytest.mark.xfail(
        strict=True,
        reason="DEFECT-D5: 承認時の実績加算が float 演算（0.30 になるべき）",
    )
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

    def test_create_invoice_current_behavior_float_total(self):
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
        assert Decimal(str(db.added[0].total_amount)) == Decimal(
            "0.30000000000000004"
        )

    @pytest.mark.xfail(
        strict=True,
        reason="DEFECT-D5: 請求 total_amount が float 加算（0.30 になるべき）",
    )
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
    def test_update_cost_current_behavior_accepts_negative_amount(self):
        cost = make_cost(ORG_A, amount="100")
        db = CaptureDB()
        db.put(cost)
        client = make_client(db, org=ORG_A)

        response = client.put(
            f"/api/v1/erp/costs/{cost.id}", json={"amount": "-100"}
        )

        assert response.status_code == 200
        assert Decimal(str(cost.amount)) == Decimal("-100")

    @pytest.mark.xfail(
        strict=True,
        reason="DEFECT-D5/異常系: 原価更新で負値が拒否されない（gt=0 制約が無い）",
    )
    def test_update_cost_rejects_non_positive_amount(self):
        cost = make_cost(ORG_A, amount="100")
        db = CaptureDB()
        db.put(cost)
        client = make_client(db, org=ORG_A)

        response = client.put(
            f"/api/v1/erp/costs/{cost.id}", json={"amount": "-100"}
        )
        assert response.status_code in (400, 422)

    def test_update_ledger_current_behavior_accepts_negative_contract(self):
        ledger = make_ledger(ORG_A, contract="1000000")
        db = CaptureDB()
        db.put(ledger)
        client = make_client(db, org=ORG_A)

        response = client.put(
            f"/api/v1/erp/ledger/{ledger.id}", json={"contract_amount": "-5"}
        )

        assert response.status_code == 200
        assert Decimal(str(ledger.contract_amount)) == Decimal("-5")

    @pytest.mark.xfail(
        strict=True,
        reason="DEFECT-D5/異常系: 請負金額の負値が拒否されない（gt=0 制約が無い）",
    )
    def test_update_ledger_rejects_non_positive_contract(self):
        ledger = make_ledger(ORG_A, contract="1000000")
        db = CaptureDB()
        db.put(ledger)
        client = make_client(db, org=ORG_A)

        response = client.put(
            f"/api/v1/erp/ledger/{ledger.id}", json={"contract_amount": "-5"}
        )
        assert response.status_code in (400, 422)

    @pytest.mark.parametrize("progress_rate", ["150", "-10"])
    def test_update_ledger_current_behavior_accepts_out_of_range_progress(
        self, progress_rate
    ):
        ledger = make_ledger(ORG_A)
        db = CaptureDB()
        db.put(ledger)
        client = make_client(db, org=ORG_A)

        response = client.put(
            f"/api/v1/erp/ledger/{ledger.id}",
            json={"progress_rate": progress_rate},
        )

        assert response.status_code == 200
        assert Decimal(str(ledger.progress_rate)) == Decimal(progress_rate)

    @pytest.mark.xfail(
        strict=True,
        reason="DEFECT-D5/異常系: 進捗率の範囲(0..100)検査が無い",
    )
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
class TestH6LedgerSummaryStub:
    EXPECTED_STUB = {
        "total_revenue": 850000000,
        "total_cost": 680000000,
        "gross_profit": 170000000,
        "operating_profit": 145000000,
        "projects_count": 12,
        "gross_margin": 0.2,
        "operating_margin": 0.171,
    }

    def test_summary_current_behavior_is_fixed_constant_without_db_access(self):
        """台帳 0 件でも固定値。SQL も一切発行しない（実データ非参照）。"""
        db = CaptureDB()
        client = make_client(db, org=ORG_A)

        response = client.get("/api/v1/erp/ledger/summary")

        assert response.status_code == 200
        assert response.json() == self.EXPECTED_STUB
        assert db.statements == []
        assert statement_wheres(db) == []

    def test_summary_current_behavior_ignores_existing_ledger_data(self):
        db = CaptureDB()
        db.put(make_ledger(ORG_A, contract="1234", actual="999", budget="1"))
        client = make_client(db, org=ORG_A)

        response = client.get("/api/v1/erp/ledger/summary")

        assert response.status_code == 200
        assert response.json()["total_revenue"] == 850000000
        assert response.json()["projects_count"] == 12

    @pytest.mark.xfail(
        strict=True,
        reason="DEFECT-D6: /ledger/summary が実データを集計せず固定値を返す（仕様/画面は実データ前提）",
    )
    def test_summary_reflects_persisted_ledger_data(self):
        db = CaptureDB()
        db.put(make_ledger(ORG_A, contract="1000000", actual="0", budget="800000"))
        client = make_client(db, org=ORG_A)

        response = client.get("/api/v1/erp/ledger/summary")

        assert response.status_code == 200
        assert Decimal(str(response.json()["total_revenue"])) == Decimal("1000000")


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
