#!/usr/bin/env bash
# stg の `ceos_stg` が復旧できることを、**破壊的操作なしで**実際に確かめる訓練。
#
# 何をするか:
#   1. `ceos_stg` を論理バックアップ（pg_dump -Fc）する
#   2. 別名の訓練用 DB へ `pg_restore` する
#   3. 本番（= stg）と訓練用 DB のスキーマ数・テーブル数・主要表の行数を突き合わせる
#   4. 訓練用 DB とダンプを削除する
#
# 何をしないか（重要）:
#   `pgbackrest restore` は**実行しない**。あれは stanza の `pg1-path` を書き換える
#   破壊的操作であり、`18/infra_stg` クラスタは他システム（`mirai` DB）と共有している。
#   誤ると稼働中のデータを失う。PITR の復旧訓練はホスト管理者の立会いの下で行う
#   Human Gate の操作である（`docs/operations/staging.md` §8）。
#   本スクリプトが確かめるのは「論理ダンプから完全に戻せること」までである。
#
# 使い方:
#   scripts/stg/restore_drill.sh
#
# 出力はそのまま証跡として使える。失敗は成功として扱わない。
set -euo pipefail

PORT="${STG_PG_PORT:-55438}"
SRC_DB="${STG_DB_NAME:-ceos_stg}"
DRILL_DB="${SRC_DB}_drill_$(date +%Y%m%d%H%M%S)"
# PATH 上の pg_dump は 17 系で、サーバーは 18.4 のためバージョン不一致で中断する。
# クラスタと同じメジャーのバイナリを明示的に使う。
PG_BIN="${STG_PG_BIN:-/usr/lib/postgresql/${PORT:+}/bin}"
PG_BIN="${STG_PG_BIN:-$(dirname "$(ls -d /usr/lib/postgresql/18/bin/pg_dump 2>/dev/null || echo /usr/bin/pg_dump)")}"
PG_DUMP="${PG_BIN}/pg_dump"
PG_RESTORE="${PG_BIN}/pg_restore"
DUMP_DIR="/var/lib/postgresql/ceos-stg-drills"
DUMP_FILE="${DUMP_DIR}/${DRILL_DB}.dump"

cleanup() {
  sudo -n -u postgres psql -p "$PORT" -d postgres -q -c "DROP DATABASE IF EXISTS ${DRILL_DB}" 2>/dev/null || true
  sudo -n -u postgres rm -f "$DUMP_FILE" 2>/dev/null || true
}
trap cleanup EXIT

echo "== stg 復旧訓練（論理バックアップ / $(date -Iseconds)） =="
echo "対象: ${SRC_DB} @ port ${PORT}"
echo "使用バイナリ: ${PG_DUMP}"
echo

echo "-- 1. 論理バックアップ --"
sudo -n -u postgres mkdir -p "$DUMP_DIR"
sudo -n -u postgres "$PG_DUMP" -p "$PORT" -d "$SRC_DB" -Fc -f "$DUMP_FILE"
size="$(sudo -n -u postgres stat -c '%s' "$DUMP_FILE")"
echo "  OK: $(basename "$DUMP_FILE") (${size} bytes)"

echo
echo "-- 2. 訓練用 DB へ復元 --"
sudo -n -u postgres psql -p "$PORT" -d postgres -q -c "CREATE DATABASE ${DRILL_DB}"
sudo -n -u postgres "$PG_RESTORE" -p "$PORT" -d "$DRILL_DB" --no-owner --no-privileges "$DUMP_FILE"
echo "  OK: ${DRILL_DB} へ復元"

echo
echo "-- 3. 突き合わせ（stg と訓練用 DB） --"
counts() {
  sudo -n -u postgres psql -p "$PORT" -d "$1" -tAc "
    SELECT (SELECT count(*) FROM information_schema.schemata
             WHERE schema_name NOT IN ('pg_catalog','information_schema','pg_toast')
               AND schema_name NOT LIKE 'pg\_%') || '|' ||
           (SELECT count(*) FROM information_schema.tables
             WHERE table_schema NOT IN ('pg_catalog','information_schema'))"
}
src_counts="$(counts "$SRC_DB")"
drill_counts="$(counts "$DRILL_DB")"
src_schemas="${src_counts%%|*}"
src_tables="${src_counts##*|}"
drill_schemas="${drill_counts%%|*}"
drill_tables="${drill_counts##*|}"

fail=0
cmp_field() {
  local label="$1" expected="$2" actual="$3"
  if [ "$expected" = "$actual" ]; then
    echo "  PASS: ${label} (${expected})"
  else
    echo "  FAIL: ${label} — stg=${expected} drill=${actual}" >&2
    fail=$((fail + 1))
  fi
}
cmp_field "スキーマ数" "$src_schemas" "$drill_schemas"
cmp_field "テーブル数" "$src_tables" "$drill_tables"

echo
echo "-- 4. 主要表の行数照合 --"
# 業務の要になる表を抜き出して、行数が一致することを確かめる（スキーマだけ戻って
# データが空、という「気付かず緑」を防ぐ）。
TABLES="auth.users auth.roles workflow.workflow_definitions document.documents notification.notification_templates"
for t in $TABLES; do
  schema="${t%%.*}"
  table="${t##*.}"
  exists="$(sudo -n -u postgres psql -p "$PORT" -d "$SRC_DB" -tAc \
    "SELECT count(*) FROM information_schema.tables WHERE table_schema='${schema}' AND table_name='${table}'")"
  if [ "$exists" != "1" ]; then
    echo "  SKIP: ${t} は存在しない（この版のスキーマに無い）"
    continue
  fi
  a="$(sudo -n -u postgres psql -p "$PORT" -d "$SRC_DB" -tAc "SELECT count(*) FROM ${schema}.${table}")"
  b="$(sudo -n -u postgres psql -p "$PORT" -d "$DRILL_DB" -tAc "SELECT count(*) FROM ${schema}.${table}")"
  cmp_field "${t} の行数" "$a" "$b"
done

echo
echo "-- 5. 後始末 --"
cleanup
trap - EXIT
echo "  OK: ${DRILL_DB} とダンプを削除"

echo
if [ "$fail" -gt 0 ]; then
  echo "NG: 復旧訓練で ${fail} 件が不一致。復旧できると記録しない。" >&2
  exit 1
fi
echo "OK: 論理バックアップからの復旧を実測で確認した（破壊的操作は行っていない）。"
echo "注意: PITR（pgbackrest restore）の訓練は別途、ホスト管理者の立会いで実施すること。"
