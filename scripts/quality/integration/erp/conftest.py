"""erp サービス 実 DB 統合検証の conftest（Lead 所有）。

erp には migrations/000_base_schema.sql が追加された（本障害の修正）。
ただし本ハーネスは依然として ORM メタデータからテスト用スキーマを生成しており、
同梱 DDL の適用経路（構文・適用順序・冪等性）は検証していない。

TODO(要判断): construction と同様に `_shared.reset_service_tables` 経由で
同梱 DDL を適用する方式へ切り替える。DDL を実 DB へ適用する操作を伴うため、
適用可否の判断後に別変更単位で実施する。

実行方法:
    cd <repo root>
    PYTHONPATH=services/erp:scripts/quality/integration \\
      python3 -m pytest scripts/quality/integration/erp -q -p no:cacheprovider
"""

from __future__ import annotations

import os
import pathlib
import sys

_HERE = pathlib.Path(__file__).resolve()
_REPO = _HERE.parents[3]
sys.path.insert(0, str(_HERE.parents[1]))
sys.path.insert(0, str(_REPO / "services" / "erp"))

import _shared  # noqa: E402

os.environ.setdefault("ENVIRONMENT", "test")
os.environ["DATABASE_URL"] = _shared.sqlalchemy_dsn()
os.environ.setdefault("JWT_PUBLIC_KEY", _shared.DEV_JWT_SECRET)
os.environ.setdefault("JWT_ALGORITHM", "HS256")
os.environ["DEBUG"] = "false"

import asyncio  # noqa: E402
import uuid  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import src.models.models  # noqa: E402,F401  (テーブル定義の登録)
from src.main import create_app  # noqa: E402
from src.models.base import Base, engine  # noqa: E402

ORG_A = _shared.ORG_A
ORG_B = _shared.ORG_B
PROJECT_A = uuid.UUID("00000000-0000-0000-0000-00000000aa01")
PROJECT_B = uuid.UUID("00000000-0000-0000-0000-00000000bb01")

LEDGER_B = uuid.UUID("00000000-0000-0000-0000-0000000b0011")
COST_B = uuid.UUID("00000000-0000-0000-0000-0000000b0012")
INVOICE_B = uuid.UUID("00000000-0000-0000-0000-0000000b0013")
LEDGER_A = uuid.UUID("00000000-0000-0000-0000-0000000a0011")


@pytest.fixture(scope="session", autouse=True)
def _prepare_database():
    async def _setup() -> None:
        from sqlalchemy import text

        _shared.assert_destructive_target_allowed()
        async with engine.begin() as conn:
            await conn.execute(text("CREATE SCHEMA IF NOT EXISTS erp"))
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
        await engine.dispose()

    asyncio.run(_setup())
    yield


@pytest.fixture(scope="session")
def client():
    with TestClient(create_app()) as c:
        yield c


def headers_for_org_a() -> dict[str, str]:
    return {"Authorization": f"Bearer {_shared.make_token(ORG_A, _shared.USER_A)}"}


def headers_for_org_b() -> dict[str, str]:
    return {"Authorization": f"Bearer {_shared.make_token(ORG_B, _shared.USER_B)}"}
