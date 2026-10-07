"""construction サービス 実 DB 統合検証の conftest（Lead 所有）。

実行方法:
    cd <repo root>
    PYTHONPATH=services/construction:scripts/quality/integration \
      python3 -m pytest scripts/quality/integration/construction -q -p no:cacheprovider
"""

from __future__ import annotations

import os
import pathlib
import sys

_HERE = pathlib.Path(__file__).resolve()
_REPO = _HERE.parents[3]
sys.path.insert(0, str(_HERE.parents[1]))  # scripts/quality/integration -> _shared
sys.path.insert(0, str(_REPO / "services" / "construction"))

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

from src.main import create_app  # noqa: E402

ORG_A = _shared.ORG_A
ORG_B = _shared.ORG_B
PROJECT_B = _shared.PROJECT_B

RESOURCE_B = uuid.UUID("00000000-0000-0000-0000-0000000b0001")
SCHEDULE_B = uuid.UUID("00000000-0000-0000-0000-0000000b0002")
METHOD_B = uuid.UUID("00000000-0000-0000-0000-0000000b0003")


@pytest.fixture(scope="session", autouse=True)
def _prepare_database():
    """スキーマのみ準備する。データは各テストが自分で TRUNCATE + 再投入する。"""
    asyncio.run(
        _shared.reset_service_tables(
            "construction", ["resources", "schedules", "method_statements", "wbs_items"]
        )
    )
    yield


async def _seed_org_b() -> None:
    import asyncpg

    conn = await asyncpg.connect(_shared.raw_dsn())
    try:
        await conn.execute(
            """
            INSERT INTO construction.resources
              (id, organization_id, project_id, resource_type, name, unit,
               planned_quantity, actual_quantity, unit_cost, total_cost, status)
            VALUES ($1,$2,$3,'labor','テスト要員B','人日',10,0,20000,0,'planned')
            """,
            RESOURCE_B,
            ORG_B,
            PROJECT_B,
        )
        await conn.execute(
            """
            INSERT INTO construction.schedules
              (id, organization_id, project_id, name, schedule_type,
               planned_start, planned_end, predecessor_ids, successor_ids,
               critical_path, status, progress_percent)
            VALUES ($1,$2,$3,'テスト工程B','construction', DATE '2026-01-01',
                    DATE '2026-02-01', '{}', '{}', true, 'planned', 0)
            """,
            SCHEDULE_B,
            ORG_B,
            PROJECT_B,
        )
        await conn.execute(
            """
            INSERT INTO construction.method_statements
              (id, organization_id, project_id, title, document_type, attachments, status)
            VALUES ($1,$2,$3,'テスト施工計画B','method_statement','{}','review')
            """,
            METHOD_B,
            ORG_B,
            PROJECT_B,
        )
    finally:
        await conn.close()


@pytest.fixture(scope="session")
def client():
    """TestClient は session スコープ。

    SQLAlchemy の async engine はコネクションプールをイベントループに束縛するため、
    テストごとに新しい TestClient(=新しいイベントループ)を作ると
    「another operation is in progress」で全リクエストが失敗する。
    """
    with TestClient(create_app()) as c:
        yield c


def headers_for_org_a() -> dict[str, str]:
    return {"Authorization": f"Bearer {_shared.make_token(ORG_A, _shared.USER_A)}"}


def headers_for_org_b() -> dict[str, str]:
    return {"Authorization": f"Bearer {_shared.make_token(ORG_B, _shared.USER_B)}"}
