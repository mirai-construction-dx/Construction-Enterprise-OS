#!/usr/bin/env bash
# stg 用のデータベースとロールを、ホスト PostgreSQL 18 クラスタ `18/infra_stg` に作成する。
#
# 設計: docs/architecture/ADR-0005-staging-environment.md §2
#   - stg の system of record はホスト PostgreSQL 18（port 55438, localhost 限定）。
#   - ロール払い出しの正本は Mirai-Platform-Infra の db/roles.yaml。
#     本スクリプトは stg の隔離された DB（ceos_stg）を作るだけで、
#     `mirai` DB のスキーマやロールには触れない。
#   - 冪等。既存の DB / ロール / 拡張は変更しない（パスワードのみ再設定する）。
#
# 使い方:
#   scripts/stg/bootstrap_stg_db.sh              # 作成（パスワードは既存値を再利用）
#   scripts/stg/bootstrap_stg_db.sh --rotate     # パスワードを再生成して stg.env を更新
#   scripts/stg/bootstrap_stg_db.sh --dry-run    # 実行する SQL を表示するだけ
#
# 前提:
#   - sudo -u postgres でクラスタへ接続できること（peer 認証）
#   - scripts/stg/gen_stg_env.sh を先に実行しておくこと
set -euo pipefail

PORT="${STG_PG_PORT:-55438}"
CLUSTER="${STG_PG_CLUSTER:-18/infra_stg}"
DB_NAME="${STG_DB_NAME:-ceos_stg}"
APP_ROLE="${STG_DB_APP_ROLE:-ceos_stg_app}"
MIGRATOR_ROLE="${STG_DB_MIGRATOR_ROLE:-ceos_stg_migrator}"
AUDIT_ROLE="${STG_DB_AUDIT_ROLE:-ceos_stg_audit_reader}"
SCHEMA_PREFIX=""
ENV_FILE="${HOME}/.config/ceos/stg.env"

ROTATE=0
DRY_RUN=0
for arg in "$@"; do
  case "$arg" in
    --rotate) ROTATE=1 ;;
    --dry-run) DRY_RUN=1 ;;
    -h | --help)
      sed -n '2,20p' "${BASH_SOURCE[0]}"
      exit 0
      ;;
    *)
      echo "unknown option: $arg" >&2
      exit 2
      ;;
  esac
done

psql_super() {
  # `sudo -u postgres` は kensan 所有の 0600 ファイルを読めないため、
  # SQL は必ず呼び出し側シェルの stdin から渡す（一時ファイルを postgres に読ませない）。
  local db="$1"
  shift
  sudo -n -u postgres psql -p "$PORT" -d "$db" -v ON_ERROR_STOP=1 "$@"
}

# --- 0. 前提確認（fail closed） ----------------------------------------------
echo "== 前提確認 =="
if ! sudo -n true 2>/dev/null; then
  echo "NG: sudo -n が使えない。postgres へ peer 認証で接続できない。" >&2
  exit 1
fi
if ! pg_lsclusters -h | awk '{print $1"/"$2}' | grep -qx "$CLUSTER"; then
  echo "NG: クラスタ $CLUSTER が存在しない。Mirai-Platform-Infra の stg クラスタを確認すること。" >&2
  pg_lsclusters
  exit 1
fi
status="$(pg_lsclusters -h | awk -v c="$CLUSTER" '$1"/"$2 == c {print $4}')"
if [ "$status" != "online" ]; then
  echo "NG: クラスタ $CLUSTER は online ではない（status=$status）。" >&2
  echo "    自動起動は無効（UnitFileState=disabled）である。手動で起動する:" >&2
  echo "      sudo pg_ctlcluster ${CLUSTER%/*} ${CLUSTER#*/} start" >&2
  exit 1
fi
echo "OK: クラスタ $CLUSTER は online（port $PORT）"

if [ ! -f "$ENV_FILE" ]; then
  echo "NG: $ENV_FILE が無い。先に scripts/stg/gen_stg_env.sh を実行すること。" >&2
  exit 1
fi

if [ "$ROTATE" = "1" ]; then
  APP_PW="$(openssl rand -hex 24)"
  MIGRATOR_PW="$(openssl rand -hex 24)"
  AUDIT_PW="$(openssl rand -hex 24)"
  echo "OK: --rotate のためパスワードを再生成した"
else
  # shellcheck disable=SC1090
  APP_PW="$(. "$ENV_FILE" && printf '%s' "${STG_DB_APP_PASSWORD:-}")"
  MIGRATOR_PW="$(. "$ENV_FILE" && printf '%s' "${STG_DB_MIGRATOR_PASSWORD:-}")"
  AUDIT_PW="$(. "$ENV_FILE" && printf '%s' "${STG_DB_AUDIT_PASSWORD:-}")"
  if [ -z "$APP_PW" ] || [ "$APP_PW" = "__FILLED_BY_BOOTSTRAP__" ]; then
    APP_PW="$(openssl rand -hex 24)"
  fi
  if [ -z "$MIGRATOR_PW" ] || [ "$MIGRATOR_PW" = "__FILLED_BY_BOOTSTRAP__" ]; then
    MIGRATOR_PW="$(openssl rand -hex 24)"
  fi
  if [ -z "$AUDIT_PW" ] || [ "$AUDIT_PW" = "__FILLED_BY_BOOTSTRAP__" ]; then
    AUDIT_PW="$(openssl rand -hex 24)"
  fi
fi

SQL_FILE="$(mktemp)"
trap 'rm -f "$SQL_FILE"' EXIT

cat <<SQL >"$SQL_FILE"
-- 冪等: 既存は変更しない。パスワードのみ再設定する。
DO \$\$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '${MIGRATOR_ROLE}') THEN
    CREATE ROLE ${MIGRATOR_ROLE} LOGIN;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '${APP_ROLE}') THEN
    CREATE ROLE ${APP_ROLE} LOGIN;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '${AUDIT_ROLE}') THEN
    CREATE ROLE ${AUDIT_ROLE} LOGIN;
  END IF;
END
\$\$;
ALTER ROLE ${MIGRATOR_ROLE} PASSWORD '${MIGRATOR_PW}';
ALTER ROLE ${APP_ROLE} PASSWORD '${APP_PW}';
ALTER ROLE ${AUDIT_ROLE} PASSWORD '${AUDIT_PW}';
-- 既定では何も作れない。スキーマ作成は migrator だけに許す。
ALTER ROLE ${APP_ROLE} NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;
ALTER ROLE ${MIGRATOR_ROLE} NOSUPERUSER NOCREATEDB NOCREATEROLE;
ALTER ROLE ${AUDIT_ROLE} NOSUPERUSER NOCREATEDB NOCREATEROLE;
SQL

if [ "$DRY_RUN" = "1" ]; then
  echo "== [dry-run] ロール SQL =="
  cat "$SQL_FILE"
  echo "== [dry-run] DB 作成: CREATE DATABASE ${DB_NAME} OWNER ${MIGRATOR_ROLE} =="
  exit 0
fi

echo "== ロール作成 / パスワード設定 =="
psql_super postgres -q <"$SQL_FILE"
rm -f "$SQL_FILE"

echo "== データベース作成 =="
# CREATE DATABASE はトランザクション内で実行できないため、存在確認を分けて行う。
if psql_super postgres -tAc "SELECT 1 FROM pg_database WHERE datname='${DB_NAME}'" | grep -q 1; then
  echo "既存: ${DB_NAME}（作成をスキップ）"
else
  psql_super postgres -q -c "CREATE DATABASE ${DB_NAME} OWNER ${MIGRATOR_ROLE} ENCODING 'UTF8' LC_COLLATE 'C' LC_CTYPE 'C' TEMPLATE template0"
  echo "作成: ${DB_NAME}"
fi

echo "== 拡張の導入 =="
# gis / bim は postgis、ai は vector を必要とする（services/*/migrations 内で CREATE EXTENSION）。
for ext in postgis vector pg_trgm pg_stat_statements; do
  if psql_super "$DB_NAME" -tAc "SELECT 1 FROM pg_available_extensions WHERE name='${ext}'" | grep -q 1; then
    psql_super "$DB_NAME" -q -c "CREATE EXTENSION IF NOT EXISTS ${ext}"
    echo "  OK  ${ext}"
  else
    echo "  NG  ${ext} はクラスタで利用できない（$CLUSTER に未導入）" >&2
  fi
done

echo "== スキーマ作成権限（migrator へ public スキーマの作成を許可） =="
psql_super "$DB_NAME" -q -c "GRANT CREATE, USAGE ON SCHEMA public TO ${MIGRATOR_ROLE}"
psql_super "$DB_NAME" -q -c "GRANT USAGE ON SCHEMA public TO ${APP_ROLE}, ${AUDIT_ROLE}"
# app へは「今ある表」ではなく「将来作られる表」への権限が必要。既定権限で担保する。
psql_super "$DB_NAME" -q -c "ALTER DEFAULT PRIVILEGES FOR ROLE ${MIGRATOR_ROLE} IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO ${APP_ROLE}"
psql_super "$DB_NAME" -q -c "ALTER DEFAULT PRIVILEGES FOR ROLE ${MIGRATOR_ROLE} IN SCHEMA public GRANT SELECT ON TABLES TO ${AUDIT_ROLE}"
psql_super "$DB_NAME" -q -c "ALTER DEFAULT PRIVILEGES FOR ROLE ${MIGRATOR_ROLE} IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO ${APP_ROLE}"
psql_super "$DB_NAME" -q -c "GRANT CONNECT ON DATABASE ${DB_NAME} TO ${APP_ROLE}, ${MIGRATOR_ROLE}, ${AUDIT_ROLE}"

echo "== stg.env の更新（mode 0600） =="
umask 077
tmp="$(mktemp)"
sed \
  -e "s|^STG_DB_APP_PASSWORD=.*|STG_DB_APP_PASSWORD=${APP_PW}|" \
  -e "s|^STG_DB_MIGRATOR_PASSWORD=.*|STG_DB_MIGRATOR_PASSWORD=${MIGRATOR_PW}|" \
  -e "s|^STG_DB_AUDIT_PASSWORD=.*|STG_DB_AUDIT_PASSWORD=${AUDIT_PW}|" \
  -e "s|^STG_MIGRATION_DATABASE_URL=.*|STG_MIGRATION_DATABASE_URL=postgresql+asyncpg://${MIGRATOR_ROLE}:${MIGRATOR_PW}@10.201.0.1:${PORT}/${DB_NAME}|" \
  -e "s|^STG_DATABASE_URL=.*|STG_DATABASE_URL=postgresql+asyncpg://${APP_ROLE}:${APP_PW}@10.201.0.1:${PORT}/${DB_NAME}|" \
  "$ENV_FILE" >"$tmp"
# 既存ファイルにキーが無い場合（スキーマ追加時）は末尾へ足す。冪等。
grep -q '^STG_MIGRATION_DATABASE_URL=' "$tmp" ||
  echo "STG_MIGRATION_DATABASE_URL=postgresql+asyncpg://${MIGRATOR_ROLE}:${MIGRATOR_PW}@10.201.0.1:${PORT}/${DB_NAME}" >>"$tmp"
grep -q '^STG_DATABASE_URL=' "$tmp" ||
  echo "STG_DATABASE_URL=postgresql+asyncpg://${APP_ROLE}:${APP_PW}@10.201.0.1:${PORT}/${DB_NAME}" >>"$tmp"
chmod 600 "$tmp"
mv "$tmp" "$ENV_FILE"
echo "更新した: $ENV_FILE (mode $(stat -c '%a' "$ENV_FILE"))"

echo "== 実測（read-back） =="
psql_super "$DB_NAME" -c "SELECT current_database() AS db, current_user AS role"
psql_super "$DB_NAME" -tAc "SELECT extname FROM pg_extension ORDER BY 1" | tr '\n' ' '
echo
echo "完了。次: scripts/stg/up.sh"
