# QA-Construction 品質テスト報告 — services/construction

- 担当: `[🧪 QA-Construction]`（teammate）/ Task: `task-1`
- 日付: 2026-10-07 (Asia/Tokyo)
- 対象: `services/construction`（施工管理フロー: WBS → 工程 → 資源 → 数量/原価 → 施工計画書承認）
- 制約遵守: synthetic fixture のみ（UUID `...00aa`/`...00bb`、名称「テスト工区A」等）。
  外部 Provider / MCP / 本番 DB / 実サービスへ**未接続**（DB は `AsyncMock`）。
  `git add/commit/checkout/stash` は**未実施**。
- 実装修正: `services/construction` 内のみ。**1件のみ**実施（DEF-05a）。他サービスへは波及させていない。

---

## 1. 仕様根拠（テナント境界・承認者同定）

| 根拠 | 内容 |
|---|---|
| `docs/architecture/01-auth-platform.md:184-199` | JWT クレームに `sub`（user-uuid）と `org`（org-uuid）が含まれる |
| `docs/architecture/04-common-platforms.md:181` | 共通ログの `organization_id` はサービスが同定する値 |
| `docs/api/overview.md:71-73` | construction の対象エンドポイント一覧 |
| `services/document/src/api/documents.py:42-43,72-79` | 参照実装: 一覧 API は `organization_id` を**クエリに持たずトークン由来** |
| `services/construction/src/api/wbs.py:23-27,37,53` | 同一サービス内の模範実装: `_org_id(user)` でトークン由来 |
| `services/construction/migrations/000_base_schema.sql` | **RLS / POLICY なし**（`grep -in "row level security\|policy\|rls"` が 0 件）→ アプリ層が唯一のテナント境界 |
| `services/construction/src/schemas/__init__.py:44-45` vs `WBSUpdateRequest` | PATCH は `progress_percent` に `ge=0, le=100` を持つ → 0–100 は本サービスの自明な仕様 |

> 補足: `organization_id` をクエリで受ける実装は construction 固有ではなく、`erp` / `safety` / `iot` など 40 超の API に同型が存在する（`grep -rn "organization_id: UUID | None = Query" services/*/src/api/*.py`）。
> ただし WBS が同一サービス内でトークン由来を採用しているため、**是正可能な非対称**である。

---

## 2. 追加テスト一覧

| ファイル | 内容 | テスト数 |
|---|---|---|
| `tests/quality_helpers.py` | 共通ヘルパー（mock DB / SQL 捕捉 / synthetic factory）。**新規** | — |
| `tests/test_quality_tenant_isolation.py` | H1/H2/H3/H4/H7 テナント分離。**新規** | 27（pass 3 / xfail 24） |
| `tests/test_quality_calculation_approval.py` | H5/H6 承認・計算 ＋ 状態遷移・未認証・境界値。**新規** | 26（pass 19 / xfail 7） |

検証手法:
- HTTP 層は既存 `tests/test_construction.py` と同じ `create_app()` + `dependency_overrides` + `TestClient`。
- SQL は `db.execute` に渡された文を捕捉し
  `str(stmt.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))`
  の **WHERE 句のみ**を検査（`SELECT` 列の `organization_id` と混同しないため）。
- 純関数 `_calculate_resource_total_cost` は直接 import して検証。
- 欠陥が未修正の検証は `xfail(strict=True)`。**修正されると XPASS→FAIL になり気付ける**。
  xfail は「成功」ではない（本報告でも pass と区別して計上）。

---

## 3. 実行コマンドと実出力（証跡）

### 3.1 修正前（欠陥の観測）

```
$ cd services/construction && python3 -m pytest tests/ -q -p no:cacheprovider     # 既存のみ（ベースライン）
26 passed, 1 warning in 28.28s

$ python3 -m pytest tests/test_quality_tenant_isolation.py -q -p no:cacheprovider
3 passed, 24 xfailed, 1 warning in 3.24s

$ python3 -m pytest tests/test_quality_tenant_isolation.py -q -p no:cacheprovider --runxfail
24 failed, 3 passed, 1 warning in 37.53s          # ← xfail は全て本物の欠陥検知

$ python3 -m pytest tests/test_quality_calculation_approval.py -q -p no:cacheprovider
2 failed, 17 passed, 5 xfailed, 1 warning in 2.88s  # ← H5-1,H5-2 が失敗（未修正）
```

xfail が fixture エラー等による偽陽性でないことを `--runxfail` で確認済み。実際の失敗メッセージ例:

```
E  AssertionError: resources の一覧がテナントで絞られていない: ''
E  AssertionError: resources の個別GETが他テナント 00000000-...-00bb を 200 で返した
E  assert 200 == 404
E  AssertionError: resources のDELETEが他テナント 00000000-...-00bb を 204 で削除した
E  assert 204 == 404
E  AssertionError: 原価集計がテナントで絞られていない: "WHERE construction.resources.project_id = '...' GROUP BY construction.resources.resource_type"
E  AssertionError: body の他テナント 00000000-...-00bb が保存された: 00000000-...-00bb
E  AssertionError: actual=0 で planned=30 にフォールバックした: total_cost=3000.0
E  AssertionError: 作成時に total_cost が未計算（None）
E  AssertionError: ロールを持たない利用者が承認できた: 200
E  AssertionError: 他テナント 00000000-...-00bb の計画書を 200 で承認した
E  AssertionError: ボディ指定の別人 00000000-...-00ee が作成者として記録された
E  AssertionError: 範囲外の進捗率 150 が 200 で受理された
```

### 3.2 修正後（最終）

```
$ cd services/construction && python3 -m pytest tests/ -q -p no:cacheprovider
48 passed, 31 xfailed, 1 warning in 6.19s

$ python3 -m pytest tests/ -p no:cacheprovider --collect-only -q | tail -1
79 tests collected in 1.33s
```

ファイル別:

| ファイル | 結果 |
|---|---|
| `tests/test_construction.py`（既存） | 23 passed |
| `tests/test_health_readiness.py`（既存） | 1 passed |
| `tests/test_public_endpoint_authz.py`（既存） | 2 passed |
| `tests/test_quality_tenant_isolation.py`（新規） | 3 passed, 24 xfailed |
| `tests/test_quality_calculation_approval.py`（新規） | 19 passed, 7 xfailed |
| **合計** | **48 passed, 31 xfailed, 0 failed, 0 error, 0 skipped** |

既存 26 件は修正後も全件 pass（回帰なし）。`skip` は 0 件。

---

## 4. 欠陥一覧

重大度は CHARTER §5 に準拠。`修正` 列が「未」のものは**実施していない**（理由も記載）。

| ID | 症状（要約） | 重大度 | 修正 |
|---|---|---|---|
| DEF-01a | 一覧 API が組織で絞られず全テナントを返す | **Critical** | 未 |
| DEF-01b | 一覧 API がクエリ指定の他テナント組織を信頼する | **Critical** | 未 |
| DEF-02a | 個別GET が他テナント資源/工程/計画書を返す | **Critical** | 未 |
| DEF-02b | 個別PUT が他テナントを更新する | **Critical** | 未 |
| DEF-02c | 個別DELETE が他テナントを削除する（データ破壊） | **Critical** | 未 |
| DEF-03a | 原価集計が組織未検査（他テナント原価漏えい） | **Critical** | 未 |
| DEF-03b | critical-path が組織未検査（工程漏えい） | **Critical** | 未 |
| DEF-03c | gantt が組織未検査（工程漏えい） | **Critical** | 未 |
| DEF-04a/b/c | 作成時に body の `organization_id` をそのまま保存（テナント偽装） | **Critical** | 未 |
| DEF-05a | 承認者がボディ由来 → 承認者偽装・否認不能 | **Critical** | **修正済** |
| DEF-05b | 承認にロール検査が一切ない（`roles` 未使用） | High | 未 |
| DEF-05c | 他テナントの施工計画書を承認できる | **Critical** | 未 |
| DEF-05d | `created_by` がボディ由来 → 作成者偽装（証跡の信頼性） | High | 未 |
| DEF-06a | `actual_quantity == 0` が planned にフォールバックし原価を水増し | High | 未 |
| DEF-06b | `create_resource` が `total_cost` を計算せず `None` のまま保存 | High | 未 |
| DEF-07a | `/wbs/tree` の子ノード取得が組織未検査 | **Critical** | 未 |
| DEF-07b | `/wbs/tree` が他テナント子ノードを応答に混入 | **Critical** | 未 |
| DEF-07c | `/wbs/{id}/children` が他テナント子ノードを返す | **Critical** | 未 |
| DEF-08a | `PUT /wbs/{id}` が進捗率の 0–100 制約を検証しない（PATCH と非対称） | Medium | 未 |
| OBS-01 | 却下（reject）に却下者・理由の記録がない（証跡欠落） | High（仕様未確認） | 未 |
| OBS-02 | 原価の定義が二重（集計は実績のみ / `total_cost` は実績なければ計画） | Medium（仕様未確認） | 未 |
| OBS-03 | `GET /wbs` は無視される `organization_id` クエリパラメータを公開（デッドパラメータ） | Low | 未 |

### DEF-01a / DEF-01b — 一覧 API のテナント越境
- **症状**: `GET /resources` `GET /schedules` `GET /methods` は `organization_id` をクエリで受け取り、
  省略時は `WHERE organization_id` が付かない（=全テナント）。他テナント組織を指定するとそのまま絞り込む。
- **再現手順**:
  1. token `org=...00aa` で `GET /api/v1/construction/resources` → 発行 SQL の WHERE が空。
  2. `GET /api/v1/construction/resources?organization_id=...00bb` → WHERE に `...00bb` が入る。
- **根拠**: `src/api/resources.py:34,43-51` / `src/api/schedule.py:33,42-50` / `src/api/methods.py:47,55-63` /
  `src/services/construction_service.py:162,266,360`（`if organization_id:` ガード）。
- **影響**: 全組織の資源・工程・施工計画書（機密含む）が読める。RLS がないため他層の防御もない。
- **テスト**: `TestH1ListTenantSource` 6件（xfail）。

### DEF-02a/b/c — 個別 CRUD のテナント越境
- **症状**: `get_resource` / `get_schedule` / `get_method` は PK のみで取得し組織検査をしない。
  WBS の `get_wbs(..., organization_id)` と非対称。
- **再現手順**: `mock_db.get` が `organization_id=...00bb` の資源を返す状態で
  `GET|PUT|DELETE /resources/{id}` → 200 / 200 / 204（404 になるべき）。
- **根拠**: `src/api/resources.py:61,74,86` / `src/api/schedule.py:60,73,85` / `src/api/methods.py:74,87,99` /
  `src/services/construction_service.py:146-147,250-251,344-345`。
- **影響**: 他テナントの資源/工程/計画書の**読み・改ざん・削除**。DELETE はデータ破壊。
- **テスト**: `TestH2DetailTenantBoundary` 9件（xfail）＋ 正の対照 1件（pass）。

### DEF-03a/b/c — プロジェクト集計のテナント越境
- **症状**: `resource-cost-summary` / `critical-path` / `gantt` は `project_id` のみで絞る。
- **再現手順**: `GET /api/v1/construction/projects/{project_id}/resource-cost-summary` 他2本 → 発行 SQL の WHERE に `organization_id` なし。
- **根拠**: `src/api/resources.py:105-111` / `src/api/schedule.py:91-106` /
  `src/services/construction_service.py:205-230`（WHERE は `:219` の project_id のみ）, `300-306`（`:303`）, `309-314`（`:312`）。
- **影響**: 他テナントの**原価（planned/actual 金額）と工程**が漏えい。`project_id` は UUID だが、漏えい経路がある以上推測耐性に依存できない。
- **テスト**: `TestH3ProjectAggregateTenantBoundary` 3件（xfail）。

### DEF-04a/b/c — 作成時テナント偽装
- **症状**: `POST /resources` `/schedules` `/methods` は `body.model_dump()` をそのまま保存するため、
  ボディの `organization_id` がそのまま永続化される。`create_wbs` はトークンで上書きする（非対称）。
- **再現手順**: token org `...00aa`、body `organization_id=...00bb` で `POST` → `db.add` された実体の組織が `...00bb`。
- **根拠**: `src/api/resources.py:29` / `src/api/schedule.py:28` / `src/api/methods.py:42` /
  `src/services/construction_service.py:138-143,242-247,336-341`。
- **影響**: 攻撃者が任意組織のデータを作成でき、被害テナント側の一覧・集計に混入する。
- **テスト**: `TestH4CreateTenantSpoof` 3件（xfail）＋ WBS 正の対照 1件（pass）。

### DEF-05a — 承認者の偽装（**修正済**）
- **症状**: `POST /methods/{id}/approve` が `body.approved_by` をそのまま承認者として記録。
- **再現手順（修正前）**: token `sub=...00cc`、body `approved_by=...00ee` → `method.approved_by == ...00ee`。
- **根拠（修正前）**: `src/api/methods.py`（旧 `body.approved_by` を `approve_method` に渡していた）/ `src/services/construction_service.py:410-421`。
- **影響**: 承認者を任意に詐称でき、承認の否認不能（非否認性の破壊）。
- **修正**: 下記 §5。**テスト**: `TestH5ApprovalIdentity::test_approve_uses_token_identity_not_body` / `test_approve_without_body_uses_token_identity`（pass）。

### DEF-05b — 承認のロール検査なし
- **症状**: `roles` クレームは取得されるが、どのエンドポイントでも検査されない。`roles=[]` でも承認できる。
- **根拠**: `src/middleware/auth.py:33-39`（roles 取得のみ）/ `src/api/methods.py:120-138`（検査なし）。
- **影響**: 施工計画書の承認という統制行為を権限のない利用者が実行できる。
- **要人の確認**: **承認に必要なロール名が仕様に未定義**（承認権限マトリクスが見つからない）。閾値を勝手に決めると仕様を曲げるため、**修正せず**報告する。
- **テスト**: `test_approve_requires_explicit_role`（xfail）。

### DEF-05c — 他テナント計画書の承認
- **症状**: ORG_A のトークンで ORG_B の `review` 計画書を 200 で承認でき、状態が `approved` に変わる。
- **根拠**: `get_method`（`construction_service.py:344-345`）+ `methods.py:127-132`。
- **影響**: 他テナントの文書状態を改変。DEF-02a/05a の複合。
- **テスト**: `test_approve_other_tenant_method_rejected`（xfail、状態不変も検証）。

### DEF-05d — 作成者の偽装
- **症状**: `MethodCreateRequest.created_by` がボディ由来でそのまま保存される。
- **根拠**: `src/schemas/__init__.py:255` / `src/api/methods.py:42` / `construction_service.py:336-341`。
- **影響**: 監査時に「誰が作ったか」を詐称できる（証跡の信頼性）。
- **テスト**: `test_create_method_created_by_is_token_derived`（xfail）。

### DEF-06a — `actual_quantity == 0` のフォールバック
- **症状**: `qty = float(resource.actual_quantity or resource.planned_quantity or 0)` のため、
  実績 0 が偽値として扱われ計画数量で計算される。
- **再現手順**: `_calculate_resource_total_cost(Resource(actual_quantity=Decimal("0"), planned_quantity=Decimal("30"), unit_cost=Decimal("100")))`
  → `total_cost == 3000.0`（期待 0）。
- **根拠**: `src/services/construction_service.py:234`。
- **影響**: 未消化の実績 0 が計画値で水増しされ、原価が過大計上される。
- **テスト**: `test_total_cost_zero_actual_is_not_replaced_by_planned`（xfail）。

### DEF-06b — 作成時に `total_cost` を計算しない
- **症状**: `create_resource` は `total_cost` を計算しないため、`planned_quantity`/`unit_cost` を入れても `None`。
  一方 `update_resource` は再計算する（非対称）。
- **再現手順**: `POST /resources`（planned 30 / unit 25000 / total_cost 未指定）→ 保存実体の `total_cost is None`。
- **根拠**: `src/services/construction_service.py:138-143`（計算なし）vs `:190`（更新時は計算）。
- **影響**: 作成直後の資源は原価が未確定。原価集計・帳票が欠損する。
- **テスト**: `test_create_resource_computes_total_cost`（xfail）＋ 更新の正の対照（pass）。

### DEF-07a/b/c — WBS ツリー子ノードのテナント混入
- **症状**: `build_wbs_tree` はルートを組織で絞るが、`_build_subtree` → `get_wbs_children(db, node.id)` に組織を渡さない。
  `/wbs/{id}/children` も同様。
- **再現手順**: root(ORG_A) と child(ORG_B) を用意し `/wbs/tree?project_id=...` →
  子ノード取得 SQL の WHERE に `organization_id` がなく、応答 `children[].organization_id` に `...00bb` が現れる。
- **根拠**: `src/services/construction_service.py:113-114,78-82` / `src/api/wbs.py:122`。
- **影響**: 他テナントの WBS 名称・原価・進捗がツリーで漏えい。ルートは防御済みなのに子で破れる**非対称**。
- **テスト**: `TestH7WbsTreeChildTenantLeak` 3件（xfail）。

### DEF-08a — 進捗率の範囲検証漏れ
- **症状**: `PATCH /wbs/{id}/progress` は `ge=0, le=100` を強制するが、`PUT /wbs/{id}`（`WBSUpdateRequest`）は無制約。
- **再現手順**: `PUT /wbs/{id}` body `{"progress_percent": "150"}`（および `"-5"`）→ 200。
- **根拠**: `src/schemas/__init__.py:44-45`（PATCH は制約あり）vs `:28-41`（`WBSUpdateRequest` は制約なし）/ `src/services/construction_service.py:68-75`。
- **影響**: 進捗 150% など不正な状態が保存され、出来高・原価計算が破綻する。
- **テスト**: `TestBoundaryValidationQ8` 2件（xfail）。

### OBS-01 — 却下の証跡欠落
- `reject_method` は `status="draft"` に戻すだけで、却下者・却下理由を記録しない。
  `MethodStatement` に `rejected_by` / `rejection_reason` 列が存在しない（`src/models/__init__.py:147-186`）。
- 影響: 承認フローの否認・差戻しの説明責任が果たせない。**証跡欠落**（CHARTER High）。
- ただし却下理由の要否は仕様に明記が見当たらないため **人の確認が必要**。テストは追加していない（未確認として計上）。

### OBS-02 — 原価の定義が二重
- `get_resource_cost_summary` は `sum(actual_quantity * unit_cost)`（実績のみ）。
  `_calculate_resource_total_cost` は実績が無ければ計画を使う。
  → 同一資源に対して「実績 0 円」と「計画額」の 2 種類の原価が併存し得る。
- 根拠: `construction_service.py:212-217` vs `:233-236`。どちらが正かは**仕様未定義** → 人の確認が必要。

### OBS-03 — デッドパラメータ
- `GET /wbs` は `organization_id` クエリを宣言するが無視して `_org_id(user)` を使う（`src/api/wbs.py:43,53`）。
- セキュリティは保たれるが、API 契約として紛らわしい（Low）。テスト `test_wbs_list_uses_token_org_ignoring_query` が pass で挙動を固定。

---

## 5. 最小修正の差分要約（DEF-05a のみ）

対象: `services/construction/src/api/methods.py` / `services/construction/src/schemas/__init__.py`

```
+def _actor_id(user: TokenData) -> UUID:
+    """トークンの sub から操作者を同定する（ボディ由来の値は信用しない）。"""
+    try:
+        return UUID(user.sub)
+    except (TypeError, ValueError):
+        raise HTTPException(status_code=403, detail={...INVALID_IDENTITY...})

 async def approve_method(
     method_id: UUID,
-    body: MethodApprovalRequest,
+    _body: MethodApprovalRequest | None = None,
     db: AsyncSession = Depends(get_db),
-    _user: TokenData = Depends(get_current_user),
+    user: TokenData = Depends(get_current_user),
 ):
     ...
-    return await construction_service.approve_method(db, method, body.approved_by)
+    # 承認者同定はトークン由来（_body.approved_by は後方互換のため受理のみ）。
+    return await construction_service.approve_method(db, method, _actor_id(user))

 # schemas
 class MethodApprovalRequest(BaseModel):
-    approved_by: UUID
+    # 後方互換のため受理するが、承認者同定には使用しない（トークン由来に変更）。
+    approved_by: UUID | None = None
```

- **互換性**: 既存クライアントは `approved_by` を送り続けられる（無視される）。ボディなしの承認も可能になった。
- **波及なし**: 変更は `src/api/methods.py` と `schemas` の `MethodApprovalRequest` のみ。他ルーター・他サービスに影響しない。
- **既存テストへの追随（緩和ではなく是正）**: `tests/test_construction.py`
  - fixture の `sub="test-user-id"` を UUID（`...00cc`）へ変更（`sub` は仕様上 user-uuid）。
  - `test_approve_method` は「ボディの別人を承認者として記録する」という**脆弱な挙動を固定していた**ため、
    「トークン由来の承認者を記録し、ボディ指定は採用しない」へ**強化**した。
  - skip 追加・削除・アサーション緩和はしていない。修正後も既存 26 件は全件 pass。

`git diff --stat -- services/construction`:
```
 src/api/methods.py         | 21 ++++++++++++++++++---
 src/schemas/__init__.py    |  3 ++-
 tests/test_construction.py | 11 +++++++----
```

---

## 6. 未確認事項・残課題（成功と書かない）

1. **承認に必要なロール名が未定義**（DEF-05b）。承認権限マトリクスが仕様に見当たらないため、ロール検査は**実装していない**。人の判断が必要。
2. **却下の証跡要件が未確認**（OBS-01）。却下理由・却下者を必須とするかは仕様判断。
3. **原価の正定義が未確認**（OBS-02 / DEF-06a）。「実績優先・計画フォールバック」と「実績のみ」のどちらが正か。
4. **API Gateway / 監査基盤側の防御は未検証**。本サービスのアプリ層では遮断がないことは確認済みだが、
   上流（`docs/architecture/03-api-gateway.md`）でテナント強制しているかは未確認。
5. **実 DB（PostgreSQL 55432）での統合検証は未実施**。本報告の DB は `AsyncMock` であり、
   実 DB のスキーマ/権限/RLS 挙動は Lead の統合検証に委ねる（migration に RLS が無いことは静的に確認済み）。
6. **他サービスへの横展開は未実施**。同型の `organization_id` クエリが 40 超の API にあることは確認したが、
   construction 以外は本タスクの write scope 外。
7. `pytest` の `PytestDeprecationWarning: asyncio_default_fixture_loop_scope` が出る（既存設定、機能影響なし）。
8. 本報告の xfail 31 件は**未修正の欠陥**であり、成功ではない。`skip` は 0 件。

---

## 7. 再現コマンド

```bash
cd services/construction
# 全件
python3 -m pytest tests/ -q -p no:cacheprovider

# 欠陥が本物かを確認（xfail を通常実行して失敗理由を見る）
python3 -m pytest tests/test_quality_tenant_isolation.py -q -p no:cacheprovider --runxfail
python3 -m pytest tests/test_quality_calculation_approval.py -q -p no:cacheprovider --runxfail
```
