"""ERPサービス テスト"""

import uuid
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from src.main import create_app
from src.middleware.auth import TokenData, get_current_user
from src.models.base import get_db

# approved_by / created_by はトークンの sub から導出するため、sub は有効な UUID で固定する。
USER = uuid.UUID("00000000-0000-0000-0000-0000000000a1")


class MockScalarResult:
    def __init__(self, value=None, items=None, total=0):
        self._value = value
        self._items = items or []
        self._total = total

    def scalar_one_or_none(self):
        return self._value

    def scalar(self):
        return self._total if self._total else self._value

    def scalars(self):
        return self

    def all(self):
        return self._items

    def first(self):
        return self._items[0] if self._items else None


def _auto_refresh(obj):
    if obj.id is None:
        obj.id = uuid.uuid4()
    if not hasattr(obj, "created_at") or obj.created_at is None:
        obj.created_at = datetime.now(timezone.utc)
    if hasattr(obj, "updated_at") and obj.updated_at is None:
        obj.updated_at = datetime.now(timezone.utc)
    for attr in ("actual_cost", "budget_amount", "progress_rate", "actual_amount", "tax_amount", "estimated_profit"):
        if hasattr(obj, attr) and getattr(obj, attr, None) is None:
            setattr(obj, attr, 0)
    if hasattr(obj, "status") and getattr(obj, "status", None) is None:
        # Set default status based on model conventions
        cls_name = type(obj).__name__
        defaults = {
            "ProjectLedger": "planning",
            "CostItem": "pending",
            "Invoice": "draft",
        }
        setattr(obj, "status", defaults.get(cls_name, "active"))
    return obj


@pytest.fixture
def mock_db():
    db = AsyncMock()
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    db.close = AsyncMock()
    db.flush = AsyncMock()
    db.delete = AsyncMock()
    db.execute = AsyncMock(return_value=MockScalarResult())
    db.get = AsyncMock(return_value=None)

    async def mock_refresh(obj):
        _auto_refresh(obj)

    db.refresh = mock_refresh
    return db


@pytest.fixture
def app(mock_db):
    _app = create_app()

    async def mock_get_db():
        yield mock_db

    async def mock_get_current_user():
        return TokenData(sub=str(USER), type="user", org="test-org", roles=["admin"])

    _app.dependency_overrides[get_db] = mock_get_db
    _app.dependency_overrides[get_current_user] = mock_get_current_user
    return _app


@pytest.fixture
def client(app):
    return TestClient(app)


def _auth_headers():
    return {"Authorization": "Bearer test-token"}


# ============================================
# Health Check
# ============================================
class TestHealthCheck:
    def test_health_returns_200(self, client):
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["service"] == "erp-service"


# ============================================
# Auth Required (uses clean app without overrides)
# ============================================
class TestAuthRequired:
    @pytest.fixture
    def app_no_auth(self):
        _app = create_app()
        return _app

    @pytest.fixture
    def client_no_auth(self, app_no_auth):
        return TestClient(app_no_auth)

    def test_create_ledger_requires_auth(self, client_no_auth):
        response = client_no_auth.post("/api/v1/erp/ledger", json={})
        assert response.status_code == 401

    def test_list_ledgers_requires_auth(self, client_no_auth):
        response = client_no_auth.get("/api/v1/erp/ledger")
        assert response.status_code == 401

    def test_get_ledger_requires_auth(self, client_no_auth):
        response = client_no_auth.get(f"/api/v1/erp/ledger/{uuid.uuid4()}")
        assert response.status_code == 401

    def test_create_budget_requires_auth(self, client_no_auth):
        response = client_no_auth.post(f"/api/v1/erp/ledger/{uuid.uuid4()}/budgets", json={})
        assert response.status_code == 401

    def test_create_cost_requires_auth(self, client_no_auth):
        response = client_no_auth.post(f"/api/v1/erp/ledger/{uuid.uuid4()}/costs", json={})
        assert response.status_code == 401

    def test_create_invoice_requires_auth(self, client_no_auth):
        response = client_no_auth.post("/api/v1/erp/invoices", json={})
        assert response.status_code == 401


# ============================================
# Ledger CRUD + Financial Summary
# ============================================
class TestLedgerCRUD:
    def test_create_ledger(self, client, mock_db):

        org_id = uuid.uuid4()
        project_id = uuid.uuid4()

        response = client.post(
            "/api/v1/erp/ledger",
            json={
                "organization_id": str(org_id),
                "project_id": str(project_id),
                "project_code": "PJ-001",
                "project_name": "テスト工事",
                "project_type": "building",
                "client_name": "テスト建設",
                "contract_amount": "1000000",
                "budget_amount": "800000",
                "status": "planning",
                "start_date": "2026-04-01",
                "planned_end_date": "2027-03-31",
                "location": "東京都",
            },
            headers=_auth_headers(),
        )
        assert response.status_code == 201
        assert mock_db.add.called
        called = mock_db.add.call_args[0][0]
        assert called.project_code == "PJ-001"
        assert called.project_name == "テスト工事"
        assert float(called.contract_amount) == 1000000

    def test_list_ledgers(self, client, mock_db):
        from src.models.models import ProjectLedger

        org_id = uuid.uuid4()
        ledger = ProjectLedger(
            id=uuid.uuid4(),
            organization_id=org_id,
            project_id=uuid.uuid4(),
            project_code="PJ-001",
            project_name="テスト工事",
            project_type="building",
            contract_amount=1000000,
            budget_amount=800000,
            actual_cost=0,
            estimated_profit=1000000,
            progress_rate=0,
            status="planning",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        mock_db.execute = AsyncMock(
            return_value=MockScalarResult(items=[ledger], total=1)
        )

        response = client.get(
            f"/api/v1/erp/ledger?organization_id={org_id}",
            headers=_auth_headers(),
        )
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert len(data["items"]) == 1
        assert data["items"][0]["project_code"] == "PJ-001"

    def test_get_ledger_detail(self, client, mock_db):
        from src.models.models import ProjectLedger

        ledger_id = uuid.uuid4()
        org_id = uuid.uuid4()
        ledger = ProjectLedger(
            id=ledger_id,
            organization_id=org_id,
            project_id=uuid.uuid4(),
            project_code="PJ-001",
            project_name="テスト工事",
            project_type="building",
            client_name="テスト建設",
            contract_amount=1000000,
            budget_amount=800000,
            actual_cost=150000,
            estimated_profit=850000,
            progress_rate=15.5,
            status="in_progress",
            start_date=date(2026, 4, 1),
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        mock_db.get = AsyncMock(return_value=ledger)
        mock_db.execute = AsyncMock(
            return_value=MockScalarResult(items=[])
        )

        response = client.get(
            f"/api/v1/erp/ledger/{ledger_id}",
            headers=_auth_headers(),
        )
        assert response.status_code == 200
        data = response.json()
        assert data["project_code"] == "PJ-001"
        assert data["status"] == "in_progress"

    def test_ledger_not_found(self, client, mock_db):
        mock_db.get = AsyncMock(return_value=None)
        response = client.get(
            f"/api/v1/erp/ledger/{uuid.uuid4()}",
            headers=_auth_headers(),
        )
        assert response.status_code == 404

    def test_financial_summary(self, client, mock_db):
        from src.models.models import ProjectLedger

        ledger_id = uuid.uuid4()
        ledger = ProjectLedger(
            id=ledger_id,
            organization_id=uuid.uuid4(),
            project_id=uuid.uuid4(),
            project_code="PJ-001",
            project_name="テスト工事",
            project_type="building",
            contract_amount=1000000,
            budget_amount=800000,
            actual_cost=200000,
            estimated_profit=800000,
            progress_rate=20.0,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        mock_db.get = AsyncMock(return_value=ledger)

        response = client.get(
            f"/api/v1/erp/ledger/{ledger_id}/summary",
            headers=_auth_headers(),
        )
        assert response.status_code == 200
        data = response.json()
        assert float(data["contract_amount"]) == 1000000
        assert float(data["budget_amount"]) == 800000
        assert float(data["actual_cost"]) == 200000
        assert float(data["estimated_profit"]) == 800000
        assert float(data["profit_margin"]) == 80.0
        assert float(data["progress_rate"]) == 20.0
        assert float(data["budget_utilization"]) == 25.0


# ============================================
# Budget CRUD + Auto-update from costs
# ============================================
class TestBudgetCRUD:
    def test_create_budget(self, client, mock_db):
        from src.models.models import ProjectLedger

        ledger_id = uuid.uuid4()
        ledger = ProjectLedger(
            id=ledger_id,
            organization_id=uuid.uuid4(),
            project_id=uuid.uuid4(),
            project_code="PJ-001",
            project_name="テスト工事",
            project_type="building",
            contract_amount=1000000,
            budget_amount=800000,
            actual_cost=0,
            estimated_profit=1000000,
            progress_rate=0,
            status="planning",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        mock_db.get = AsyncMock(return_value=ledger)

        response = client.post(
            f"/api/v1/erp/ledger/{ledger_id}/budgets",
            json={
                "organization_id": str(ledger.organization_id),
                "category": "materials",
                "planned_amount": "300000",
                "note": "主要資材",
            },
            headers=_auth_headers(),
        )
        assert response.status_code == 201
        added = mock_db.add.call_args[0][0]
        assert added.category == "materials"
        assert float(added.planned_amount) == 300000

    def test_create_budget_ledger_not_found(self, client, mock_db):
        mock_db.get = AsyncMock(return_value=None)
        response = client.post(
            f"/api/v1/erp/ledger/{uuid.uuid4()}/budgets",
            json={
                "organization_id": str(uuid.uuid4()),
                "category": "materials",
                "planned_amount": "300000",
            },
            headers=_auth_headers(),
        )
        assert response.status_code == 404

    def test_list_budgets(self, client, mock_db):
        from src.models.models import Budget, ProjectLedger

        ledger_id = uuid.uuid4()
        org_id = uuid.uuid4()
        ledger = ProjectLedger(
            id=ledger_id,
            organization_id=org_id,
            project_id=uuid.uuid4(),
            project_code="PJ-001",
            project_name="テスト工事",
            project_type="building",
            contract_amount=1000000,
            budget_amount=800000,
            actual_cost=0,
            estimated_profit=1000000,
            progress_rate=0,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        budget = Budget(
            id=uuid.uuid4(),
            organization_id=org_id,
            ledger_id=ledger_id,
            category="materials",
            planned_amount=300000,
            actual_amount=50000,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        mock_db.get = AsyncMock(return_value=ledger)
        mock_db.execute = AsyncMock(
            return_value=MockScalarResult(items=[budget])
        )

        response = client.get(
            f"/api/v1/erp/ledger/{ledger_id}/budgets",
            headers=_auth_headers(),
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["category"] == "materials"
        assert float(data[0]["variance"]) == 250000

    def test_budget_summary(self, client, mock_db):
        from src.models.models import Budget, ProjectLedger

        ledger_id = uuid.uuid4()
        org_id = uuid.uuid4()
        ledger = ProjectLedger(
            id=ledger_id,
            organization_id=org_id,
            project_id=uuid.uuid4(),
            project_code="PJ-001",
            project_name="テスト工事",
            project_type="building",
            contract_amount=1000000,
            budget_amount=800000,
            actual_cost=0,
            estimated_profit=1000000,
            progress_rate=0,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        b1 = Budget(
            id=uuid.uuid4(),
            organization_id=org_id,
            ledger_id=ledger_id,
            category="materials",
            planned_amount=300000,
            actual_amount=100000,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        b2 = Budget(
            id=uuid.uuid4(),
            organization_id=org_id,
            ledger_id=ledger_id,
            category="labor",
            planned_amount=200000,
            actual_amount=50000,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        mock_db.get = AsyncMock(return_value=ledger)
        mock_db.execute = AsyncMock(
            return_value=MockScalarResult(items=[b1, b2])
        )

        response = client.get(
            f"/api/v1/erp/ledger/{ledger_id}/budget-summary",
            headers=_auth_headers(),
        )
        assert response.status_code == 200
        data = response.json()
        assert float(data["total_planned"]) == 500000
        assert float(data["total_actual"]) == 150000
        assert float(data["total_variance"]) == 350000


# ============================================
# Cost Recording + Approval Flow
# ============================================
class TestCostFlow:
    def test_create_cost(self, client, mock_db):
        from src.models.models import ProjectLedger

        ledger_id = uuid.uuid4()
        ledger = ProjectLedger(
            id=ledger_id,
            organization_id=uuid.uuid4(),
            project_id=uuid.uuid4(),
            project_code="PJ-001",
            project_name="テスト工事",
            project_type="building",
            contract_amount=1000000,
            budget_amount=800000,
            actual_cost=0,
            estimated_profit=1000000,
            progress_rate=0,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        mock_db.get = AsyncMock(return_value=ledger)

        response = client.post(
            f"/api/v1/erp/ledger/{ledger_id}/costs",
            json={
                "organization_id": str(ledger.organization_id),
                "category": "materials",
                "description": "セメント購入",
                "amount": "50000",
                "cost_date": "2026-05-01",
                "vendor_name": "建材商事",
            },
            headers=_auth_headers(),
        )
        assert response.status_code == 201
        added = mock_db.add.call_args[0][0]
        assert added.category == "materials"
        assert added.description == "セメント購入"
        assert float(added.amount) == 50000
        assert added.status == "pending"

    def test_approve_cost_updates_budget_and_ledger(self, client, mock_db):
        from src.models.models import Budget, CostItem, ProjectLedger

        org_id = uuid.uuid4()
        ledger_id = uuid.uuid4()
        budget_id = uuid.uuid4()
        cost_id = uuid.uuid4()

        ledger = ProjectLedger(
            id=ledger_id,
            organization_id=org_id,
            project_id=uuid.uuid4(),
            project_code="PJ-001",
            project_name="テスト工事",
            project_type="building",
            contract_amount=1000000,
            budget_amount=800000,
            actual_cost=0,
            estimated_profit=1000000,
            progress_rate=0,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        budget = Budget(
            id=budget_id,
            organization_id=org_id,
            ledger_id=ledger_id,
            category="materials",
            planned_amount=300000,
            actual_amount=0,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        cost_item = CostItem(
            id=cost_id,
            organization_id=org_id,
            ledger_id=ledger_id,
            budget_id=budget_id,
            category="materials",
            description="鋼材購入",
            amount=150000,
            cost_date=date(2026, 5, 1),
            status="pending",
            created_at=datetime.now(timezone.utc),
        )

        cost_get_count = 0

        async def mock_get(entity, entity_id):
            nonlocal cost_get_count
            if str(entity_id) == str(cost_id):
                cost_get_count += 1
                if cost_get_count == 1:
                    return cost_item
                return cost_item
            if str(entity_id) == str(budget_id):
                return budget
            if str(entity_id) == str(ledger_id):
                return ledger
            return None

        mock_db.get = mock_get

        approver_id = USER
        response = client.post(
            f"/api/v1/erp/costs/{cost_id}/approve",
            json={"approved_by": str(approver_id)},
            headers=_auth_headers(),
        )
        assert response.status_code == 200

        assert cost_item.status == "approved"
        assert cost_item.approved_by == USER
        assert cost_item.approved_at is not None
        assert float(budget.actual_amount) == 150000
        assert float(ledger.actual_cost) == 150000
        assert float(ledger.estimated_profit) == 850000

    def test_cannot_approve_already_approved(self, client, mock_db):
        from src.models.models import CostItem

        cost_id = uuid.uuid4()
        cost_item = CostItem(
            id=cost_id,
            organization_id=uuid.uuid4(),
            ledger_id=uuid.uuid4(),
            category="materials",
            description="鋼材購入",
            amount=150000,
            cost_date=date(2026, 5, 1),
            status="approved",
            created_at=datetime.now(timezone.utc),
        )
        mock_db.get = AsyncMock(return_value=cost_item)

        response = client.post(
            f"/api/v1/erp/costs/{cost_id}/approve",
            json={"approved_by": str(uuid.uuid4())},
            headers=_auth_headers(),
        )
        assert response.status_code == 400

    def test_delete_pending_cost(self, client, mock_db):
        from src.models.models import CostItem

        cost_id = uuid.uuid4()
        cost_item = CostItem(
            id=cost_id,
            organization_id=uuid.uuid4(),
            ledger_id=uuid.uuid4(),
            category="materials",
            description="削除予定",
            amount=10000,
            cost_date=date(2026, 5, 1),
            status="pending",
            created_at=datetime.now(timezone.utc),
        )
        mock_db.get = AsyncMock(return_value=cost_item)

        response = client.delete(
            f"/api/v1/erp/costs/{cost_id}",
            headers=_auth_headers(),
        )
        assert response.status_code == 204
        mock_db.delete.assert_called_once_with(cost_item)

    def test_cannot_delete_approved_cost(self, client, mock_db):
        from src.models.models import CostItem

        cost_id = uuid.uuid4()
        cost_item = CostItem(
            id=cost_id,
            organization_id=uuid.uuid4(),
            ledger_id=uuid.uuid4(),
            category="materials",
            description="承認済み",
            amount=10000,
            cost_date=date(2026, 5, 1),
            status="approved",
            created_at=datetime.now(timezone.utc),
        )
        mock_db.get = AsyncMock(return_value=cost_item)

        response = client.delete(
            f"/api/v1/erp/costs/{cost_id}",
            headers=_auth_headers(),
        )
        assert response.status_code == 400


# ============================================
# Invoice Management
# ============================================
class TestInvoiceManagement:
    def test_create_invoice(self, client, mock_db):
        org_id = uuid.uuid4()

        response = client.post(
            "/api/v1/erp/invoices",
            json={
                "organization_id": str(org_id),
                "invoice_number": "INV-001",
                "invoice_type": "payable",
                "vendor_name": "建材商事",
                "amount": "100000",
                "tax_amount": "10000",
                "issue_date": "2026-05-20",
                "due_date": "2026-06-20",
            },
            headers=_auth_headers(),
        )
        assert response.status_code == 201
        added = mock_db.add.call_args[0][0]
        assert added.invoice_number == "INV-001"
        assert added.vendor_name == "建材商事"
        assert float(added.total_amount) == 110000

    def test_list_invoices(self, client, mock_db):
        from src.models.models import Invoice

        org_id = uuid.uuid4()
        inv = Invoice(
            id=uuid.uuid4(),
            organization_id=org_id,
            invoice_number="INV-001",
            invoice_type="payable",
            vendor_name="建材商事",
            amount=100000,
            tax_amount=10000,
            total_amount=110000,
            issue_date=date(2026, 5, 20),
            status="issued",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        mock_db.execute = AsyncMock(
            return_value=MockScalarResult(items=[inv], total=1)
        )

        response = client.get(
            "/api/v1/erp/invoices?status=issued",
            headers=_auth_headers(),
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data["items"]) == 1
        assert data["items"][0]["invoice_number"] == "INV-001"

    def test_get_invoice(self, client, mock_db):
        from src.models.models import Invoice

        inv_id = uuid.uuid4()
        inv = Invoice(
            id=inv_id,
            organization_id=uuid.uuid4(),
            invoice_number="INV-001",
            invoice_type="payable",
            vendor_name="建材商事",
            amount=100000,
            tax_amount=10000,
            total_amount=110000,
            issue_date=date(2026, 5, 20),
            status="issued",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        mock_db.get = AsyncMock(return_value=inv)

        response = client.get(
            f"/api/v1/erp/invoices/{inv_id}",
            headers=_auth_headers(),
        )
        assert response.status_code == 200
        data = response.json()
        assert data["invoice_number"] == "INV-001"
        assert float(data["total_amount"]) == 110000

    def test_pay_invoice(self, client, mock_db):
        from src.models.models import Invoice

        inv_id = uuid.uuid4()
        inv = Invoice(
            id=inv_id,
            organization_id=uuid.uuid4(),
            invoice_number="INV-001",
            invoice_type="payable",
            vendor_name="建材商事",
            amount=100000,
            tax_amount=10000,
            total_amount=110000,
            issue_date=date(2026, 5, 20),
            due_date=date(2026, 6, 20),
            status="issued",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        mock_db.get = AsyncMock(return_value=inv)

        response = client.post(
            f"/api/v1/erp/invoices/{inv_id}/pay",
            json={"payment_method": "bank_transfer"},
            headers=_auth_headers(),
        )
        assert response.status_code == 200
        assert inv.status == "paid"
        assert inv.paid_date is not None
        assert inv.payment_method == "bank_transfer"

    def test_pay_invoice_invalid_status(self, client, mock_db):
        from src.models.models import Invoice

        inv_id = uuid.uuid4()
        inv = Invoice(
            id=inv_id,
            organization_id=uuid.uuid4(),
            invoice_number="INV-001",
            invoice_type="payable",
            vendor_name="建材商事",
            amount=100000,
            tax_amount=10000,
            total_amount=110000,
            issue_date=date(2026, 5, 20),
            status="paid",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        mock_db.get = AsyncMock(return_value=inv)

        response = client.post(
            f"/api/v1/erp/invoices/{inv_id}/pay",
            json={},
            headers=_auth_headers(),
        )
        assert response.status_code == 400

    def test_update_invoice_recalculates_total(self, client, mock_db):
        from src.models.models import Invoice

        inv_id = uuid.uuid4()
        inv = Invoice(
            id=inv_id,
            organization_id=uuid.uuid4(),
            invoice_number="INV-001",
            invoice_type="payable",
            vendor_name="建材商事",
            amount=100000,
            tax_amount=10000,
            total_amount=110000,
            issue_date=date(2026, 5, 20),
            status="draft",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        mock_db.get = AsyncMock(return_value=inv)

        response = client.put(
            f"/api/v1/erp/invoices/{inv_id}",
            json={"amount": "200000", "tax_amount": "20000"},
            headers=_auth_headers(),
        )
        assert response.status_code == 200
        assert float(inv.amount) == 200000
        assert float(inv.tax_amount) == 20000
        assert float(inv.total_amount) == 220000
