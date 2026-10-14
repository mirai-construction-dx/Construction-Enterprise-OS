#!/usr/bin/env python3
"""Makefile の DB 操作ターゲットが、**CEOS 以外のデータベース**を掴んでいないか検査する。

なぜ必要か（2026-10-14 の実測）:
    `Makefile` の `db-migrate` / `db-seed` / `schema-bootstrap` は
    `"${DATABASE_URL:?…}"` をそのまま使う。つまり**環境に置かれている値**を無条件に信頼する。

    ところが DeepSeek Harness（本作業環境）は、シェルへ自分の DB を注入する:

        $ echo "$DATABASE_URL"
        postgresql://deepseek_harness:...@127.0.0.1:5435/deepseek_harness

    この状態でうっかり `make db-seed` を実行すると、
    **ハーネス自身のデータベースへ CEOS のシードが入る**。
    `make repo-invariants` も同じ理由で失敗する（`schema-check` がモデルを import し、
    `postgresql://`（非 async ドライバ）で `create_async_engine` が落ちる）。
    実測（2026-10-14）:

        $ make repo-invariants
        sqlalchemy.exc.InvalidRequestError: The asyncio extension requires an async driver …
        $ env -u DATABASE_URL make repo-invariants
        ✅ リポジトリ不変条件 OK          # 6 検査すべて通過

    「気をつける」ではなく、**別システムの DB を掴んだら停止する**。

判定（fail closed）:
    1. スキームが `postgresql` / `postgres` 系でなければ拒否。
    2. データベース名が `FOREIGN_DATABASES`（他システムの既知 DB）なら拒否。
    3. データベース名が `CEOS_DATABASES`（CEOS が持つ DB の接頭辞）に一致しなければ拒否。
    4. ただし `CEOS_DB_ALLOW_ANY=1` が明示されていれば 3 を免除する（理由の記録用）。

    2 と 3 は「知らないものを拒否する」側に倒してある。CEOS 以外の DB を
    意図して触る場合は、環境変数で明示的に宣言すること。

使い方:
    python3 scripts/db/check_target_db.py "$DATABASE_URL"
    # Makefile からは各ターゲットの先頭で呼ばれる
"""

from __future__ import annotations

import os
import sys
from urllib.parse import urlsplit

# CEOS が持つデータベースの接頭辞（本番 / MVP / 開発 / stg / テスト）。
# `construction_os` は本番・開発の既定名、`ceos_*` は stg 以降の分離名。
CEOS_DATABASES: tuple[str, ...] = (
    "construction_os",  # 開発・本番
    "construction_os_test",  # 統合テスト
    "ceos_",  # stg（ceos_stg）以降の分離名
)

# 他システムのデータベース。ここに載る名前は**接続した時点で事故**である。
FOREIGN_DATABASES: tuple[str, ...] = (
    "deepseek_harness",  # DeepSeek Harness 自身の DB（本作業環境が注入する）
    "postgres",
    "template0",
    "template1",
    "mirai",  # Mirai-Platform-Infra の DB
    "mirai_info",  # Mirai-Info の DB
)

ASYNC_HINT = "postgresql+asyncpg"


def database_name(url: str) -> str:
    """URL からデータベース名を取り出す。"""
    try:
        parts = urlsplit(url)
    except ValueError:
        return ""
    return (parts.path or "").lstrip("/").split("?", 1)[0]


def evaluate(url: str, allow_any: bool = False) -> tuple[bool, str]:
    """(許可するか, 説明) を返す。"""
    if not url.strip():
        return False, "DATABASE_URL が空である"
    try:
        scheme = urlsplit(url).scheme
    except ValueError:
        return False, "DATABASE_URL を URL として解釈できない"
    if not scheme.startswith("postgres"):
        return False, f"PostgreSQL の URL ではない（scheme={scheme!r}）"

    name = database_name(url)
    if not name:
        return False, "データベース名を取り出せない"

    if name in FOREIGN_DATABASES:
        return False, (
            f"データベース名 {name!r} は他システムのものである"
            "（CEOS の表・シードを入れてはならない）"
        )

    if any(name == prefix or name.startswith(prefix) for prefix in CEOS_DATABASES):
        return True, f"{name!r} は CEOS のデータベースである"

    if allow_any:
        return True, f"{name!r} は CEOS の命名ではないが、CEOS_DB_ALLOW_ANY=1 が明示されている"

    return False, (
        f"データベース名 {name!r} は CEOS の命名"
        f"（{' / '.join(CEOS_DATABASES)}）に一致しない。"
        " 意図して別の DB を使うなら CEOS_DB_ALLOW_ANY=1 を明示すること"
    )


def main(argv: list[str]) -> int:
    url = argv[1] if len(argv) > 1 else os.environ.get("DATABASE_URL", "")
    allow_any = os.environ.get("CEOS_DB_ALLOW_ANY", "") == "1"
    ok, reason = evaluate(url, allow_any)

    if not ok:
        print(f"NG: 対象 DB を拒否した: {reason}", file=sys.stderr)
        print(
            "    CEOS の DB を指定し直すこと（例: postgresql+asyncpg://…@127.0.0.1:5432/construction_os）。",
            file=sys.stderr,
        )
        print(
            "    本作業環境は DeepSeek Harness が DATABASE_URL を注入するため、"
            "`env -u DATABASE_URL make …` で外せる。",
            file=sys.stderr,
        )
        return 2

    print(f"OK: {reason}（db={database_name(url)} / scheme={urlsplit(url).scheme}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
