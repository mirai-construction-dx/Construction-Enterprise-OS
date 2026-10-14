#!/usr/bin/env bash
# stg の**上流 1 サービス停止**時の縮退を実測する訓練。
#
# なぜ必要か:
#   `scripts/stg/failure_drill.sh` は **DB 到達不能**（`db-bridge` 断）だけを扱う。
#   実際に起きる障害は「業務サービスが 1 つ落ちる」も多い。2026-10-14 の手動実測で
#   そこから 2 つの課題が見つかった（下記）。手順をスクリプトにして毎回同じ目で見る。
#
#   1. 停止した上流への要求が 502 を返すまで **16.1 秒**かかっていた
#      （原因は HTTP タイムアウトではなく**名前解決**。§6.14）。
#      → 静的 IP ＋ gateway の extra_hosts ＋ 接続タイムアウトの分離で 3.0 秒に短縮。
#   2. 巻き込み（カスケード）は起きていなかった（無関係な上流は無事）。
#
# 何をするか:
#   1. 基準状態を記録する（ゲートウェイ /health、集約ヘルス、無関係な上流のルート）
#   2. 対象の上流（既定: `vision`）を止める
#   3. 障害中の挙動を実測する
#        D-1 ゲートウェイ自身の /health は 200 のまま（巻き込みなし）
#        D-2 集約ヘルスが**そのサービスだけ**を unhealthy と報告し overall が unhealthy
#        D-3 無関係な上流（既定: `gis`）のルートは素早く応答する（巻き込みなし）
#        D-4 停止した上流への**認証付き**要求が上限時間内に定義された応答を返す
#            （ハングしない。502/504）
#        D-5 意図的に止めたサービス以外に停止・再起動ループ入りしたコンテナが無い
#   4. 対象を戻し、復旧を確認する（集約ヘルスとスモーク）
#
# 何をしないか:
#   - データを壊す操作はしない（停止と起動のみ）
#   - ホストの他システム（`mirai` DB 等）には触れない
#
# 使い方:
#   scripts/stg/upstream_failure_drill.sh
#   STG_DRILL_SERVICE=erp STG_DRILL_CONTROL=gis scripts/stg/upstream_failure_drill.sh
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

TARGET="${STG_DRILL_SERVICE:-vision}"
CONTROL="${STG_DRILL_CONTROL:-gis}"
GATEWAY="${STG_GATEWAY_URL:-http://127.0.0.1:19500}"
# 停止した上流への要求が返るまでの上限（秒）。接続タイムアウト（既定 3 秒）に
# 余裕を見る。これを超えたら「ハングしている」と判定する。
MAX_FAIL_SECONDS="${STG_DRILL_MAX_FAIL_SECONDS:-10}"
fails=0

code() { curl -sS -o /dev/null -w '%{http_code}' --max-time 15 "$1" 2>/dev/null || echo 000; }

cleanup() {
  # 訓練の途中で中断しても対象サービスは必ず戻す。
  scripts/stg/compose.sh start "$TARGET" >/dev/null 2>&1 || true
}
trap cleanup EXIT

# 認証付きで 1 本叩き、"status elapsed_ms" を返す。
# パスワードは ~/.config/ceos/stg.env から読む（コマンドラインへ出さない）。
timed_authenticated_get() {
  python3 - "$GATEWAY" "$1" <<'PY' 2>/dev/null || echo "000 -1"
import base64, json, sys, time, urllib.error, urllib.request
from pathlib import Path

gateway, path = sys.argv[1], sys.argv[2]
env = Path.home() / ".config" / "ceos" / "stg.env"
password = ""
for line in env.read_text(encoding="utf-8").splitlines():
    if line.startswith("STG_SMOKE_ADMIN_PASSWORD="):
        password = line.split("=", 1)[1]

def call(url, token=None, payload=None):
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, headers=headers,
                                 method="POST" if payload is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=15) as res:
            return res.status, res.read().decode()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode()
    except Exception:
        return 0, ""

status, body = call(f"{gateway}/api/v1/auth/login",
                    payload={"email": "stg-admin@stg.mirai-dx-platform.com",
                             "password": password})
try:
    token = json.loads(body)["data"]["access_token"] if status == 200 else None
except Exception:
    token = None
if not token:
    print("000 -1")
    raise SystemExit(0)
started = time.perf_counter()
status, _ = call(f"{gateway}{path}", token=token)
print(f"{status} {int((time.perf_counter() - started) * 1000)}")
PY
}

aggregate() {
  # "overall|サービス数|healthy 以外の名前（カンマ区切り）" を返す。
  curl -sS --max-time 20 "$GATEWAY/api/v1/health/services" 2>/dev/null |
    python3 -c "
import json, sys
try:
    d = json.load(sys.stdin)
except Exception:
    print('PARSE_ERROR')
    raise SystemExit(0)
bad = sorted(s['name'] for s in d.get('services', []) if s.get('status') != 'healthy')
print('%s|%s|%s' % (d.get('overall'), len(d.get('services', [])), ','.join(bad)))
"
}

echo "== stg 上流停止訓練（対象=${TARGET} / 対照=${CONTROL} / $(date -Iseconds)） =="
echo
echo "-- 1. 基準状態 --"
gw_before="$(code "$GATEWAY/health")"
agg_before="$(aggregate)"
control_before="$(timed_authenticated_get "/api/v1/${CONTROL}/health")"
echo "ゲートウェイ /health=${gw_before}"
echo "集約ヘルス（overall|サービス数|healthy 以外）=${agg_before}"
echo "対照 ${CONTROL} のルート=${control_before}"
if [ "$gw_before" != "200" ] || ! printf '%s' "$agg_before" | grep -q '^healthy|'; then
  echo "NG: 訓練前から健全でない。先に状態を直すこと。" >&2
  exit 1
fi

echo
echo "-- 2. ${TARGET} を停止する --"
scripts/stg/compose.sh stop "$TARGET" >/dev/null 2>&1
sleep 6
if docker ps --filter "name=ceos-stg-${TARGET}" --format '{{.Names}}' | grep -q .; then
  echo "NG: 停止したのに ceos-stg-${TARGET} が動いている。" >&2
  exit 1
fi
echo "OK: ceos-stg-${TARGET} は停止した"

echo
echo "-- 3. 障害中の挙動 --"
gw_down="$(code "$GATEWAY/health")"
if [ "$gw_down" = "200" ]; then
  echo "PASS: D-1 ゲートウェイ自身の /health は 200 のまま（巻き込みなし）"
else
  echo "FAIL: D-1 ゲートウェイの /health が ${gw_down} に変わった" >&2
  fails=$((fails + 1))
fi

agg_down="$(aggregate)"
echo "集約ヘルス=${agg_down}"
if printf '%s' "$agg_down" | grep -q "^unhealthy|.*|${TARGET}$"; then
  echo "PASS: D-2 集約ヘルスが ${TARGET} だけを unhealthy と報告し overall も unhealthy"
else
  echo "FAIL: D-2 集約ヘルスの報告が想定と違う（${agg_down}）" >&2
  fails=$((fails + 1))
fi

control_down="$(timed_authenticated_get "/api/v1/${CONTROL}/health")"
echo "対照 ${CONTROL} のルート=${control_down}"
control_ms="$(printf '%s' "$control_down" | awk '{print $2}')"
if [ "${control_ms:-9999}" -lt 2000 ] 2>/dev/null; then
  echo "PASS: D-3 無関係な上流（${CONTROL}）は ${control_ms}ms で応答（巻き込みなし）"
else
  echo "FAIL: D-3 無関係な上流（${CONTROL}）の応答が遅い（${control_down}）" >&2
  fails=$((fails + 1))
fi

target_down="$(timed_authenticated_get "/api/v1/${TARGET}/health")"
echo "停止した上流 ${TARGET} のルート=${target_down}"
target_status="$(printf '%s' "$target_down" | awk '{print $1}')"
target_ms="$(printf '%s' "$target_down" | awk '{print $2}')"
if [ "${target_ms:-99999}" -gt "$((MAX_FAIL_SECONDS * 1000))" ] 2>/dev/null; then
  echo "FAIL: D-4 停止した上流への要求が上限（${MAX_FAIL_SECONDS} 秒）を超えた（${target_down}）" >&2
  fails=$((fails + 1))
elif [ "$target_status" = "502" ] || [ "$target_status" = "504" ]; then
  echo "PASS: D-4 停止した上流へは ${target_status} を ${target_ms}ms で返す（ハングしない）"
else
  echo "FAIL: D-4 停止した上流への応答が想定外（${target_down}）" >&2
  fails=$((fails + 1))
fi

# 意図的に止めた対象以外に、落ちた／再起動ループに入ったコンテナが無いこと。
restarting="$(docker ps -a --filter 'name=ceos-stg-' --format '{{.Names}}|{{.Status}}' 2>/dev/null |
  awk -F'|' -v skip="ceos-stg-${TARGET}" '$2 ~ /Restarting|Exited/ && $1 != skip {printf "%s ", $1}')"
if [ -z "$restarting" ]; then
  echo "PASS: D-5 （意図的に止めた ${TARGET} 以外に）停止・再起動ループ入りしたコンテナは無い"
else
  echo "FAIL: D-5 障害中に停止・再起動ループ入りしたコンテナ: ${restarting}" >&2
  fails=$((fails + 1))
fi

echo
echo "-- 4. 復旧（${TARGET} を戻す） --"
scripts/stg/compose.sh start "$TARGET" >/dev/null 2>&1
deadline=$((SECONDS + 120))
agg_after=""
while [ $SECONDS -lt $deadline ]; do
  agg_after="$(aggregate)"
  printf '%s' "$agg_after" | grep -q '^healthy|' && break
  sleep 5
done
echo "集約ヘルス=${agg_after}"
if printf '%s' "$agg_after" | grep -q '^healthy|'; then
  echo "PASS: D-6 復旧後に集約ヘルスが healthy に戻る"
else
  echo "FAIL: D-6 復旧後も集約ヘルスが healthy に戻らない（${agg_after}）" >&2
  fails=$((fails + 1))
fi

after_smoke="$(scripts/stg/smoke.sh 2>&1 | grep -E '^結果:' || true)"
echo "スモーク: ${after_smoke:-（取得できず）}"
if printf '%s' "$after_smoke" | grep -q 'FAIL=0'; then
  echo "PASS: D-7 復旧後のスモークが全通過"
else
  echo "FAIL: D-7 復旧後のスモークが通らない" >&2
  fails=$((fails + 1))
fi

echo
echo "結果: 基準 ${agg_before} / 障害中 ${agg_down} / 復旧後 ${agg_after}"
if [ "$fails" -gt 0 ]; then
  echo "NG: 上流停止訓練で ${fails} 件が失敗。縮退の挙動を記録どおりとみなさない。" >&2
  exit 1
fi
echo "OK: 上流 1 サービスの停止で巻き込まれず、定義された応答を上限内に返し、復旧後に戻ることを実測した。"
