# CEOS 品質テスト憲章（Lead 所有・全 teammate 必読）

対象: `/home/kensan/Projects/Mirai-Construction-DX/Construction-Enterprise-OS`
目的: 建設土木向け主要業務フローに対する、仕様準拠の品質テストの整備・実行・証跡化。

## 1. 横断制約（全 Agent 必須）

1. **実装変更は対象 Repository 内のみ**。`git add` / `git commit` / `git checkout` / `git stash` /
   branch 操作は**禁止**（Lead のみが最終差分を確認する）。
2. **本番・個人・顧客・現場の実データを使わない**。synthetic / 匿名化 fixture のみ。
   UUID は `00000000-0000-0000-0000-0000000000aa` 形式、氏名は `テスト太郎` 等を使う。
3. **外部 Provider / MCP / 本番 DB / 実サービス / deploy へ接続しない**。
   ネットワーク呼び出しを行うコードは mock で遮断する。
4. **既存テストを壊さない**。既存テストの緩和・skip 追加・削除は禁止。
5. **業務判定ロジックや承認条件を緩めて合格させない**。テストを通すために仕様を曲げない。
6. 並列実行時は `-p no:cacheprovider` を付け、`.pytest_cache` 競合を避ける。
7. 生成物は担当の write scope 配下のみ。他担当のディレクトリへ書かない。

## 2. 利用可能なテスト基盤

- Python 3.12 / pytest 8.3.3 / pytest-asyncio / httpx / asyncpg 0.31（`~/.local` に導入済み）
- 各サービスは `src/main.py` の `create_app()` + `TestClient` + `dependency_overrides` 方式。
  既存の `tests/conftest.py`, `tests/test_*.py` を踏襲すること。
- **実 PostgreSQL（Lead が起動済み・テスト専用エフェメラル）**
  `postgresql+asyncpg://ceos_qa:ceos_qa_local_only@127.0.0.1:55432/ceos_qa`
  スキーマはサービス単位で分離（construction / erp / document / workflow / gis / bim / field）。
  実 DB を使う場合は自分のスキーマのみを DROP/CREATE し、他スキーマに触れないこと。
- DB を使わない mock/文脈テストを主とし、実 DB は Lead が統合検証で使う。

## 3. 品質観点（重点確認）

| ID | 観点 | 確認内容 |
|---|---|---|
| Q1 | 権限境界 | 未認証 401/403、ロール不足 403、他テナント 404/403 |
| Q2 | データ分離 | `organization_id` がトークン由来か。クエリ/ボディ由来なら欠陥 |
| Q3 | 計算再現性 | 数量×単価、丸め、合計、0/None/境界、決定性（同入力→同出力） |
| Q4 | 単位・座標系 | 単位表記、測地系/座標参照、緯度経度範囲、精度 |
| Q5 | 版・由来 | 文書/図面/BIM の版番号、更新履歴、改ざん検知 |
| Q6 | 承認・証跡 | 承認者の同定（トークン由来か）、状態遷移、履歴、再実行/重複 |
| Q7 | AI 入力境界 | 機密区分、masking、引用根拠、人間確認の強制 |
| Q8 | 異常・復旧 | 境界値、重複、途中失敗、ロールバック、エラー表示 |

## 4. 完了条件（担当分）

- 担当フローの主要シナリオについて **実行可能な pytest** が追加されていること。
- `python3 -m pytest tests/ -q -p no:cacheprovider` の**実出力**（pass/fail/skip 件数）を証跡に貼ること。
- 発見した欠陥は「症状 / 再現手順 / 根拠（ファイル:行）/ 重大度 / 影響」を明記。
- 未実行・skip・未確認を**成功と書かない**。
- 成果物レポート: `reports/quality-tests/<担当名>.md`（自分のファイルのみ書く）。

## 5. 重大度定義

- **Critical**: テナント越境の読み書き、認証回避、承認の偽装・否認不能。
- **High**: 権限昇格、証跡欠落、計算結果の誤り、データ破壊。
- **Medium**: 境界値の誤り、エラー表示不備、再現性の欠如。
- **Low**: 表記・UX・軽微な不整合。
- **Info**: 仕様が確認できず判定不能（未確認として報告）。
