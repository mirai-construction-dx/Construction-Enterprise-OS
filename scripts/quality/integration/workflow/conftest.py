"""workflow サービス 実 DB 統合検証の conftest（Lead 所有）。

目的: teammate が「実 DB 同時実行では未検証」と明示した WF-1（承認の競合状態）を
Lead が独立に再現する。通知・文書アダプタは外部接続を避けるため無効化する。

    cd <repo root>
    PYTHONPATH=services/workflow:scripts/quality/integration \\
      python3 -m pytest scripts/quality/integration/workflow -q -p no:cacheprovider
"""

from __future__ import annotations

import os
import pathlib
import sys

_HERE = pathlib.Path(__file__).resolve()
_REPO = _HERE.parents[3]
sys.path.insert(0, str(_HERE.parents[1]))
sys.path.insert(0, str(_REPO / "services" / "workflow"))

import _shared  # noqa: E402

os.environ.setdefault("ENVIRONMENT", "test")
os.environ["DATABASE_URL"] = _shared.sqlalchemy_dsn()
os.environ.setdefault("JWT_PUBLIC_KEY", _shared.DEV_JWT_SECRET)
os.environ.setdefault("JWT_ALGORITHM", "HS256")
os.environ["DEBUG"] = "false"
# 外部サービスへの通知を明示的に無効化する（外部接続禁止）
os.environ["NOTIFICATION_SERVICE_URL"] = ""
os.environ["AUTH_SERVICE_URL"] = ""

import asyncio  # noqa: E402
import uuid  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import src.models  # noqa: E402,F401  (テーブル定義の登録)
from src.main import create_app  # noqa: E402
from src.models.base import Base, engine  # noqa: E402

ORG_A = _shared.ORG_A
USER_A = _shared.USER_A

INSTANCE_ID = uuid.UUID("00000000-0000-0000-0000-0000000c0001")
APPROVAL_ID = uuid.UUID("00000000-0000-0000-0000-0000000c0002")


@pytest.fixture(scope="session", autouse=True)
def _prepare_database():
    async def _setup() -> None:
        from sqlalchemy import text

        _shared.assert_destructive_target_allowed()
        async with engine.begin() as conn:
            # workflow 本体に加え、WorkflowAuditLog が書込む共有の auth.audit_logs も
            # テスト専用 DB 上にのみ作成する（本番・他サービスには影響しない）。
            await conn.execute(text("CREATE SCHEMA IF NOT EXISTS workflow"))
            await conn.execute(text("CREATE SCHEMA IF NOT EXISTS auth"))
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
        await engine.dispose()

    asyncio.run(_setup())
    yield


@pytest.fixture(scope="session")
def client():
    """session スコープ。同一イベントループ上で並行リクエストを処理させる。"""
    with TestClient(create_app()) as c:
        yield c


def headers_org_a(roles: list[str] | None = None) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {_shared.make_token(ORG_A, USER_A, roles or ['admin'])}"
    }
