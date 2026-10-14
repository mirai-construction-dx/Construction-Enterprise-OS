#!/usr/bin/env bash
# ゲートウェイが持つ**全ての上流ルート**が実際に到達可能かを確かめる。
#
# なぜ必要か:
#   ゲートウェイは `UPSTREAM_SERVICES` に 21 のサービスへのルートを持つが、
#   確認していたのは auth 系だけだった。コンテナが起動していても、
#   ルート定義の綴り・コンテナ名・ポートがずれていれば気付けない。
#
# なぜ「ゲートウェイ経由で叩く」だけでは足りないか:
#   上流のエンドポイントパスを推測して叩くと、サービスの 404（そのパスが無い）と
#   ゲートウェイの 404（そのルートが無い）を区別できない（2026-10-14 実測。
#   20 ルートを推測パスで叩いたところ 7 件が 404 になり、切り分けができなかった）。
#
# そこで 2 段で見る:
#   A. ゲートウェイのコンテナの中から、`UPSTREAM_SERVICES` に列挙された
#      各上流の `/health` を叩く → **全ルートの到達性**を直接確かめる。
#   B. ホストから、パスが実在すると実測で確認できたルートを叩く → 外側からの疎通。
#
# 使い方:
#   scripts/stg/check_gateway_upstreams.sh
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

echo "== A. 上流の到達性（ゲートウェイのコンテナ内から） =="
out="$(scripts/stg/compose.sh exec -T gateway python - <<'PY' 2>/dev/null
import json, os, urllib.error, urllib.request

raw = os.environ.get("UPSTREAM_SERVICES", "")
try:
    routes = json.loads(raw)
except Exception as exc:
    print(json.dumps({"error": f"UPSTREAM_SERVICES を解釈できない: {exc}"}))
    raise SystemExit(0)

upstreams = {}
for prefix, url in routes.items():
    upstreams.setdefault(url, prefix)

results = []
for url, prefix in sorted(upstreams.items(), key=lambda kv: kv[1]):
    target = url.rstrip("/") + "/health"
    try:
        with urllib.request.urlopen(target, timeout=10) as res:
            results.append({"prefix": prefix, "url": url, "status": res.status})
    except urllib.error.HTTPError as exc:
        results.append({"prefix": prefix, "url": url, "status": exc.code})
    except Exception as exc:
        results.append({"prefix": prefix, "url": url, "status": 0, "error": str(exc)})

print(json.dumps({"routes": len(routes), "upstreams": results}, ensure_ascii=False))
PY
)"

if [ -z "$out" ]; then
  echo "NG: ゲートウェイのコンテナから結果を取得できない。" >&2
  exit 1
fi

printf '%s' "$out" | python3 -c "
import json, sys

data = json.load(sys.stdin)
if 'error' in data:
    print('FAIL: ' + data['error'], file=sys.stderr)
    raise SystemExit(1)

ok = bad = 0
for item in data['upstreams']:
    status = item['status']
    if status == 200:
        print(f\"PASS: {item['prefix']:<34} {item['url']:<34} 200\")
        ok += 1
    else:
        detail = item.get('error') or status
        print(f\"FAIL: {item['prefix']:<34} {item['url']:<34} {detail}\", file=sys.stderr)
        bad += 1
print()
print(f\"上流: 到達={ok} 不達={bad}（ルート定義 {data['routes']} 件 / 上流 {len(data['upstreams'])} 件）\")
raise SystemExit(1 if bad else 0)
"
a_rc=$?

echo
echo "== B. 外側からの疎通（パスが実在すると実測できたルート） =="
ENV_FILE="${HOME}/.config/ceos/stg.env"
BASE="${STG_GATEWAY_BASE:-http://127.0.0.1:19500}"
ADMIN_EMAIL="${STG_GATEWAY_ADMIN_EMAIL:-stg-admin@stg.mirai-dx-platform.com}"
PASSWORD="$(grep -m1 '^STG_SMOKE_ADMIN_PASSWORD=' "$ENV_FILE" 2>/dev/null | cut -d= -f2-)"
TOKEN=""
if [ -n "$PASSWORD" ]; then
  TOKEN="$(curl -sS --max-time 20 -X POST "${BASE}/api/v1/auth/login" \
    -H 'Content-Type: application/json' \
    -d "$(printf '{"email":"%s","password":"%s"}' "$ADMIN_EMAIL" "$PASSWORD")" 2>/dev/null |
    python3 -c "
import json, sys
try:
    d = json.load(sys.stdin)
except Exception:
    sys.exit(0)
print(d.get('access_token') or (d.get('data') or {}).get('access_token') or '')
" 2>/dev/null)"
fi

VERIFIED=(
  "/api/v1/health/services"
  "/api/v1/users"
  "/api/v1/roles"
  "/api/v1/documents"
  "/api/v1/workflow/definitions"
  "/api/v1/gis/sites"
  "/api/v1/iot/devices"
  "/api/v1/ai/models"
  "/api/v1/safety/incidents"
  "/api/v1/bim/models"
  "/api/v1/automation/rules"
  "/api/v1/autonomous/tasks"
  "/api/v1/vision/analyses"
  "/api/v1/field/reports"
)
b_bad=0
if [ -z "$TOKEN" ]; then
  echo "FAIL: アクセストークンを取得できないため B を実施できない。" >&2
  b_bad=1
else
  for path in "${VERIFIED[@]}"; do
    code="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 15 \
      -H "Authorization: Bearer ${TOKEN}" "${BASE}${path}" 2>/dev/null || echo 000)"
    case "$code" in
      2* | 3* | 400 | 401 | 403 | 422)
        printf 'PASS: %-40s %s\n' "$path" "$code"
        ;;
      *)
        printf 'FAIL: %-40s %s\n' "$path" "$code" >&2
        b_bad=$((b_bad + 1))
        ;;
    esac
  done
fi

echo
if [ "$a_rc" != "0" ] || [ "$b_bad" != "0" ]; then
  echo "NG: 到達しないルートがある。UPSTREAM_SERVICES とコンテナの状態を確認すること。" >&2
  exit 1
fi
echo "OK: ゲートウェイの全上流と、外側から確認したルートが到達可能。"
