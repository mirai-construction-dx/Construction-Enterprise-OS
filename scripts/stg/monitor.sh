#!/usr/bin/env bash
# stg の健全性を定期検査する（systemd timer `ceos-stg-status.timer` から呼ばれる）。
#
# なぜ必要か（2026-10-14 の実測）:
#   `scripts/stg/status.sh` は「クラスタ / db-bridge / コンテナ / スモーク / DB の中身 /
#   pgBackRest」を 1 コマンドで要約し、異常時は非ゼロ終了する。文書には
#   「cron・systemd timer から呼べる」と書いてあるが、**timer は 1 つも無かった**
#   （`systemctl list-timers --all | grep -i ceos` → 0 件）。
#   検査は**誰かが叩いたときだけ**走っており、stg は常時監視されていなかった。
#
# 何をするか:
#   1. stg スタック（`ceos-stg.service`）が動いていなければ**検査を省略**して 0 で終わる。
#      「止まっていること」は `ceos-stg.service` の状態で見える。ここで失敗を積むと
#      停止が常態のときに失敗が常態化し、本当の異常が埋もれる。
#      （スタックを自動起動するかは Mirai-Platform-Infra の未決 B-2 と同時に決める。
#        `ceos-stg.service` は enable していない。）
#   2. 動いていれば `scripts/stg/status.sh` を実行し、**その終了コードをそのまま返す**。
#      異常を握りつぶさない（systemd が failed として記録する = 黙って緑にしない）。
#   3. 実行のたびに日時と要約を `~/.local/state/ceos-stg/status.log` へ追記する
#      （journald だけでは「いつから異常か」を追いにくいため）。
#   4. **連続失敗回数**を数え（`~/.local/state/ceos-stg/consecutive_failures`）、
#      通知先 `CEOS_STG_ALERT_WEBHOOK`（任意の環境変数）があれば POST する。
#      初回とその後 1 時間ごとだけ送る（5 分ごとに同じ警報を並べない）。
#      未設定なら**何もしないが、その事実をログに明示する**（「送ったつもり」を作らない）。
#      通知の成否で**検査結果（終了コード）を変えない**。
#
# なぜ通知が要るか（2026-10-14 実測）:
#   監視は 5 分ごとに回っていたが、失敗は journald と systemd の failed に残るだけで
#   **誰にも届かなかった**。基盤サービスが落ちても誰も起こさない問題（§6.10）と同根である。
#
# 通知の落とし穴（実測）:
#   `curl` の終了コードだけを見ると、**プロキシが 502 を返したときに成功と誤認する**
#   （本環境のプロキシは到達不能な宛先へ 502 を返し、そのとき curl は 0 で終わる）。
#   そのため HTTP ステータスまで見て 2xx のときだけ「送信した」と記録する。
#
# 使い方:
#   scripts/stg/monitor.sh            # 手動実行（同じ判定）
#   systemctl list-timers ceos-stg-status
#   journalctl -u ceos-stg-status -n 50
#   tail -40 ~/.local/state/ceos-stg/status.log
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
STATE_DIR="${CEOS_STG_STATE_DIR:-${HOME}/.local/state/ceos-stg}"
LOG="${STATE_DIR}/status.log"
UNIT="${CEOS_STG_UNIT:-ceos-stg}"
# ログの上限（超えたら直近だけ残す）。検査は 5 分ごとなので 1 日で約 288 行。
MAX_LOG_LINES=4000

mkdir -p "$STATE_DIR"

stamp() { date -Is; }

# 1. スタックが動いていないときは検査しない。
if ! systemctl is-active --quiet "$UNIT"; then
  printf '%s SKIP %s is not active（監視はスタック稼働時のみ）\n' "$(stamp)" "$UNIT" | tee -a "$LOG"
  exit 0
fi

# 2. 状態検査（終了コードをそのまま使う）。
out="$("${REPO_ROOT}/scripts/stg/status.sh" 2>&1)"
rc=$?

# 3. 連続失敗回数を数える（「たまたま 1 回」と「ずっと壊れている」を区別する）。
COUNTER="${STATE_DIR}/consecutive_failures"
consecutive=0
if [ "$rc" -ne 0 ]; then
  consecutive=$(cat "$COUNTER" 2>/dev/null || echo 0)
  case "$consecutive" in
    ''|*[!0-9]*) consecutive=0 ;;
  esac
  consecutive=$((consecutive + 1))
  printf '%s\n' "$consecutive" > "$COUNTER"
else
  : > "$COUNTER"
fi

# 4. 記録。
{
  printf '%s rc=%d consecutive_failures=%d\n' "$(stamp)" "$rc" "$consecutive"
  printf '%s\n' "$out" | sed 's/^/    /'
} >> "$LOG"
printf '%s\n' "$out"

if [ -f "$LOG" ] && [ "$(wc -l < "$LOG")" -gt "$MAX_LOG_LINES" ]; then
  tail -n "$MAX_LOG_LINES" "$LOG" > "${LOG}.tmp" && mv "${LOG}.tmp" "$LOG"
fi

# 5. 通知（best-effort。**通知の失敗で検査結果を変えない**）。
#
# なぜ必要か（2026-10-14 実測）:
#   監視は 5 分ごとに回っていたが、失敗は journald と systemd の failed に残るだけで
#   **誰にも届かなかった**。§6.10 の括り（基盤が落ちても誰も起こさない）と同根である。
#
# 設計:
#   - 送信先は環境変数 `CEOS_STG_ALERT_WEBHOOK`（任意）。資格情報ファイルは読まない。
#   - 未設定なら**何もしない**が、その事実をログと stderr に明示する
#     （「通知したつもり」を作らない）。
#   - 初回（consecutive=1）と、その後 1 時間ごと（5 分 × 12 = 60 分）に送る。
#     毎回送ると 5 分ごとに同じ警報が並び、本当の変化が埋もれる。
#   - `curl` の失敗・未導入でも exit code は rc のまま。
ALERT_INTERVAL=12
if [ "$rc" -ne 0 ]; then
  should_alert=0
  if [ "$consecutive" -eq 1 ] || [ $((consecutive % ALERT_INTERVAL)) -eq 0 ]; then
    should_alert=1
  fi
  if [ -n "${CEOS_STG_ALERT_WEBHOOK:-}" ]; then
    if [ "$should_alert" -eq 1 ]; then
      payload=$(printf '{"text":"[CEOS stg] 状態検査が失敗（rc=%d / 連続 %d 回）: %s"}' \
        "$rc" "$consecutive" "$(hostname)")
      # **HTTP ステータスまで見る。** curl の終了コードだけでは足りない:
      # 本環境のプロキシは到達不能な宛先へ 502 を返し、そのとき curl は 0 で終わる
      # （2026-10-14 実測）。終了コードだけを信じると「送ったつもり」になる。
      http_code=$(curl -sS -o /dev/null --max-time 10 -w '%{http_code}' -X POST \
        -H 'Content-Type: application/json' -d "$payload" \
        "$CEOS_STG_ALERT_WEBHOOK" 2>>"$LOG" || echo 000)
      case "$http_code" in
        2*)
          printf '%s ALERT 送信した（連続 %d 回 / http=%s）\n' \
            "$(stamp)" "$consecutive" "$http_code" >> "$LOG"
          ;;
        *)
          printf '%s ALERT 送信に失敗した（連続 %d 回 / http=%s）。検査結果は変えない\n' \
            "$(stamp)" "$consecutive" "$http_code" >> "$LOG"
          ;;
      esac
    fi
  else
    printf '%s ALERT 通知先が未設定（CEOS_STG_ALERT_WEBHOOK）。失敗は journald とこのログにのみ残る\n' \
      "$(stamp)" >> "$LOG"
  fi
  echo "NG: stg の状態検査が失敗した（rc=${rc} / 連続 ${consecutive} 回）。ログ: ${LOG}" >&2
fi
exit "$rc"
