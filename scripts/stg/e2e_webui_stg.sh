#!/usr/bin/env bash
# stg が配信する WebUI 成果物（Cloudflare Pages に載る単一 HTML）を、
# **デプロイ前にローカルで** Playwright E2E にかける。
#
# なぜ必要か:
#   `staging-deploy.yml` が Pages へ配るのは `webui/Construction-Enterprise-OS---CRUD.html`
#   （`index.html` として配置）である。`e2e/mvp.spec.ts` / `e2e/crud.spec.ts` は
#   まさにこの成果物を対象にしているが、従来は **本番/MVP の Pages URL を直叩き**していた。
#   つまり「壊れた成果物を本番へ出してから気付く」経路だった。
#   stg の役割はそこを前倒しすることなので、同じ成果物をローカルで配って同じテストを回す。
#
# 何を確かめないか:
#   Pages Functions（`webui/functions/api/[[path]].ts`）のプロキシは wrangler の
#   Workers ランタイムで動くため、`python3 -m http.server` では再現しない。
#   `/api/*` を伴う検証は stg ドメインへデプロイ後に `scripts/stg/e2e_stg.sh` で行う。
#
# 使い方:
#   scripts/stg/e2e_webui_stg.sh
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PORT="${STG_WEBUI_PORT:-19560}"
SERVE_DIR="$(mktemp -d)"
BUNDLE="webui/Construction-Enterprise-OS---CRUD.html"

cleanup() {
  [ -n "${SERVER_PID:-}" ] && kill "$SERVER_PID" 2>/dev/null || true
  rm -rf "$SERVE_DIR"
}
trap cleanup EXIT

cd "$REPO_ROOT"
if [ ! -f "$BUNDLE" ]; then
  echo "NG: $BUNDLE が無い。" >&2
  exit 1
fi

# Pages のデプロイ内容と同じ配置を作る（pages-deploy.yml / staging-deploy.yml と同順）。
cp "$BUNDLE" "$SERVE_DIR/index.html"
[ -f "webui/Construction-Enterprise-OS---Standalone-_1_.html" ] &&
  cp "webui/Construction-Enterprise-OS---Standalone-_1_.html" "$SERVE_DIR/standalone-prototype.html"
[ -d webui/functions ] && cp -r webui/functions "$SERVE_DIR/functions"
[ -f webui/brand-spec.md ] && cp webui/brand-spec.md webui/DESIGN-HANDOFF.md webui/DESIGN-MANIFEST.json "$SERVE_DIR/" 2>/dev/null || true

echo "== stg WebUI 成果物の E2E（ローカル配信） =="
echo "成果物: ${BUNDLE}"
echo "配信:   http://127.0.0.1:${PORT}"

# python3 -m http.server は未知のパスに 404 を返し、Pages の SPA フォールバックを
# 再現できない。成果物の欠陥ではない理由で mvp.spec.ts が落ちるため（2026-10-14 実測）、
# Pages と同じ挙動のローカルサーバーを使う。
python3 "$REPO_ROOT/scripts/stg/serve_webui.py" "$SERVE_DIR" "$PORT" >/dev/null 2>&1 &
SERVER_PID=$!

# 起動待ち（最大 15 秒）
for _ in $(seq 1 15); do
  if curl -sS -o /dev/null --max-time 2 "http://127.0.0.1:${PORT}/"; then break; fi
  sleep 1
done
if ! curl -sS -o /dev/null --max-time 2 "http://127.0.0.1:${PORT}/"; then
  echo "NG: ローカル配信が起動しなかった。" >&2
  exit 1
fi

E2E_BASE_URL="http://127.0.0.1:${PORT}" \
  npx --yes playwright test e2e/mvp.spec.ts e2e/crud.spec.ts --reporter=list "$@"

echo
echo "注意: /api/* は Pages Functions が担うためローカル配信では検証していない。"
echo "      API を含む検証は stg ドメインへデプロイ後に scripts/stg/e2e_stg.sh で行う。"
