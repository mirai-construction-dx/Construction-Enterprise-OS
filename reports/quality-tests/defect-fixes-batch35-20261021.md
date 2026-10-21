# 第35バッチ — actor フィールドの静的検査と制御指令の発行者（2026-10-21）

- 対象: Construction-Enterprise-OS（CEOS）
- 統合 PR: #229（`auto/ceos-b35-identity-guard`）
- 方針: Required Checks 通過後に squash merge。`--admin` 迂回・force push なし。

## 1. 10 ステップの結果

| # | 内容 | 結果 |
|---|---|---|
| 1 | リクエストモデルの actor フィールドを全サービスで再監査 | 9 種類を対象に 24 スキーマを走査 |
| 2 | autonomous 制御指令 `issued_by` の本文偽装を修正 | **merged 予定**（PR #229） |
| 3 | safety `IncidentUpdate.investigated_by` をスキーマから削除 | PR #229 |
| 4 | construction `MethodApprovalRequest.approved_by` を削除 | PR #229 |
| 5 | 静的検出器 `check_identity_fields.py` を追加 | PR #229 |
| 6 | 検出器の回帰テスト 5 件を追加 | PR #229 |
| 7 | `repo-invariants` / `repo-invariants-ci` へ配線 | Makefile |
| 8 | `ci-hardening.md` のターゲット数を 14/13 に更新 | 文書 |
| 9 | stg の autonomous を再ビルドして再検証 | 下記 §3 |
| 10 | 本記録 | — |

## 2. 検証（実測）

| 対象 | 結果 |
|---|---|
| autonomous | **417 passed**（`issued_by` がトークン `sub` になる断言を追加） |
| construction | **225 passed** |
| safety | **82 passed** |
| identity-fields 検出器 | **5 tests OK** / 24 スキーマ走査で違反 0 |
| `repo-invariants-ci` | **exit 0**（identity-fields を含む 13 ターゲット） |

## 3. 監査で分かったこと

- **実害のある偽装**: `autonomous` の `ControlSendRequest.issued_by` は本文の UUID を
  そのまま `AutonomousControl.issued_by` に保存していた。他者名義の制御指令を作れる。
  → スキーマから削除し、API がトークンの `sub` を設定するよう修正。
- `safety IncidentUpdate.investigated_by` / `construction MethodApprovalRequest.approved_by` は
  API 側で既にトークン `sub` を使っており、スキーマに残っていただけ。削除して契約を明確化。
- `inspector_id` / `operator_id` は**割当先**（管理者が他人を指定できる業務フィールド）であり、
  actor ではないため対象外とした。`detected_by`（security）は自由文字列の検知元であり対象外。
- 再発防止として、リクエストモデルが actor フィールドを持たないことを CI で検査する。

## 4. 残課題・未確認

| 項目 | 状態 |
|---|---|
| stg の autonomous 再ビルド | 本 PR マージ後に実施（制御指令の実 API 検証は未実施） |
| status 遷移の妥当性 | 別課題（maintenance の暫定遷移表など） |
| #209 / #222 | オーナー操作待ち（DNS/Pages、CI の pytest 固定） |
| ADR-0006 / 0007 | **proposed**。採択はオーナー判断 |
| 監視の外部通知 | webhook 未設定 |

## 5. 参照

- PR #229: 本バッチの実装
- `scripts/ci/check_identity_fields.py`（検出器）
- `reports/quality-tests/defect-fixes-batch34-20261021.md`（前バッチ）
