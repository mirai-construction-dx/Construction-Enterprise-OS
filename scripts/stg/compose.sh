#!/usr/bin/env bash
# stg の compose を、秘密ファイルを読み込んだ状態で実行する薄いラッパー。
#
# 使い方:
#   scripts/stg/compose.sh ps
#   scripts/stg/compose.sh logs -f auth
#   scripts/stg/compose.sh up -d db-bridge redis
#   scripts/stg/compose.sh exec auth python -c 'print(1)'
#
# 秘密は ~/.config/ceos/stg.env からのみ読み、リポジトリへは置かない（ADR-0005 §5）。
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ENV_FILE="${HOME}/.config/ceos/stg.env"

if [ ! -f "$ENV_FILE" ]; then
  echo "NG: $ENV_FILE が無い。scripts/stg/gen_stg_env.sh を実行すること。" >&2
  exit 1
fi

set -a
# shellcheck disable=SC1090
. "$ENV_FILE"
set +a

cd "$REPO_ROOT"
exec docker compose -f docker-compose.stg.yml "$@"
