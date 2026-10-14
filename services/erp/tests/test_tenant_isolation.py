"""Organization (tenant) isolation tests for the ERP service (Issue #114, ADR-0004)."""

import uuid
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from src.main import create_app
from src.middleware.auth import TokenData, get_current_user
from src.middleware.tenant import create_org, scope_org
from src.models.base import get_db
from src.models.models import Budget, CostItem, ProjectLedger

ORG_A = uuid.uuid4()
ORG_B = uuid.uuid4()
BASE = "/api/v1/erp"


def _user(org: str | None = str(ORG_A), roles: list[str] | None = None) -> TokenData:
    return TokenData(
        sub=str(uuid.uuid4()),
        type="user",
        org=org,
        roles=roles if roles is not None else ["accountant"],
    )


class _Result:
    def __init__(self, value=None, items=None, total=0):
        self._value = value
        self._items = items or []
        self._total = total

    def scalar(self):
        return self._total

    def scalar_one_or_none(self):
        return self._value

    def scalars(self):
        return self

    def all(self):
        return self._items


def _client(*results, user: TokenData | None = None):
    """App whose DB returns ``results`` for successive ``execute`` calls (``get`` returns None)."""
    app = create_app()
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=list(results))
    db.get = AsyncMock(return_value=None)
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.delete = AsyncMock()

    async def _refresh(obj):
        # emulate server defaults so the response model validates
        now = datetime.now(timezone.utc)
        obj.id = obj.id or uuid.uuid4()
        defaults = {
            "created_at": now,
            "updated_at": now,
            "actual_cost": 0,
            "budget_amount": 0,
            "progress_rate": 0,
            "tax_amount": 0,
            "status": "draft",
        }
        for attr, default in defaults.items():
            if hasattr(obj, attr) and getattr(obj, attr) is None:
                setattr(obj, attr, default)

    db.refresh = AsyncMock(side_effect=_refresh)

    async def _db():
        yield db

    async def _current_user():
        return user or _user()

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[get_current_user] = _current_user
    return TestClient(app), db


def _compiled(db, index: int):
    stmt = db.execute.await_args_list[index].args[0]
    return str(stmt), stmt.compile().params


def _assert_scoped_to(db, index: int, org: uuid.UUID):
    sql, params = _compiled(db, index)
    assert ".organization_id = :" in sql  # a WHERE predicate, not just the column list
    assert org in params.values()


def _ledger(
    org: uuid.UUID = ORG_A, ledger_id: uuid.UUID | None = None
) -> ProjectLedger:
    now = datetime.now(timezone.utc)
    return ProjectLedger(
        id=ledger_id or uuid.uuid4(),
        organization_id=org,
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
        created_at=now,
        updated_at=now,
    )


# Valid bodies (so requests never short-circuit with 422)
LEDGER_BODY = {
    "project_id": str(uuid.uuid4()),
    "project_code": "PJ-001",
    "project_name": "テスト工事",
    "project_type": "building",
    "contract_amount": "1000000",
}
BUDGET_BODY = {"category": "materials", "planned_amount": "300000"}
COST_BODY = {
    "category": "materials",
    "description": "セメント購入",
    "amount": "50000",
    "cost_date": "2026-05-01",
}
INVOICE_BODY = {
    "invoice_number": "INV-001",
    "invoice_type": "payable",
    "vendor_name": "建材商事",
    "amount": "100000",
    "issue_date": "2026-05-20",
}


# ── helper rules ─────────────────────────────────────────────


def test_scope_org_regular_user_is_pinned_to_token_org():
    assert scope_org(_user()) == ORG_A
    assert scope_org(_user(), ORG_A) == ORG_A


def test_scope_org_rejects_other_org_for_regular_user():
    with pytest.raises(HTTPException) as exc:
        scope_org(_user(), ORG_B)
    assert exc.value.status_code == 403
    assert exc.value.detail["code"] == "ORG_FORBIDDEN"


@pytest.mark.parametrize(
    ("org", "code"),
    [(None, "ORG_REQUIRED"), ("", "ORG_REQUIRED"), ("not-a-uuid", "ORG_INVALID")],
)
def test_scope_org_fails_closed_without_valid_org(org, code):
    with pytest.raises(HTTPException) as exc:
        scope_org(_user(org=org))
    assert exc.value.status_code == 403
    assert exc.value.detail["code"] == code


def test_roles_none_is_not_admin():
    user = TokenData(sub="u", type="user", org=str(ORG_A), roles=None)
    assert scope_org(user) == ORG_A


def test_admin_is_cross_org():
    admin = _user(org=None, roles=["admin"])
    assert scope_org(admin) is None  # no filter
    assert scope_org(admin, ORG_B) == ORG_B
    assert create_org(admin, ORG_B) == ORG_B


def test_create_org_rejects_other_org_for_regular_user():
    assert create_org(_user(), ORG_A) == ORG_A
    with pytest.raises(HTTPException) as exc:
        create_org(_user(), ORG_B)
    assert exc.value.status_code == 403
    assert exc.value.detail["code"] == "ORG_FORBIDDEN"


# ── lists: other org → 403, default → token org ─────────────


@pytest.mark.parametrize("path", [f"{BASE}/ledger", f"{BASE}/invoices"])
def test_list_other_org_is_forbidden(path):
    client, db = _client()

    resp = client.get(path, params={"organization_id": str(ORG_B)})

    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "ORG_FORBIDDEN"
    db.execute.assert_not_awaited()


@pytest.mark.parametrize("path", [f"{BASE}/ledger", f"{BASE}/invoices"])
def test_list_defaults_to_token_org(path):
    client, db = _client(_Result(total=0), _Result(items=[]))

    resp = client.get(path)

    assert resp.status_code == 200
    _assert_scoped_to(db, 0, ORG_A)  # count
    _assert_scoped_to(db, 1, ORG_A)  # rows


@pytest.mark.parametrize("path", [f"{BASE}/ledger", f"{BASE}/invoices"])
def test_list_without_org_claim_is_rejected(path):
    client, db = _client(user=_user(org=None))

    resp = client.get(path)

    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "ORG_REQUIRED"
    db.execute.assert_not_awaited()


# ── by-id: org-scoped lookup → other org is 404 ─────────────

_LEDGER_ID = uuid.uuid4()
_BUDGET_ID = uuid.uuid4()
_COST_ID = uuid.uuid4()
_INVOICE_ID = uuid.uuid4()


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        # ledger and everything nested under it (child rows are gated by the parent ledger)
        ("get", f"{BASE}/ledger/{_LEDGER_ID}", None),
        ("put", f"{BASE}/ledger/{_LEDGER_ID}", {"project_name": "x"}),
        ("get", f"{BASE}/ledger/{_LEDGER_ID}/summary", None),
        ("get", f"{BASE}/ledger/{_LEDGER_ID}/budgets", None),
        ("get", f"{BASE}/ledger/{_LEDGER_ID}/budget-summary", None),
        ("get", f"{BASE}/ledger/{_LEDGER_ID}/costs", None),
        (
            "post",
            f"{BASE}/ledger/{_LEDGER_ID}/budgets",
            {**BUDGET_BODY, "organization_id": str(ORG_A)},
        ),
        (
            "post",
            f"{BASE}/ledger/{_LEDGER_ID}/costs",
            {**COST_BODY, "organization_id": str(ORG_A)},
        ),
        # budgets / costs / invoices by id
        ("put", f"{BASE}/budgets/{_BUDGET_ID}", {"planned_amount": "1"}),
        ("put", f"{BASE}/costs/{_COST_ID}", {"description": "x"}),
        (
            "post",
            f"{BASE}/costs/{_COST_ID}/approve",
            {"approved_by": str(uuid.uuid4())},
        ),
        ("delete", f"{BASE}/costs/{_COST_ID}", None),
        ("get", f"{BASE}/invoices/{_INVOICE_ID}", None),
        ("put", f"{BASE}/invoices/{_INVOICE_ID}", {"notes": "x"}),
        ("post", f"{BASE}/invoices/{_INVOICE_ID}/pay", {}),
    ],
)
def test_by_id_is_scoped_to_token_org(method, path, body):
    """A record of another organization is not found (404) because the lookup is org-scoped."""
    client, db = _client(_Result(None))

    kwargs = {"json": body} if body is not None else {}
    resp = client.request(method.upper(), path, **kwargs)

    assert resp.status_code == 404
    db.execute.assert_awaited_once()
    _assert_scoped_to(db, 0, ORG_A)
    db.get.assert_not_awaited()  # never an unscoped primary-key lookup
    db.add.assert_not_called()
    db.delete.assert_not_awaited()


def test_by_id_in_own_org_is_found():
    ledger = _ledger()
    client, db = _client(_Result(ledger))

    resp = client.get(f"{BASE}/ledger/{ledger.id}/summary")

    assert resp.status_code == 200
    _assert_scoped_to(db, 0, ORG_A)


# ── nested child rows are filtered by their own organization too ──
# Defense in depth (ADR-0004): even when the parent ledger belongs to the caller's
# organization, a child row (budget / cost item) of another organization must never
# appear in a list, total, summary or detail. With a mocked DB we assert on the SQL:
# every child query carries a WHERE predicate on the child table's organization_id.

_BUDGETS_ORG = "budgets.organization_id = :"
_COSTS_ORG = "cost_items.organization_id = :"


def _nested_cases(ledger_id):
    """(path, DB results after the ledger lookup, [(child execute offset, predicate)])."""
    return [
        (
            f"{BASE}/ledger/{ledger_id}/budgets",
            [_Result(items=[])],
            [(0, _BUDGETS_ORG)],
        ),
        (
            f"{BASE}/ledger/{ledger_id}/budget-summary",
            [_Result(items=[])],
            [(0, _BUDGETS_ORG)],
        ),
        (
            f"{BASE}/ledger/{ledger_id}/costs",
            [_Result(total=0), _Result(items=[])],
            [(0, _COSTS_ORG), (1, _COSTS_ORG)],  # total, rows
        ),
        (
            f"{BASE}/ledger/{ledger_id}",
            [_Result(items=[]), _Result(items=[])],
            [(0, _BUDGETS_ORG), (1, _COSTS_ORG)],  # budgets, cost summary
        ),
    ]


_NESTED_IDS = ["budgets", "budget-summary", "costs", "detail"]


@pytest.mark.parametrize("case", range(4), ids=_NESTED_IDS)
def test_nested_child_rows_are_scoped_to_token_org(case):
    """Own-org ledger, but other-org child rows are excluded by the child's org predicate."""
    ledger = _ledger(org=ORG_A)
    path, child_results, checks = _nested_cases(ledger.id)[case]
    client, db = _client(_Result(ledger), *child_results)

    resp = client.get(path)

    assert resp.status_code == 200
    assert db.execute.await_count == 1 + len(child_results)
    _assert_scoped_to(db, 0, ORG_A)  # parent ledger
    for offset, predicate in checks:
        sql, params = _compiled(db, 1 + offset)
        assert predicate in sql
        assert ORG_A in params.values()
        assert ORG_B not in params.values()


@pytest.mark.parametrize("case", range(4), ids=_NESTED_IDS)
def test_admin_nested_child_rows_are_unscoped(case):
    ledger = _ledger(org=ORG_B)
    path, child_results, checks = _nested_cases(ledger.id)[case]
    client, db = _client(*child_results, user=_user(roles=["admin"]))
    db.get = AsyncMock(return_value=ledger)  # admin ledger lookup is an unscoped get

    resp = client.get(path)

    assert resp.status_code == 200
    assert db.execute.await_count == len(child_results)
    for offset, _predicate in checks:
        assert ".organization_id = :" not in _compiled(db, offset)[0]


# ── create: body org must equal token org ───────────────────


@pytest.mark.parametrize(
    ("path", "body"),
    [
        (f"{BASE}/ledger", LEDGER_BODY),
        (f"{BASE}/ledger/{uuid.uuid4()}/budgets", BUDGET_BODY),
        (f"{BASE}/ledger/{uuid.uuid4()}/costs", COST_BODY),
        (f"{BASE}/invoices", INVOICE_BODY),
    ],
)
def test_create_in_other_org_is_forbidden(path, body):
    client, db = _client()

    resp = client.post(path, json={**body, "organization_id": str(ORG_B)})

    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "ORG_FORBIDDEN"
    db.execute.assert_not_awaited()
    db.get.assert_not_awaited()
    db.add.assert_not_called()


def test_create_ledger_in_own_org():
    client, db = _client()

    resp = client.post(
        f"{BASE}/ledger", json={**LEDGER_BODY, "organization_id": str(ORG_A)}
    )

    assert resp.status_code == 201
    assert resp.json()["organization_id"] == str(ORG_A)
    assert db.add.call_args[0][0].organization_id == ORG_A


def test_create_invoice_with_other_org_ledger_is_not_found():
    client, db = _client(_Result(None))

    resp = client.post(
        f"{BASE}/invoices",
        json={
            **INVOICE_BODY,
            "organization_id": str(ORG_A),
            "ledger_id": str(uuid.uuid4()),
        },
    )

    assert resp.status_code == 404
    _assert_scoped_to(db, 0, ORG_A)
    db.add.assert_not_called()


def test_create_cost_with_other_org_budget_is_not_found():
    """budget_id of another organization must not be attachable (approve would update it)."""
    ledger = _ledger()
    client, db = _client(_Result(ledger), _Result(None))

    resp = client.post(
        f"{BASE}/ledger/{ledger.id}/costs",
        json={
            **COST_BODY,
            "organization_id": str(ORG_A),
            "budget_id": str(uuid.uuid4()),
        },
    )

    assert resp.status_code == 404
    _assert_scoped_to(db, 0, ORG_A)  # ledger
    _assert_scoped_to(db, 1, ORG_A)  # budget
    db.add.assert_not_called()


def test_create_cost_with_budget_of_other_ledger_is_not_found():
    ledger = _ledger()
    budget = Budget(
        id=uuid.uuid4(),
        organization_id=ORG_A,
        ledger_id=uuid.uuid4(),
        category="materials",
        planned_amount=1,
        actual_amount=0,
    )
    client, db = _client(_Result(ledger), _Result(budget))

    resp = client.post(
        f"{BASE}/ledger/{ledger.id}/costs",
        json={**COST_BODY, "organization_id": str(ORG_A), "budget_id": str(budget.id)},
    )

    assert resp.status_code == 404
    db.add.assert_not_called()


# ── admin: cross-organization ───────────────────────────────


@pytest.mark.parametrize("path", [f"{BASE}/ledger", f"{BASE}/invoices"])
def test_admin_list_without_org_is_global(path):
    client, db = _client(
        _Result(total=0), _Result(items=[]), user=_user(roles=["admin"])
    )

    resp = client.get(path)

    assert resp.status_code == 200
    assert ".organization_id = :" not in _compiled(db, 0)[0]
    assert ".organization_id = :" not in _compiled(db, 1)[0]


def test_admin_list_other_org_is_allowed():
    client, db = _client(
        _Result(total=0), _Result(items=[]), user=_user(roles=["admin"])
    )

    resp = client.get(f"{BASE}/invoices", params={"organization_id": str(ORG_B)})

    assert resp.status_code == 200
    _assert_scoped_to(db, 0, ORG_B)


def test_admin_by_id_is_unscoped():
    client, db = _client(user=_user(roles=["admin"]))
    ledger = _ledger(org=ORG_B)
    db.get = AsyncMock(return_value=ledger)

    resp = client.get(f"{BASE}/ledger/{ledger.id}/summary")

    assert resp.status_code == 200
    db.execute.assert_not_awaited()


def test_admin_create_in_other_org_is_allowed():
    client, db = _client(user=_user(roles=["admin"]))

    resp = client.post(
        f"{BASE}/invoices", json={**INVOICE_BODY, "organization_id": str(ORG_B)}
    )

    assert resp.status_code == 201
    assert db.add.call_args[0][0].organization_id == ORG_B


def test_admin_nested_create_must_match_ledger_org():
    client, db = _client(user=_user(roles=["admin"]))
    ledger = _ledger(org=ORG_A)
    db.get = AsyncMock(return_value=ledger)

    resp = client.post(
        f"{BASE}/ledger/{ledger.id}/budgets",
        json={**BUDGET_BODY, "organization_id": str(ORG_B)},
    )

    assert resp.status_code == 400
    db.add.assert_not_called()


# ── approve side effects never cross organizations ──────────


def test_approve_does_not_update_other_org_budget_or_ledger():
    # D9: 他テナントの予算を参照した原価の承認は拒否され、予算・台帳へ実績は加算されない。
    cost = CostItem(
        id=uuid.uuid4(),
        organization_id=ORG_A,
        ledger_id=uuid.uuid4(),
        budget_id=uuid.uuid4(),
        category="materials",
        description="x",
        amount=100,
        cost_date=date(2026, 5, 1),
        status="pending",
        created_at=datetime.now(timezone.utc),
    )
    foreign_budget = Budget(
        id=cost.budget_id,
        organization_id=ORG_B,
        ledger_id=cost.ledger_id,
        category="materials",
        planned_amount=1000,
        actual_amount=0,
    )
    foreign_ledger = _ledger(org=ORG_B, ledger_id=cost.ledger_id)

    async def _get(model, _id):
        return {Budget: foreign_budget, ProjectLedger: foreign_ledger}.get(model)

    client, db = _client(_Result(cost))
    db.get = AsyncMock(side_effect=_get)

    resp = client.post(
        f"{BASE}/costs/{cost.id}/approve", json={"approved_by": str(uuid.uuid4())}
    )

    assert resp.status_code in (400, 422)
    assert cost.status == "pending"  # 拒否され、承認されない
    assert float(foreign_budget.actual_amount) == 0
    assert float(foreign_ledger.actual_cost) == 0
