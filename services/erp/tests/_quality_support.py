"""品質テスト共通サポート（synthetic fixture / DB モック / SQL 検査）。

本モジュールは pytest のテストとして収集されない（先頭が ``test_`` でない）。
実 DB・ネットワーク・外部 Provider には一切接続しない。すべて合成データ。

設計方針:
- ``CaptureDB`` は ``db.execute`` に渡された SQLAlchemy 文を捕捉する。
  テナント境界の有無は、捕捉した文の **WHERE 句のみ** を ``postgresql.dialect()`` で
  compile して検査する（SELECT 句の列名に ``organization_id`` が現れても誤検知しない）。
- ``make_client`` は ``get_db`` / ``get_current_user`` を dependency_overrides で差し替える。
  既存 ``tests/test_erp.py`` と同じ方式。
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy.dialects import postgresql

from src.main import create_app
from src.middleware.auth import TokenData, get_current_user
from src.models.base import get_db
from src.models.models import Budget, CostItem, Invoice, ProjectLedger

# --- synthetic テナント（憲章: UUID は ...00aa 形式） -------------------------
ORG_A = uuid.UUID("00000000-0000-0000-0000-0000000000aa")
ORG_B = uuid.UUID("00000000-0000-0000-0000-0000000000bb")
USER_A = uuid.UUID("00000000-0000-0000-0000-0000000000a1")
SPOOFED_APPROVER = uuid.UUID("00000000-0000-0000-0000-0000000000ff")

_STATUS_DEFAULTS = {
    "ProjectLedger": "planning",
    "CostItem": "pending",
    "Invoice": "draft",
}
_ZERO_IF_NONE = (
    "actual_cost",
    "budget_amount",
    "progress_rate",
    "estimated_profit",
    "actual_amount",
    "tax_amount",
    "total_amount",
)


class Result:
    """``db.execute`` の戻り値スタブ。"""

    def __init__(self, items=None, total=0):
        self._items = list(items or [])
        self._total = total

    def scalar_one_or_none(self):
        return self._items[0] if self._items else None

    def scalar(self):
        return self._total

    def scalars(self):
        return self

    def all(self):
        return self._items

    def first(self):
        return self._items[0] if self._items else None


def fill_defaults(obj):
    """mock の ``refresh`` 相当。DB が付与する既定値を合成する。"""
    if getattr(obj, "id", None) is None:
        obj.id = uuid.uuid4()
    now = datetime.now(timezone.utc)
    for attr in ("created_at", "updated_at"):
        if hasattr(obj, attr) and getattr(obj, attr, None) is None:
            setattr(obj, attr, now)
    for attr in _ZERO_IF_NONE:
        if hasattr(obj, attr) and getattr(obj, attr, None) is None:
            setattr(obj, attr, 0)
    if hasattr(obj, "status") and getattr(obj, "status", None) is None:
        setattr(obj, "status", _STATUS_DEFAULTS.get(type(obj).__name__, "active"))
    return obj


class CaptureDB:
    """AsyncSession の最小スタブ。execute された文と DB 操作を記録する。"""

    def __init__(self, entities=None, items=None):
        self.entities = dict(entities or {})
        self.items = list(items or [])
        self.statements = []
        self.added = []
        self.deleted = []
        self.flushed = 0
        self.committed = False
        self.rolled_back = False

    # --- 記録用ヘルパ ---------------------------------------------------
    def put(self, obj):
        self.entities[(type(obj).__name__, str(obj.id))] = obj
        return obj

    # --- AsyncSession 互換 ---------------------------------------------
    def add(self, obj):
        self.added.append(obj)
        return None

    async def delete(self, obj):
        self.deleted.append(obj)

    async def flush(self):
        self.flushed += 1

    async def refresh(self, obj):
        return fill_defaults(obj)

    async def commit(self):
        self.committed = True

    async def rollback(self):
        self.rolled_back = True

    async def close(self):
        return None

    async def get(self, entity, entity_id):
        if entity_id is None:
            return None
        return self.entities.get((entity.__name__, str(entity_id)))

    async def execute(self, statement, *args, **kwargs):
        self.statements.append(statement)
        return Result(items=self.items, total=len(self.items))


def make_client(db, org=ORG_A, sub=USER_A, roles=None, scopes=None):
    """依存性を差し替えた TestClient を返す（DB 不要）。"""
    app = create_app()

    async def _override_db():
        yield db

    async def _override_user():
        return TokenData(
            sub=str(sub),
            type="user",
            org=str(org) if org is not None else None,
            roles=list(roles or []),
            scopes=list(scopes or []),
        )

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_current_user] = _override_user
    return TestClient(app, raise_server_exceptions=False)


def unauthenticated_client():
    """認証 override をしない素のアプリ（401 の positive control 用）。"""
    return TestClient(create_app(), raise_server_exceptions=False)


# --- synthetic エンティティ ---------------------------------------------------
def make_ledger(
    org=ORG_A,
    *,
    lid=None,
    contract="1000000",
    budget="800000",
    actual="0",
    status="planning",
):
    return ProjectLedger(
        id=lid or uuid.uuid4(),
        organization_id=org,
        project_id=uuid.uuid4(),
        project_code="PJ-QA-001",
        project_name="テスト工事A",
        project_type="building",
        client_name="テスト建設",
        contract_amount=Decimal(str(contract)),
        budget_amount=Decimal(str(budget)),
        actual_cost=Decimal(str(actual)),
        estimated_profit=Decimal("0"),
        progress_rate=Decimal("0"),
        status=status,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )


def make_cost(
    org=ORG_A,
    *,
    lid=None,
    cid=None,
    budget_id=None,
    amount="150000",
    status="pending",
    description="テスト原価A",
):
    return CostItem(
        id=cid or uuid.uuid4(),
        organization_id=org,
        ledger_id=lid,
        budget_id=budget_id,
        category="materials",
        description=description,
        amount=Decimal(str(amount)),
        cost_date=date(2026, 5, 1),
        status=status,
        created_at=datetime.now(timezone.utc),
    )


def make_budget(
    org=ORG_A,
    *,
    lid=None,
    bid=None,
    planned="300000",
    actual="0",
):
    return Budget(
        id=bid or uuid.uuid4(),
        organization_id=org,
        ledger_id=lid,
        category="materials",
        planned_amount=Decimal(str(planned)),
        actual_amount=Decimal(str(actual)),
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )


def make_invoice(
    org=ORG_A,
    *,
    iid=None,
    ledger_id=None,
    number="INV-QA-001",
    status="issued",
    amount="100",
    tax="10",
):
    total = Decimal(str(amount)) + Decimal(str(tax))
    return Invoice(
        id=iid or uuid.uuid4(),
        organization_id=org,
        ledger_id=ledger_id,
        invoice_number=number,
        invoice_type="payable",
        vendor_name="テスト商事",
        amount=Decimal(str(amount)),
        tax_amount=Decimal(str(tax)),
        total_amount=total,
        issue_date=date(2026, 5, 20),
        status=status,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )


# --- SQL 検査 ---------------------------------------------------------------
def where_sql(statement) -> str:
    """文の WHERE 句のみを PostgreSQL dialect で compile した文字列を返す。"""
    whereclause = getattr(statement, "whereclause", None)
    if whereclause is None:
        return ""
    return str(
        whereclause.compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )


def statement_wheres(db) -> list[str]:
    return [where_sql(statement) for statement in db.statements]


def has_org_filter(db, org) -> bool:
    needle = str(org)
    return any(
        needle in where and "organization_id" in where
        for where in statement_wheres(db)
    )
