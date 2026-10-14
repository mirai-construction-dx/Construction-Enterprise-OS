#!/usr/bin/env python3
"""各サービスが「モデルを持つなら DDL の出所も持つ」ことを検査する。

なぜ必要か（2026-10-14 の実測）:
    `services/erp` は `src/models` に `MetaData(schema="erp")` のモデルを持つのに、
      - `src/models/__init__.py` が空で `Base.metadata` にモデルが登録されず
      - `scripts/db/generate_base_schema.py` の `TARGETS` からも漏れていた
    ため、基盤 DDL が**一度も生成されていなかった**。
    結果として staging で `erp` スキーマ自体が存在せず、
    `GET /api/v1/erp/ledger/summary` が
    `UndefinedTableError: リレーション"erp.project_ledger"は存在しません` で 500 になっていた。

    `generate_base_schema.py --check` は `TARGETS` に載っているサービスしか見ないため、
    **`TARGETS` からの漏れそのものは検出できない**。本検査がその穴を塞ぐ。

検査する内容:
    C-1 モデルが schema 付きの `MetaData` を宣言しているのに、
        `migrations/*.sql` も `alembic/` も無いサービスが無いこと。
    C-2 SQL マイグレーションを持つサービスが `generate_base_schema.py` の `TARGETS` に
        載っていること（載っていないと DDL がモデルと乖離しても気付けない）。

    `auth` / `workflow` は alembic 管理のため C-2 の対象外（`TARGETS` のコメントどおり）。
    gateway / logs / mcp のように DB モデルを持たないサービスは対象外。

`SKIP` を作らない。判定できないものは FAIL として報告する（`AGENTS.md` §4.7）。

使い方:
    python3 scripts/db/check_service_ddl_coverage.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SERVICES = REPO / "services"

SCHEMA_RE = re.compile(r'MetaData\(\s*schema\s*=\s*"([^"]+)"')

# alembic 管理のサービス（`generate_base_schema.py` の TARGETS から除外されている）
ALEMBIC_MANAGED = {"auth", "workflow"}


def load_targets() -> set[str]:
    """生成器の TARGETS を正本として読み込む（第二の一覧を作らない）。"""
    sys.path.insert(0, str(REPO / "scripts" / "db"))
    import generate_base_schema

    return set(generate_base_schema.TARGETS)


def main() -> int:
    targets = load_targets()
    failures: list[str] = []
    checked = 0
    skipped_no_models: list[str] = []

    for service_dir in sorted(p for p in SERVICES.iterdir() if p.is_dir()):
        name = service_dir.name
        models_dir = service_dir / "src" / "models"
        schemas = set()
        if models_dir.is_dir():
            for path in models_dir.rglob("*.py"):
                schemas |= set(SCHEMA_RE.findall(path.read_text(encoding="utf-8", errors="replace")))

        if not schemas:
            skipped_no_models.append(name)
            continue

        checked += 1
        has_sql = bool(list((service_dir / "migrations").glob("*.sql"))) if (service_dir / "migrations").is_dir() else False
        has_alembic = (service_dir / "alembic").is_dir()

        # C-1: モデルがあるのに DDL の出所が無い
        if not has_sql and not has_alembic:
            failures.append(
                f"C-1 {name}: モデルが schema={sorted(schemas)} を宣言しているが、"
                "migrations/*.sql も alembic/ も無い（DDL が存在しない）"
            )
            continue

        # C-2: SQL マイグレーションを持つのに生成器の TARGETS に無い
        if has_sql and not has_alembic and name not in targets:
            failures.append(
                f"C-2 {name}: SQL マイグレーションを持つが generate_base_schema.py の "
                "TARGETS に無い（モデルと DDL の乖離を検出できない）"
            )
        if has_alembic and name not in ALEMBIC_MANAGED:
            failures.append(
                f"C-2 {name}: alembic/ を持つが ALEMBIC_MANAGED に無い"
                "（どちらの管理下か不明確になる）"
            )

    print(f"モデルと DDL を持つサービスを {checked} 件検査した。")
    if skipped_no_models:
        print(f"DB モデルを持たないため対象外: {' '.join(skipped_no_models)}")

    if failures:
        print()
        for item in failures:
            print(f"FAIL: {item}", file=sys.stderr)
        print()
        print(f"NG: {len(failures)} 件。モデルがあるのに DDL の出所が無いサービスを残さない。", file=sys.stderr)
        return 1

    print("OK: すべてのサービスがモデルに対応する DDL の出所を持っている。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
