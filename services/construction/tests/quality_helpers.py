"""品質テスト共通ヘルパー（QA-Construction）。

制約:
- synthetic fixture のみ。実データ・個人情報・実在企業データを含まない。
- 外部 Provider / MCP / 本番 DB / 実サービスへ接続しない（DB は AsyncMock）。
- 既存 `tests/test_construction.py` の mock_db / app / client 方式を踏襲する。
"""

import uuid
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.dialects import postgresql

from src.main import create_app
from src.middleware.auth import TokenData, get_current_user
from src.models import MethodStatement, Resource, Schedule, WBSItem
from src.models.base import get_db

# ============================================
# synthetic identifiers（実在の値ではない）
# ============================================
ORG_A = uuid.UUID("00000000-0000-0000-0000-0000000000aa")  # トークン保持組織
ORG_B = uuid.UUID("00000000-0000-0000-0000-0000000000bb")  # 他テナント
USER_A = uuid.UUID("00000000-0000-0000-0000-0000000000cc")  # トークン保持者
USER_B = uuid.UUID("00000000-0000-0000-0000-0000000000ee")  # 偽装に用いる別人
PROJECT_A = uuid.UUID("00000000-0000-0000-0000-0000000000dd")
PROJECT_B = uuid.UUID("00000000-0000-0000-0000-0000000000ff")

NOW = datetime(2026, 5, 1, tzinfo=timezone.utc)
START = date(2026, 5, 1)
END = date(2026, 6, 30)

AUTH_HEADERS = {"Authorization": "Bearer synthetic-test-token"}

API = "/api/v1/construction"


# ============================================
# mock DB（既存テストと同一方式）
# ============================================
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
    if hasattr(obj, "status") and getattr(obj, "status", None) is None:
        defaults = {
            "WBSItem": "pending",
            "Resource": "planned",
            "Schedule": "planned",
            "MethodStatement": "draft",
        }
        setattr(obj, "status", defaults.get(type(obj).__name__, "active"))
    return obj


def make_mock_db() -> AsyncMock:
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
def mock_db():
    return make_mock_db()


def build_client(mock_db, *, org=ORG_A, sub=USER_A, roles=("admin",)):
    """依存性を差し替えた (app, TestClient) を返す。"""
    app = create_app()

    async def mock_get_db():
        yield mock_db

    async def mock_get_current_user():
        return TokenData(
            sub=str(sub), type="user", org=str(org), roles=list(roles)
        )

    app.dependency_overrides[get_db] = mock_get_db
    app.dependency_overrides[get_current_user] = mock_get_current_user
    return app, TestClient(app)


@pytest.fixture
def app(mock_db):
    _app, _client = build_client(mock_db)
    return _app


@pytest.fixture
def client(mock_db):
    _app, _client = build_client(mock_db)
    return _client


@pytest.fixture
def client_no_auth():
    """認証オーバーライドなし（未認証アクセス検証用）。"""
    return TestClient(create_app())


# ============================================
# SQL 捕捉（DB 不要）
# ============================================
def record_execute(mock_db, results):
    """`db.execute` に渡された文を捕捉しつつ、指定結果を順に返す。

    results の要素は MockScalarResult、または () -> MockScalarResult。
    返り値: 捕捉した文のリスト（呼び出し順）。
    """
    captured = []
    queue = list(results)

    async def _execute(stmt, *args, **kwargs):
        captured.append(stmt)
        if queue:
            item = queue.pop(0)
            return item() if callable(item) else item
        return MockScalarResult()

    mock_db.execute = AsyncMock(side_effect=_execute)
    return captured


def compile_sql(stmt) -> str:
    return str(
        stmt.compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )


def where_clause(sql: str) -> str:
    """SELECT 文の WHERE 以降だけを返す（SELECT 列の organization_id と区別する）。"""
    idx = sql.upper().find("WHERE")
    return sql[idx:] if idx >= 0 else ""


# ============================================
# synthetic model factories
# ============================================
def make_wbs(**kw) -> WBSItem:
    data = dict(
        id=uuid.uuid4(),
        organization_id=ORG_A,
        project_id=PROJECT_A,
        parent_id=None,
        wbs_code="1",
        name="テスト工区A",
        description=None,
        level=1,
        planned_start=None,
        planned_end=None,
        actual_start=None,
        actual_end=None,
        planned_cost=None,
        actual_cost=None,
        weight_percent=None,
        progress_percent=0,
        status="pending",
        responsible_person=None,
        created_at=NOW,
        updated_at=NOW,
    )
    data.update(kw)
    return WBSItem(**data)


def make_resource(**kw) -> Resource:
    data = dict(
        id=uuid.uuid4(),
        organization_id=ORG_A,
        project_id=PROJECT_A,
        wbs_item_id=None,
        resource_type="labor",
        name="テスト資源A",
        specification=None,
        unit="人日",
        planned_quantity=None,
        actual_quantity=None,
        unit_cost=None,
        total_cost=None,
        allocation_start=None,
        allocation_end=None,
        status="planned",
        created_at=NOW,
    )
    data.update(kw)
    return Resource(**data)


def make_schedule(**kw) -> Schedule:
    data = dict(
        id=uuid.uuid4(),
        organization_id=ORG_A,
        project_id=PROJECT_A,
        wbs_item_id=None,
        name="テスト工程A",
        schedule_type="master",
        planned_start=START,
        planned_end=END,
        actual_start=None,
        actual_end=None,
        duration_days=None,
        predecessor_ids=[],
        successor_ids=[],
        float_days=None,
        critical_path=False,
        status="planned",
        progress_percent=0,
        created_at=NOW,
        updated_at=NOW,
    )
    data.update(kw)
    return Schedule(**data)


def make_method(**kw) -> MethodStatement:
    data = dict(
        id=uuid.uuid4(),
        organization_id=ORG_A,
        project_id=PROJECT_A,
        wbs_item_id=None,
        title="テスト施工計画書A",
        document_type="method_statement",
        content=None,
        safety_measures=None,
        environmental_measures=None,
        quality_control_points=None,
        required_equipment=None,
        required_materials=None,
        required_labor=None,
        attachments=[],
        status="draft",
        approved_by=None,
        approved_at=None,
        created_by=None,
        created_at=NOW,
        updated_at=NOW,
    )
    data.update(kw)
    return MethodStatement(**data)
