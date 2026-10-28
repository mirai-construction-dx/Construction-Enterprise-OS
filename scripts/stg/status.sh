#!/usr/bin/env bash
# stg の状態を 1 コマンドで要約する。運用時の目視と、cron / systemd timer からの
# 定期監視の両方に使える（異常があれば非ゼロで終了する）。
#
# 出力するもの:
#   - 前提（ホスト PostgreSQL 18 クラスタ / db-bridge）の状態
#   - コンテナの health 集計と異常コンテナの列挙
#   - スモークテスト（`smoke.sh`）の結果
#   - stg DB のスキーマ数・主要表の行数（「空のまま緑」を防ぐ）
#   - pgBackRest stanza の状態（読める場合のみ。ホスト権限が要る）
#
# 使い方:
#   scripts/stg/status.sh            # 要約
#   scripts/stg/status.sh --quiet    # 異常のみ出力（監視向け）
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
QUIET=0
[ "${1:-}" = "--quiet" ] && QUIET=1

PORT="${STG_PG_PORT:-55438}"
DB_NAME="${STG_DB_NAME:-ceos_stg}"
CLUSTER="${STG_PG_CLUSTER:-18/infra_stg}"
fails=0
say() { [ "$QUIET" = "1" ] || echo "$@"; }
bad() { echo "$@" >&2; fails=$((fails + 1)); }

cd "$REPO_ROOT"

# --- 1. 前提 ---------------------------------------------------------------
# 生死は「接続を受け付けるか」で判定する。`pg_lsclusters` は external_pid_file を優先して
# 判定するため（PgCommon.pm）、`/var/run/postgresql/18-infra_stg.pid` が失われているだけで
# 稼働中のクラスタを `down` と表示する。2026-10-19 にこれが原因で本監視が 732 回連続で
# 失敗し、恒常的な赤が本当の異常を覆い隠した。`pg_lsclusters` は失敗時の診断にだけ使う。
if pg_isready -h 127.0.0.1 -p "$PORT" >/dev/null 2>&1; then
  say "OK  : ホスト PG クラスタ ${CLUSTER} は接続を受け付ける（port ${PORT}）"
else
  listing="$(pg_lsclusters -h 2>/dev/null | awk -v c="$CLUSTER" '$1"/"$2 == c {print $4}')"
  bad "NG  : ホスト PG クラスタ ${CLUSTER} が接続を受け付けない（pg_lsclusters=${listing:-unknown}）"
fi

# ss の出力を先に変数へ取り込む。pipefail 下で `grep -q` が一致時に早く終わると、上流の awk が
# SIGPIPE で 141 終了し、パイプ全体が偽になって稼働中でも NG を出す（2026-10-28 に 1 日 12 回の偽陽性）。
listeners="$(ss -lnt 2>/dev/null | awk '{print $4}')"
if grep -qx "10.201.0.1:${PORT}" <<<"$listeners"; then
  say "OK  : db-bridge が 10.201.0.1:${PORT} で LISTEN"
else
  bad "NG  : db-bridge が LISTEN していない（コンテナから DB へ到達できない）"
fi

# --- 2. コンテナ -----------------------------------------------------------
total=0
abnormal=""
if command -v docker >/dev/null 2>&1; then
  while IFS='|' read -r name state; do
    [ -z "$name" ] && continue
    total=$((total + 1))
    # "Up ..." は起動中とみなす（unhealthy / Restarting / Exited は下で別途拾う）。
    # healthcheck を持たないコンテナ（kibana 等）は "Up N minutes" とだけ出るため、
    # healthy の有無で判定すると誤検知する（2026-10-14 実測）。
    case "$state" in
      Up\ *) : ;;
      *) abnormal="${abnormal}${name}(${state}) " ;;
    esac
  done < <(docker ps --filter 'name=ceos-stg-' --format '{{.Names}}|{{.Status}}' 2>/dev/null)
  # unhealthy / Restarting / Exited を明示的に拾う（"Up N seconds" は起動直後として許容）
  restarted="$(docker ps -a --filter 'name=ceos-stg-' --format '{{.Names}}|{{.Status}}' 2>/dev/null |
    awk -F'|' '$2 ~ /unhealthy|Restarting|Exited/ {printf "%s(%s) ", $1, $2}')"
  abnormal="${abnormal}${restarted}"
fi
if [ "$total" = "0" ]; then
  bad "NG  : ceos-stg-* のコンテナが 1 つも起動していない（scripts/stg/up.sh）"
else
  say "OK  : ceos-stg-* コンテナ ${total} 個が起動"
fi
[ -n "$abnormal" ] && bad "NG  : 異常なコンテナ: ${abnormal}"

# --- 3. スモーク -----------------------------------------------------------
smoke_out="$(scripts/stg/smoke.sh 2>&1)"
smoke_tail="$(printf '%s\n' "$smoke_out" | grep -E '^結果:' || true)"
if printf '%s\n' "$smoke_out" | grep -q '^OK: stg スモークテスト通過'; then
  say "OK  : スモーク ${smoke_tail:-通過}"
else
  bad "NG  : スモーク失敗 ${smoke_tail:-}（詳細は scripts/stg/smoke.sh を直接実行）"
fi

# --- 4. stg DB の中身（空のまま緑を防ぐ） -----------------------------------
db_line="$(sudo -n -u postgres psql -p "$PORT" -d "$DB_NAME" -tAc "
  SELECT (SELECT count(*) FROM information_schema.schemata
           WHERE schema_name NOT IN ('pg_catalog','information_schema','pg_toast')
             AND schema_name NOT LIKE 'pg\_%') || ' schemas / ' ||
         (SELECT count(*) FROM information_schema.tables
           WHERE table_schema NOT IN ('pg_catalog','information_schema')) || ' tables / users=' ||
         (SELECT count(*) FROM auth.users)" 2>/dev/null)"
if [ -n "$db_line" ]; then
  say "OK  : ${DB_NAME}: ${db_line}"
  case "$db_line" in
    *"users=0"*) bad "NG  : auth.users が 0 行（scripts/stg/seed_stg.sh を実行すること）" ;;
  esac
else
  bad "NG  : ${DB_NAME} を読めない（sudo -n -u postgres が使えるか確認）"
fi

# --- 5. pgBackRest（読める場合のみ） ---------------------------------------
if [ -r /etc/pgbackrest/infra-stg.conf ] || sudo -n test -r /etc/pgbackrest/infra-stg.conf 2>/dev/null; then
  pg_status="$(sudo -n -u postgres pgbackrest --config=/etc/pgbackrest/infra-stg.conf --stanza=infra_stg info 2>/dev/null | awk '/status:/{print $2; exit}')"
  if [ "$pg_status" = "ok" ]; then
    say "OK  : pgBackRest stanza infra_stg status=ok"
  else
    bad "NG  : pgBackRest stanza infra_stg status=${pg_status:-unknown}"
  fi
else
  say "----: pgBackRest の設定を読めないため未確認（成功と記録しない）"
fi

# --- 結果 -----------------------------------------------------------------
if [ "$fails" -gt 0 ]; then
  echo "NG: ${fails} 件の異常。" >&2
  exit 1
fi
say "OK  : stg は正常。"
exit 0
