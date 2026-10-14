# 🧪 品質テスト報告 — 協力会社・契約フロー（services/partner）

| 項目 | 内容 |
|---|---|
| 担当 | `qa-docs-approval`（task-10 / QA-Partner） |
| 対象 | `services/partner`（partners / contracts / assignments / evaluations / rating） |
| 作業ディレクトリ | `/home/kensan/Projects/Mirai-Construction-DX/Construction-Enterprise-OS` |
| 実行環境 | Python 3.12 / pytest 8.3.3 / httpx ASGITransport |
| 準拠 | `reports/quality-tests/CHARTER.md` 全制約 |
| 実データ | ❌ 未使用（synthetic fixture のみ。`テスト建設株式会社`/`テスト商事株式会社` 等） |
| 外部接続 | ❌ なし（DB session は AsyncMock、service は patch。実 DB・通知・外部 API 未使用） |
| git 操作 | ❌ `add`/`commit`/`checkout`/`stash` 未実施 |
| 他サービスの未コミット変更 | ✅ 保持（一切触れていない） |

---

## 1. 🔴 最重要結論（3 行）

1. **① org 欠落トークンが本社組織 `00000000-0000-0000-0000-000000000001`（ADMIN_ORG_ID）へフォールバックしていた**（4 エンドポイント）。**修正済（fail-closed 403）**。
2. **⑤ 一覧・個別取得・更新が `organization_id` で絞られていない**（協力会社/契約/評価/配置の全経路）。**未修正・Critical**。`docs/architecture/ADR-0001-ceos-responsibility-boundary.md:44`「認可は **組織（テナント）＋案件＋ロール**で行い」に反する。
3. **②③ sign の署名者がボディ由来で、署名済み契約へ再署名でき、終了済み契約も `active` に戻せる**。**未修正・High**（証跡の否認不能性が成立しない）。

---

## 2. 🎯 対象フロー

- **協力会社**: 登録 `POST /api/v1/partners` / 一覧 `GET` / 詳細 `GET /{id}`（contacts・contracts_summary 同時取得）/ 更新 `PUT /{id}` / 担当者 `POST|GET /{id}/contacts`
- **契約**: 起票 `POST /api/v1/partners/contracts` / 一覧 / 取得 / 更新 `PUT /{id}` / **署名 `POST /{id}/sign`** / 協力会社別 `GET /partners/{id}/contracts`
- **配置**: 起票 `POST /api/v1/partners/assignments` / 一覧 / 案件別 `GET /api/v1/projects/{id}/assignments`
- **評価・評点**: 登録 `POST /api/v1/partners/evaluations`（登録時に `partner.rating` を再計算）/ 一覧 / 協力会社別 / 評点 `GET /partners/{id}/rating`

---

## 3. 🧾 テスト一覧（追加分・57 tests）

### 3.1 `tests/test_quality_tenant_isolation.py` — 40 tests
| クラス | 検証内容 |
|---|---|
| `TestOrgMissingFallback` | org 欠落トークンが 4 エンドポイントで **403**（本社組織へ倒れない）/ service に ADMIN_ORG_ID が渡らない / 不正 org は 4xx / sub 欠落・非 UUID は 401 / API ソースにフォールバック定数が残っていない |
| `TestServiceScoping` | service 層クエリの **WHERE 句**に `organization_id` があるか（協力会社取得・一覧／契約取得・一覧／評価一覧・集計／配置一覧） |
| `TestApiPassesTokenOrg` | API がトークン org を service に渡しているか（協力会社・契約・評価・配置の一覧＋協力会社詳細） |
| `TestAuthRequired` | 11 エンドポイントの 401 |
| `TestRegression` | org 付きトークンでの作成がトークン org を使う／ページング meta |

### 3.2 `tests/test_quality_contract_workflow.py` — 17 tests
| クラス | 検証内容 |
|---|---|
| `TestSignerIdentity` | sign の署名者がトークン `sub` 由来か（ボディ由来でないか）／認証必須 |
| `TestSignatureStateTransition` | 未署名→署名の正常系（署名者・時刻記録）／再署名で先行署名が上書きされないか／`terminated` から sign で `active` に戻らないか／PUT の `status` で署名を迂回できないか |
| `TestAmountValidation` | 作成時の金額 `gt=0`（回帰）／**更新時**の金額 `gt=0` |
| `TestRatingAggregation` | 評点の丸め決定性（銀行丸めの明示）／0 件時の平均と件数／全件平均／0 点サブスコアが null 化しないか／評点ヘルパ間の 0.0 平均の一貫性 |
| `TestDuplicateEvaluation` | 評価の一意制約の有無／同一評価の重複登録／スコア範囲 1.0–5.0 の回帰 |
| `TestMasterValueValidation` | `company_type` / `status` が許可リストで検証されるか |

---

## 4. ▶️ 実行コマンドと実出力（証跡）

```bash
cd services/partner && python3 -m pytest tests/ -q -p no:cacheprovider
```
```
59 passed, 20 xfailed, 1 warning in 3.28s
```

### 4.1 内訳（証跡）
| 実行 | 結果 |
|---|---|
| 既存テストのみ（`test_partner.py` + `test_health_readiness.py`） | **22 passed**（変更前 baseline 22 passed と一致・1 件も壊していない） |
| 追加テストのみ（新規 2 ファイル） | **37 passed, 20 xfailed** |
| 全体 | **59 passed, 20 xfailed** |
| `test_quality_tenant_isolation.py`（collect 40） | 28 passed / 12 xfailed |
| `test_quality_contract_workflow.py`（collect 17） | 9 passed / 8 xfailed |

```bash
# 未修正欠陥の実失敗内容（xfail を無効化して確認）
cd services/partner && python3 -m pytest tests/ -q -p no:cacheprovider --runxfail -k defect
```

> ⚠️ `xfail(strict=True)` は **成功でも skip でもない**。期待した正しい挙動が現状成立しない
> 「未修正の欠陥」の証跡である。実失敗メッセージは §6.2 に引用。修正すると XPASS → strict で
> 失敗に変わり、マーカー除去が強制される。

---

## 5. ✅ 必須観点の判定

| # | 観点 | 判定 | 根拠 |
|---|---|---|---|
| ① | org 欠落時の ADMIN_ORG_ID フォールバック | ✅ **欠陥を確認 → 修正済** | 4 箇所に存在。`require_organization_id` で 403。8 テストで固定 |
| ② | sign の署名者がトークン由来か | ❌ **欠陥（未修正）** | `body.signed_by_our` がそのまま記録される（P-2） |
| ③ | 署名済み契約への再署名 | ❌ **欠陥（未修正）** | 状態チェックなしで上書き（P-3）。`terminated→active` も可（P-4） |
| ④ | 金額・評点・集計の丸めと再現性 | ⚠️ **一部欠陥** | 決定性は ✅。0 点の null 化は修正済（P-7）。銀行丸め（`round(4.25,1)=4.2`）は仕様未確定 → Info。0 平均の扱いが 2 ヘルパで不一致（P-8） |
| ⑤ | 個別取得・更新・削除のテナント境界 | ❌ **欠陥（未修正・Critical）** | 全経路で org 絞り込みなし（**P-1**） |
| ⑥ | 評価の重複登録 | ❌ **欠陥（未修正）** | 一意制約なし・アプリ側チェックなし（P-9） |
| — | Q1 権限境界（未認証） | ✅ 正常 | 全エンドポイント 401 |
| — | Q1 ロール要件 | ℹ️ **仕様未確定** | 協力会社/契約/評価の作成・更新・署名に**ロール検査が一切無い**（`_require_management` 相当が存在しない）。§7 で人の確認が必要と報告 |
| — | 削除エンドポイント | ℹ️ 存在しない | 協力会社/契約/評価/配置に DELETE は未実装（削除経路そのものが無い） |

---

## 6. 🐞 欠陥表

**重大度**: Critical = テナント越境の読み書き/認証回避/承認偽装、High = 権限昇格/証跡欠落/データ破壊、
Medium = 境界値/異常系/再現性、Low = 表記/軽微、Info = 仕様未確定。

### 6.1 欠陥一覧

| ID | 症状 | 再現手順 | 根拠 (file:line) | 重大度 | 影響 | 修正 |
|---|---|---|---|---|---|---|
| **P-1** | **テナント越境**: 協力会社・契約・評価・配置の一覧／個別取得／更新が `organization_id` で絞られていない。他組織のデータを読み、更新できる | ① `partner_service.list_partners(db)` 等を実行し発行 SQL の WHERE 句を確認 → `organization_id` が無い ② `GET /api/v1/partners` を org=A のトークンで実行 → service に org が渡らない | service: `partner_service.py:24,35,80,105,114` / `contract_service.py:24,33,75` / `evaluation_service.py:24,60,66,80` / `assignment_service.py:23,62`<br>API: `partners.py:95,123,151,168,188,208,232,254` / `contracts.py:72,100,117` / `evaluations.py:69` / `assignments.py:63,92`<br>spec: `docs/architecture/ADR-0001-ceos-responsibility-boundary.md:44` | **Critical** | 他組織の協力会社情報（担当者連絡先含む）・契約金額・評価・配置の**読み取りと更新**。組織＝テナント分離が機能していない | ❌ なし（全経路の改修が必要・大規模のため報告） |
| **P-2** | **署名者の偽装**: `sign` の `signed_by_our` がリクエストボディ由来で、トークン `sub` と無関係に任意の内部ユーザーを署名者にできる | `POST /api/v1/partners/contracts/{id}/sign` に `{"signed_by_our":"<他ユーザーUUID>","signed_by_partner":"X"}` を送信 → ボディの UUID が署名者として記録される | `contracts.py:135`、`contract_service.py:96` | **High** | 契約締結の**証跡偽装**（誰が署名したかが否認不能でない） | ❌ なし（`signed_by_our` の意味＝「操作者」か「指定署名権者」か業務判断が必要 → **人の確認が必要**） |
| **P-3** | **再署名**: 署名済み（`status=active`, `signed_at` あり）契約に再度 sign でき、先行署名・署名時刻を上書きする | `sign_contract(db, id, 別ユーザー, "後行商事")` を署名済み契約へ実行 → `signed_by_our`/`signed_at` が後着で置換 | `contract_service.py:88-99`（状態チェックなし） | **High** | 契約署名の**否認不能性の破壊**。先行署名の記録が失われる | ❌ なし（再署名を許す状態の定義が仕様未確定 → 人の確認が必要） |
| **P-4** | **状態機械の迂回（sign）**: `terminated` 等の終了状態からも sign で `active` に遷移する | `status="terminated"` の契約へ `sign_contract` → `status=="active"` | `contract_service.py:95` | **High** | 終了済み契約が有効化される | ❌ なし（署名可能な状態の定義が仕様未確定） |
| **P-5** | **状態機械の迂回（UPDATE）**: `PUT /contracts/{id}` の `status` が無検証で、署名を経ずに `active` にできる | `PUT /api/v1/partners/contracts/{id}` に `{"status":"active"}` → **200 OK**・`signed_at=null` | `contracts.py:117`、`schemas/__init__.py:167` | **High** | 署名なしで契約が有効化され、署名フローが形骸化 | ❌ なし（status の遷移表が仕様未確定） |
| **P-6** | 契約**更新**時に金額の正値検証が無く、0/負値を登録できる（作成時は `gt=0`） | `PUT /contracts/{id}` に `{"amount": -1000000}` → **200 OK** | 修正前 `schemas/__init__.py:161` | Medium | 契約金額の不正値（集計・請求への波及） | ✅ **修正済** |
| **P-7** | 評価の**0 点**サブスコアが `null` に化ける（`if eval_.x else None` は `Decimal("0.0")` が falsy） | `_evaluation_to_response(quality_score=Decimal("0.0"))` → `quality_score is None` | 修正前 `evaluations.py:29-33` | Low | 0 点と未評価の区別が消える。API は `ge=1.0` のため通常経路では到達しないが、DB 直投入・移行データ・将来の下限変更で顕在化 | ✅ **修正済** |
| **P-8** | 評点ヘルパ間で**平均 0.0** の扱いが不一致（片方 `None`、片方 `0.0`） | `partner_service.calculate_partner_rating` → `None` / `evaluation_service.get_partner_rating` → `0.0` | `partner_service.py:123` vs `evaluation_service.py:76` | Low | 0 平均の表現が呼び出し元ごとに変わる（API 未露出のため実害は限定的） | ❌ なし（どちらに寄せるか仕様判断） |
| **P-9** | **評価の重複登録**: `evaluations` に一意制約が無く、アプリ側チェックも無い。同一評価者・同一対象・同一期間を何度でも登録でき、件数と平均が汚染される | 同一 payload で `POST /api/v1/partners/evaluations` を 2 回 → 2 回目も **201** | `models/__init__.py:150-156`（UniqueConstraint なし）、`migrations/000_base_schema.sql:60-77`（UNIQUE なし）、`evaluation_service.py:11-21` | **High** | 評点（`partner.rating`）の**計算結果が誤る**（重複行が平均・件数に算入）。Q3/Q6 | ❌ なし（重複判定キーの定義＝業務判断が必要） |
| **P-10** | `company_type` / `status` が**許可リストで検証されない**（`COMPANY_TYPES`/`PARTNER_STATUSES` は定義済みだが未使用） | `POST /api/v1/partners` に `{"company_type":"__arbitrary__","status":"__arbitrary__"}` → **201** | `schemas/__init__.py:37,41`（定義）, `:47`, `:59`（未検証）, `:77` | Medium | マスタ外の値が混入し、一覧フィルタ・集計が破綻 | ❌ なし（許可リストは定義済みのため**小さい修正で対応可能**だが、既存データの是正方針が必要） |
| **P-11** | **org 欠落トークンが本社組織（ADMIN_ORG_ID）へフォールバック**し、本社データの作成・到達経路になる | `org` クレーム無しトークンで `POST /api/v1/partners` → 修正前は作成が進行（現在は 403） | 修正前 `partners.py:76`, `contracts.py:53`, `evaluations.py:48`, `assignments.py:45` | **Critical** | 組織を持たないトークンが本社（`00000000-...-0001`）のデータを操作しうる。**テナント境界の崩壊** | ✅ **修正済**（403 fail-closed） |
| **P-12** | `sub` クレームの**欠落・非 UUID** で 500（`payload["sub"]` の KeyError / 利用側 `UUID()` の ValueError） | `sub` 無し or `sub="not-a-uuid"` のトークンで `POST /evaluations` → 修正前は 500（現在は 401） | 修正前 `middleware/auth.py:25` | Medium | クライアント起因の不備が 500 になり原因切り分け不能。内部エラー表示 | ✅ **修正済**（401 INVALID_TOKEN） |
| **P-13** | 丸めが Python の**銀行丸め**（`round(4.25, 1) == 4.2`）で、JIS の四捨五入（4.3）と一致しない | `get_partner_rating` に `avg=Decimal("4.25")` を与える → `4.2` | `evaluation_service.py:76` | **Info** | 表示・帳票の期待値と 0.1 ずれる可能性。**仕様が未確認のため判定不能** | ❌ なし・**仕様確認が必要** |

### 6.2 xfail テストが示す実失敗内容（`--runxfail` の実出力・抜粋）
```
E  AssertionError: ボディの signed_by_our がそのまま署名者として記録された
E  assert UUID('1111...1111') == UUID('6666...6666')                 # P-2
E  AssertionError: 先行署名者が上書きされた                            # P-3
E  AssertionError: terminated 契約が active へ遷移した                 # P-4
E  AssertionError: 署名なしで契約を active にできてしまう(status 迂回)
E  assert 200 >= 400                                                  # P-5
E  AssertionError: assert None == 0.0                                  # P-8
E  AssertionError: 評価の一意制約が無い (existing unique sets: [])      # P-9
E  AssertionError: 同一評価が重複登録できてしまう
E  assert 201 >= 400                                                   # P-9
E  AssertionError: 未定義の company_type/status が受理された            # P-10
E  AssertionError: assert 'organization_id' in ' partner.partners.id = :id_1'
E  AssertionError: assert 'organization_id' in ' partner.contracts.id = :id_1'
E  AssertionError: assert 'organization_id' in ' partner.evaluations.partner_id = :partner_id_1'
E  AssertionError: assert 'organization_id' in ' | '                   # P-1（WHERE 句が空）
E  AssertionError: assert UUID('2222...2222') in [<AsyncMock>, 1, 20, None, None, None]  # P-1（org 未伝播）
```

---

## 7. 🛠 修正差分の要約

**修正は `services/partner/src/**` の 6 ファイル・+54 / -15 のみ。業務判定ロジック・状態遷移・
テナント境界は一切緩めていない（むしろ厳格化のみ）。**

| 修正 | 内容 | 検証 |
|---|---|---|
| **P-11/P-12** | `middleware/auth.py` に `require_organization_id()` を追加。org 欠落→`403 ORG_REQUIRED`、org 不正→`403 ORG_INVALID`。`_decode_token` で `sub` の UUID 形式を検証（欠落・非 UUID→`401`）。4 API の `... else UUID("00000000-...-0001")` を全廃 | 8 + 2 テスト ✅ |
| **P-6** | `ContractUpdate.amount` に `Field(gt=0)`（`ContractCreate` と整合） | `test_update_rejects_non_positive_amount` ✅ |
| **P-7** | `_evaluation_to_response` の 5 サブスコアを `if x is not None` に（0 点を保持） | `test_zero_subscore_is_preserved_as_zero` ✅ |

**変更ファイル**: `src/middleware/auth.py` / `src/api/{partners,contracts,evaluations,assignments}.py` / `src/schemas/__init__.py`

### 7.1 未修正とした判断（CHARTER「迷う修正はせず欠陥報告」）
| 欠陥 | 未修正の理由 |
|---|---|
| **P-1** | service 層 20 関数＋API 層 17 呼び出しへの org 引き回しが必要で「最小修正」の範囲を超える。かつ実 DB での越境確認（Lead 統合検証）と合わせて設計すべき。**最優先の改修対象** |
| **P-2 / P-3 / P-4 / P-5** | 「署名者＝操作者か指定署名権者か」「再署名を許す状態」「status の遷移表」が**仕様として未定義**。推測で状態遷移を実装すると業務要件を歪めるため、**人の確認が必要** |
| **P-8 / P-13** | 丸め規約・0 平均の表現が仕様未確認 |
| **P-9** | 重複判定キー（partner×project×evaluator×期間 のどれで一意にするか）が業務判断。DB 制約追加は既存データの重複解消を伴う |
| **P-10** | 許可リストは定義済みだが、既存のマスタ外データの是正方針が必要 |

---

## 8. ⚠️ 残課題・未確認事項（成功として扱わないもの）

| # | 未確認事項 | 理由 | 推奨する確認手順 |
|---|---|---|---|
| 1 | **P-1 の実 DB での越境再現** | 実 PostgreSQL は Lead の統合検証用とされ、mock 主体の方針に従った。本報告の P-1 は「発行 SQL の WHERE 句」と「API→service 引数」の 2 面での確認であり、**実データでの越境取得は未実施** | `partner` スキーマに org=A/org=B のデータを投入し、org=A のトークンで org=B の `id` を指定して `GET /partners/{id}` が 200 を返すことを確認 |
| 2 | **ロール要件が未定義** | 協力会社・契約・評価・配置の作成/更新/署名に**ロール検査が一切無い**（認証済みなら誰でも可）。必要なロール（例: 契約は管理部のみ）が仕様に無い | 各操作に必要なロールを定義し、`_require_management` 相当を実装 |
| 3 | **署名フローの仕様全体** | 誰が署名権者か、再署名・取消・再締結の扱い、署名可能な状態遷移が未定義（P-2〜P-5） | 契約状態機械（draft→pending_approval→active→completed/terminated）と署名権限を明文化 |
| 4 | **評価の重複判定キー** | 一意とすべき組み合わせが未定義（P-9） | `(organization_id, partner_id, project_id, evaluator_id, period)` 等を決定し、部分一意索引を追加 |
| 5 | **丸め規約** | 銀行丸め vs 四捨五入、表示桁（P-13） | 評点の丸め規約を明文化（`Decimal` + `ROUND_HALF_UP` 推奨） |
| 6 | **`calculate_partner_rating` の利用箇所** | 0 平均で `None` を返す本関数が実際にどこから呼ばれるか未追跡（P-8 の実害評価） | 全リポジトリで呼び出し元を確認 |
| 7 | **削除経路** | DELETE エンドポイントが未実装のため、削除のテナント境界は**検証不能**（成功とは書かない） | 削除 API の要否を決定 |
| 8 | **実在企業名を含む既存テストデータ** | `tests/conftest.py:47` に `テスト建設株式会社`（synthetic だが実在しうる一般名）。本タスクでは変更していない（write scope 内だが既存テスト保護のため未変更） | 既存テストの fixture 命名をレビュー |

---

## 9. 🔁 証跡の再現方法

```bash
cd /home/kensan/Projects/Mirai-Construction-DX/Construction-Enterprise-OS

# 全体（報告の数値）
( cd services/partner && python3 -m pytest tests/ -q -p no:cacheprovider )

# 既存テストのみ（回帰）
( cd services/partner && python3 -m pytest tests/test_partner.py tests/test_health_readiness.py -q -p no:cacheprovider )

# 未修正欠陥の実失敗内容
( cd services/partner && python3 -m pytest tests/ -q -p no:cacheprovider --runxfail -k defect )
```

### 変更ファイル（write scope 内のみ）
| 種別 | パス |
|---|---|
| 追加テスト | `services/partner/tests/test_quality_tenant_isolation.py` |
| 追加テスト | `services/partner/tests/test_quality_contract_workflow.py` |
| 修正（最小） | `services/partner/src/middleware/auth.py` |
| 修正（最小） | `services/partner/src/api/partners.py` / `contracts.py` / `evaluations.py` / `assignments.py` |
| 修正（最小） | `services/partner/src/schemas/__init__.py` |
| 本報告 | `reports/quality-tests/qa-partner.md` |

> 既存テストの緩和・skip 追加・削除は一切行っていない（既存 22 件すべて pass を維持）。
> 他サービスの未コミット変更には触れていない。
