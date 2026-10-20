# 第33バッチ — 開発ステップ 10 件（組織境界・内部API遮断・監視 watchdog・ADR）（2026-10-21）

- 対象: Construction-Enterprise-OS（CEOS）
- 統合 PR: #224（`auto/ceos-b33-integration` / squash `cd7d438`）
- 方針: Required Checks 通過後に squash merge。`--admin` 迂回・force push なし。

## 1. 10 ステップの結果

| # | Issue | 内容 | 結果 |
|---|---|---|---|
| 1 | #132 | iot の heartbeat / ingest 組織照合を実測確認（PR #153 で実装済み） | **クローズ**・回帰 22 passed |
| 2 | #122 | erp `PUT /invoices/{id}` から `status` を除外 | **クローズ**（統合 PR） |
| 3 | #139 | maintenance の作成者を token `sub` から設定、status 遷移を検証 | **クローズ**（統合 PR） |
| 4 | #139 | analytics の `created_by` を `sub` から設定、pipeline status を `/run` に限定 | **クローズ**（統合 PR） |
| 5 | #103 | gateway で `/api/v1/workflow/internal*` を 404 遮断 | **クローズ**（統合 PR） |
| 6 | #149 | autonomous の cascade 削除で他組織の子を巻き込まない（409 拒否） | **クローズ**（統合 PR） |
| 7 | #151 | ADR-0006（proposed）外部 ID の組織照合を段階的に行う | 提案を追加（Issue は継続） |
| 8 | #154 | ADR-0007（proposed）iot デバイス個体認証 | 提案を追加（Issue は継続） |
| 9 | — | 監視の死活 watchdog（script + systemd timer）を追加・設置 | 完了 |
| 10 | — | 統合 CI・stg 再検証 | 本記録 |

## 2. 検証（実測）

| 対象 | 結果 |
|---|---|
| erp | **126 passed**（修正前 1 failed）、ruff / mypy clean |
| maintenance | **118 passed**（修正前 7 failed）、ruff / mypy clean |
| analytics | **107 passed**（修正前 4 failed）、ruff / mypy clean |
| gateway | **107 passed**、mypy 12 files Success |
| autonomous | **416 passed**、mypy 27 files Success |
| 統制 | `make repo-invariants-ci` exit 0 / docs-links OK / `git diff --check` 0 |
| stg 越境子検査（読み取りのみ） | `tasks_agents=0` / `tasks_twins=0` / `simulations_twins=0` |
| watchdog | 設置＋`enable --now`、初回 `Result=success` / `ExecMainStatus=0`、次回 08:08 |
| stg 再ビルド | 変更 5 サービス（erp / maintenance / analytics / gateway / autonomous）を再作成 |
| **stg の gateway 遮断** | `/api/v1/workflow/internal/{jobs/deadline-notifications,jobs/workload-notifications,notification-callback}` → **404**、`/api/v1/workflow/internals` → 401（近接パスは巻き込まない） |
| stg の健全性 | 32 コンテナ / smoke 12 PASS 0 FAIL / 22 schemas 98 tables / pgBackRest ok |
| stg API E2E | **16 passed** |

## 3. 設計上の決定（ADR・提案）

- **ADR-0006（proposed）**: 外部 ID（`project_id` 等）の組織照合。13 サービスが `project_id` を受ける
  実測を根拠に、参照整合性が権限判断に効く ID から同期照合（fail-closed）する段階案。
- **ADR-0007（proposed）**: iot のデバイス個体認証。per-device secret + 短命 device JWT を推奨し、
  mTLS は将来の選択肢。#132 の組織照合は実装済みという前提を明記。
- いずれも **採択されていない**。実装 Issue への分割は採択後。

## 4. 残課題・未確認

| 項目 | 状態 |
|---|---|
| maintenance の状態遷移表 | 正式仕様が無く暫定（コードに明記）。ドメイン確認が必要 |
| maintenance PUT の `performed_by` | notes のみの更新でも更新者で上書き。仕様意図の確認が必要 |
| analytics pipeline の完了遷移 | running→completed 等は範囲外 |
| identity フィールド削除の旧クライアント影響 | 未実測（Pydantic の extra=ignore で黙って無視） |
| ADR-0006 / 0007 | proposed。採択・実装 Issue 分割はオーナー判断 |
| #209 / #222 | オーナー操作待ち（DNS/Pages、CI の pytest 固定） |

## 5. 参照

- 統合 PR: https://github.com/mirai-construction-dx/Construction-Enterprise-OS/pull/224
- ADR-0006: `docs/architecture/ADR-0006-external-id-organization-verification.md`
- ADR-0007: `docs/architecture/ADR-0007-iot-device-credential.md`
- 監視: `docs/operations/staging.md` §6.17 / `scripts/stg/check_monitoring_health.sh`
- 第32バッチ: `reports/quality-tests/defect-fixes-20261021.md`
