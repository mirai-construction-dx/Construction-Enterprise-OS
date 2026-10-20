#!/usr/bin/env bash
# stg の監視そのものが生きているかを検査する（watchdog）。
#
# なぜ必要か（2026-10-21 実測）:
#   `ceos-stg-status.timer` は 5 分ごとに `monitor.sh` を実行し、stg の異常を
#   journald と `~/.local/state/ceos-stg/status.log` に残す。しかし **監視が止まったこと** は
#   誰も検査していなかった。timer が無効化・失敗・停止すると、stg の異常も
#   「静かに」見えなくなる（監視の死は監視できない、という典型的な穴）。
#
# 何をするか:
#   1. `ceos-stg-status.timer` が active か
#   2. `status.log` の最終実行が 15 分以内か（timer は 5 分間隔）
#   3. `consecutive_failures` が 0 か（監視は動いているが stg が失敗し続けている状態）
#   いずれかが満たされなければ非ゼロで終了し、systemd が failed として記録する。
#
# 使い方:
#   scripts/stg/check_monitoring_health.sh
#   systemctl start ceos-stg-watchdog.service
#   systemctl list-timers ceos-stg-watchdog
set -uo pipefail

STATE_DIR="${CEOS_STG_STATE_DIR:-${HOME}/.local/state/ceos-stg}"
LOG="${STATE_DIR}/status.log"
COUNTER="${STATE_DIR}/consecutive_failures"
MAX_AGE_SECONDS="${CEOS_STG_MONITOR_MAX_AGE_SECONDS:-900}"
TIMER_UNIT="${CEOS_STG_STATUS_TIMER:-ceos-stg-status.timer}"

failures=0

if systemctl is-active --quiet "$TIMER_UNIT"; then
  echo "OK: ${TIMER_UNIT} は active"
else
  echo "NG: ${TIMER_UNIT} が active ではない（監視が停止している）" >&2
  failures=$((failures + 1))
fi

if [ -f "$LOG" ]; then
  last_ts="$(grep -E '^[0-9]{4}-[0-9]{2}-[0-9]{2}T' "$LOG" | tail -n 1 | cut -d' ' -f1 || true)"
  if [ -n "$last_ts" ]; then
    last_epoch="$(date -d "$last_ts" +%s 2>/dev/null || echo 0)"
    now_epoch="$(date +%s)"
    age=$((now_epoch - last_epoch))
    if [ "$last_epoch" -le 0 ]; then
      echo "NG: status.log の最終実行時刻を解釈できない（${last_ts}）" >&2
      failures=$((failures + 1))
    elif [ "$age" -gt "$MAX_AGE_SECONDS" ]; then
      echo "NG: status.log の最終実行が ${age} 秒前（閾値 ${MAX_AGE_SECONDS} 秒）。監視が止まっている" >&2
      failures=$((failures + 1))
    else
      echo "OK: status.log の最終実行は ${age} 秒前（閾値 ${MAX_AGE_SECONDS} 秒）"
    fi
  else
    echo "NG: status.log にタイムスタンプ付きの実行記録が無い" >&2
    failures=$((failures + 1))
  fi
else
  echo "NG: ${LOG} が無い（監視が一度も実行されていない）" >&2
  failures=$((failures + 1))
fi

if [ -f "$COUNTER" ]; then
  consecutive="$(cat "$COUNTER" 2>/dev/null || echo 0)"
  case "$consecutive" in
    ''|*[!0-9]*) consecutive=0 ;;
  esac
  if [ "$consecutive" -ne 0 ]; then
    echo "NG: stg の状態検査が連続 ${consecutive} 回失敗している（status.log を確認）" >&2
    failures=$((failures + 1))
  else
    echo "OK: 連続失敗回数は 0"
  fi
else
  echo "OK: 連続失敗回数は 0（カウンタ未作成）"
fi

if [ "$failures" -ne 0 ]; then
  echo "NG: 監視の健全性検査に ${failures} 件の異常" >&2
  exit 1
fi
echo "OK: 監視は生きている（${TIMER_UNIT} / 最終実行 ${MAX_AGE_SECONDS} 秒以内 / 連続失敗 0）"
