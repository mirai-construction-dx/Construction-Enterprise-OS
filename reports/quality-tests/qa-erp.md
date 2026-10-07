# [🧪 QA-ERP] services/erp 原価管理フロー 品質テスト報告

- 担当: qa-erp（task-2）
- 対象: `/home/kensan/Projects/Mirai-Construction-DX/Construction-Enterprise-OS/services/erp`
- フロー: 工事台帳 → 原価明細 → 承認 → 請求 → 支払
- 準拠: `reports/quality-tests/CHARTER.md`（synthetic のみ / 外部接続なし / git 操作なし / 既存テスト非破壊）
- **実装は変更していない（`services/erp/src/**` の差分ゼロ）。** 欠陥はすべて報告のみ。理由は §6。

---

## 1. 結論サマリ

| 区分 | 件数 |
|---|---|
| 既存テスト（変更なし・全 pass 維持） | 30 pass |
| 追加テスト（`test_quality_tenant_isolation.py`） | 17 pass / 15 xfail |
| 追加テスト（`test_quality_costing.py`） | 24 pass / 10 xfail |
| **全テスト合計** | **96 collected = 71 passed / 25 xfailed** |

`xfail(strict=True)` は「仕様どおりの期待」を assert しており、**現状失敗する＝欠陥が実在する**ことを示す。
25 xfail はすべて欠陥 ID（`DEFECT-D1`〜`D9`）と対応する。**xfail は pass ではない**（CI 上も成功扱いにしていない）。
逆に `*_current_behavior*` テストは「現状の脆弱な挙動」を固定して **pass** しており、欠陥の積極的証拠になっている。

発見した欠陥: **Critical 3 / High 3 / Medium 3**（+ 仕様どおり確認 8 項目）。

---

## 2. 実行環境とコマンド（実出力）

### 2.1 追加テストのみ

```console
$ cd services/erp
$ python3 -m pytest tests/test_quality_tenant_isolation.py tests/test_quality_costing.py -q -p no:cacheprovider -rxX
...
1 failed, 40 passed, 25 xfailed, 1 warning in 5.60s   # ← 初回（自作テスト1件のバグ。修正済み）
```
初回失敗は自作境界テストの期待値ミス（`contract=1` で `profit_margin=100.0`）であり、製品欠陥ではない。
`contract=0` に修正後は下記のとおり。

```console
$ python3 -m pytest tests/test_quality_tenant_isolation.py -q -p no:cacheprovider
17 passed, 15 xfailed, 1 warning in 2.82s

$ python3 -m pytest tests/test_quality_costing.py -q -p no:cacheprovider
24 passed, 10 xfailed, 1 warning in 7.49s
```

### 2.2 全体（憲章指定コマンド）

```console
$ cd services/erp
$ python3 -m pytest tests/ -q -p no:cacheprovider
.........................................x.x.xx...x.x.x.x..x..x...x.x.x. [ 75%]
x..x.x.x.x.x.x.x.x.x.x.x                                                 [100%]
=============================== warnings summary ===============================
../../../../../.local/lib/python3.12/site-packages/fastapi/testclient.py:1
  ... StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated ...
-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
71 passed, 25 xfailed, 1 warning in 5.54s
```

### 2.3 既存テストの非破壊確認（追加前と同じ 30 件）

```console
$ python3 -m pytest tests/test_erp.py tests/test_health_readiness.py tests/test_public_endpoint_authz.py -q -p no:cacheprovider
30 passed, 1 warning in 2.48s
```

### 2.4 xfail 明細（欠陥 ID 付き）

```console
$ python3 -m pytest tests/ -q -p no:cacheprovider -rxX
=========================== short test summary info ============================
XFAIL tests/test_quality_costing.py::TestD9BudgetAttribution::test_approve_rejects_budget_of_other_ledger - DEFECT-D9: 他台帳の予算へ実績が加算される（budget_id の整合検査なし）
XFAIL tests/test_quality_costing.py::TestD9BudgetAttribution::test_approve_rejects_budget_of_other_tenant - DEFECT-D9: 他テナントの予算へ実績が加算される（予算の org 検査なし）
XFAIL tests/test_quality_costing.py::TestH5MoneyPrecision::test_summary_estimated_profit_is_two_decimals - DEFECT-D5: 金額が float 経由で計算され 2 桁に収まらない（0.20 になるべき）
XFAIL tests/test_quality_costing.py::TestH5MoneyPrecision::test_summary_rates_are_rounded - DEFECT-D5: 利益率/予算消化率が丸められない（無限小数が返る）
XFAIL tests/test_quality_costing.py::TestH5MoneyPrecision::test_approve_accumulation_is_decimal_exact - DEFECT-D5: 承認時の実績加算が float 演算（0.30 になるべき）
XFAIL tests/test_quality_costing.py::TestH5MoneyPrecision::test_create_invoice_total_is_exact - DEFECT-D5: 請求 total_amount が float 加算（0.30 になるべき）
XFAIL tests/test_quality_costing.py::TestH5BoundaryValidation::test_update_cost_rejects_non_positive_amount - DEFECT-D5/異常系: 原価更新で負値が拒否されない（gt=0 制約が無い）
XFAIL tests/test_quality_costing.py::TestH5BoundaryValidation::test_update_ledger_rejects_non_positive_contract - DEFECT-D5/異常系: 請負金額の負値が拒否されない（gt=0 制約が無い）
XFAIL tests/test_quality_costing.py::TestH5BoundaryValidation::test_update_ledger_rejects_out_of_range_progress - DEFECT-D5/異常系: 進捗率の範囲(0..100)検査が無い
XFAIL tests/test_quality_costing.py::TestH6LedgerSummaryStub::test_summary_reflects_persisted_ledger_data - DEFECT-D6: /ledger/summary が実データを集計せず固定値を返す（仕様/画面は実データ前提）
XFAIL tests/test_quality_tenant_isolation.py::TestD1ListLedgerTenantScope::test_list_ledger_filters_by_token_org_when_query_omitted - DEFECT-D1: GET /ledger がクエリ省略時にトークン org で絞らない（全テナント返却）
XFAIL tests/test_quality_tenant_isolation.py::TestD1ListLedgerTenantScope::test_list_ledger_ignores_foreign_org_query - DEFECT-D1: クエリの organization_id を信頼している（トークン org を使うべき）
XFAIL tests/test_quality_tenant_isolation.py::TestD1ListLedgerTenantScope::test_list_invoices_filters_by_token_org - DEFECT-D1: GET /invoices がクエリ省略時にトークン org で絞らない
XFAIL tests/test_quality_tenant_isolation.py::TestD2LedgerTenantBoundary::test_get_ledger_other_tenant_should_be_404 - DEFECT-D2: GET /ledger/{id} にテナント境界が無い（404 になるべき）
XFAIL tests/test_quality_tenant_isolation.py::TestD2CostTenantBoundary::test_list_costs_other_tenant_should_be_404 - DEFECT-D2: GET /ledger/{id}/costs が他テナント台帳を 404 にしない
XFAIL tests/test_quality_tenant_isolation.py::TestD2CostTenantBoundary::test_create_cost_other_tenant_should_be_404 - DEFECT-D2: POST /ledger/{id}/costs が他テナント台帳へ原価を追加できる
XFAIL tests/test_quality_tenant_isolation.py::TestD2CostTenantBoundary::test_update_cost_other_tenant_should_be_404 - DEFECT-D2: PUT /costs/{id} が他テナント原価を改変できる
XFAIL tests/test_quality_tenant_isolation.py::TestD2CostTenantBoundary::test_delete_cost_other_tenant_should_be_404 - DEFECT-D2: DELETE /costs/{id} が他テナント原価を削除できる
XFAIL tests/test_quality_tenant_isolation.py::TestD2CostTenantBoundary::test_approve_cost_other_tenant_should_be_404 - DEFECT-D2: POST /costs/{id}/approve が他テナント原価を承認できる
XFAIL tests/test_quality_tenant_isolation.py::TestD2InvoiceTenantBoundary::test_invoice_cross_tenant_should_be_404 - DEFECT-D2: 請求書の GET/PUT/PAY にテナント境界が無い（404 になるべき）
XFAIL tests/test_quality_tenant_isolation.py::TestD3ApproverSpoofing::test_approve_should_use_token_subject - DEFECT-D3: approved_by がボディ由来でトークン主体(sub)と一致しない（承認者偽装）
XFAIL tests/test_quality_tenant_isolation.py::TestD4CreateTenantFromBody::test_create_ledger_should_force_token_org - DEFECT-D4: POST /ledger の organization_id がボディ由来（トークン org を使うべき）
XFAIL tests/test_quality_tenant_isolation.py::TestD4CreateTenantFromBody::test_create_cost_should_force_token_org - DEFECT-D4: POST /ledger/{id}/costs の organization_id がボディ由来
XFAIL tests/test_quality_tenant_isolation.py::TestD7NoRbacOnFinancialWrites::test_approve_requires_finance_role - DEFECT-D7: 財務書込にロール/スコープ検証が無い（roles=[] でも承認できる）
XFAIL tests/test_quality_tenant_isolation.py::TestD9BudgetLedgerConsistency::test_create_cost_rejects_budget_of_other_ledger - DEFECT-D9: 他台帳の budget_id を指定した原価作成が拒否されない
25 xfailed
```

> **未実行/skip は無い。** xfail は「欠陥が存在するため失敗するテスト」であり、成功として集計していない。

---

## 3. テスト実装（追加ファイル）

| ファイル | pass | xfail | 主な観点 |
|---|---|---|---|
| `services/erp/tests/_quality_support.py` | – | – | 共通サポート（`CaptureDB` / synthetic fixture / WHERE 句 compile）。テストとしては収集されない |
| `services/erp/tests/test_quality_tenant_isolation.py` | 17 | 15 | Q1 権限境界 / Q2 テナント分離 / Q6 承認主体 / Q8 整合 |
| `services/erp/tests/test_quality_costing.py` | 24 | 10 | Q3 計算再現性・丸め / Q6 承認・証跡 / Q8 境界値・整合 |

方式（既存 `tests/test_erp.py` / `conftest.py` を踏襲）:
- `create_app()` + `TestClient` + `dependency_overrides`（`get_db` / `get_current_user`）。
- DB 不要。`db.execute` に渡された文を `CaptureDB` が捕捉し、**WHERE 句のみ**を
  `postgresql.dialect()` + `literal_binds=True` で compile して `organization_id` 条件の有無を検査。
  （SELECT 句の列一覧に `organization_id` が現れるため、文全体の部分一致では誤検知する。WHERE 限定で判定している。）
- fixture はすべて合成。UUID は `...00aa` / `...00bb`、名称は「テスト工事A」等。実データ・実在企業名なし。

テストクラス一覧:

**test_quality_tenant_isolation.py**
| クラス | 内容 |
|---|---|
| `TestAuthRequiredControl` | 未認証 401（positive control） |
| `TestD1ListLedgerTenantScope` | `GET /ledger`・`GET /invoices` の org フィルタ（省略時 / 他テナント指定） |
| `TestD2LedgerTenantBoundary` | `GET /ledger/{id}` の越境 |
| `TestD2CostTenantBoundary` | 原価の一覧 / 作成 / 更新 / 削除 / 承認の越境 |
| `TestD2InvoiceTenantBoundary` | 請求書の取得 / 更新 / 支払の越境 |
| `TestD3ApproverSpoofing` | `approved_by` の由来（ボディ vs トークン） |
| `TestD4CreateTenantFromBody` | 作成系 `organization_id` の由来 |
| `TestD7NoRbacOnFinancialWrites` | roles/scopes 空でも承認できる |
| `TestD9BudgetLedgerConsistency` | `budget_id` の台帳整合 |

**test_quality_costing.py**
| クラス | 内容 |
|---|---|
| `TestH4ApprovedCostDeleteGuard` | 承認済み削除禁止の実効性（**仕様どおり**） |
| `TestQ6ApprovalStateMachine` | 承認の状態遷移・証跡・再承認/更新拒否・404 |
| `TestD9BudgetAttribution` | 予算の誤帰属（他台帳 / 他テナント） |
| `TestH5MoneyPrecision` | float 誤差・丸め・決定性・ゼロ除算 |
| `TestH5BoundaryValidation` | 負値・範囲外の境界値 |
| `TestH6LedgerSummaryStub` | 固定スタブの証明 |
| `TestNumericSchemaConsistency` | `Numeric(15,2)` と Pydantic `Decimal` の整合 |

---

## 4. 欠陥一覧

| ID | 重大度 | 症状（要約） | 根拠 |
|---|---|---|---|
| D1 | **Critical** | `GET /ledger`・`GET /invoices` がクエリの `organization_id` を信頼。省略時は全テナントを返す | `ledger.py:54,62-69` / `ledger_service.py:35-37`、`invoices.py:37,46-54` |
| D2 | **Critical** | `get_ledger`/`get_cost`/`get_invoice` に組織検査が無く、他テナントの台帳・原価・請求を閲覧/作成/改変/削除/承認/支払できる | `ledger_service.py:20-21` / `cost_service.py:22-23,33` / `invoice_service.py:27-28` |
| D3 | **Critical** | 承認者がリクエストボディ `approved_by` 由来。トークン主体を無視 → 承認者偽装・否認 | `costs.py:88` / `schemas.py:165-166` / `cost_service.py:73` |
| D4 | **High** | 作成系の `organization_id` がボディ由来 → 他テナントへの書込み・テナント偽装 | `schemas.py:14,105,143,201` / `ledger.py:48` / `costs.py:36` / `invoices.py:32` |
| D5 | **High** | 金額計算が float 経由。合計・利益・率が 2 桁に収まらず無限小数が API に漏れる。更新系で負値も許容 | `ledger_service.py:98-110,113-114` / `cost_service.py:80,87-90` / `invoice_service.py:13-15,76` / `schemas.py:34-36,155-162` |
| D6 | **High** | `GET /ledger/summary` が固定定数。財務レポート画面と外部 MCP ツールが実データとして消費 | `ledger.py:23-37` / `finance/page.tsx:77-111,118-136` / `definitions.py:150-167` / `ADR-0002:33` |
| D7 | **Medium** | 財務書込みにロール/スコープ検証が無い。`roles=[]` でも承認可能（RBAC は仕様上 P0） | `auth.py:44-73` / 各 endpoint の `_user` 未使用 / `01-auth-platform.md:24` |
| D8 | **Medium** | 更新系スキーマに正値・範囲制約が無い（負の原価/請負額、進捗率 150% 等） | `schemas.py:34-36,155-162` |
| D9 | **Medium** | `budget_id` の台帳・テナント整合を検査せず、他台帳/他テナントの予算へ実績を加算 | `cost_service.py:15,77-81` / `costs.py:27-36` |

### D1: `GET /ledger` の全テナント返却（Critical）

- **症状**: `organization_id` を省略すると WHERE に org 条件が 1 つも付かず、全テナントの工事台帳が返る。
  他テナントの org を指定してもそのまま採用される。
- **再現手順**:
  1. `CaptureDB` で `db.execute` の文を捕捉。
  2. トークン org=`...00aa` で `GET /api/v1/erp/ledger`（クエリなし）。
  3. 捕捉した SELECT / COUNT の WHERE を compile → `organization_id` 条件が **存在しない**。
  4. `GET /api/v1/erp/ledger?organization_id=...00bb` → WHERE は `...00bb`（クライアント指定が反映）。
- **テスト**: `TestD1ListLedgerTenantScope`（pass 2 + xfail 2）、`test_list_invoices_*`（pass 1 + xfail 1）。
- **根拠**: `services/erp/src/api/ledger.py:54`（`organization_id: UUID | None = Query(None)`）、
  `:62-69`（service へそのまま委譲）。`services/erp/src/services/ledger_service.py:35-37`（`if organization_id:` の時だけ WHERE）。
  請求も同型: `services/erp/src/api/invoices.py:37,46-54`。
- **影響**: 画面は org を付けずに呼ぶため、各テナントの利用者に**他社の工事台帳・請求が表示される**
  （`apps/web/src/app/(dashboard)/erp/page.tsx:143`、`apps/web/src/app/(dashboard)/dashboard/exec/page.tsx:50` は
  `/erp/ledger?per_page=20` のみ）。
  さらに MCP の読み取り専用ツール `ceos.contract.list`（GET `/api/v1/erp/invoices`、`services/mcp/src/tools/definitions.py:169,216`）が
  外部公開されるため、**テナント越境が MCP 経由で外部到達可能**。
  比較: 施工サービスは正しく実装している（`services/construction/src/api/wbs.py:23-28,42-53`、
  `services/construction/src/services/construction_service.py:23-33` はトークン org でスコープし不一致は `None`）。

### D2: 単体取得系のテナント境界欠如（Critical）

- **症状**: `get_ledger` / `get_cost` / `get_invoice` は `db.get(...)` のみで組織検査をせず、
  API も org を渡さない。他テナントの ID を知っていれば以下がすべて成功する（実測ステータス）。

  | 操作 | 期待 | 実測 |
  |---|---|---|
  | `GET /ledger/{id}`（他テナント） | 404 | **200**（body に相手 org） |
  | `GET /ledger/{id}/costs` | 404 | **200**（WHERE は `ledger_id` のみ、`cost_items.organization_id` 条件なし） |
  | `POST /ledger/{id}/costs` | 404 | **201**（相手台帳に原価追加） |
  | `PUT /costs/{id}` | 404 | **200**（金額改変） |
  | `DELETE /costs/{id}` | 404 | **204**（実削除） |
  | `POST /costs/{id}/approve` | 404 | **200**（相手原価を承認） |
  | `GET/PUT/PAY /invoices/{id}` | 404 | **200 / 200 / 200**（支払済へ遷移） |

- **再現手順**: `CaptureDB` に org=`...00bb` の台帳/原価/請求を登録し、トークン org=`...00aa` で上表を順に叩く。
- **テスト**: `TestD2LedgerTenantBoundary`、`TestD2CostTenantBoundary`、`TestD2InvoiceTenantBoundary`。
- **根拠**: `services/erp/src/services/ledger_service.py:20-21`、`services/erp/src/services/cost_service.py:22-23`・`:33-34`、
  `services/erp/src/services/invoice_service.py:27-28`。API 側も org を渡していない
  （`ledger.py:79`、`costs.py:33,50,66,84,99`、`invoices.py:64,77,92`）。
- **影響**: 他テナントの原価の閲覧・改変・削除・承認、請求の改変・支払が可能。
  MCP ツール `ceos.cost.list` は `GET /api/v1/erp/ledger/{ledger_id}/costs` を外部公開しており
  （`services/mcp/src/tools/definitions.py:106,145`、`ADR-0002:32`）、`ledger_id` さえ渡せば**他テナントの原価が取得できる**。

### D3: 承認者の偽装（Critical）

- **症状**: `CostApproveRequest.approved_by` をそのまま `cost.approved_by` に保存する。トークンの `sub` は使われない。
  任意の UUID を送れば「その人が承認した」証跡になる。
- **再現手順**: トークン `sub=...00a1` で `POST /api/v1/erp/costs/{id}/approve` に
  `{"approved_by": "00000000-0000-0000-0000-0000000000ff"}` を送る → 200、`cost.approved_by == ...00ff`、`...00a1` ではない。
- **テスト**: `TestD3ApproverSpoofing`（pass 1 = 現状固定 / xfail 1 = 仕様期待）。
- **根拠**: `services/erp/src/api/costs.py:88`（`body.approved_by`）、`services/erp/src/schemas/schemas.py:165-166`、
  `services/erp/src/services/cost_service.py:73`。
- **影響**: 承認証跡（`approved_by` / `approved_at`）が信頼できず、**否認不能・内部統制破綻**。
  既存テスト `tests/test_erp.py:568-577` が「ボディの承認者を保存する」ことを正として固定しているため、
  修正には既存テストの更新（＝憲章上不可）とプロダクト判断が必要。

### D4: 作成系 `organization_id` のボディ由来（High）

- **症状**: `POST /ledger`・`POST /ledger/{id}/costs`・`POST /budgets`・`POST /invoices` が
  ボディの `organization_id` をそのまま保存。トークン org を一切参照しない。
- **再現手順**: トークン org=`...00aa` で `POST /api/v1/erp/ledger` に `organization_id=...00bb` を送信 →
  201、生成エンティティの `organization_id == ...00bb`。
- **テスト**: `TestD4CreateTenantFromBody`（pass 2 / xfail 2）。
- **根拠**: `services/erp/src/schemas/schemas.py:14,105,143,201`（各 Create スキーマ）、
  `api/ledger.py:48`、`api/costs.py:36`、`api/budget.py:35`、`api/invoices.py:32`。
  正例: `services/construction/src/api/wbs.py:37`（`data["organization_id"] = _org_id(user)`）。
- **影響**: 任意テナントの台帳・原価・予算・請求を新規作成でき、テナント分離が成立しない。

### D5: 金額計算の float 起因の精度劣化（High）

- **症状**: `GET /ledger/{id}/summary` が 2 桁に収まらない金額・率を返す。
- **再現手順**: `contract_amount=0.30, actual_cost=0.10, budget_amount=0.30` の台帳で summary を取得。
- **実測レスポンス**（Decimal は JSON 文字列で返る）:

  ```json
  {"contract_amount":"0.3","budget_amount":"0.3","actual_cost":"0.1",
   "estimated_profit":"0.19999999999999998",
   "profit_margin":"66.66666666666666",
   "progress_rate":"0.0",
   "budget_utilization":"33.333333333333336"}
  ```
  `0.30 - 0.10 = 0.20` であるべき値が `0.19999999999999998`。率も丸めなし。
- **承認時の実績加算**も float: `0.10` と `0.20` の原価を承認すると
  `budget.actual_amount = ledger.actual_cost = 0.30000000000000004`。
- **請求**: `amount=0.10, tax_amount=0.20` → `total_amount = 0.30000000000000004`。
- **テスト**: `TestH5MoneyPrecision`（pass 3 / xfail 4）。
- **根拠**: `services/erp/src/services/ledger_service.py:98-110`（`float(...)` 変換後の減算・除算）、
  `:113-114`（`_recalculate_profit`）、`services/erp/src/services/cost_service.py:80,87-90`、
  `services/erp/src/services/invoice_service.py:13-15,76`。
  DB 列は `Numeric(15,2)` だが Python 側注釈は `Mapped[float]`
  （`services/erp/src/models/models.py:40-44,80-81,120,156-158`）、
  Pydantic 側は `Decimal`（`schemas.py:54-61,169-187,228-245`）で、**型の持ち方が三者で不整合**。
- **影響**: 財務諸表・原価集計の金額が機械的にずれる。税務/決算での丸め規約違反。
  `budget_utilization` / `profit_margin` の無限小数は画面の `toFixed` で隠れるが API 契約としては不正。
- **補足（未確認）**: 実 PostgreSQL では `Numeric(15,2)` への書込み時に量子化されるため、
  書込み後の再読込値は 2 桁に戻る可能性がある。**実 DB での最終表示値は未検証**（§8）。

### D5-2 / D8: 更新系の境界値検査欠如（Medium）

- **症状**: `PUT /costs/{id}` に `amount: -100`、`PUT /ledger/{id}` に `contract_amount: -5` や
  `progress_rate: 150` / `-10` を送ると **200 で保存される**。
- **テスト**: `TestH5BoundaryValidation`（pass 4 / xfail 3）。
- **根拠**: `services/erp/src/schemas/schemas.py:34-36`（`LedgerUpdateRequest` に `gt`/範囲なし）、
  `:155-162`（`CostUpdateRequest.amount` に `gt` なし）。作成系には `gt=0` がある（`:20,147`）のに更新系に無い非対称。
- **影響**: 負の原価・請負額が混入すると集計・利益が破壊される。進捗率 >100% は画面表示の破綻。
  `Numeric(15,2)` の上限（約 10^13）を超える値もスキーマで弾かれず、DB 例外（500）になり得る（実 DB 未検証）。

### D6: `GET /ledger/summary` が固定スタブ（High）

- **症状**: 台帳が 0 件でも SQL を 1 文も発行せず、固定値を返す。
  実測: `{"total_revenue":850000000,"total_cost":680000000,"gross_profit":170000000,
  "operating_profit":145000000,"projects_count":12,"gross_margin":0.2,"operating_margin":0.171}`。
- **テスト**: `TestH6LedgerSummaryStub`（pass 2 = スタブであることの証明 / xfail 1 = 実データ期待）。
- **根拠**: `services/erp/src/api/ledger.py:23-37`（docstring に「スタブ」と明記）。
- **仕様との不整合（重要）**:
  - 画面 `apps/web/src/app/(dashboard)/erp/finance/page.tsx:118-136` は本 API を取得し、
    `:77-111` で損益計算書（売上高・売上原価・粗利・販管費・営業利益）として描画。`:237` に「損益計算書サマリー（2026年度）」。
    **画面側に「スタブ/見本」の表示は無い。**
  - 外部公開 MCP ツール `ceos.ledger.get_summary` の説明は
    「全社の工事台帳 財務サマリー（売上・原価・利益）を取得する（読み取り専用）」
    （`services/mcp/src/tools/definitions.py:150-167`、`ADR-0002:33` でハッシュ固定・公開）。
  - `docs/api/overview.md:69` も通常の読み取り API として列挙。
- **影響**: 実在しない全社財務数値が、社内画面と外部 MCP 消費者に「実データ」として提示される。
  財務レポートの誤認は経営判断に直結する。

### D7: 財務書込みの RBAC 不在（Medium）

- **症状**: `roles=[]` / `scopes=[]` のトークンでも原価の承認が 200 で通る。
- **テスト**: `TestD7NoRbacOnFinancialWrites`（pass 1 / xfail 1）。
- **根拠**: `services/erp/src/middleware/auth.py:44-73` は `type == "user"` のみ検証し、
  `roles` / `scopes` を一切検査しない。各 endpoint の `_user` は未使用。
  仕様は RBAC を P0 と定義（`docs/architecture/01-auth-platform.md:24`、`rbac_middleware.py` 構想 `:243`）。
- **影響**: 現場作業員ロールでも原価の登録・承認・削除が可能（権限昇格）。

### D9: 予算の誤帰属（Medium）

- **症状**: 原価の `budget_id` が当該 `ledger_id` に属するかを検査しない。
  承認時も `db.get(Budget, cost.budget_id)` して無条件に `actual_amount` を加算する。
- **再現手順**: `ledger_id=L1` の原価に、別台帳 `L2` の `budget_id=B2` を指定して作成（201）→ 承認（200）→
  `B2.actual_amount` に加算される。`L1` と無関係な予算の実績が増える。
  他テナントの予算（org=`...00bb`）でも同様に加算される。
- **テスト**: `TestD9BudgetLedgerConsistency`（pass 1 / xfail 1）、`TestD9BudgetAttribution`（pass 2 / xfail 2）。
- **根拠**: `services/erp/src/services/cost_service.py:15`（`CostItem(**data)` を無検証）、
  `:77-81`（budget の org/ledger 未検査）、`services/erp/src/api/costs.py:27-36`。
- **影響**: 予算実績が別工事・別テナントへ混入し、原価管理の集計が破壊される。

---

## 5. 仕様どおり機能していた項目（欠陥ではない）

| 項目 | 確認内容 | テスト |
|---|---|---|
| H4 承認済み原価の削除禁止 | `status != "pending"` で `False` → API が 400。`approved` / `rejected` / `APPROVED` / `""` すべて拒否、`pending` のみ 204。 | `TestH4ApprovedCostDeleteGuard`（pass 6） |
| 二重承認の拒否 | `status != "pending"` で 400（**既存** `test_erp.py:583` も維持） | `test_approve_twice_blocked` |
| 承認済み原価の編集拒否 | `update_cost` が 400、値も不変 | `test_update_approved_cost_blocked` |
| 存在しない原価の承認 | 404 | `test_approve_unknown_cost_404` |
| 未認証 401 | 台帳・原価・承認・削除・請求・summary すべて 401 | `TestAuthRequiredControl` |
| ゼロ除算ガード | `contract=0` / `budget=0` で 0 を返す（例外なし） | `test_summary_handles_zero_budget_and_contract_safely` |
| 決定性 | 同一入力→同一出力（値の正しさとは別に再現性は満たす） | `test_summary_is_deterministic_for_same_input` |
| 型の整合 | DB 列は `Numeric(15,2)`、レスポンススキーマは `Decimal` | `TestNumericSchemaConsistency` |

---

## 6. 実装修正の有無

**`services/erp/src/**` は一切変更していない（差分ゼロ）。** 追加ファイルは `services/erp/tests/` の 3 ファイルのみ。

理由:
1. **D2/D4/D1 の修正は既存テストを破壊する。** 既存 `tests/test_erp.py` は
   `get_current_user` の override で `org="test-org"`（UUID ではない）を返し、
   台帳・原価をランダム UUID の org で構築している。トークン org を強制すると
   `test_get_ledger_detail` / `test_create_cost` / `test_financial_summary` / `test_approve_cost_*` 等が 404 となり、
   憲章 §1-4「既存テストを壊さない」に違反する。
2. **D3 の修正は既存テストの期待値を反転させる。** `tests/test_erp.py:568-577` が
   「ボディの `approved_by` を保存する」ことを正としている。修正には既存テストの変更が必要で、これも憲章上不可。
3. **D1/D2 は API 契約と外部公開 MCP ハッシュ固定に波及する。** `ceos.cost.list` / `ceos.contract.list` /
   `ceos.ledger.get_summary` は `ADR-0002` で `definition_sha256` を固定公開しており
   （`ADR-0002:32-34`）、挙動・説明を変えると契約（Core Allowlist）との整合判断が必要。
4. D5/D6 は「金額の丸め規約」「スタブを実データ扱いするか」という**プロダクト判断**を含む。

したがって憲章 §1-5 および task-2 の「迷う修正は実施せず欠陥報告＋人の確認が必要と明記」に従い、
**報告のみ**とした。修正する場合の最小案（未適用・要レビュー）:

- テナント: `services/construction/src/api/wbs.py:23-28` の `_org_id(user)` 方式を ERP に移植し、
  作成時はボディの `organization_id` を上書き、取得・一覧はトークン org を service へ渡し不一致は 404。
- 承認者: `approved_by` をボディから廃止し `_user.sub` を保存（既存テスト 1 件の更新が前提）。
- 金額: `float()` を排除し `Decimal` + `quantize(Decimal("0.01"))`、率は `ROUND_HALF_UP` で明示丸め。
- summary: 実集計実装 or 画面と MCP に「サンプル値」であることを明示（外部公開を停止する選択肢も要判断）。

---

## 7. 残課題・未確認事項（成功として扱わない）

1. **実 PostgreSQL 未検証**: 本報告のテストはすべて `CaptureDB`（DB 不要）による。
   `Numeric(15,2)` への書込み量子化・`Numeric(15,2)` 上限超過時の挙動・実トランザクションのロールバックは未検証。
   憲章 §2 の QA DB（`127.0.0.1:55432/ceos_qa`、erp スキーマ）を使った統合検証は Lead 側で必要。
2. **D5 の実害の最終確認**: float 誤差が実 DB の量子化でどこまで隠蔽されるか（特に `approve_cost` の
   in-session 値 vs 再読込値）は未確認。
3. **D6 の仕様判断**: 「固定スタブが許容される仕様か」を示す一次仕様文書を特定できなかった。
   `docs/api/overview.md:69` と `ADR-0002:33` は通常の読み取り API / 公開ツールとして扱っており、
   **スタブ前提の画面は存在しない**。→ **人の確認が必要**。
4. **D7 の適用範囲**: 全 26 サービスの中で endpoint 単位のスコープ検証を実装しているサービスは確認できず、
   ERP 固有の欠陥か全体方針かを判定できていない（`01-auth-platform.md:24` は RBAC を P0 と記載）。
5. **金額の丸め規約**: 消費税・按分の端数処理（切捨て/四捨五入）の社内規約文書を特定できていない。
   D5 の「正しい丸め」は 2 桁一致を期待値として置いており、規約次第で期待値の調整が必要。
6. **重複・冪等**: 同時承認（レース）による二重加算は DB ロック/トランザクションが必要で、
   モックでは検証不能。未確認。
7. **D2 の実データ影響範囲**: 他テナント ID の推測可能性（UUID v4）は評価していないが、
   D1（一覧が全件返る）により**実際に ID が列挙できる**ため、D1 と D2 の組合せは実質的に全件操作可能。

---

## 8. 再現用の最小リクエスト例（synthetic）

```http
# 前提: トークン org = 00000000-0000-0000-0000-0000000000aa
# 相手テナント台帳 = 露知らずの id (org = ...00bb)

GET  /api/v1/erp/ledger                                   # → 全テナント一覧（D1）
GET  /api/v1/erp/ledger?organization_id=...00bb           # → 相手 org で絞れる（D1）
GET  /api/v1/erp/ledger/{ledger_bb}                       # → 200（D2）
GET  /api/v1/erp/ledger/{ledger_bb}/costs                 # → 200（D2）
POST /api/v1/erp/ledger/{ledger_bb}/costs                 # → 201（D2/D4）
PUT  /api/v1/erp/costs/{cost_bb}   {"amount":"999999"}    # → 200（D2）
DELETE /api/v1/erp/costs/{cost_bb}                        # → 204（D2）
POST /api/v1/erp/costs/{cost_bb}/approve {"approved_by":"...00ff"}  # → 200（D2/D3）
POST /api/v1/erp/ledger            {"organization_id":"...00bb", ...}  # → 201（D4）
GET  /api/v1/erp/ledger/summary                           # → 固定値 850000000 等（D6）
```

---

## 9. 添付（追加ファイル）

- `services/erp/tests/_quality_support.py` — 共通サポート（`CaptureDB` / synthetic fixture / WHERE compile）
- `services/erp/tests/test_quality_tenant_isolation.py` — Q1/Q2/Q6/Q8（32 tests: 17 pass / 15 xfail）
- `services/erp/tests/test_quality_costing.py` — Q3/Q6/Q8（34 tests: 24 pass / 10 xfail）

既存ファイルの変更なし。`git add/commit/checkout/stash` は実行していない。
