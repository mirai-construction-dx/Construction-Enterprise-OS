#!/usr/bin/env bash
# stg スタックを停止する。データ（名前付きボリューム）は保持する。
#
# 使い方:
#   scripts/stg/down.sh           # 停止（コンテナのみ削除、ボリュームは残す）
#   scripts/stg/down.sh --purge   # ボリュームも削除する（stg の状態を捨てる）
#
# 注意: ホスト PostgreSQL 18 の `ceos_stg` は削除しない。
#       DB を消す操作は不可逆であり Human Gate である（ADR-0005 §5 の対象外操作）。
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PURGE=0
for arg in "$@"; do
  case "$arg" in
    --purge) PURGE=1 ;;
    *)
      echo "unknown option: $arg" >&2
      exit 2
      ;;
  esac
done

# compose.sh 経由で実行する。compose ファイルは ${STG_...} を参照するため、
# 秘密ファイルを読み込まずに `docker compose down` を直接叩くと
# "required variable ... is missing a value" で失敗する（2026-10-14 実測）。
if [ "$PURGE" = "1" ]; then
  echo "警告: stg のボリュームを削除する。ホスト PostgreSQL の ceos_stg は残る。"
  "$REPO_ROOT/scripts/stg/compose.sh" down --volumes --remove-orphans
else
  "$REPO_ROOT/scripts/stg/compose.sh" down --remove-orphans
fi
echo "停止完了。"
