"""erp の基盤DDLとモデルの同期を守る回帰テスト。

背景（本テストが防ぐ障害）:
    erp は `src/models/models.py` にテーブルを定義していたが `src/models/__init__.py`
    が空だったため、`import src.models` ではテーブルが Base.metadata に登録されず、
    DDL 生成器 (`scripts/db/generate_base_schema.py`) が erp のスキーマを検出できなかった。
    さらに erp が同スクリプトの TARGETS に含まれていなかったため、
    CI の「Base schema DDL is in sync with models」ステップは erp を
    「skip して成功」させ、空DBでは erp のテーブルが1つも作られない状態が検知されなかった。

このテストは DB を必要とせず、次の3点を固定する:
    1. `import src.models` だけで全テーブルが Base.metadata に入ること
    2. `migrations/000_base_schema.sql` がモデルの全テーブル・全列を網羅すること
    3. erp が DDL 生成対象（TARGETS）から外れていないこと
"""

from __future__ import annotations

import pathlib
import re

import pytest

from src.models.base import Base

REPO = pathlib.Path(__file__).resolve().parents[3]
DDL_PATH = pathlib.Path(__file__).resolve().parents[1] / "migrations" / "000_base_schema.sql"
GENERATOR = REPO / "scripts" / "db" / "generate_base_schema.py"


def _table_blocks(ddl: str) -> dict[str, str]:
    """DDL をテーブル単位に分解する。キーは "schema.table"、値は列定義本体。"""
    blocks: dict[str, str] = {}
    for chunk in ddl.split("CREATE TABLE IF NOT EXISTS ")[1:]:
        header, _, rest = chunk.partition("(")
        body = rest.split("\n);", 1)[0]
        blocks[header.strip()] = body
    return blocks


def test_all_erp_tables_are_registered_by_package_import():
    """`import src.models` でモデルが登録されること（空の __init__.py の再発防止）。"""
    tables = list(Base.metadata.sorted_tables)
    assert tables, (
        "src.models を import してもテーブルが登録されていない。"
        "services/erp/src/models/__init__.py が models.py を再輸出しているか確認すること"
    )
    assert {t.schema for t in tables} == {"erp"}
    names = {t.name for t in tables}
    assert names == {
        "project_ledger",
        "budgets",
        "cost_items",
        "invoices",
        "labor_costs",
    }


def test_base_schema_ddl_exists():
    assert DDL_PATH.exists(), (
        f"{DDL_PATH} が存在しない。"
        "`python3 scripts/db/generate_base_schema.py erp` で生成すること"
    )


def test_base_schema_ddl_covers_every_table_and_column():
    ddl = DDL_PATH.read_text(encoding="utf-8")
    blocks = _table_blocks(ddl)
    missing: list[str] = []
    for table in Base.metadata.sorted_tables:
        key = f"{table.schema}.{table.name}"
        body = blocks.get(key)
        if body is None:
            missing.append(f"table {key}")
            continue
        for column in table.columns:
            if not re.search(rf"(?m)^\s*{re.escape(column.name)}\s", body):
                missing.append(f"column {key}.{column.name}")
    assert not missing, "DDL がモデルを網羅していない: " + ", ".join(missing)


def test_base_schema_ddl_is_idempotent():
    ddl = DDL_PATH.read_text(encoding="utf-8")
    # 既存データを壊さない（再実行しても安全）こと
    assert "CREATE SCHEMA IF NOT EXISTS erp;" in ddl
    assert "CREATE TABLE IF NOT EXISTS erp." in ddl
    lowered = ddl.lower()
    assert "drop table" not in lowered
    assert "drop schema" not in lowered
    assert "alter table" not in lowered


def test_erp_is_registered_as_ddl_generation_target():
    """TARGETS から erp が外れると CI が再び erp を黙って skip するため固定する。"""
    source = GENERATOR.read_text(encoding="utf-8")
    match = re.search(r"^TARGETS = \[(.*?)^\]", source, re.DOTALL | re.MULTILINE)
    assert match, "generate_base_schema.py の TARGETS 定義を解析できなかった"
    targets = re.findall(r'"([^"]+)"', match.group(1))
    assert "erp" in targets, "erp が DDL 生成対象から外れている（CI が黙って skip する）"

    excluded = re.search(r"^EXCLUDED = \{(.*?)^\}", source, re.DOTALL | re.MULTILINE)
    if excluded:
        assert '"erp"' not in excluded.group(1), (
            "erp は ORM モデルを持つため EXCLUDED に入れてはならない"
        )


@pytest.mark.parametrize("service", ["auth", "workflow"])
def test_alembic_managed_services_remain_excluded(service: str):
    """誤って alembic 管理サービスを TARGETS に含めないこと（fail-closed の副作用防止）。"""
    source = GENERATOR.read_text(encoding="utf-8")
    match = re.search(r"^TARGETS = \[(.*?)^\]", source, re.DOTALL | re.MULTILINE)
    assert match
    targets = re.findall(r'"([^"]+)"', match.group(1))
    assert service not in targets
