#!/usr/bin/env bash
# 各サービスの SQL マイグレーションを空のデータベースへ順番に適用する。
#
# 使い方:
#   scripts/db/bootstrap_schema.sh "postgresql://user:pass@host:5432/db"
#
# 前提:
#   - PostGIS を使うサービス(gis / bim)には PostGIS 拡張が必要
#   - pgvector を使うサービス(ai)には vector 拡張が必要
#     (各 DDL 内で CREATE EXTENSION IF NOT EXISTS を実行する)
#   - auth / workflow は alembic 管理のため対象外。別途
#     `cd services/<name> && alembic upgrade head` を実行する
#   - すべてのファイルは冪等(additive)なので再実行しても安全
#
# 失敗時の扱い:
#   1ファイルの失敗で全体を中断すると、拡張が1つ足りないだけで他の
#   サービスまで未適用のまま残る。適用可能なものは最後まで適用し、
#   失敗があれば末尾で一覧表示して非ゼロで終了する(成功扱いにしない)。
set -uo pipefail

if [ $# -ne 1 ]; then
  echo "usage: $0 <DATABASE_URL>" >&2
  exit 2
fi

DATABASE_URL="$1"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

# 事前検査: ORM モデルを持つのに適用対象(migrations/*.sql)も alembic も無いサービスを検出する。
# これらは下の探索で「黙って skip」され、空DBにテーブルが作られないまま
# 「適用完了」と表示されてしまう (erp で実際に発生した障害)。
uncovered=()
for service_dir in "$REPO_ROOT"/services/*/; do
  [ -d "${service_dir}src/models" ] || continue
  grep -rq "__tablename__" "${service_dir}src/models" 2>/dev/null || continue
  if [ ! -d "${service_dir}migrations" ] && [ ! -d "${service_dir}alembic" ]; then
    uncovered+=("$(basename "$service_dir")")
  fi
done
if [ ${#uncovered[@]} -gt 0 ]; then
  echo "スキーマ適用対象が存在しないサービスがあります: ${uncovered[*]}" >&2
  echo "  migrations/000_base_schema.sql を生成するか、alembic 管理であることを明記してください。" >&2
  echo "  (生成: python3 scripts/db/generate_base_schema.py <service>)" >&2
  exit 3
fi

applied=0
failed_files=()
# サービス名の昇順、同一サービス内はファイル名の昇順(= 000 → 001 → 002)
for dir in $(find "$REPO_ROOT/services" -maxdepth 2 -type d -name migrations | sort); do
  service="$(basename "$(dirname "$dir")")"
  files=$(find "$dir" -maxdepth 1 -name '*.sql' | sort)
  if [ -z "$files" ]; then
    continue
  fi
  for file in $files; do
    if [ "${DRY_RUN:-0}" = "1" ]; then
      echo "[dry-run] $service: $(basename "$file")"
      continue
    fi
    echo "[apply] $service: $(basename "$file")"
    if psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -q -f "$file"; then
      applied=$((applied + 1))
    else
      echo "[failed] $service: $(basename "$file")" >&2
      failed_files+=("$service/$(basename "$file")")
    fi
  done
done

if [ "${DRY_RUN:-0}" = "1" ]; then
  exit 0
fi

echo "適用完了: ${applied} ファイル"

if [ ${#failed_files[@]} -gt 0 ]; then
  echo "" >&2
  echo "失敗: ${#failed_files[@]} ファイル" >&2
  for f in "${failed_files[@]}"; do
    echo "  - $f" >&2
  done
  echo "" >&2
  echo "ヒント: 拡張が必要なサービスは CREATE EXTENSION できる DB へ個別に適用してください。" >&2
  echo "  gis / bim : postgis" >&2
  echo "  ai        : vector (pgvector)" >&2
  exit 1
fi

echo "注意: auth / workflow は alembic 管理です (cd services/<name> && alembic upgrade head)"
