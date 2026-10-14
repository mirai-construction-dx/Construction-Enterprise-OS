#!/usr/bin/env bash
# stg の `ceos_stg` へ各サービスのスキーマを適用する。
#
# 設計: docs/architecture/ADR-0005-staging-environment.md §2
#   - SQL マイグレーションを持つ 18 サービスは `services/<name>/migrations/*.sql` を昇順に適用する
#     （`scripts/db/bootstrap_schema.sh` と同じ順序・同じ冪等性）。
#   - auth / workflow は alembic 管理のため、コンテナ内で `alembic upgrade head` を実行する。
#   - 失敗を成功と記録しない。1 ファイルでも失敗したら非ゼロで終了し、末尾に一覧を出す。
#
# 認証:
#   SQL 側は `sudo -u postgres`（peer 認証）で流す。アプリのパスワードを使わないため
#   `~/.config/ceos/stg.env` を postgres へ渡す必要が無い。
#   alembic 側は stg の migrator ロールを使う（STG_MIGRATION_DATABASE_URL）。
#
# 使い方:
#   scripts/stg/migrate_stg.sh            # 適用
#   scripts/stg/migrate_stg.sh --dry-run  # 対象の列挙だけ
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PORT="${STG_PG_PORT:-55438}"
DB_NAME="${STG_DB_NAME:-ceos_stg}"

DRY_RUN=0
[ "${1:-}" = "--dry-run" ] && DRY_RUN=1

apply_sql() {
  sudo -n -u postgres psql -p "$PORT" -d "$DB_NAME" -v ON_ERROR_STOP=1 -q
}

applied=0
failed=()

echo "== SQL マイグレーション（$DB_NAME @ port $PORT） =="
for dir in $(find "$REPO_ROOT/services" -maxdepth 2 -type d -name migrations | sort); do
  service="$(basename "$(dirname "$dir")")"
  files="$(find "$dir" -maxdepth 1 -name '*.sql' | sort)"
  [ -z "$files" ] && continue
  for file in $files; do
    if [ "$DRY_RUN" = "1" ]; then
      echo "[dry-run] $service: $(basename "$file")"
      continue
    fi
    if apply_sql <"$file"; then
      echo "[apply] $service: $(basename "$file")"
      applied=$((applied + 1))
    else
      echo "[failed] $service: $(basename "$file")" >&2
      failed+=("$service/$(basename "$file")")
    fi
  done
done

if [ "$DRY_RUN" = "1" ]; then
  echo "[dry-run] alembic: auth, workflow (cd services/<name> && alembic upgrade head)"
  exit 0
fi

echo
echo "SQL 適用完了: ${applied} ファイル"

echo
echo "== alembic（auth / workflow） =="
# コンテナ内で実行する。migrator ロール（DDL 用ロール）を使う。
# 値は env ファイルから読み、compose の `-e` で渡す。
ENV_FILE="${HOME}/.config/ceos/stg.env"
MIGRATION_URL="$(grep -m1 '^STG_MIGRATION_DATABASE_URL=' "$ENV_FILE" 2>/dev/null | cut -d= -f2- || true)"

if [ "$DRY_RUN" != "1" ]; then
  # alembic は version_table_schema="auth"/"workflow" を使うため、スキーマが先に要る。
  apply_sql <<SQL
CREATE SCHEMA IF NOT EXISTS auth AUTHORIZATION ${STG_DB_MIGRATOR_ROLE:-ceos_stg_migrator};
CREATE SCHEMA IF NOT EXISTS workflow AUTHORIZATION ${STG_DB_MIGRATOR_ROLE:-ceos_stg_migrator};
SQL
  echo "  ok: alembic 用スキーマ（auth / workflow）を用意した"
fi

if [ -n "$MIGRATION_URL" ]; then
  for svc in auth workflow; do
    echo "-- $svc --"
    if "$REPO_ROOT/scripts/stg/compose.sh" run --rm --no-deps \
      -e "DATABASE_URL=${MIGRATION_URL}" \
      -e PYTHONPATH=/app \
      --entrypoint alembic "$svc" upgrade head; then
      echo "   ok: $svc"
    else
      echo "   NG: $svc の alembic が失敗した" >&2
      failed+=("$svc/alembic")
    fi
  done
else
  echo "NG: STG_MIGRATION_DATABASE_URL が $ENV_FILE に無い。bootstrap_stg_db.sh を再実行すること。" >&2
  failed+=("auth/alembic" "workflow/alembic")
fi

echo
if [ ${#failed[@]} -gt 0 ]; then
  echo "失敗: ${#failed[@]} 件" >&2
  for f in "${failed[@]}"; do echo "  - $f" >&2; done
  echo "未適用を成功と記録しない。原因を解消してから再実行すること。" >&2
  exit 1
fi
echo "完了: stg のスキーマ適用がすべて成功した。"
