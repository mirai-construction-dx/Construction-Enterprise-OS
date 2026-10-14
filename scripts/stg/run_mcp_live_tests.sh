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

# `compose run` は対象サービスの environment とネットワークを引き継ぐ。
# ただし mcp のイメージには tests/ と requirements-dev.txt が入っていない
# （Dockerfile は requirements.txt と src/ だけを写す）ため、ホストのリポジトリを
# /repo へマウントして実行する。`/repo` にするのは、テストが
# `Path(__file__).resolve().parents[3]` でリポジトリ根を求めるためである
# （`/app/tests/...` に置くと parents[3] が存在せず IndexError: 3 になる。2026-10-14 実測）。
set +e
"$REPO_ROOT/scripts/stg/compose.sh" run --rm --no-deps \
  -v "$REPO_ROOT:/repo" -w /repo/services/mcp \
  --entrypoint sh mcp -c '
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
