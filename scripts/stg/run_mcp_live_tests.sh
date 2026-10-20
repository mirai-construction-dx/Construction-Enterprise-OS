#!/usr/bin/env bash
# MCP の**上流結合テスト**を stg のネットワーク内で実行する。
#
# なぜ必要か:
#   `services/mcp/tests/test_upstream_live.py` は
#   「上流（construction / erp）へ TCP 到達できなければ skip」する作りである。
#   CI では上流が起動していないため**常に skip** され、
#   **ツールの上流パス束縛（どのツールがどの URL を叩くか）は検証されないまま**になる。
#   stg では上流が動いているので、ここで初めて実行できる。
#   「CI が skip するテストを stg が実行する」のは、検証環境を分離した目的そのものである。
#
# 何をするか:
#   1. `services/mcp` の開発依存（pytest 等）を一時コンテナへ入れる
#   2. `mcp` サービスと同じ環境変数・同じネットワークで live_upstream マークのテストを実行する
#
# 使い方:
#   scripts/stg/run_mcp_live_tests.sh
#
# 注意: 一時コンテナを作るだけで、稼働中のコンテナには触れない。
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

echo "== MCP 上流結合テスト（stg ネットワーク内） =="
echo "上流: CONSTRUCTION_SERVICE_URL / ERP_SERVICE_URL（compose の設定を使用）"

# `compose run` は使わない（2026-10-21 実測）:
#   stg は G-11 で全サービスに**静的 IPv4** を割り当てている。`compose run` は
#   対象サービスのネットワーク定義をそのまま複製するため、稼働中の `mcp`
#   コンテナと同じ IP を取ろうとして
#   `failed to set up container networking: Address already in use` で必ず失敗する。
#   代わりに `docker run` で同じイメージ・同じネットワーク・同じ環境変数を使い、
#   IP だけを Docker に任せる（静的 IP を持たない一時コンテナ）。
#
# mcp のイメージには tests/ と requirements-dev.txt が入っていない
# （Dockerfile は requirements.txt と src/ だけを写す）ため、ホストのリポジトリを
# /repo へマウントして実行する。`/repo` にするのは、テストが
# `Path(__file__).resolve().parents[3]` でリポジトリ根を求めるためである
# （`/app/tests/...` に置くと parents[3] が存在せず IndexError: 3 になる。2026-10-14 実測）。
CONTAINER="${CEOS_STG_MCP_CONTAINER:-ceos-stg-mcp}"
if ! docker inspect "$CONTAINER" >/dev/null 2>&1; then
  echo "NG: 稼働中の ${CONTAINER} が見つからない（先に stg を起動する）。" >&2
  exit 1
fi
IMAGE="$(docker inspect -f '{{.Config.Image}}' "$CONTAINER")"
NETWORK="$(docker inspect -f '{{range $k,$v := .NetworkSettings.Networks}}{{$k}}{{end}}' "$CONTAINER")"
if [ -z "$IMAGE" ] || [ -z "$NETWORK" ]; then
  echo "NG: ${CONTAINER} のイメージ/ネットワークを特定できない。" >&2
  exit 1
fi
echo "一時コンテナ: image=${IMAGE} network=${NETWORK}（静的 IP は使わない）"

set +e
# 環境変数は稼働コンテナから引き継ぐ。secret をファイルへ書き出さないため
# プロセス置換（/dev/fd）を `--env-file` に渡す。
docker run --rm --network "$NETWORK" \
  --env-file <(docker inspect -f '{{range .Config.Env}}{{println .}}{{end}}' "$CONTAINER") \
  -v "$REPO_ROOT:/repo" -w /repo/services/mcp \
  --entrypoint sh "$IMAGE" -c '
  set -e
  pip install -q -r requirements-dev.txt
  echo "--- pytest (live_upstream) ---"
  python -m pytest tests/test_upstream_live.py -v -m live_upstream --no-header -p no:cacheprovider
'
rc=$?
set -e

echo
if [ "$rc" != "0" ]; then
  echo "NG: 上流結合テストが失敗した（exit=${rc}）。" >&2
  echo "    ツールの上流パス束縛が実在のルートとずれている可能性がある。" >&2
  exit 1
fi
echo "OK: MCP のツールが stg の上流（construction / erp）へ実際に到達できる。"
