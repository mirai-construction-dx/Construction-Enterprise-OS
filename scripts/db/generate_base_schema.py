"""ORMモデルから各サービスの基盤DDL(000_base_schema.sql)を生成する。

単一の真実(SQLAlchemyメタデータ)からDDLを出すため、モデルとDDLが乖離しない。
生成物は冪等(IF NOT EXISTS / DOブロックでの型ガード)で、既存データを変更しない。

使い方:
    python3 scripts/db/generate_base_schema.py            # 生成
    python3 scripts/db/generate_base_schema.py --check     # 差分があれば失敗
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]
SERVICES = REPO / "services"

# auth は alembic 管理のため対象外
TARGETS = [
    "advanced",
    "ai",
    "analytics",
    "automation",
    "autonomous",
    "bim",
    "construction",
    # 2026-10-14: erp は models に MetaData(schema="erp") を持つのに TARGETS から漏れており、
    # migrations/000_base_schema.sql が一度も生成されていなかった（stg で
    # UndefinedTableError: erp.project_ledger が実測された）。
    "erp",
    "field-dx",
    "gis",
    "iot",
    "maintenance",
    "partner",
    "platform",
    "safety",
    "security",
    "vision",
    # 基盤DDLを先に手当てしたサービスも、以後は生成元と一致していることを保証する
    "document",
    "notification",
]
# auth と workflow は alembic 管理のため対象外

HEADER = """-- {schema} スキーマ 基盤 DDL (自動生成 / 冪等)
--
-- 生成元: services/{service}/src/models (SQLAlchemy メタデータ)
-- 再生成: python3 scripts/db/generate_base_schema.py {service}
--
-- このファイルは models の定義と一致します。既存オブジェクトがある場合は
-- 何もせず、既存データを変更しません。
"""

EMITTER = r'''
import json
import sys

from sqlalchemy import Enum as SAEnum
from sqlalchemy.types import UserDefinedType
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable

sys.path.insert(0, sys.argv[1])
from src.models.base import Base
import src.models  # noqa: F401

dialect = postgresql.dialect()
tables = list(Base.metadata.sorted_tables)
schemas = sorted({t.schema for t in tables if t.schema})
out = {
    "schemas": schemas,
    "extensions": [],
    "enums": [],
    "tables": [],
    "indexes": [],
}

seen_enums = set()
seen_ext = set()
# PostgreSQL 拡張が必要なカラム型 → 拡張名
EXTENSION_TYPES = {
    "Geometry": "postgis",
    "Geography": "postgis",
    "Vector": "vector",
    "VECTOR": "vector",
}
UNKNOWN_EXTENSION_TYPES: set[str] = set()
for table in tables:
    for column in table.columns:
        type_name = type(column.type).__name__
        extension = EXTENSION_TYPES.get(type_name)
        if extension:
            seen_ext.add(extension)
        elif isinstance(column.type, UserDefinedType):
            # 未知の拡張型は CREATE EXTENSION 漏れの原因になるため気付けるようにする
            UNKNOWN_EXTENSION_TYPES.add(type_name)
        if isinstance(column.type, SAEnum) and column.type.name:
            enum_schema = column.type.schema or table.schema
            key = (enum_schema, column.type.name)
            if key in seen_enums:
                continue
            seen_enums.add(key)
            out["enums"].append(
                {
                    "schema": enum_schema,
                    "schema_explicit": column.type.schema is not None,
                    "name": column.type.name,
                    "values": list(column.type.enums),
                }
            )

if UNKNOWN_EXTENSION_TYPES:
    out["unknown_types"] = sorted(UNKNOWN_EXTENSION_TYPES)
out["extensions"] = sorted(seen_ext)
for table in tables:
    out["tables"].append(
        str(CreateTable(table, if_not_exists=True).compile(dialect=dialect)).strip()
    )
    for index in sorted(table.indexes, key=lambda i: i.name or ""):
        out["indexes"].append(
            str(CreateIndex(index, if_not_exists=True).compile(dialect=dialect)).strip()
        )

print(json.dumps(out))
'''


def emit_metadata(service: str) -> dict:
    result = subprocess.run(
        [sys.executable, "-c", EMITTER, str(SERVICES / service)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise SystemExit(f"{service}: モデル読み込み失敗\n{result.stderr[-3000:]}")
    return json.loads(result.stdout.strip().splitlines()[-1])


def render(service: str, data: dict) -> str:
    schemas = data["schemas"]
    if len(schemas) != 1:
        raise SystemExit(f"{service}: スキーマが一意でない: {schemas}")
    schema = schemas[0]
    if data.get("unknown_types"):
        raise SystemExit(
            f"{service}: 拡張が必要な未知のカラム型 {data['unknown_types']} — "
            "EXTENSION_TYPES に追加してください"
        )

    parts = [HEADER.format(schema=schema, service=service)]
    for extension in data["extensions"]:
        parts.append(f"CREATE EXTENSION IF NOT EXISTS {extension};")
    parts.append(f"CREATE SCHEMA IF NOT EXISTS {schema};")
    # ENUM や PostGIS 型の非修飾参照がこのスキーマで解決されるようにする
    parts.append(f"SET search_path TO {schema}, public;")
    for enum in data["enums"]:
        values = ", ".join("'" + v.replace("'", "''") + "'" for v in enum["values"])
        # enum.schema が未指定のモデルは SQLAlchemy も非修飾名で扱う。
        # search_path を固定しているため、非修飾で作れば参照側と一致する。
        qualified = (
            f"{enum['schema']}.{enum['name']}"
            if enum.get("schema_explicit")
            else enum["name"]
        )
        parts.append(
            "DO $$\nBEGIN\n"
            f"    IF to_regtype('{qualified}') IS NULL THEN\n"
            f"        CREATE TYPE {qualified} AS ENUM ({values});\n"
            "    END IF;\n"
            "END\n$$;"
        )
    for ddl in data["tables"]:
        parts.append(ddl.rstrip(";") + ";")
    for ddl in data["indexes"]:
        parts.append(ddl.rstrip(";") + ";")
    return "\n\n".join(parts) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument("services", nargs="*")
    args = parser.parse_args()

    targets = args.services or TARGETS
    if args.services:
        for service in [s for s in targets if s not in TARGETS]:
            print(f"skip {service}: 生成対象外 (models 無し or alembic 管理)")
        targets = [s for s in targets if s in TARGETS]

    drifted = []
    for service in targets:
        target = SERVICES / service / "migrations" / "000_base_schema.sql"
        generated = re.sub(r"\n{3,}", "\n\n", render(service, emit_metadata(service)))
        if args.check:
            if not target.exists() or target.read_text() != generated:
                drifted.append(service)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(generated)
        print(f"wrote {target.relative_to(REPO)}")

    if args.check:
        if drifted:
            print("DDL がモデルと不一致: " + ", ".join(drifted))
            return 1
        print("全サービスの基盤DDLがモデルと一致")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
