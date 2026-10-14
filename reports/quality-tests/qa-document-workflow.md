# 🧪 品質テスト報告 — 文書管理フロー & 承認ワークフロー

| 項目 | 内容 |
|---|---|
| 担当 | `qa-docs-approval` (task-3) |
| 対象 | `services/document`, `services/workflow` |
| 作業ディレクトリ | `/home/kensan/Projects/Mirai-Construction-DX/Construction-Enterprise-OS` |
| 実行環境 | Python 3.12 / pytest 8.3.3 / fastapi TestClient (`httpx`) |
| 準拠 | `reports/quality-tests/CHARTER.md` 全制約 |
| 実データ | ❌ 未使用（synthetic fixture のみ。UUID は `00000000-...-0000000000aa` 形式） |
| 外部接続 | ❌ なし（MinIO/S3 は patch、通知 httpx は mock、実 DB 未使用） |
| git 操作 | ❌ `add`/`commit`/`checkout`/`stash` 未実施 |

---

## 1. 🎯 対象フロー

### 1.1 document（文書・図面版管理）
`POST /upload` → 版管理（`POST /{id}/versions`, `GET /{id}/versions`, `GET /{id}/versions/{n}`）
→ 取得（`GET /{id}`, `GET /{id}/download`）→ 内部API（`POST /internal/{id}/store-canonical`, `store-work-area`）

### 1.2 workflow（承認）
定義（`POST/PATCH/DELETE /definitions`）→ 起票（`POST /instances`）→ 提出（`/submit`, `/resubmit`）
→ 承認/却下（`/approve`, `/reject`, `/cancel`）→ 履歴（`GET /instances/{id}/history`, `WorkflowAuditLog`）
→ 通知（`notification_adapter`, `/internal/notification-callback`, `/internal/jobs/*`）

---

## 2. 🧾 テスト一覧（追加分）

### 2.1 `services/document/tests/test_quality_versions.py` — 18 tests
| クラス | 主な検証 | 対応仮説 |
|---|---|---|
| `TestVersionMonotonicity` | 版番号 1→2→3→4 の単調増加 / 重複アップロードでの非再利用・非巻き戻し / `current_version` 由来の採番 / soft delete 後の前進 / 一意索引のモデル・DDL 宣言 / 組織スコープ | H1, H2 |
| `TestStorageKeyPredictability` | UUID 成分・版セグメント / 組織・文書ごとの一意性 / `put_object` へのキー伝播 / 正本パスの無害化（対照） / **生キーの traversal 未処理（欠陥）** | H3 |
| `TestVersionEndpointBoundary` | 版 API の 401 / 版番号境界値 0・-1・999999 → 404 / トークン org の伝播 / 他組織文書 404 | H2 |

### 2.2 `services/document/tests/test_quality_approval_flow.py` — 30 tests
| クラス | 主な検証 | 対応仮説 |
|---|---|---|
| `TestTenantBoundary` | 認証必須 / `get`・`download`・`update`・`delete` の org 伝播 / 他組織 404 / **無権限での承認状態変更・削除（欠陥）** | H2, Q1 |
| `TestUploadValidation` | トークン identity 伝播 / 413（本編・版） / 保存失敗の fail-loud / **不正 tags・project_id・document_type・MIME（欠陥→一部修正）** | H5, Q8 |
| `TestInternalApiAuth` | キー欠落/誤り 403 / 未設定時 fail-closed / org ヘッダ不一致 403 / 一致時 200（対照） | H4 |

### 2.3 `services/workflow/tests/test_quality_approval_transitions.py` — 31 tests
| クラス | 主な検証 | 対応仮説 |
|---|---|---|
| `TestApprovalTransitions` | 途中承認で in_progress 維持 / 最終承認で approved + 履歴 / **二重承認拒否（2経路）** / 承認後却下拒否 / 却下の履歴・コメント / 非カレント step 拒否 / ロール不一致・ロール無し拒否 / 確定後拒否 / org スコープ | H6, H7 |
| `TestConcurrencyGap` | **行ロック不在の静的確認 + 競合白箱モデル（欠陥）** | H7 |
| `TestApprovalApi` | 認証必須 / 非 draft submit 400 / 非提出者 submit 400 / **admin でも step ロール無しは不可** / ロールベース承認の設計確認 / 二重承認 400 / 非カレント却下 400 / 確定後 cancel 400 / 却下→再提出の承認リセット / org 欠落 403 / 履歴オブジェクト記録 | H6, H7, H8 |

### 2.4 `services/workflow/tests/test_quality_audit_isolation.py` — 20 tests
| クラス | 主な検証 | 対応仮説 |
|---|---|---|
| `TestOrganizationIsolation` | クエリ `organization_id` 不一致 403 / トークン org 優先 / org 欠落・不正 403 / 他組織 404 / 無関係ユーザー 404 / management は閲覧可 | H9 |
| `TestAuditTrail` | 承認・却下の `WorkflowAuditLog` 追記（actor = トークン sub） / add のみ（delete なし） / 監査ログ改変ルートの不在 | H10 |
| `TestInternalJobAuth` | ジョブ 2 本の 403（欠落/誤り） / 未設定時 fail-closed / callback の 403 | H11 |
| `TestNotificationIdempotency` | callback の重複抑止（`recorded:false/duplicate:true`） / 冪等キーの決定性と式 / 未設定時は未送信 / 送信失敗でも例外を投げない | H12 |

---

## 3. ▶️ 実行コマンドと実出力（証跡）

### 3.1 document（全体）
```bash
cd services/document && python3 -m pytest tests/ -q -p no:cacheprovider
```
```
97 passed, 4 xfailed, 4 warnings in 4.11s
```

### 3.2 workflow（全体）
```bash
cd services/workflow && python3 -m pytest tests/ -q -p no:cacheprovider
```
```
92 passed, 1 xfailed, 1 warning in 4.05s
```

### 3.3 既存テストのみ（回帰確認 — 1 件も壊れていない）
```bash
cd services/document && python3 -m pytest tests/test_bucket_init.py tests/test_canonical_storage.py \
  tests/test_documents.py tests/test_health_readiness.py tests/test_internal.py tests/test_response_metadata.py \
  -q -p no:cacheprovider
# 53 passed, 1 warning in 2.50s          ← 変更前 baseline 53 passed と一致

cd services/workflow && python3 -m pytest tests/test_workflow.py tests/test_checks.py \
  tests/test_deadline_notifications.py tests/test_jwt_key_resolution.py \
  tests/test_response_metadata.py tests/test_workload_notifications.py -q -p no:cacheprovider
# 42 passed, 1 warning in 2.71s          ← 変更前 baseline 42 passed と一致
```

### 3.4 追加テストのみ
```
document: 44 passed, 4 xfailed, 4 warnings in 3.04s
workflow: 50 passed, 1 xfailed, 1 warning in 3.04s
```

### 3.5 件数整合
| サービス | 既存 (pass) | 追加 (pass) | 追加 (xfail=未修正欠陥) | 合計 (pass / xfail) |
|---|---|---|---|---|
| document | 53 | 44 | 4 | **97 / 4** |
| workflow | 42 | 50 | 1 | **92 / 1** |

> ⚠️ `xfail(strict=True)` は **成功でも skip でもない**。期待した正しい挙動が現状成立しない
> 「未修正の欠陥」の証跡である。`--runxfail` で実際の失敗内容を確認済み（§5 に引用）。
> コードが修正されると XPASS となり strict により失敗へ変わる（マーカー除去の強制）。

---

## 4. 🔍 必須仮説の判定

| ID | 仮説 | 判定 | 根拠テスト / 備考 |
|---|---|---|---|
| H1 | 版番号の単調増加・重複時の飛び/巻き戻り/再利用 | ✅ **正常** | `TestVersionMonotonicity` 6 件。`current_version + 1` 採番 ＋ DB 一意索引で保護 |
| H2 | document のテナント境界（get/versions/download） | ✅ **正常** | 全経路で `WHERE organization_id = <token org>`。他組織は 404 で存在を隠す |
| H3 | ストレージキーの推測可能性 | ⚠️ **一部欠陥** | UUID 成分で列挙困難（正常）だが file_name 未無害化（DOC-7） |
| H4 | `/internal/*` の認証 | ✅ **正常** | `secrets.compare_digest` ＋ key 未設定時 403 の fail-closed。org ヘッダも必須 |
| H5 | ダウンロード署名・サイズ/種別検証 | ⚠️ **一部欠陥** | サイズ 413 は正常。署名URLは不使用（ストリーム配信、有効期限面なし）。種別検証なし（DOC-6）。不正入力 500（DOC-3/4/5 → 修正済） |
| H6 | submit→approve/reject の状態遷移 | ✅ **正常** | 非 draft submit 400 / 非提出者 400 / 非カレント step 400 / 確定後 400 |
| H7 | 二重承認/二重却下・並行競合 | ⚠️ **逐次は正常 / 並行は欠陥** | 逐次 2 回目は 400 で拒否。同時実行の排他制御なし（**DOC/WF-1**） |
| H8 | `_require_management` の承認への適用 | ℹ️ **設計確認** | 承認/却下には `_require_management` は**適用されない**。ステップの `approver_role` とトークン `roles` の一致で判定。admin でも step ロールが無ければ拒否（昇格不可・回帰テストで固定） |
| H9 | `_organization_id`（トークン由来）の境界機能 | ✅ **正常** | クエリ `organization_id` は不一致で 403、欠落時はトークン org を使用。org 欠落/不正は 403 |
| H10 | `WorkflowAuditLog` の記録と不変性 | ✅ **正常** | actor はトークン `sub`。`db.add` のみ。監査ログを変更する HTTP ルートは存在しない |
| H11 | `require_internal_job_key` の無認証アクセス | ✅ **正常** | ジョブ 2 本・callback とも 403。`INTERNAL_JOB_API_KEY` 未設定時も 403（fail-closed） |
| H12 | 通知の冪等性 | ✅ **正常** | `workflow:{inst}:{transition}:{actor}:{recipient}` は決定的。callback は重複を `duplicate:true` で抑止 |

---

## 5. 🐞 欠陥表

**重大度**: Critical = テナント越境/認証回避/承認偽装・否認不能、High = 権限昇格/証跡欠落/データ破壊、
Medium = 境界値・異常系・再現性、Low = 表記/軽微、Info = 仕様未確定。

| ID | 症状 | 再現手順 | 根拠 (file:line) | 重大度 | 影響 | 修正 |
|---|---|---|---|---|---|---|
| **DOC-1** | 文書ステータスを任意ロールのトークンで `approved` にできる（承認の偽装） | `PUT /api/v1/documents/{id}` に `{"status":"approved"}` を `roles:[]`,`scopes:[]` のトークンで送信 → **200 OK**（期待 403） | `services/document/src/api/documents.py:244`（ロール検査なし）、`src/schemas/__init__.py:57-60`（status は pattern のみ） | **High** | 承認状態の偽装・改ざん。監査上「承認済み」が権限と無関係に成立 | ❌ なし（要件確定が必要） |
| **DOC-2** | 文書の削除に権限検査が無い | `DELETE /api/v1/documents/{id}` を `roles:[]` のトークンで送信 → **200 OK**（期待 403） | `services/document/src/api/documents.py:268` | **Medium** | 権限のない利用者による業務文書の消失（soft delete） | ❌ なし（要件確定が必要） |
| **DOC-3** | `tags` の不正 JSON が 500 になる | `POST /upload` に `tags={not-json` → **500**（期待 400） | 修正前 `documents.py:76`（`json.loads` が try 外） | Medium | クライアント入力不備が Internal Server Error に化け、原因切り分けが不能 | ✅ **修正済** |
| **DOC-4** | `project_id` の不正 UUID が 500 になる | `POST /upload` に `project_id=not-a-uuid` → **500**（期待 400） | 修正前 `documents.py:78` | Medium | 同上 | ✅ **修正済** |
| **DOC-5** | `document_type` が API 層で未検証（DB enum 到達まで素通し） | `POST /upload` に `document_type=not_a_document_type` → **200 OK**（期待 422）。実DBでは enum 違反 → `except Exception` が 500 化 | 修正前 `documents.py:50`（Form 引数に検証なし）、`src/models/__init__.py:44-54`（DB enum） | Medium | 不正値は 500。エラー内容が業務エラーとして扱えない | ✅ **修正済** |
| **DOC-6** | アップロードの MIME 種別検証（許可リスト）が無い | `POST /upload` に `application/x-msdownload` のファイル → **200 OK**（期待 415） | `documents.py:127`・`documents.py:308`（`file.content_type` を無検証で保存） | Medium | 実行形式等の持ち込み。ストレージ/配布面のリスク | ❌ なし（許可種別ポリシー未定義） |
| **DOC-7** | 生ストレージキーが `file_name` を無害化しない | `generate_storage_key(org, doc, 1, "../../etc/passwd")` → `.../v1/../../etc/passwd` が生成される | `services/document/src/services/storage_service.py:25-28` | Medium | オブジェクトキーへ擬似ディレクトリを注入可能。S3 はフラット名前空間のため越境には至らないが、キーをファイルパスへ写像する実装（OneDrive 連携等）では traversal になりうる。正本パス側は無害化済みで**不整合** | ❌ なし（キー形式変更は既存オブジェクト移行を伴うため要判断） |
| **DOC-8** | 版の同時アップロードで敗者が 500 になる | 同一文書へ版アップロードを並行実行（要 実DB） | `src/services/document_service.py:186`（`current_version + 1` を非ロックで読む）、`src/api/documents.py:321`（`except Exception` → 500） | Medium | データ破壊は無い（`ix_document_versions_document_id_version` 一意索引が阻止）が、409/リトライではなく 500 | ❌ なし・**実行時再現は未確認**（§7） |
| **WF-1** | 承認の排他制御が無く、同時 approve が双方成功しうる | 2 セッションが同一 pending 承認行を同時に読む（白箱モデルで再現） | `services/workflow/src/services/approval_service.py:21-34`（`_get_approval` に `FOR UPDATE` なし）、`:52-68`（`_get_scoped_instance` も同様） | **High** | 二重承認。`approver_id` / `approved_at` が後着で上書きされ、**誰が承認したかの証跡が不定**。`WorkflowStatusHistory` も二重記録されうる | ❌ なし・**実行時再現は未確認**（§7） |

### 5.1 xfail テストが示す実失敗内容（`--runxfail` の実出力）
```
E  AssertionError: 権限なしで承認状態へ遷移できてしまう
E  assert 200 == 403                                        # DOC-1
E  AssertionError: 権限なしで文書を削除できてしまう
E  assert 200 == 403                                        # DOC-2
E  AssertionError: 危険な MIME 種別が受理された
E  assert 200 == 415                                        # DOC-6
E  AssertionError: ストレージキーに path traversal が混入:
   '00000000-...-aa/00000000-...-dd/v1/../../etc/passwd'     # DOC-7
E  Failed: DID NOT RAISE <class 'ValueError'>                # WF-1（2回目の approve が成功）
```

---

## 6. 🛠 修正差分の要約

**修正は 1 ファイルのみ・最小限**（`services/document/src/api/documents.py`、+50 / -3）。
業務判定ロジック・承認条件・状態遷移は一切変更していない。

```diff
+ALLOWED_DOCUMENT_TYPES = frozenset({"pdf","cad","bim","photo","video","spreadsheet","other"})
+
-    parsed_tags = json.loads(tags) if isinstance(tags, str) else tags
-    parsed_metadata = json.loads(metadata) if isinstance(metadata, str) else metadata
-    parsed_project_id = UUID(project_id) if project_id else None
+    try:
+        parsed_tags = json.loads(tags) if isinstance(tags, str) else tags
+        parsed_metadata = json.loads(metadata) if isinstance(metadata, str) else metadata
+        parsed_project_id = UUID(project_id) if project_id else None
+    except (ValueError, TypeError):
+        raise HTTPException(400, {"code": "INVALID_REQUEST", ...}) from None
+
+    if not isinstance(parsed_tags, list):      raise HTTPException(400, {"code": "INVALID_TAGS", ...})
+    if parsed_metadata is not None and not isinstance(parsed_metadata, dict):
+        raise HTTPException(400, {"code": "INVALID_METADATA", ...})
+    if document_type not in ALLOWED_DOCUMENT_TYPES:
+        raise HTTPException(422, {"code": "INVALID_DOCUMENT_TYPE", ...})
```

| 欠陥 | 修正内容 | 検証 |
|---|---|---|
| DOC-3 | パース失敗を `400 INVALID_REQUEST` に。`tags`/`metadata` の型も検証（`INVALID_TAGS`/`INVALID_METADATA`） | `test_malformed_tags_returns_400`, `test_non_list_tags_returns_400`, `test_non_object_metadata_returns_400` ✅ |
| DOC-4 | UUID パース失敗を同じ `400 INVALID_REQUEST` に包含 | `test_invalid_project_id_returns_400` ✅ |
| DOC-5 | `document_type` を許可リストで検証し `422 INVALID_DOCUMENT_TYPE` に。許可リストが DB enum と乖離しない回帰テストを追加 | `test_invalid_document_type_is_rejected_with_422`, `test_allowed_document_types_match_db_enum` ✅ |

**未修正とした判断**:
- DOC-1 / DOC-2 は「誰が文書を承認・削除できるか」という**認可ポリシーの決定**が必要（仕様書に明記なし）。テストを通すために緩めるのではなく、要件確定後に実装すべきと判断。
- DOC-6 は MIME 許可リストという**ポリシー定義**が必要。
- DOC-7 はストレージキー形式の変更＝**既存オブジェクトの移行**を伴うため、単独判断を避けた。
- WF-1 は `with_for_update` 導入が実 DB でのデッドロック/性能に影響しうるため、Lead の統合検証と合わせて判断すべきと判断（CHARTER §「迷う修正はせず欠陥報告」に従う）。

---

## 7. ⚠️ 残課題・未確認事項（成功として扱わないもの）

| # | 未確認事項 | 理由 | 推奨する確認手順 |
|---|---|---|---|
| 1 | **WF-1 の実 DB 同時実行再現** | 実 PostgreSQL は Lead の統合検証用とされ、mock 主体の方針に従った。本報告の WF-1 は「行ロック不在の静的根拠 ＋ stale-snapshot 白箱モデル」であり、**実 DB での timing 再現は未実施** | `workflow` スキーマに definition/instance/approval を投入し、`asyncio.gather` で `approve_step` を 2 並行実行 → 双方 200・`approver_id` が後着で上書きされることを確認 |
| 2 | **DOC-8 の実 DB 同時実行再現** | 同上 | 同一 document へ `create_new_version` を 2 並行実行 → 一方が `IntegrityError` → 500 になることを確認（データ重複は起きないこと） |
| 3 | DOC-1 の**仕様上の期待値** | 「文書ステータス変更に必要なロール」が `docs/` に明記されていない。Q1/Q6 原則からの指摘であり、要件的に許容なら欠陥ではない | 要件確定 → ロール要件を明文化。`_require_management` 相当の適用範囲を決定 |
| 4 | DOC-6 の**許可 MIME リスト** | ポリシー未定義 | 建設書類（PDF/CAD/BIM/画像/表計算）の許可リストを定義し 415 で拒否 |
| 5 | DOC-7 の**実害評価** | S3 はフラット名前空間のため単独では越境不能。OneDrive/FS 写像経路での実害は未検証 | `canonical_storage` 以外で storage_key を実パスへ変換する実装の有無を全リポジトリで確認 |
| 6 | `download` の `Content-Length` 整合 | DB の `file_size` と実体バイト数が乖離した場合の挙動（クライアント側 truncate/hang）は未検証 | 実体差し替え時のレスポンスを実機で確認 |
| 7 | document の版番号**リトライ/409 設計** | DOC-8 の修正方針（409 or 自動リトライ）が未決定 | API 仕様として決定 |
| 8 | workflow `cases.py`（遷移 API 群） | 今回の対象は承認フローに限定。`cases.py` の 4 遷移は `_require_management` 適用を静的に確認したのみで、網羅テストは未実施 | 別タスクで `cases.py` の遷移・権限を網羅 |
| 9 | 通知の**実送信** | 方針どおり一律 mock。冪等キーの生成と重複抑止は検証済みだが、Notification サービス側の重複排除実装は未確認 | notification サービスの idempotency_key 実装を別途レビュー |

---

## 8. 🔁 証跡の再現方法

```bash
cd /home/kensan/Projects/Mirai-Construction-DX/Construction-Enterprise-OS

# 全体（報告の数値）
( cd services/document && python3 -m pytest tests/ -q -p no:cacheprovider )
( cd services/workflow && python3 -m pytest tests/ -q -p no:cacheprovider )

# 未修正欠陥の実失敗内容を確認（xfail を無効化）
( cd services/document && python3 -m pytest tests/ -q -p no:cacheprovider --runxfail -k defect )
( cd services/workflow && python3 -m pytest tests/ -q -p no:cacheprovider --runxfail -k defect )

# 追加テストのみ
( cd services/document && python3 -m pytest tests/test_quality_versions.py tests/test_quality_approval_flow.py -q -p no:cacheprovider )
( cd services/workflow && python3 -m pytest tests/test_quality_approval_transitions.py tests/test_quality_audit_isolation.py -q -p no:cacheprovider )
```

### 変更ファイル（write scope 内のみ）
| 種別 | パス |
|---|---|
| 追加テスト | `services/document/tests/test_quality_versions.py` |
| 追加テスト | `services/document/tests/test_quality_approval_flow.py` |
| 追加テスト | `services/workflow/tests/test_quality_approval_transitions.py` |
| 追加テスト | `services/workflow/tests/test_quality_audit_isolation.py` |
| 修正（最小） | `services/document/src/api/documents.py` (+50 / -3) |
| 本報告 | `reports/quality-tests/qa-document-workflow.md` |

> `services/workflow/src/**` は**未変更**（成熟度が高く、回帰テストによる固定を優先）。
> 既存テストの緩和・skip 追加・削除は一切行っていない（既存 53 + 42 件すべて pass を維持）。
