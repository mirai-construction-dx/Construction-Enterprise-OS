#!/usr/bin/env bash
# stg の API を Cloudflare Tunnel で公開するための**準備**（正本はリポジトリ側）。
#
# なぜ必要か（2026-10-14 実測）:
#   `docs/operations/staging.md` §6.4 はホスト名・トンネル名・転送先・設定ファイルの
#   パスまで決めていたが、**systemd unit も生成手順も無く、文章だけ**だった。
#   そして DNS（CNAME）が作れないためトンネルは未作成のままである。
#   DNS が解けた瞬間に有効化できるよう、**設定とunitの正本をリポジトリに置く**。
#
# 何をするか（`--apply` のとき）:
#   1. `~/.cloudflared/<name>-config.yml` を生成する（mode 0600。生成物。手で編集しない）
#   2. トンネルが無ければ `cloudflared tunnel create` する
#   3. systemd unit を `/etc/systemd/system/` へ設置する（enable はしない）
#   4. **DNS ルートのコマンドを表示する**（Zone→DNS→Edit 権限が必要。ここでは実行しない）
#
# 既定は `--dry-run`。**何も書き換えず**、生成される設定と実行するコマンドを表示する。
#
# 使い方:
#   scripts/stg/prepare_api_tunnel.sh              # 何をするかを見る（書き換えない）
#   scripts/stg/prepare_api_tunnel.sh --apply      # 実際に用意する
#   scripts/stg/prepare_api_tunnel.sh --apply --install-unit   # unit も設置する（sudo）
#
# 注意:
#   - 認証情報（credentials JSON）はリポジトリに置かない。`~/.cloudflared/` に留まる。
#   - 本番の `construction-os-api` トンネルとは**別トンネル**にする（入口を共有しない）。
#   - DNS ルートはこのスクリプトでは実行しない（権限が要る。§6.4/§6.0 を参照）。
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

# ---- 文書（§6.4）と一致していなければならない値 ----------------------------
# これらは scripts/stg/check_staging_guards.py の G-13 が
# docs/operations/staging.md §6.4 / staging-deploy.workflow.yml と突き合わせる。
TUNNEL_NAME="construction-os-stg-api"
PUBLIC_HOST="construction-os-stg-api.mirai-dx-platform.com"
TARGET="http://127.0.0.1:19500"
CONFIG="${HOME}/.cloudflared/${TUNNEL_NAME}-config.yml"
UNIT_NAME="construction-os-stg-api-cloudflared.service"
UNIT_SRC="${REPO_ROOT}/infra/systemd/${UNIT_NAME}"
UNIT_DST="/etc/systemd/system/${UNIT_NAME}"

APPLY=0
INSTALL_UNIT=0
for arg in "$@"; do
  case "$arg" in
    --apply) APPLY=1 ;;
    --install-unit) INSTALL_UNIT=1 ;;
    --dry-run) APPLY=0 ;;
    -h|--help) sed -n '2,30p' "$0"; exit 0 ;;
    *) echo "NG: 不明な引数: $arg" >&2; exit 2 ;;
  esac
done

render_config() {
  # credentials-file はトンネル ID に依存するため、作成後に埋める。
  cat <<EOF
# ${TUNNEL_NAME} — stg の gateway を Cloudflare Tunnel で公開する（生成物）
#
# 生成: scripts/stg/prepare_api_tunnel.sh
# 正本: docs/operations/staging.md §6.4（値を変えるときは文書と G-13 も更新する）
# 手で編集しないこと。
tunnel: ${TUNNEL_NAME}
credentials-file: ${HOME}/.cloudflared/${TUNNEL_ID}.json

ingress:
  # stg の公開ホスト → stg のゲートウェイ（127.0.0.1:19500。LAN へは出さない）
  - hostname: ${PUBLIC_HOST}
    service: ${TARGET}
  # 定義に無いホストは 404（本番へ流さない）
  - service: http_status:404
EOF
}

echo "== stg API Tunnel の準備 =="
echo "  トンネル名 : ${TUNNEL_NAME}"
echo "  公開ホスト : ${PUBLIC_HOST}"
echo "  転送先     : ${TARGET}（stg のゲートウェイ）"
echo "  設定ファイル: ${CONFIG}"
echo "  unit        : ${UNIT_DST}"
echo "  モード      : $([ "$APPLY" = "1" ] && echo "apply（書き換える）" || echo "dry-run（書き換えない）")"
echo

if ! command -v cloudflared >/dev/null 2>&1; then
  echo "NG: cloudflared が PATH に無い（ホストに導入すること）。" >&2
  exit 1
fi
if [ ! -f "$UNIT_SRC" ]; then
  echo "NG: unit の正本が無い: ${UNIT_SRC}" >&2
  exit 1
fi
echo "OK: cloudflared=$(cloudflared --version 2>/dev/null | head -1)"
echo "OK: unit の正本がある"

if [ "$APPLY" != "1" ]; then
  echo
  echo "---- 生成される設定（dry-run） ----"
  TUNNEL_ID="<TUNNEL_ID>"
  render_config
  echo "---- ここまで（--apply で実際に書く） ----"
  echo
  echo "apply のときに実行するコマンド:"
  echo "  1. cloudflared tunnel create ${TUNNEL_NAME}        # 無ければ"
  echo "  2. ${CONFIG} を mode 0600 で生成"
  echo "  3. sudo install -m 644 ${UNIT_SRC} ${UNIT_DST} && sudo systemctl daemon-reload"
  echo "  4. DNS ルート（別途。Zone→DNS→Edit 権限が必要）:"
  echo "     cloudflared tunnel route dns ${TUNNEL_NAME} ${PUBLIC_HOST}"
  exit 0
fi

# ---- --apply ----
echo
echo "-- 1. トンネルの存在確認 --"
if cloudflared tunnel list --output json 2>/dev/null | grep -q "\"name\": \"${TUNNEL_NAME}\""; then
  echo "OK: トンネル ${TUNNEL_NAME} は既にある"
else
  echo "  トンネル ${TUNNEL_NAME} を作成する"
  if ! cloudflared tunnel create "$TUNNEL_NAME"; then
    echo "NG: トンネルを作成できない（~/.cloudflared/cert.pem と権限を確認すること）。" >&2
    exit 1
  fi
fi

TUNNEL_ID="$(cloudflared tunnel list --output json 2>/dev/null |
  python3 -c "
import json, sys
name = sys.argv[1]
try:
    items = json.load(sys.stdin)
except Exception:
    raise SystemExit(1)
for item in items:
    if item.get('name') == name:
        print(item.get('id', ''))
        break
" "$TUNNEL_NAME")"

if [ -z "${TUNNEL_ID:-}" ]; then
  echo "NG: トンネル ID を取り出せない。" >&2
  exit 1
fi
echo "OK: tunnel id = ${TUNNEL_ID}"

echo
echo "-- 2. 設定を書く（mode 0600） --"
mkdir -p "$(dirname "$CONFIG")"
umask 077
render_config > "$CONFIG"
chmod 600 "$CONFIG"
echo "OK: ${CONFIG}"

if [ "$INSTALL_UNIT" = "1" ]; then
  echo
  echo "-- 3. unit を設置する --"
  sudo install -m 644 "$UNIT_SRC" "$UNIT_DST" && sudo systemctl daemon-reload && echo "OK: ${UNIT_DST}"
  echo "  （enable はしていない。§6.4 と B-2 の決定後に行う）"
else
  echo
  echo "-- 3. unit の設置はスキップ（--install-unit を付けると実行する） --"
fi

echo
echo "-- 4. 次にやること（このスクリプトでは実行しない） --"
echo "  DNS ルート（Zone→DNS→Edit 権限が必要）:"
echo "    cloudflared tunnel route dns ${TUNNEL_NAME} ${PUBLIC_HOST}"
echo "  unit の有効化:"
echo "    sudo systemctl enable --now ${UNIT_NAME}"
echo "  到達確認:"
echo "    curl -sS -o /dev/null -w '%{http_code}\\n' https://${PUBLIC_HOST}/health   # 302 なら Access 保護下"
