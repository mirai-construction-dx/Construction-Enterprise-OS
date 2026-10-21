# 第34バッチ — stg 実 API 検証・identity 偽装の残り・依存更新（2026-10-21）

- 対象: Construction-Enterprise-OS（CEOS）
- 起点: `main` = `3297872`（第33バッチ後）
- 方針: Required Checks 通過後に squash merge。`--admin` 迂回・force push なし。

## 1. 10 ステップの結果

| # | 内容 | PR | 結果 |
|---|---|---|---|
| 1 | 第33バッチ修正を stg の実 API で検証するスクリプトを追加 | #226 | **merged** |
| 2 | リクエスト本文の identity フィールドを全サービスで監査 | — | 7 スキーマを検出 |
| 3 | autonomous simulation の `created_by` をトークン `sub` に固定 | #227 | **merged** |
| 4 | construction method の `created_by` をトークン `sub` に固定 | #227 | **merged** |
| 5 | erp 原価作成・承認の identity フィールドをスキーマから削除 | #227 | **merged** |
| 6 | safety 危険・事故作成の `reported_by` をスキーマから削除 | #227 | **merged** |
| 7 | Dependabot: actions/upload-artifact 7.0.1 → 7.0.2 | #203 | **merged** |
| 8 | Dependabot: actions/setup-node 7.0.0 → 7.1.0 | #204 | **merged** |
| 9 | 変更 4 サービス（autonomous / construction / erp / safety）を stg へ再ビルド | — | 完了 |
| 10 | stg の再検証（status / smoke / API E2E / security E2E） | — | 全 PASS |

## 2. 検証（実測）

| 対象 | 結果 |
|---|---|
| autonomous | **417 passed** |
| construction | **225 passed** |
| erp | **126 passed** |
| safety | **82 passed** |
| `git diff --check` | 0 |
| stg 稼働 | 32 コンテナ / smoke **12 PASS 0 FAIL** / 22 schemas 98 tables |
| stg API E2E | **16 passed** |
| stg security E2E（`check_security_fixes.py`） | **G-1 / D-1 / A-1 / M-1 すべて PASS** |
| stg の gateway 内部API遮断 | `/api/v1/workflow/internal/*` 3 パス **404** / 近接パス 401 |
| 監視 | status timer 5 分 / watchdog 15 分、いずれも active |

## 3. identity 監査の結果

リクエストスキーマが identity フィールドを受け取っていたのは 7 件。

| サービス | スキーマ | 対応 |
|---|---|---|
| autonomous | `SimulationCreateRequest.created_by` | API でトークン `sub` を設定（**従来は本文値を保存**） |
| construction | `MethodCreateRequest.created_by` | API で `_actor_id(user)` を設定（**従来は本文値を保存**） |
| construction | `MethodApprovalRequest.approved_by` | 既に無視。後方互換のため受理のみ残す |
| erp | `CostCreateRequest.created_by` | スキーマから削除（API は既に `sub` を使用） |
| erp | `CostApproveRequest.approved_by` | スキーマから削除（API は既に `sub` を使用） |
| safety | `HazardCreate.reported_by` | スキーマから削除（API は既に `sub` を使用） |
| safety | `IncidentCreate.reported_by` | スキーマから削除（API は既に `sub` を使用） |

回帰テストとして、本文に偽の `created_by` を送っても保存されるのはトークンの `sub` であることを固定した。

## 4. 残課題・未確認

| 項目 | 状態 |
|---|---|
| #209 stg 公開入口 | DNS Write / Pages 権限が無く未開通（オーナー操作） |
| #222 CI の pytest 8.3.3 固定 | `.github/workflows/**` は AI 書込不可（オーナー操作） |
| ADR-0006 / 0007 | **proposed**。採択・実装 Issue 分割はオーナー判断 |
| 監視の外部通知 | webhook 未設定。watchdog は監視の死活のみ検査 |
| maintenance の状態遷移 | 正式仕様が無く暫定（第33バッチの残課題） |
| `MethodApprovalRequest.approved_by` | 後方互換のため受理のみ（削除はクライアント移行後） |

## 5. 参照

- PR #226: 第33バッチ修正の stg 実 API 検証
- PR #227: identity 偽装の残り
- PR #203 / #204: Dependabot（actions）
- 第33バッチ: `reports/quality-tests/defect-fixes-batch33-20261021.md`
- 監視: `docs/operations/staging.md` §6.17〜§6.18
