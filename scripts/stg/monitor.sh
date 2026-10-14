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

# 3. 記録。
{
  printf '%s rc=%d\n' "$(stamp)" "$rc"
  printf '%s\n' "$out" | sed 's/^/    /'
} >> "$LOG"
printf '%s\n' "$out"

if [ -f "$LOG" ] && [ "$(wc -l < "$LOG")" -gt "$MAX_LOG_LINES" ]; then
  tail -n "$MAX_LOG_LINES" "$LOG" > "${LOG}.tmp" && mv "${LOG}.tmp" "$LOG"
fi

if [ "$rc" -ne 0 ]; then
  echo "NG: stg の状態検査が失敗した（rc=${rc}）。ログ: ${LOG}" >&2
fi
exit "$rc"
