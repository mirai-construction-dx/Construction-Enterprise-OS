#!/usr/bin/env bash
# stg スタックのロールバック訓練。停止して同じリビジョンで戻せることを実測する。
#
# 何を確かめるか:
#   1. 訓練前の状態（全コンテナの health）を記録する
#   2. `down.sh` でスタックを落とす
#   3. `up.sh` で戻す（イメージはキャッシュ済み。ボリュームは保持される）
#   4. 全コンテナが health に戻るまで待つ
#   5. `smoke.sh` が通ることを確かめる
#
# 何を確かめないか:
#   - **イメージを前のリビジョンへ戻す訓練ではない。** それは digest 固定の
#     イメージタグ運用（release 工程）が前提で、まだ整備されていない。
#   - DB のポイントインタイム復旧は含まない（`restore_drill.sh` と §4.2 を参照）。
#
# 使い方:
#   scripts/stg/rollback_drill.sh
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

echo "== stg ロールバック訓練（$(date -Iseconds)） =="
echo
echo "-- 1. 訓練前の状態 --"
before="$(scripts/stg/compose.sh ps --format '{{.Status}}' | sort | uniq -c)"
echo "$before"
if echo "$before" | grep -qE 'unhealthy|Restarting'; then
  echo "警告: 訓練前に unhealthy / Restarting のコンテナがある。先に §6 の残作業を解消すること。" >&2
fi

echo
echo "-- 2. 停止（down.sh） --"
scripts/stg/down.sh
remaining="$(docker ps --filter 'name=ceos-stg-' --format '{{.Names}}' | wc -l)"
if [ "$remaining" != "0" ]; then
  echo "NG: ceos-stg-* のコンテナが $remaining 個残っている。" >&2
  docker ps --filter 'name=ceos-stg-' --format '{{.Names}} {{.Status}}' >&2
  exit 1
fi
echo "  OK: ceos-stg-* は 0 個"

echo
echo "-- 3. 起動（up.sh --no-wait） --"
scripts/stg/up.sh --no-wait

echo
echo "-- 4. health 待ち（最大 5 分） --"
deadline=$((SECONDS + 300))
while [ $SECONDS -lt $deadline ]; do
  pending="$(scripts/stg/compose.sh ps --format '{{.Name}}|{{.Health}}' | awk -F'|' '$2 != "" && $2 != "healthy" {print $1}' | wc -l)"
  [ "$pending" = "0" ] && break
  sleep 10
done
scripts/stg/compose.sh ps --format '{{.Status}}' | sort | uniq -c
bad="$(scripts/stg/compose.sh ps --format '{{.Name}}|{{.Status}}' | awk -F'|' '$2 ~ /unhealthy|Restarting|Exited/ {print $1}' | wc -l)"
if [ "$bad" != "0" ]; then
  echo "NG: 起動後に unhealthy / Restarting / Exited が $bad 個ある。" >&2
  scripts/stg/compose.sh ps --format '{{.Name}}|{{.Status}}' | awk -F'|' '$2 ~ /unhealthy|Restarting|Exited/' >&2
  exit 1
fi
echo "  OK: 異常なコンテナは 0 個"

echo
echo "-- 5. スモークテスト --"
scripts/stg/smoke.sh | tail -3

echo
echo "OK: 停止から復帰までを実測で確認した（同じリビジョンへのロールバック）。"
echo "注意: 前リビジョンのイメージへ戻す訓練は digest 固定の release 工程が前提。未整備。"
