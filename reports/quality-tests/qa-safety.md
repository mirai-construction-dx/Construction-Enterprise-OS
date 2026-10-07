# 安全管理（safety）品質テスト報告（task-9 / 担当: qa-field-spatial）

対象: `services/safety`（危険予知 hazards / 安全巡視 inspections / 事故 incidents）
準拠: [reports/quality-tests/CHARTER.md](reports/quality-tests/CHARTER.md)（全制約）
参照実装: `services/workflow/src/api/cases.py`, `services/workflow/src/api/workflows.py`（task-9 指定）

---

## 1. サマリ

| 区分 | 件数 |
|---|---|
| 変更前ベースライン（既存テスト） | **19 passed** |
| 追加テスト | **46** |
| 追加テストのうち pass | 15 |
| 追加テストのうち **fail（= 検出欠陥）** | **31** |
| 検出欠陥（DEF-SAF-01〜33） | **33**（うち **2 件を最小修正で解消**、31 件は報告） |
| skip | **0** |

最終実行の実出力:

```
$ cd services/safety && python3 -m pytest tests/ -q -p no:cacheprovider
31 failed, 34 passed, 1 warning in 3.56s
```

* **fail 31 件はすべて「欠陥を検出するために仕様準拠の期待値を assert したテスト」の失敗**であり、
  テストの誤り・環境不備ではない（各 docstring に欠陥IDと根拠 `ファイル:行` を明記）。
* 既存テストは 1 件も変更・削除・skip 追加していない（回帰確認: **19 passed**）。
* 最小修正 2 件を適用し、対応する 2 テストが pass に転じた（§6）。
* **テナント境界・行為者同定・状態遷移の修正は行っていない**（API 契約とロール要件の確定が前提のため。§6・§8）。

### 最重要（Critical）
1. **一覧・個別取得・更新・完了・統計のほぼすべてに organization 条件が無い**（DEF-SAF-01〜12）。
   クエリ `?organization_id=<他社>` の値がそのまま検索条件になる（バインド値で実証）。
2. **報告者・調査担当者・実施者がすべてリクエストボディ由来**でなりすませる（DEF-SAF-18〜22）。
3. **`get_db` が commit しないため、作成/更新が一切永続化されない**（DEF-SAF-33 → **修正済み**）。

---

## 2. 重点観点①〜⑥の判定

| # | 観点 | 判定 | 根拠 |
|---|---|---|---|
| ① | 一覧・個別取得がクエリ `organization_id` 依存でないか | **依存している（欠陥）** | 一覧 3 種の WHERE 句から organization 条件が欠落（DEF-SAF-01〜03）、個別取得は id のみ（DEF-SAF-06/07）。クエリ値がそのままバインドされる（DEF-SAF-05） |
| ② | 作成時の `organization_id` がボディ由来でないか | **ボディ由来（欠陥）** | 3 作成 API すべて `body.organization_id` を保存（DEF-SAF-15〜17）。参照実装 `cases.py:80-82` は token.org 不一致を 403 で拒否 |
| ③ | `reported_by` / `investigated_by` がボディ由来でないか | **ボディ由来（欠陥）** | `incidents.py:56`（reported_by）, `:119`（investigated_by）, `hazards.py:51`, `inspections.py:53/121`（inspector_id）= DEF-SAF-18〜22 |
| ④ | `complete` の実行者・実施日・証跡 | **記録されない / 二重実行可（欠陥）** | `safety_service.py:117-135` は inspector_id も inspection_date も更新せず、status を無条件上書き（DEF-SAF-23〜26）。`InspectionComplete` に実施者・実施日の入力も無い |
| ⑤ | `hazards` の severity / status 遷移と境界値 | **語彙未定義・遷移ガードなし（欠陥）** | severity/risk_level は自由文字列（DEF-SAF-27/28）、closed→reported の差し戻し可（DEF-SAF-29）、`resolved` で `resolved_at` 未設定（DEF-SAF-30）、未クローズ判定が `closed` のみ（DEF-SAF-31） |
| ⑥ | `inspections/stats` の計算再現性 | **決定性・ゼロ除算は OK。ただし欠測と 0 の混同（欠陥）** | 同一入力→同一出力・0 件でも例外なし（検証済）。平均 0.0 が null になる（DEF-SAF-32 → **修正済み**）。加えて集計が全テナント横断（DEF-SAF-12） |

---

## 3. 実行コマンドと実出力（証跡）

### 3.1 変更前ベースライン

```
$ cd services/safety && python3 -m pytest tests/ -q -p no:cacheprovider
19 passed, 1 warning in 1.99s
```

### 3.2 追加テスト込みの最終実行

```
$ cd services/safety && python3 -m pytest tests/ -q -p no:cacheprovider
31 failed, 34 passed, 1 warning in 3.56s
```

### 3.3 既存テストのみの回帰確認（無破壊の証跡）

```
$ cd services/safety && python3 -m pytest tests/test_safety.py tests/test_health_readiness.py tests/test_jwt_key_resolution.py -q -p no:cacheprovider
19 passed, 1 warning in 1.87s
```

### 3.4 最小修正で解消した 2 件のみを実行

```
$ cd services/safety && python3 -m pytest tests/test_quality_safety_workflow.py::TestInspectionStatsDefects tests/test_quality_safety_workflow.py::TestPersistenceDefects -q -p no:cacheprovider
2 passed, 1 warning in 1.51s
```

### 3.5 代表的な失敗メッセージ（欠陥の直接証拠）

```
テナント絞り込みなし / actual WHERE = ''
報告者が body 由来: reported_by=00000000-0000-0000-0000-0000000000ff (トークン sub=00000000-0000-0000-0000-0000000000dd)
未クローズ判定の除外語彙が ['closed'] のみ（resolved が除外されない）
完了操作の実施者が記録されていない: inspector_id=00000000-0000-0000-0000-0000000000cc (トークン sub=00000000-0000-0000-0000-0000000000dd)
確定済み巡視の再完了を受理した: status=200, 結果=failed, score=10
再完了で findings が上書きされた: findings=None
```

---

## 4. 追加テスト一覧

| ファイル | クラス | 件数 | 内容 |
|---|---|---|---|
| `services/safety/tests/test_quality_tenant_isolation.py` | `TestTenantScopingDefects` | 14 | 一覧 4 種・個別取得 2 種・更新 3 種・完了・統計のテナント境界、クエリ org 越境、org クレーム検証 |
| 同上 | `TestCreateOrgSourceDefects` | 3 | 作成 body の organization_id |
| 同上 | `TestActorIdentityDefects` | 5 | reported_by / investigated_by / inspector_id の出所 |
| 同上 | `TestTenantIsolationVerified` | 4 | 未認証 401、非 user トークン 403、JWT 鍵解決、hazards 個別取得 API 不在の記録 |
| `services/safety/tests/test_quality_safety_workflow.py` | `TestInspectionCompleteDefects` | 4 | 実行者・実施日の証跡、二重 complete、findings 消失 |
| 同上 | `TestHazardStateDefects` | 5 | severity / risk_level / status 遷移 / resolved_at / 未クローズ判定 |
| 同上 | `TestInspectionStatsDefects` | 1 | 平均 0.0 の欠測化 |
| 同上 | `TestPersistenceDefects` | 1 | `get_db` の commit 欠落 |
| 同上 | `TestWorkflowVerified` | 9 | 正常系 complete、スコア境界値（0/100 と -1/101）、ゼロ除算、決定性・丸め、resolved_at、例外時 rollback |

---

## 5. 欠陥一覧

重大度は CHARTER §5 に準拠。

### 5.1 テナント分離・権限境界（Q1 / Q2）

| ID | 症状 | 再現手順 | 根拠（ファイル:行） | 重大度 | 影響 | 修正 |
|---|---|---|---|---|---|---|
| DEF-SAF-01 | 危険予知一覧が全テナント横断 | org=A のトークンで `GET /api/v1/safety/hazards` → WHERE が空 | `src/api/hazards.py:62`, `src/services/safety_service.py:220-221` | Critical | 他社のヒヤリハットが閲覧可能 | なし |
| DEF-SAF-02 | 安全巡視一覧が全テナント横断 | `GET /inspections` → WHERE に org なし | `src/api/inspections.py:64`, `safety_service.py:57-58` | Critical | 他社の点検記録が閲覧可能 | なし |
| DEF-SAF-03 | 事故一覧が全テナント横断 | `GET /incidents` → WHERE に org なし | `src/api/incidents.py:69`, `safety_service.py:336-337` | Critical | 他社の事故・労災情報が閲覧可能（特に機微） | なし |
| DEF-SAF-04 | 未クローズ危険予知は org 条件を一切持たない | `GET /hazards/open` | `src/api/hazards.py:83-89`, `safety_service.py:241-246` | Critical | 全社の未対応リスクが漏洩 | なし |
| DEF-SAF-05 | クエリ `organization_id` で他テナントを選択できる | `GET /hazards?organization_id=<B>` → バインド値が B | `hazards.py:62`, `inspections.py:64`, `incidents.py:69` | Critical | 1 パラメータで越境読み取り | なし |
| DEF-SAF-06 | 他テナントの巡視を ID 指定で取得 | `GET /inspections/{他社id}` → 200 | `inspections.py:94-106`, `safety_service.py:70-75` | Critical | 越境読み取り | なし |
| DEF-SAF-07 | 他テナントの事故を ID 指定で取得 | `GET /incidents/{他社id}` → 200 | `incidents.py:90-102`, `safety_service.py:349-354` | Critical | 越境読み取り | なし |
| DEF-SAF-08 | 他テナントの危険予知を更新 | `PUT /hazards/{id}` → 200 | `hazards.py:92-115`, `safety_service.py:262-263` | Critical | 越境書き込み | なし |
| DEF-SAF-09 | 他テナントの巡視を更新 | `PUT /inspections/{id}` → 200 | `inspections.py:109-134` | Critical | 越境書き込み | なし |
| DEF-SAF-10 | 他テナントの巡視を完了（合否確定） | `POST /inspections/{id}/complete` → 200 | `inspections.py:137-157` | Critical | 他社の安全点検結果を確定・改変 | なし |
| DEF-SAF-11 | 他テナントの事故を更新 | `PUT /incidents/{id}` → 200 | `incidents.py:105-131` | Critical | 越境書き込み | なし |
| DEF-SAF-12 | 巡視統計が全テナント横断で集計 | `GET /inspections/stats` → 4 クエリすべて org 条件なし | `inspections.py:85-91`, `safety_service.py:138-170` | Critical | 全社の安全成績が漏洩・経営指標が汚染 | なし |
| DEF-SAF-13 | org クレームを持たないトークンを受理 | org なしトークンで `GET /hazards` → 200 | 参照実装 `workflow/src/api/workflows.py:93-101` は 403 `ORG_REQUIRED` | Critical | 組織未所属トークンが全社情報を閲覧 | なし |
| DEF-SAF-14 | 不正な org クレーム（非 UUID）を受理 | `org="not-a-uuid"` で `GET /hazards` → 200 | 参照実装 `workflows.py:102-108` は 403 `ORG_INVALID` | Medium | 組織帰属が不正なトークンを素通し | なし |
| DEF-SAF-15 | 危険予知作成で body の org を無検証採用 | `POST /hazards` に他社 org → 201 | `hazards.py:43-56`, `schemas/__init__.py:53`；参照実装 `cases.py:80-82` | Critical | 他社テナント宛の書き込み | なし |
| DEF-SAF-16 | 安全巡視作成で body の org を無検証採用 | `POST /inspections` に他社 org → 201 | `inspections.py:48-58`, `schemas/__init__.py:21` | Critical | 同上 | なし |
| DEF-SAF-17 | 事故作成で body の org を無検証採用 | `POST /incidents` に他社 org → 201 | `incidents.py:48-63`, `schemas/__init__.py:79` | Critical | 同上（労災記録の混入） | なし |

### 5.2 行為者の同定（Q6 承認・証跡）

| ID | 症状 | 再現手順 | 根拠（ファイル:行） | 重大度 | 影響 | 修正 |
|---|---|---|---|---|---|---|
| DEF-SAF-18 | 事故の報告者が body 由来 | `POST /incidents` の `reported_by` に他人 → その値で保存 | `incidents.py:56`, `safety_service.py:317`；参照実装 `cases.py:85` | Critical | 報告者のなりすまし（Q6） | なし |
| DEF-SAF-19 | 事故の調査担当者が body 由来 | `PUT /incidents/{id}` の `investigated_by` に他人 → 保存 | `incidents.py:119`, `safety_service.py:385` | Critical | 調査記録の否認不能性が破綻 | なし |
| DEF-SAF-20 | 危険予知の報告者が body 由来 | `POST /hazards` の `reported_by` に他人 | `hazards.py:51`, `safety_service.py:200` | Critical | 報告者のなりすまし | なし |
| DEF-SAF-21 | 巡視の実施者が body 由来（作成時） | `POST /inspections` の `inspector_id` に他人 | `inspections.py:53`, `safety_service.py:37` | Critical | 実施していない者を実施者として記録 | なし |
| DEF-SAF-22 | 巡視の実施者を body で差し替え可能（更新時） | `PUT /inspections/{id}` の `inspector_id` | `inspections.py:121`, `safety_service.py:98-99` | Critical | 実施者の事後差し替え＝証跡の改変 | なし |

### 5.3 巡視 complete の証跡・二重実行（Q6 / Q8）

| ID | 症状 | 再現手順 | 根拠（ファイル:行） | 重大度 | 影響 | 修正 |
|---|---|---|---|---|---|---|
| DEF-SAF-23 | complete しても実行者（inspector_id）が記録されない | トークン sub=A で complete → inspector_id は作成時のまま | `inspections.py:137-157`, `safety_service.py:117-135`, `schemas/__init__.py:43-47` | High | 「誰が完了させたか」の証跡が無い | なし |
| DEF-SAF-24 | complete しても実施日（inspection_date）が記録されない | 実施日なしで作成 → complete → 応答は `null` | `safety_service.py:117-135`, `inspections.py:56` | High | 点検の実施日が残らない | なし |
| DEF-SAF-25 | 二重 complete を拒否せず、確定済みの合否を巻き戻せる | `status="passed"` の巡視に `is_safe=false` で complete → 200 / `"failed"` に上書き | `safety_service.py:125-135`（status を検証しない） | High | 安全点検結果を後から改変でき、是正記録の否認不能性が破綻 | なし |
| DEF-SAF-26 | 二重 complete で既存 findings が None 上書きされ証跡が消える | findings 付きで complete → findings なしで再 complete → `null` | `safety_service.py:130`（None でも無条件代入）, `schemas/__init__.py:45` | High | 指摘事項の証跡消失 | なし |

補足: `complete` に状態ガードが無いため、`status` が自由文字列（値域検証なし）であることと相まって
「どの状態からでも完了でき、何度でも上書きできる」状態になっている（DEF-SAF-25）。

### 5.4 危険予知の語彙・状態遷移（Q8）

| ID | 症状 | 再現手順 | 根拠（ファイル:行） | 重大度 | 影響 | 修正 |
|---|---|---|---|---|---|---|
| DEF-SAF-27 | `severity` が自由文字列で値域検証なし | `POST /hazards` `severity="__invalid__"` → 201 | `schemas/__init__.py:60`, `safety_service.py:199` | Medium | 重大度の表記ゆれで絞り込み・集計が破綻 | なし（**語彙の確定は人の確認が必要**） |
| DEF-SAF-28 | `risk_level` も自由文字列 | `POST /hazards` `risk_level="__invalid__"` → 201 | `schemas/__init__.py:59` | Medium | 同上 | なし（同上） |
| DEF-SAF-29 | status 遷移ガードが無くクローズ済みを差し戻せる | `status="closed"` の hazard を `"reported"` に更新 → 200、resolved_at は残置 | `safety_service.py:269-272`, `schemas/__init__.py:69` | High | 是正完了記録の取消が痕跡なく行える | なし |
| DEF-SAF-30 | `status="resolved"` で `resolved_at` を設定しない（incidents と非一貫） | hazard を `"resolved"` に更新 → `resolved_at` は `None` | `safety_service.py:271-272` vs `:380-381`（incidents は resolved/closed 両方） | Medium | 終端状態の判定が不安定 | なし（どちらの語彙が正かは未確認） |
| DEF-SAF-31 | 未クローズ一覧の除外語彙が `closed` のみ | `GET /hazards/open` の除外リストが `['closed']` | `safety_service.py:244` | Medium | 解決済みが「未対応」として残る | なし（同上） |

### 5.5 集計・永続化（Q3 / Q8）

| ID | 症状 | 再現手順 | 根拠（ファイル:行） | 重大度 | 影響 | 修正 |
|---|---|---|---|---|---|---|
| DEF-SAF-32 | 平均点 0.0 が null（欠測）になる | 統計の平均が 0.0 → `average_score: null` | `safety_service.py:169` `if avg_score`（0.0 は falsy） | Medium | 全点検 0 点の現場で「データ無し」と誤表示 | **修正済み**（§6） |
| DEF-SAF-33 | `get_db` が commit せず、書き込みが永続化されない | `get_db` を駆動 → commit が 0 回、close で暗黙ロールバック | `src/models/base.py:27-35`（commit 無し）。`services/safety/src` 全体で `commit()` 呼び出しゼロ | Critical | POST/PUT が 201/200 を返しても DB に反映されずデータ消失 | **修正済み**（§6） |

---

## 6. 修正差分の要約

**適用した最小修正は 2 件のみ**（いずれも 1 行規模、リポジトリ内の多数派規約に一致する自明な修正）。

```
services/safety/src/models/base.py             | 3 +++
services/safety/src/services/safety_service.py | 4 +++-
2 files changed, 6 insertions(+), 1 deletion(-)
```

### 6.1 DEF-SAF-33: `get_db` の commit 欠落（Critical）

```diff
 async def get_db() -> AsyncGenerator[AsyncSession, None]:
     async with async_session() as session:
         try:
             yield session
+            # 17サービス（field-dx/gis/bim 等）と同じくリクエスト正常終了時に確定する。
+            # これが無いと close() 時に暗黙ロールバックされ、flush 済みの書き込みが失われる。
+            await session.commit()
         except Exception:
             await session.rollback()
             raise
```

* 根拠: 22 サービス中 **17 サービス**が `get_db` 内で `await session.commit()` を実行し、
  safety を含む 5 サービス（maintenance / safety / security / vision / workflow）だけが commit していなかった。
  `async_sessionmaker(..., expire_on_commit=False)` も commit 前提の設定である。
* 修正後: `tests/...::TestPersistenceDefects::test_defect_get_db_never_commits_the_transaction` が pass。
* **残課題（他担当領域）**: 同じ欠落が `maintenance` / `security` / `vision` / `workflow` に残っている（本タスクの write scope 外）。

### 6.2 DEF-SAF-32: 平均 0.0 の欠測化（Medium）

```diff
-        "average_score": round(float(avg_score), 2) if avg_score else None,
+        # 平均 0.0 は falsy のため ``if avg_score`` では欠測(None)と区別できない。
+        # 欠測は avg_score is None の場合のみ。
+        "average_score": round(float(avg_score), 2) if avg_score is not None else None,
```

* 修正後: `tests/...::TestInspectionStatsDefects::test_defect_average_score_zero_becomes_null` が pass。

### 6.3 修正しなかった欠陥（人の確認が必要）

以下は **API 契約・ロール要件・語彙定義の確定が前提**のため、テストを通すために条件を緩めることなく報告に留めた。

| 対象 | 修正に必要な確認事項 |
|---|---|
| DEF-SAF-01〜12（テナント分離） | トークン `org` → `organization_id` の導出規則、クエリ `organization_id` の後方互換（廃止 or 一致検証）、管理者/協力会社のクロステナント参照可否、ロール要件 |
| DEF-SAF-13/14（org クレーム検証） | org を持たないトークン（M2M・協力会社）の扱い |
| DEF-SAF-15〜17（body org） | 既存クライアントの互換性（参照実装は 403 だが、廃止か一致検証かの選択） |
| DEF-SAF-18〜22（行為者） | 「誰が報告・調査・実施できるか」のロール定義。代理登録の要否 |
| DEF-SAF-23〜26（complete の証跡・二重実行） | 状態遷移図（scheduled→in_progress→passed/failed）と、再完了の許容範囲、実施日の記録規則 |
| DEF-SAF-27〜31（severity/status 語彙） | 正規語彙（severity / risk_level / status）と許容遷移の定義 |
| DEF-SAF-12 の統計仕様 | テナント別集計の定義、`total` に対する内訳（scheduled/in_progress が返らない点） |

---

## 7. 検証済み（現状で仕様を満たす）事項

* **認証境界**: 未認証 401、`type != user` 403（HTTP で確認）。不正トークン 401。
* **JWT 鍵解決**: `settings.jwt_public_key` 経由で解決され、他サービスと同一鍵で検証できる
  （既存 `tests/test_jwt_key_resolution.py` の修正が回帰テストで担保されている）。
* **巡視 complete の正常系**: `is_safe=True/False` が `status=passed/failed` に正しく反映される。
* **スコア境界値**: `score=0` と `100` は受理、`-1` と `101` は 422 で DB に到達しない（`schemas/__init__.py:39,47`）。
* **集計のゼロ除算耐性**: 0 件でも `total/passed/failed=0`、`average_score=null` を返し例外にならない。
* **集計の決定性と丸め**: 同一入力→同一出力、平均は `round(x, 2)` で小数 2 桁。
* **`get_db` の異常時 rollback**: 例外送出時に rollback が 1 回呼ばれる（復旧経路自体は機能）。
* **hazard の `closed`**: `resolved_at` が記録される（正常系）。

---

## 8. 未確認・未実装・残課題

**未確認（資料が無く断定しない。創作しない）**

1. **巡視の状態遷移語彙**: `scheduled / in_progress / passed / failed` 等を定義したリポジトリ内資料は発見できず。
   したがって「どの遷移を禁じるべきか」は断定せず、**遷移ガードが存在しないこと**のみを欠陥として報告した。
2. **severity / risk_level / status の正規語彙**: 列挙定義が無い（`schemas/__init__.py` は長さ制約のみ）。
3. **`resolved` と `closed` の使い分け**（hazard / incident 間の非一貫。DEF-SAF-30/31）。
4. **統計の丸め規約**（小数 2 桁は実装値であり、仕様としての裏付けは未確認）。
5. **代理報告の可否**（行為者をトークン sub に固定した場合、代理入力の業務要件があるかは未確認）。
6. **ロール要件**: `roles` は middleware で取得されるが、safety の全エンドポイントで一切参照されていない
   （`safety_admin` 等の要求が無い）。必要ロール名の定義資料が無いため **人の確認が必要**。

**未実装（欠陥ではなく機能不在として報告）**

7. 危険予知には個別取得 API が存在しない（`GET /hazards/{id}` は 405）。
   → 重点観点①のうち「危険予知の個別取得テナント境界」は **検証対象なし（該当なし）**。
8. 状態遷移・操作の履歴（監査ログ）テーブルが無い。参照実装 workflow は `record_audit_log` を持つ
   （`services/workflow/src/api/cases.py:92-96`）が、safety には相当する記録が無い（Q6 証跡の欠落）。

**残課題（環境・横断）**

9. 同一の `get_db` commit 欠落が **maintenance / security / vision / workflow** の 4 サービスに残存
   （本タスクの write scope 外。横断的な修正の要否は Lead 判断）。
10. 実 PostgreSQL は本タスクでは使用していない（全テストが mock + `dependency_overrides`）。
    QA 用 DB には `safety` スキーマが存在しないため（`pg_namespace` は `public` / `information_schema` / `construction` のみ）、
    実 DB 結合検証は **未実施**。
11. テナント分離・行為者同定の修正後は、3 種の一覧/取得が「トークン org のみ返す」ことを
    実 DB で結合検証する必要がある（未実施）。

---

## 9. 制約順守の確認

| 制約 | 状態 |
|---|---|
| 書込みは担当 scope のみ | 遵守（`services/safety/tests/**` に新規 2 ファイル、`services/safety/src/**` に最小修正 2 件、`reports/quality-tests/qa-safety.md`） |
| `git add/commit/checkout/stash` 禁止 | 未実行（`git status` / `git diff` は参照のみ） |
| 既存テストを壊さない／緩和・skip・削除しない | 遵守（既存 19 passed を維持。既存ファイルは未変更） |
| 承認条件・状態遷移・テナント境界を緩めてテストを通さない | 遵守（テナント・行為者・遷移のテストは **失敗のまま** 報告。緩和していない） |
| 仕様が不明な修正は実施しない | 遵守（語彙・ロール要件・遷移定義を要する修正は未実施とし §6.3 に列挙） |
| 他サービスの未コミット変更を保持 | 遵守（`services/workflow` 等は参照のみ。`git diff` に safety 以外の変更なし） |
| synthetic fixture のみ／外部接続なし | 遵守（UUID は `00000000-…-0000000000xx`、全テストが mock。ネットワーク・DB 接続なし） |
| 未実行・skip・未確認を成功と書かない | 遵守（skip 0。fail 31 を欠陥として明記。未確認は §8 に列挙） |
| 並列実行時の `-p no:cacheprovider` | 全実行で付与 |
