#!/usr/bin/env bash
# stg スタックを起動する。
#
# 使い方:
#   scripts/stg/up.sh              # 起動して health を待つ
#   scripts/stg/up.sh --no-wait    # 起動だけ
#   scripts/stg/up.sh --build      # イメージを再ビルドする
#
# 前提:
#   scripts/stg/gen_stg_env.sh と scripts/stg/bootstrap_stg_db.sh が完了していること。
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ENV_FILE="${HOME}/.config/ceos/stg.env"
COMPOSE_FILE="${REPO_ROOT}/docker-compose.stg.yml"
CLUSTER="${STG_PG_CLUSTER:-18/infra_stg}"
PORT="${STG_PG_PORT:-55438}"
BRIDGE_BIND="${STG_DB_BRIDGE_BIND:-10.201.0.1}"

BUILD=0
WAIT=1
for arg in "$@"; do
  case "$arg" in
    --build) BUILD=1 ;;
    --no-wait) WAIT=0 ;;
    *)
      echo "unknown option: $arg" >&2
      exit 2
      ;;
  esac
done

echo "== 前提確認 =="
[ -f "$ENV_FILE" ] || {
  echo "NG: $ENV_FILE が無い。scripts/stg/gen_stg_env.sh を実行すること。" >&2
  exit 1
}
if ! grep -q '__FILLED_BY_BOOTSTRAP__' "$ENV_FILE"; then
  echo "OK: 秘密ファイルが設定済み"
else
  echo "NG: $ENV_FILE に未設定の項目がある。scripts/stg/bootstrap_stg_db.sh を実行すること。" >&2
  exit 1
fi

# 生死は接続受付で判定する（pg_lsclusters は external_pid_file 欠落だけで down を返す。
# Mirai-Platform-Infra の docs/stg-inventory.md §3.1 を参照）。
if ! pg_isready -h 127.0.0.1 -p "$PORT" >/dev/null 2>&1; then
  status="$(pg_lsclusters -h | awk -v c="$CLUSTER" '$1"/"$2 == c {print $4}')"
  echo "NG: ホスト PostgreSQL クラスタ $CLUSTER が接続を受け付けない（pg_lsclusters=${status:-unknown}）。" >&2
  echo "    自動起動は無効である。起動: sudo pg_ctlcluster ${CLUSTER%/*} ${CLUSTER#*/} start" >&2
  exit 1
fi
echo "OK: クラスタ $CLUSTER は接続を受け付ける（port $PORT）"

echo "== 生成物の一致確認 =="
python3 "${REPO_ROOT}/scripts/stg/render_stg_compose.py" --check

set -a
# shellcheck disable=SC1090
. "$ENV_FILE"
set +a

cd "$REPO_ROOT"
args=(-f docker-compose.stg.yml up -d --remove-orphans)
[ "$BUILD" = "1" ] && args=(--build "${args[@]}")

echo "== 起動 =="
docker compose "${args[@]}"

echo "== db-bridge の実測（ホスト loopback への転送） =="
if ss -lnt | awk '{print $4}' | grep -qx "${BRIDGE_BIND}:${PORT}"; then
  echo "OK: ${BRIDGE_BIND}:${PORT} が LISTEN している"
else
  echo "NG: ${BRIDGE_BIND}:${PORT} が LISTEN していない。stg のコンテナから DB へ到達できない。" >&2
  docker compose -f docker-compose.stg.yml logs --tail 50 db-bridge >&2 || true
  exit 1
fi

if [ "$WAIT" = "1" ]; then
  echo "== health 待ち（最大 5 分） =="
  deadline=$((SECONDS + 300))
  while [ $SECONDS -lt $deadline ]; do
    unhealthy="$(docker compose -f docker-compose.stg.yml ps --format '{{.Name}} {{.Health}}' | awk '$2 != "" && $2 != "healthy" {print $1}')"
    if [ -z "$unhealthy" ]; then
      break
    fi
    sleep 5
  done
  docker compose -f docker-compose.stg.yml ps --format 'table {{.Name}}\t{{.Status}}'
  if [ -n "${unhealthy:-}" ]; then
    echo "警告: 未 healthy のコンテナ: $unhealthy" >&2
  fi
fi

cat <<EOF

stg 起動完了。
  ゲートウェイ  : http://127.0.0.1:19500/health
  Web           : http://127.0.0.1:19530
  公開 URL      : ${STG_PUBLIC_BASE_URL:-https://construction-os-stg.mirai-dx-platform.com}
  確認          : scripts/stg/smoke.sh
EOF
