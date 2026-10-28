#!/usr/bin/env bash
# stg の**障害時挙動**を実測する訓練。DB 到達不能時に fail-closed で縮退し、
# 復旧後に自動で戻ることを確かめる。
#
# なぜ必要か:
#   stg は「本番前の検証環境」であり、正常系だけでなく**異常系の挙動**を練習する場である。
#   これまで確認していたのは正常系（起動・疎通・スモーク）だけだった。
#
# 何をするか:
#   1. 基準状態を記録する（全コンテナの health とスモーク）
#   2. `db-bridge` を止め、コンテナから DB へ到達できない状態を作る
#   3. 各サービスの応答を実測する
#        - auth の /health は DB 不通なら **503**（fail-closed）であること
#          ※ 200 を返すなら「DB を見ていない health」であり、監視が機能しない
#        - gateway の /health は DB を必要としないので 200 のままでよい
#        - コンテナが落ちたり再起動ループに入ったりしないこと
#   4. `db-bridge` を戻し、復旧を確認する（スモークが通ること）
#
# 何をしないか:
#   - ホスト PostgreSQL クラスタは止めない（他システムの `mirai` DB と共有している）
#   - データを壊す操作はしない（接続断のみ）
#
# 使い方:
#   scripts/stg/failure_drill.sh
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

PORT="${STG_PG_PORT:-55438}"
BRIDGE_BIND="${STG_DB_BRIDGE_BIND:-10.201.0.1}"
fails=0

code() { curl -sS -o /dev/null -w '%{http_code}' --max-time 15 "$1" 2>/dev/null || echo 000; }

cleanup() {
  # 訓練の途中で中断しても DB 到達性は必ず戻す。
  scripts/stg/compose.sh start db-bridge >/dev/null 2>&1 || true
}
trap cleanup EXIT

echo "== stg 障害訓練（DB 到達不能 / $(date -Iseconds)） =="
echo

echo "-- 1. 基準状態 --"
baseline_smoke="$(scripts/stg/smoke.sh 2>&1 | grep -E '^結果:' || true)"
echo "スモーク: ${baseline_smoke:-（取得できず）}"
auth_before="$(code http://127.0.0.1:19501/health)"
gw_before="$(code http://127.0.0.1:19500/health)"
echo "auth /health=${auth_before}  gateway /health=${gw_before}"
if [ "$auth_before" != "200" ]; then
  echo "NG: 訓練前から auth が healthy でない。先に状態を直すこと。" >&2
  exit 1
fi

echo
echo "-- 2. db-bridge を停止（コンテナから DB へ到達不能にする） --"
scripts/stg/compose.sh stop db-bridge >/dev/null 2>&1
sleep 5
listeners="$(ss -lnt 2>/dev/null | awk '{print $4}')"  # SIGPIPE 回避（status.sh の注記を参照）
if grep -qx "${BRIDGE_BIND}:${PORT}" <<<"$listeners"; then
  echo "NG: 停止したのに ${BRIDGE_BIND}:${PORT} が LISTEN している。" >&2
  exit 1
fi
echo "OK: ${BRIDGE_BIND}:${PORT} は LISTEN していない"

echo
echo "-- 3. 障害中の応答（fail-closed の確認） --"
auth_down="$(code http://127.0.0.1:19501/health)"
gw_down="$(code http://127.0.0.1:19500/health)"
echo "auth /health=${auth_down}  gateway /health=${gw_down}"
if [ "$auth_down" = "503" ]; then
  echo "PASS: auth は DB 不通で 503 を返す（fail-closed）"
elif [ "$auth_down" = "200" ]; then
  echo "FAIL: auth が DB 不通でも 200 を返す（DB を見ていない health は監視として機能しない）" >&2
  fails=$((fails + 1))
else
  echo "FAIL: auth の応答が想定外（${auth_down}）" >&2
  fails=$((fails + 1))
fi
if [ "$gw_down" = "200" ]; then
  echo "PASS: gateway は DB を必要としないため 200 のまま"
else
  echo "警告: gateway の応答が変化した（${gw_down}）。DB 依存が無いか確認すること。" >&2
fi

# コンテナが落ちていないこと（再起動ループに入っていないこと）。
# `db-bridge` は**この訓練が意図的に止めた**障害そのものなので対象外にする
# （2026-10-14 実測: 除外しないと自分で起こした障害を異常として数えてしまう）。
restarting="$(docker ps -a --filter 'name=ceos-stg-' --format '{{.Names}}|{{.Status}}' 2>/dev/null |
  awk -F'|' '$2 ~ /Restarting|Exited/ && $1 != "ceos-stg-db-bridge" {printf "%s ", $1}')"
if [ -z "$restarting" ]; then
  echo "PASS: 障害中も（意図的に止めた db-bridge 以外に）停止・再起動ループ入りしたコンテナは無い"
else
  echo "FAIL: 障害中に停止・再起動ループ入りしたコンテナ: ${restarting}" >&2
  fails=$((fails + 1))
fi

echo
echo "-- 4. 復旧（db-bridge を戻す） --"
scripts/stg/compose.sh start db-bridge >/dev/null 2>&1
deadline=$((SECONDS + 90))
auth_after="000"
while [ $SECONDS -lt $deadline ]; do
  auth_after="$(code http://127.0.0.1:19501/health)"
  [ "$auth_after" = "200" ] && break
  sleep 5
done
echo "auth /health=${auth_after}（復旧後）"
if [ "$auth_after" = "200" ]; then
  echo "PASS: DB 到達が戻ると auth は自動で healthy に復帰する"
else
  echo "FAIL: 復旧後に auth が healthy に戻らない（${auth_after}）" >&2
  fails=$((fails + 1))
fi

after_smoke="$(scripts/stg/smoke.sh 2>&1 | grep -E '^結果:' || true)"
echo "スモーク: ${after_smoke:-（取得できず）}"
if printf '%s' "$after_smoke" | grep -q 'FAIL=0'; then
  echo "PASS: 復旧後のスモークが全通過"
else
  echo "FAIL: 復旧後のスモークが通らない" >&2
  fails=$((fails + 1))
fi

echo
echo "結果: 基準 ${baseline_smoke:-?} / 障害中 auth=${auth_down} / 復旧後 ${after_smoke:-?}"
if [ "$fails" -gt 0 ]; then
  echo "NG: 障害訓練で ${fails} 件が失敗。縮退と復旧の挙動を記録どおりとみなさない。" >&2
  exit 1
fi
echo "OK: DB 到達不能時に fail-closed で縮退し、復旧後に自動で戻ることを実測した。"
