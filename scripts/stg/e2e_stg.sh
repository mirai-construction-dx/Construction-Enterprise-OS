#!/usr/bin/env bash
# stg に対して Playwright の API E2E（`e2e/api.spec.ts`）を実行する。
#
# なぜ API だけか:
#   `e2e/mvp.spec.ts` / `crud.spec.ts` は Cloudflare Pages が配信する
#   単一 HTML プロトタイプ（`webui/Construction-Enterprise-OS---CRUD.html`）を対象にしている。
#   stg のローカルスタックが配信するのは Next.js（`apps/web`）なので、これらは
#   **stg のローカルスタックには適用できない**（Pages へデプロイ後に stg ドメインで実行する）。
#   `e2e/api.spec.ts` は API 経由なので stg のゲートウェイに対してそのまま使える。
#
# 資格情報は `~/.config/ceos/stg.env` から読む（コマンドラインへ値を出さない）。
# メールアドレスは秘密ではないので定数（RFC 2606 の予約ドメインは EmailStr が 422 にする）。
#
# 使い方:
#   scripts/stg/e2e_stg.sh                 # ローカル stg スタック（127.0.0.1:19500）
#   STG_E2E_API_BASE_URL=https://construction-os-stg.mirai-dx-platform.com \
#     scripts/stg/e2e_stg.sh               # stg ドメイン（Access サービス トークンが要る）
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ENV_FILE="${HOME}/.config/ceos/stg.env"

API_BASE="${STG_E2E_API_BASE_URL:-http://127.0.0.1:19500}"
ADMIN_EMAIL="${STG_E2E_ADMIN_EMAIL:-stg-admin@stg.mirai-dx-platform.com}"

if [ ! -f "$ENV_FILE" ]; then
  echo "NG: $ENV_FILE が無い。scripts/stg/gen_stg_env.sh を実行すること。" >&2
  exit 1
fi
ADMIN_PASSWORD="$(grep -m1 '^STG_SMOKE_ADMIN_PASSWORD=' "$ENV_FILE" | cut -d= -f2-)"
if [ -z "$ADMIN_PASSWORD" ]; then
  echo "NG: $ENV_FILE に STG_SMOKE_ADMIN_PASSWORD が無い。" >&2
  exit 1
fi

echo "== stg API E2E =="
echo "対象: ${API_BASE}"
echo "ユーザ: ${ADMIN_EMAIL}"

cd "$REPO_ROOT"
# Cloudflare Access の後ろへ向ける場合はサービス トークンを付ける（未設定なら付けない）。
if [ -n "${STG_ACCESS_CLIENT_ID:-}" ] && [ -n "${STG_ACCESS_CLIENT_SECRET:-}" ]; then
  echo "Access サービス トークンを付与する"
  export E2E_EXTRA_HEADERS="{\"CF-Access-Client-Id\":\"${STG_ACCESS_CLIENT_ID}\",\"CF-Access-Client-Secret\":\"${STG_ACCESS_CLIENT_SECRET}\"}"
fi

E2E_API_BASE_URL="$API_BASE" \
  E2E_ADMIN_EMAIL="$ADMIN_EMAIL" \
  E2E_ADMIN_PASSWORD="$ADMIN_PASSWORD" \
  E2E_BASE_URL="${E2E_BASE_URL:-http://127.0.0.1:19530}" \
  npx --yes playwright test e2e/api.spec.ts --reporter=list "$@"

echo
echo "注意: mvp.spec.ts / crud.spec.ts は Pages 配信の単一 HTML を対象にするため、"
echo "      ローカル stg スタックでは実行しない（stg ドメインへデプロイ後に実行する）。"
