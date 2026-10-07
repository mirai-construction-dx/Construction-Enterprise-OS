# AGENTS.md — Construction-Enterprise-OS

このリポジトリで作業する AI エージェント（Claude Code / Codex / OpenCode / DeepSeek Harness 等）向けの
共通指示です。ハーネス固有機能には依存しません。日本語で対応し、コード内コメントは英語可とします。

## 1. リポジトリ構成

| パス | 内容 |
|---|---|
| `services/<name>/` | FastAPI マイクロサービス（`src/`, `tests/`, `migrations/000_base_schema.sql`） |
| `apps/web`, `apps/mobile` | Next.js / モバイル |
| `packages/` | 共有パッケージ（`auth-core`, `core`, `event-core`, `logging`, `ui`） |
| `contracts/` | MCP ツール定義・Harness-Core 固定参照 |
| `docs/` | 要件・アーキテクチャ・API・運用手順 |
| `scripts/` | 運用・検証スクリプト（`scripts/quality/` は品質テスト） |
| `reports/quality-tests/` | 品質テストの証跡・欠陥報告（Git 管理外） |

## 2. 主要コマンド

```bash
# 単一サービスのテスト（CI と同一）
cd services/<name> && python3 -m pytest tests/ -v -p no:cacheprovider
cd services/<name> && ruff check . && mypy src/

# 業務フロー横断の品質テスト（ポータブルランナー）
scripts/quality/run_quality_tests.sh              # 単体 + 統合
scripts/quality/run_quality_tests.sh --unit       # 単体のみ
scripts/quality/run_quality_tests.sh --integration # 実 PostgreSQL 統合のみ

# モデルとマイグレーション DDL の乖離検出（CI で必須）
python3 scripts/db/generate_base_schema.py --check <service>

# サービス横断の不変条件（matrix では検出できない「気付かず緑」を防ぐ）
make repo-invariants    # = schema-check（対象漏れ検出） + session-check（セッション確定）
python3 scripts/db/check_session_lifecycle.py   # get_db の commit 欠落＝書込み消失を検出
```

## 3. 建設土木の主要業務フローと対応サービス

| 業務フロー | サービス | 主な観点 |
|---|---|---|
| 案件・工事・施工管理（WBS/工程/資源/数量/原価） | `construction` | 工程計算、数量×単価、資源配分 |
| 原価管理（台帳/原価/請求/予算） | `erp` | 金額丸め、承認、集計 |
| 文書・図面管理（版管理/保管） | `document` | 版の単調増加、改ざん検知、署名URL |
| 承認ワークフロー（稟議/承認/証跡） | `workflow` | 状態遷移、二重承認防止、監査ログ |
| 現場DX（出来形/品質/写真/指示） | `field-dx` | 出来形数量、品質閾値、写真メタデータ |
| GIS（位置/空間検索） | `gis` | 緯度経度範囲、座標参照系、単位 |
| BIM/CIM（モデル/要素/点群） | `bim` | モデル版、要素ツリー整合、点群座標系 |
| AI・分析基盤（RAG/埋め込み/OCR） | `ai`, `vision` | 入力境界、マスキング、引用根拠 |
| 認証・認可・監査 | `auth` | ロール/パーミッション、組織分離 |

## 4. 必須の制約

1. **テナント分離**: 組織（`organization_id`）は必ず JWT の `org` クレーム由来とする。
   クエリパラメータやリクエストボディの `organization_id` を信頼してはならない。
2. **実行者・承認者**: `approved_by` 等は認証済みユーザー（`sub`）から導出する。ボディから受け取らない。
3. **AI の位置づけ**: AI は候補提示・説明・異常候補の指摘まで。構造安全、測量確定、設計適合、
   数量・原価承認などの最終判断をさせない。人の確認を通らない確定処理を合格としない。
4. **データ保護**: テストは synthetic / 匿名化 fixture のみ。本番・個人・顧客・現場の実データを使わない。
5. **外部接続禁止**: 本番 DB、実サービス、外部 Provider、MCP、deploy へ接続しない。
   テストでは外部呼び出しを mock で遮断する。
6. **規格の扱い**: 法令・規格・契約条件を資料なしに創作しない。参照規格の名称・版・適用範囲が
   確認できない場合は「未確認」と明記する。
7. **不合格の扱い**: 未実行・skip・未確認を成功と書かない。テストを通すために業務判定ロジックや
   承認条件を緩めない。
8. **Git 操作**: エージェントは `git add/commit/checkout/stash` を行わない。差分確認とコミットは人間が行う。

## 5. 品質テストのドキュメント

- 憲章: `reports/quality-tests/CHARTER.md`
- 欠陥・証跡: `reports/quality-tests/*.md`
- ポータブルランナー: `scripts/quality/run_quality_tests.sh`
