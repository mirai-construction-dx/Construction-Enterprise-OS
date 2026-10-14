#!/usr/bin/env bash
# stg のスモークテスト。stg が「stg として」正しく動いているかを検査する。
#
# 検査する内容:
#   S-1 ゲートウェイ /health が 200
#   S-2 auth /health が 200
#   S-3 Web が 200
#   S-4 認証なしの保護エンドポイントが 401（fail closed）
#   S-5 **stg では /docs が無効である**（ENVIRONMENT=staging の統制が効いている）
#   S-6 ホスト PostgreSQL 18 の ceos_stg へ db-bridge 経由で到達できる
#
# 失敗は成功として扱わない。1 つでも失敗すれば非ゼロで終了する。
#
# 使い方:
#   scripts/stg/smoke.sh                       # 既定のターゲット（127.0.0.1）
#   scripts/stg/smoke.sh --base https://construction-os-stg.mirai-dx-platform.com
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ENV_FILE="${HOME}/.config/ceos/stg.env"
BASE_URL=""
EXPECT_ACCESS=0

while [ $# -gt 0 ]; do
  case "$1" in
    --base)
      BASE_URL="$2"
      shift 2
      ;;
    --expect-access)
      EXPECT_ACCESS=1
      shift
      ;;
    *)
      echo "unknown option: $1" >&2
      exit 2
      ;;
  esac
done

# 認証情報: パスワードはファイルから読む（コマンドラインへ値を出さない）。
# メールアドレスは秘密ではないので定数。@example.invalid 等の RFC 2606 予約ドメインは
# pydantic の EmailStr が special-use として 422 にするため使えない（2026-10-14 実測）。
STG_SMOKE_ADMIN_EMAIL="stg-admin@stg.mirai-dx-platform.com"
STG_SMOKE_ADMIN_PASSWORD=""
if [ -f "$ENV_FILE" ]; then
  STG_SMOKE_ADMIN_PASSWORD="$(grep -m1 '^STG_SMOKE_ADMIN_PASSWORD=' "$ENV_FILE" | cut -d= -f2- || true)"
  BASE_URL="${BASE_URL:-${STG_SMOKE_BASE_URL:-http://127.0.0.1:19500}}"
fi
BASE_URL="${BASE_URL:-http://127.0.0.1:19500}"

pass=0
fail=0

check() {
  local id="$1" desc="$2" expected="$3" actual="$4"
  if [ "$expected" = "$actual" ]; then
    echo "PASS: $id $desc (expect=$expected got=$actual)"
    pass=$((pass + 1))
  else
    echo "FAIL: $id $desc (expect=$expected got=$actual)" >&2
    fail=$((fail + 1))
  fi
}

code() { curl -sS -o /dev/null -w '%{http_code}' --max-time 20 "$1" 2>/dev/null || echo "000"; }

# S-3 は「Web が配信できているか」を見る。Next.js は未認証の "/" を
# ログインへ 307 で飛ばすことがあるため、200 だけを合格にしない。
# 5xx と 000（無応答）は不合格とする。
check_serving() {
  local id="$1" desc="$2" url="$3" actual
  actual="$(code "$url")"
  case "$actual" in
    2* | 3*)
      echo "PASS: $id $desc (got=$actual)"
      pass=$((pass + 1))
      ;;
    *)
      echo "FAIL: $id $desc (2xx/3xx を期待したが got=$actual)" >&2
      fail=$((fail + 1))
      ;;
  esac
}

echo "== stg スモークテスト =="
echo "base: $BASE_URL"
echo

if [ "$EXPECT_ACCESS" = "1" ]; then
  # 公開入口は Cloudflare Access の後ろにある。未認証は 302（ログインへ）でなければならない。
  check "S-0" "公開入口が Access で保護されている" "302" "$(code "${BASE_URL}/")"
else
  check "S-1" "gateway /health" "200" "$(code "${BASE_URL}/health")"
  check "S-2" "gateway -> auth /api/v1/health/services" "200" "$(code "${BASE_URL}/api/v1/health/services")"
  check_serving "S-3" "web (19530) が配信している" "http://127.0.0.1:19530/"
  check "S-4" "認証なしの保護エンドポイントは 401" "401" "$(code "${BASE_URL}/api/v1/users")"
  # ENVIRONMENT=staging では docs_url/redoc_url/openapi_url が None になる（各 services/*/src/main.py）。
  check "S-5" "stg では /docs が無効" "404" "$(code "${BASE_URL}/docs")"

  # S-7 認証が DB まで通っているか（シード済み管理ユーザでログインする）。
  # スキーマだけ戻ってデータが無い「気付かず緑」を防ぐ。
  if [ -n "$STG_SMOKE_ADMIN_EMAIL" ] && [ -n "$STG_SMOKE_ADMIN_PASSWORD" ]; then
    body="$(printf '{"email":"%s","password":"%s"}' "$STG_SMOKE_ADMIN_EMAIL" "$STG_SMOKE_ADMIN_PASSWORD")"
    login_code="$(curl -sS -o /tmp/ceos-stg-login.json -w '%{http_code}' --max-time 20 \
      -X POST "${BASE_URL}/api/v1/auth/login" -H 'Content-Type: application/json' -d "$body" 2>/dev/null || echo 000)"
    check "S-7a" "管理ユーザでログインできる" "200" "$login_code"
    # 応答は APIResponse[LoginResponse] なので data 配下に入る実装と
    # 直下に入る実装の両方を受ける（どちらでも「トークンが発行された」ことを見る）。
    if python3 -c "
import json, sys
d = json.load(open('/tmp/ceos-stg-login.json'))
tok = d.get('access_token') or (d.get('data') or {}).get('access_token')
sys.exit(0 if tok else 1)
" 2>/dev/null; then
      echo "PASS: S-7b アクセストークンが発行される"
      pass=$((pass + 1))
    else
      echo "FAIL: S-7b アクセストークンが発行されない" >&2
      fail=$((fail + 1))
    fi
    rm -f /tmp/ceos-stg-login.json
  else
    echo "FAIL: S-7 認証情報が $ENV_FILE に無い（scripts/stg/seed_stg.sh を実行すること）" >&2
    fail=$((fail + 1))
  fi

  # S-8 MCP サービスの公開ツールが契約（contracts/mcp-tools/ceos.json）と一致するか。
  # services/mcp は実装も契約も存在したが compose に含まれておらず起動していなかった
  # （2026-10-14 修正）。読み取り専用 5 ツールが契約どおり公開されていることを見る。
  mcp_body="$(curl -sS --max-time 15 http://127.0.0.1:19522/health 2>/dev/null || true)"
  if printf '%s' "$mcp_body" | python3 -c "
import json, sys, pathlib
d = json.load(sys.stdin)
tools = sorted(d.get('registered_tools') or [])
contract = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding='utf-8'))
want = sorted(t['name'] for t in contract['tools'])
sys.exit(0 if tools == want and tools else 1)
" "${REPO_ROOT}/contracts/mcp-tools/ceos.json" 2>/dev/null; then
    echo "PASS: S-8 MCP の公開ツールが契約 ceos.json と一致する"
    pass=$((pass + 1))
  else
    echo "FAIL: S-8 MCP の公開ツールが契約 ceos.json と一致しない" >&2
    fail=$((fail + 1))
  fi

  # S-9 Web(Next.js) の /api/* がゲートウェイへプロキシできているか。
  # apps/web は output: "standalone" のため rewrites() が**ビルド時**に確定する。
  # Docker の runtime 環境変数は効かず、ビルド引数で渡さないと
  # http://localhost:9000 が焼き込まれて /api/* が 500 になる（2026-10-14 実測）。
  check "S-9" "web 経由で /api/v1/health/services が通る" "200" \
    "$(code "http://127.0.0.1:19530/api/v1/health/services")"

  # S-10 mobile が本番の実行形態（静的エクスポート）で配信されているか。
  # 旧版は output: 'export' と書きながら next dev（開発サーバ）で配信していた
  # （docs/operations/staging.md §9 D-1）。stg は本番の実行形態を練習する場である。
  mobile_headers="$(curl -sSI --max-time 15 http://127.0.0.1:19531/ 2>/dev/null || true)"
  if printf '%s' "$mobile_headers" | grep -qi '^x-ceos-static-export: 1'; then
    echo "PASS: S-10 mobile が静的エクスポートを配信している（開発サーバではない）"
    pass=$((pass + 1))
  else
    echo "FAIL: S-10 mobile が静的エクスポートを配信していない（next dev の可能性）" >&2
    fail=$((fail + 1))
  fi
fi

echo
echo "== DB 到達性（db-bridge 経由） =="
if ss -lnt | awk '{print $4}' | grep -qx "10.201.0.1:55438"; then
  echo "PASS: S-6a db-bridge が 10.201.0.1:55438 で LISTEN"
  pass=$((pass + 1))
else
  echo "FAIL: S-6a db-bridge が LISTEN していない" >&2
  fail=$((fail + 1))
fi

db_code=$(curl -sS -o /dev/null -w '%{http_code}' --max-time 10 "http://127.0.0.1:19501/health" 2>/dev/null || echo "000")
check "S-6b" "auth が DB 込みで healthy（/health は DB 不通なら 503）" "200" "$db_code"

echo
echo "結果: PASS=$pass FAIL=$fail"
if [ "$fail" -gt 0 ]; then
  echo "NG: スモークテストが失敗した。stg を成功と記録しない。" >&2
  exit 1
fi
echo "OK: stg スモークテスト通過。"
