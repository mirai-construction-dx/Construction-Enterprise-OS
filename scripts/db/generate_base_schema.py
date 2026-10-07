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
# 明示的な除外。ここに挙げたサービスは DDL 生成対象に含めない。
# ORM モデルを持つサービスを除外する場合は、必ず理由を添えてここへ登録する
# (登録漏れは「黙って skip して成功」ではなくエラーにする — 下記 coverage_gaps 参照)。
EXCLUDED = {
    "auth": "alembic 管理 (services/auth/alembic)",
    "workflow": "alembic 管理 (services/workflow/alembic)",
    "gateway": "ORM モデルなし (API プロキシのみ)",
    "mcp": "ORM モデルなし (DB を保持しない)",
    "logs": "実装なし (ログ保管ディレクトリのみ)",
}

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


def has_orm_models(service: str) -> bool:
    """サービスが SQLAlchemy のテーブル定義を持つか。"""
    models_dir = SERVICES / service / "src" / "models"
    if not models_dir.is_dir():
        return False
    for path in models_dir.rglob("*.py"):
        if "__tablename__" in path.read_text(encoding="utf-8", errors="ignore"):
            return True
    return False


def coverage_gaps(services: list[str]) -> list[str]:
    """ORM モデルを持つのに DDL 生成対象でも明示的除外でもないサービス。

    これらを黙って skip すると「DDL が無いのに同期チェックが成功する」偽グリーンになる。
    """
    return [
        s
        for s in services
        if s not in TARGETS and s not in EXCLUDED and has_orm_models(s)
    ]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument("services", nargs="*")
    args = parser.parse_args()

    candidates = args.services or sorted(
        p.name for p in SERVICES.iterdir() if p.is_dir()
    )

    missing = [s for s in candidates if not (SERVICES / s).is_dir()]
    if missing:
        print(
            "サービスが存在しません: " + ", ".join(sorted(missing)),
            file=sys.stderr,
        )
        return 2

    # ORM モデルを持つサービスを対象漏れのまま成功させない (偽グリーン防止)
    gaps = coverage_gaps(candidates)
    if gaps:
        print(
            "DDL 生成対象に含まれていないサービスがあります: "
            + ", ".join(sorted(gaps))
            + " — TARGETS に追加するか、EXCLUDED に理由付きで登録してください",
            file=sys.stderr,
        )
        return 2

    targets = args.services or TARGETS
    if args.services:
        for service in candidates:
            if service in EXCLUDED:
                print(f"skip {service}: 対象外 ({EXCLUDED[service]})")
            elif service not in TARGETS:
                print(f"skip {service}: 生成対象外 (ORM モデル無し)")
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
        if not targets:
            # 対象外のサービスしか指定されなかった場合に「一致」と表示しない。
            # 検査していないのに成功メッセージを出すと偽グリーンになる。
            print(
                "検査対象なし: "
                + ", ".join(sorted(candidates))
                + " はすべて生成対象外 (TARGETS 外)"
            )
            return 0
        print("全サービスの基盤DDLがモデルと一致")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
