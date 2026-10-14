#!/usr/bin/env bash
# 開発用シード（`scripts/db/seed/*.sql`）を、**マイグレーション適用後に**投入する。
#
# なぜ docker-entrypoint-initdb.d ではないのか（2026-10-14 実測）:
#   シードは `auth.organizations` / `auth.permissions` へ INSERT するが、これらの表は
#   サービス側のマイグレーション（alembic / 000_base_schema.sql）が作る。
#   docker-entrypoint は `.sql` を `psql -v ON_ERROR_STOP=1` で流すため、表がまだ無い
#   初期化時点では
#     ERROR: リレーション"auth.organizations"は存在しません   （psql exit=3）
#   となり **コンテナが起動しなかった**。したがってシードは initdb の外へ出し、
#   マイグレーション後に明示的に流す。
#
# 使い方:
#   scripts/db/seed_dev.sh "postgresql://user:pass@host:5432/db"
#   DATABASE_URL=... scripts/db/seed_dev.sh
#   make db-seed
#
# 冪等: `scripts/db/seed/*.sql` は WHERE NOT EXISTS で既存行を飛ばす。
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATABASE_URL="${1:-${DATABASE_URL:-}}"
SEED_DIR="$REPO_ROOT/scripts/db/seed"

if [ -z "$DATABASE_URL" ]; then
  echo "usage: $0 <DATABASE_URL>   （または環境変数 DATABASE_URL）" >&2
  exit 2
fi
if ! command -v psql >/dev/null 2>&1; then
  echo "NG: psql が見つからない。" >&2
  exit 1
fi
if [ ! -d "$SEED_DIR" ]; then
  echo "NG: $SEED_DIR が無い。" >&2
  exit 1
fi

# 前提確認: マイグレーションが適用済みか（未適用なら分かりやすく止める）。
if ! psql "$DATABASE_URL" -tAc "SELECT to_regclass('auth.organizations')" 2>/dev/null | grep -q .; then
  echo "NG: auth.organizations が存在しない。先にマイグレーションを適用すること。" >&2
  echo "    例: scripts/db/bootstrap_schema.sh \"\$DATABASE_URL\"" >&2
  echo "        cd services/auth && alembic upgrade head" >&2
  exit 1
fi

echo "== 開発用シードの投入 =="
for file in "$SEED_DIR"/*.sql; do
  [ -e "$file" ] || continue
  echo "-- $(basename "$file")"
  psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -q -f "$file"
done

echo
echo "実測:"
psql "$DATABASE_URL" -tAc \
  "SELECT 'organizations=' || (SELECT count(*) FROM auth.organizations) ||
          ' permissions='   || (SELECT count(*) FROM auth.permissions)"
echo "完了。"
