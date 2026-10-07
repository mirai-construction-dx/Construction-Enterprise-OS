#!/usr/bin/env bash
# CEOS 品質テスト ポータブルランナー
#
# Claude Code / Codex / OpenCode など、任意のエージェントハーネスから同じコマンドで
# 実行できるようにするための薄いラッパー。ハーネス固有機能に依存しない。
#
# 使い方:
#   scripts/quality/run_quality_tests.sh                   # 対象サービスの pytest + 統合検証
#   scripts/quality/run_quality_tests.sh --unit            # pytest のみ
#   scripts/quality/run_quality_tests.sh --integration     # 実 PostgreSQL 統合検証のみ
#   scripts/quality/run_quality_tests.sh --strict          # 未修正欠陥(xfail)が 1 件でもあれば非 0
#   scripts/quality/run_quality_tests.sh --allow-skip      # 統合検証の SKIP を許容（既定は非 0）
#
# 実 PostgreSQL 統合検証はテスト専用の使い捨てコンテナを必要とする:
#   CEOS_TEST_DATABASE_URL=postgresql://...@127.0.0.1:55432/ceos_qa
# 未起動の場合、統合検証は SKIP として明示的に報告し、既定では非 0 終了する
# （未実行を成功として扱わない）。
#
# 注意: pytest の xfail は「未修正の欠陥の証跡」であり成功ではない。
#       本ランナーは xfail を PASS と表示せず DEFECT として計上する。

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

# 品質テスト対象（建設土木の主要業務フローに対応するサービス）
UNIT_SERVICES=(
  "services/construction"   # 施工管理: WBS / 工程 / 資源 / 数量・原価 / 施工計画書承認
  "services/erp"            # 原価管理: 工事台帳 / 原価明細 / 承認 / 請求
  "services/document"       # 文書・図面管理: 版管理 / 保管 / 内部API
  "services/workflow"       # 承認ワークフロー: 起票 / 提出 / 承認 / 却下 / 履歴
  "services/field-dx"       # 現場DX: 出来形 / 品質 / 写真 / レポート
  "services/gis"            # GIS: 空間検索 / 座標系
  "services/bim"            # BIM/CIM: モデル / 要素 / 点群
  "services/ai"             # AI 入力境界: テンプレート / 埋め込み / マスキング
  "services/vision"         # 画像AI/OCR: テナント境界
  "services/safety"         # 安全管理: 危険予知 / 安全巡視 / 事故
  "services/partner"        # 協力会社・契約: 締結 / 配置 / 評価
  "services/iot"            # 現場計測・監視: デバイス / テレメトリ / アラート
  "services/maintenance"    # 維持管理: 点検 / 災害
  "services/security"       # セキュリティ統制: 事象 / 脆弱性 / ポリシー
  "services/notification"   # 通知: 配信 / テンプレート / Webhook
)

INTEGRATION_SERVICES=("construction" "erp" "workflow")

RUN_UNIT=1
RUN_INTEGRATION=1
STRICT=0
ALLOW_SKIP=0
for arg in "$@"; do
  case "${arg}" in
    --unit) RUN_INTEGRATION=0 ;;
    --integration) RUN_UNIT=0 ;;
    --strict) STRICT=1 ;;
    --allow-skip) ALLOW_SKIP=1 ;;
    *) echo "unknown option: ${arg}" >&2; exit 2 ;;
  esac
done

PYTEST_FLAGS=(-q -p no:cacheprovider --no-header)
FAILED=0
DEFECT_TOTAL=0
SKIP_TOTAL=0
SUMMARY=()
OUT="$(mktemp)"
trap 'rm -f "${OUT}"' EXIT

# pytest の出力から failed / xfailed / passed を抽出して判定する
evaluate() {
  local label="$1" rc="$2"
  local tail_line failed_n xfailed_n passed_n
  tail_line="$(grep -E '[0-9]+ (passed|failed|error|xfailed)' "${OUT}" | tail -1)"
  failed_n="$(grep -oE '[0-9]+ failed' <<<"${tail_line}" | grep -oE '[0-9]+' | head -1)"
  xfailed_n="$(grep -oE '[0-9]+ xfailed' <<<"${tail_line}" | grep -oE '[0-9]+' | head -1)"
  passed_n="$(grep -oE '[0-9]+ passed' <<<"${tail_line}" | grep -oE '[0-9]+' | head -1)"
  failed_n="${failed_n:-0}"; xfailed_n="${xfailed_n:-0}"; passed_n="${passed_n:-0}"

  if [[ ${rc} -ne 0 || ${failed_n} -ne 0 ]]; then
    SUMMARY+=("FAIL   ${label} (failed=${failed_n} passed=${passed_n} 未修正欠陥の証跡=${xfailed_n})")
    FAILED=1
    return
  fi
  if [[ ${xfailed_n} -ne 0 ]]; then
    DEFECT_TOTAL=$((DEFECT_TOTAL + xfailed_n))
    SUMMARY+=("DEFECT ${label} (passed=${passed_n} / 未修正欠陥の証跡=${xfailed_n} — 成功ではない)")
    [[ ${STRICT} -eq 1 ]] && FAILED=1
    return
  fi
  SUMMARY+=("PASS   ${label} (passed=${passed_n})")
}

if [[ "${RUN_UNIT}" == "1" ]]; then
  for svc in "${UNIT_SERVICES[@]}"; do
    if [[ ! -d "${REPO_ROOT}/${svc}/tests" ]]; then
      SUMMARY+=("SKIP   ${svc} (tests ディレクトリなし)")
      SKIP_TOTAL=$((SKIP_TOTAL + 1))
      continue
    fi
    echo "===== pytest: ${svc} ====="
    ( cd "${REPO_ROOT}/${svc}" && python3 -m pytest tests/ "${PYTEST_FLAGS[@]}" ) > "${OUT}" 2>&1
    rc=$?
    tail -12 "${OUT}"
    evaluate "${svc}" "${rc}"
  done
fi

if [[ "${RUN_INTEGRATION}" == "1" ]]; then
  DB_URL="${CEOS_TEST_DATABASE_URL:-postgresql://ceos_qa:ceos_qa_local_only@127.0.0.1:55432/ceos_qa}"
  # 資格情報を出力しないため host:port のみ表示する
  DB_HOSTPORT="$(python3 - "$DB_URL" <<'PY'
import sys
from urllib.parse import urlparse
u = urlparse(sys.argv[1])
print(f"{(u.hostname or '127.0.0.1')}:{u.port or 5432}")
PY
)"
  echo "===== integration (real PostgreSQL): ${DB_HOSTPORT} ====="
  if python3 - "$DB_URL" <<'PY'
import sys, socket
from urllib.parse import urlparse
u = urlparse(sys.argv[1])
host = u.hostname or "127.0.0.1"
port = u.port or 5432
s = socket.socket(); s.settimeout(2)
try:
    s.connect((host, port))
except OSError:
    sys.exit(1)
finally:
    s.close()
PY
  then
    for svc in "${INTEGRATION_SERVICES[@]}"; do
      target="${REPO_ROOT}/scripts/quality/integration/${svc}"
      [[ -d "${target}" ]] || { SUMMARY+=("SKIP   integration/${svc} (未整備)"); continue; }
      echo "----- integration: ${svc} -----"
      ( cd "${REPO_ROOT}" && \
        PYTHONPATH="${REPO_ROOT}/services/${svc}:${REPO_ROOT}/scripts/quality/integration" \
        CEOS_TEST_DATABASE_URL="${DB_URL}" \
        python3 -m pytest "scripts/quality/integration/${svc}" "${PYTEST_FLAGS[@]}" ) > "${OUT}" 2>&1
      rc=$?
      tail -12 "${OUT}"
      evaluate "integration/${svc}" "${rc}"
    done
  else
    SUMMARY+=("SKIP   integration (テスト用 PostgreSQL ${DB_HOSTPORT} 未起動 — 未実行であり成功ではない)")
    echo "!! integration SKIP: テスト用 PostgreSQL が起動していません（成功とは扱いません）"
    SKIP_TOTAL=$((SKIP_TOTAL + 1))
    [[ ${ALLOW_SKIP} -eq 0 ]] && FAILED=1
  fi
fi

echo
echo "===== サマリ ====="
for line in "${SUMMARY[@]}"; do echo "${line}"; done
echo "未修正欠陥の証跡(xfail 合計) = ${DEFECT_TOTAL} / 未実行(SKIP) = ${SKIP_TOTAL}"
if [[ ${FAILED} -ne 0 ]]; then
  echo "判定: FAIL（失敗または未実行あり。xfail は欠陥の証跡であり成功ではない）"
elif [[ ${SKIP_TOTAL} -ne 0 && ${DEFECT_TOTAL} -eq 0 ]]; then
  echo "判定: 部分実行（SKIP ${SKIP_TOTAL} 件あり。--allow-skip 指定のため終了コードは 0）"
elif [[ ${DEFECT_TOTAL} -ne 0 ]]; then
  echo "判定: 実行は完了したが未修正欠陥 xfail=${DEFECT_TOTAL} 件が残存（成功ではない）"
else
  echo "判定: すべて pass、未修正欠陥なし"
fi
exit ${FAILED}
