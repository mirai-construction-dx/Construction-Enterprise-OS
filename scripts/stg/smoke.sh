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

if [ -f "$ENV_FILE" ]; then
  # shellcheck disable=SC1090
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
