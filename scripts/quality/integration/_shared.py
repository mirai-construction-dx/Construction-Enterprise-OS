"""Lead 統合検証用の共通ヘルパー（テスト専用エフェメラル PostgreSQL）。

制約（reports/quality-tests/CHARTER.md）:
- 本番 DB / 実サービス / 外部 Provider へは接続しない。
- 接続先は 127.0.0.1 の使い捨てコンテナ (ceos-quality-pg) のみ。
- データは synthetic のみ。
"""

from __future__ import annotations

import os
import pathlib
import uuid

import asyncpg
import jwt

DEFAULT_DSN = "postgresql://ceos_qa:ceos_qa_local_only@127.0.0.1:55432/ceos_qa"
DEV_JWT_SECRET = "dev-only-do-not-use-in-production"

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]

# 破壊的操作（DROP SCHEMA CASCADE）を許す接続先のホワイトリスト。
# 誤設定で本番・共有 DB を壊さないための安全弁。追加はここに明示すること。
ALLOWED_DESTRUCTIVE_ENDPOINTS = {
    ("127.0.0.1", 55432),
    ("localhost", 55432),
    ("::1", 55432),
}

ORG_A = uuid.UUID("00000000-0000-0000-0000-0000000000aa")
ORG_B = uuid.UUID("00000000-0000-0000-0000-0000000000bb")
PROJECT_B = uuid.UUID("00000000-0000-0000-0000-00000000bb01")
USER_A = uuid.UUID("00000000-0000-0000-0000-0000000000a1")
USER_B = uuid.UUID("00000000-0000-0000-0000-0000000000b1")


def raw_dsn() -> str:
    return os.environ.get("CEOS_TEST_DATABASE_URL", DEFAULT_DSN)


def assert_destructive_target_allowed() -> None:
    """DROP SCHEMA CASCADE を実行してよい接続先かを検証する（安全弁）。"""
    from urllib.parse import urlparse

    parsed = urlparse(raw_dsn())
    endpoint = (parsed.hostname or "127.0.0.1", parsed.port or 5432)
    if endpoint not in ALLOWED_DESTRUCTIVE_ENDPOINTS:
        raise RuntimeError(
            "破壊的操作（DROP SCHEMA CASCADE）は許可されたテスト用接続先でのみ実行できます。"
            f" 現在の接続先: {endpoint[0]}:{endpoint[1]}."
            " テスト専用の使い捨て PostgreSQL を 127.0.0.1:55432 で起動してください。"
        )


def sqlalchemy_dsn() -> str:
    return raw_dsn().replace("postgresql://", "postgresql+asyncpg://", 1)


def make_token(org: uuid.UUID, sub: uuid.UUID, roles: list[str] | None = None) -> str:
    """Auth Service と同じ HS256 開発鍵で署名した synthetic トークン。"""
    payload = {
        "sub": str(sub),
        "type": "user",
        "org": str(org),
        "roles": roles or ["admin"],
    }
    return jwt.encode(payload, DEV_JWT_SECRET, algorithm="HS256")


async def bootstrap_schema(service: str) -> None:
    """サービス同梱の 000_base_schema.sql を適用する（冪等）。"""
    sql_path = REPO_ROOT / "services" / service / "migrations" / "000_base_schema.sql"
    sql = sql_path.read_text(encoding="utf-8")
    conn = await asyncpg.connect(raw_dsn())
    try:
        await conn.execute(sql)
    finally:
        await conn.close()


async def reset_service_tables(service: str, tables: list[str]) -> None:
    """自サービス相当のスキーマのみを初期化する（他サービスのスキーマに触れない）。"""
    assert_destructive_target_allowed()
    conn = await asyncpg.connect(raw_dsn())
    try:
        await conn.execute(f'DROP SCHEMA IF EXISTS "{service}" CASCADE')
    finally:
        await conn.close()
    await bootstrap_schema(service)
    conn = await asyncpg.connect(raw_dsn())
    try:
        for table in tables:
            await conn.execute(f'TRUNCATE TABLE "{service}".{table} CASCADE')
    finally:
        await conn.close()
