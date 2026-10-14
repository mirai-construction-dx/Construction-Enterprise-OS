# [🔍 QA-CrossAudit] CEOS 全24サービス横断 テナント分離・認可 実装棚卸し

対象: `/home/kensan/Projects/Mirai-Construction-DX/Construction-Enterprise-OS`
担当: `qa-crossaudit`（**読み取り専用**。`services/**`, `packages/**`, `docs/**`, `contracts/**` は一切変更していない）
根拠となる観点: CHARTER §3 Q1（権限境界）/ Q2（データ分離）/ Q6（承認・証跡）

## 0. 監査スナップショット（重要）

本監査は**実行中に他 teammate が同一ファイルを編集している最中**に取得した。数値は下記時点のスナップショットである。

- 測定時刻: **2026-10-07 08:34〜08:45 (Asia/Tokyo)**
- 監査中に `services/construction/src/api/methods.py` が **08:41:24 に変更された**（`git status` で ` M`）。
  08:39 時点の読みでは `approve_method` は `body.approved_by` を使用していたが、08:41 時点では
  `_actor_id(user)`（トークン由来）へ修正済み。**本レポートの construction 記載は 08:41 以降の状態**を用いた。
- `git status --porcelain` の変更/未追跡（20件）: `services/construction/src/api/methods.py`,
  `services/construction/src/schemas/__init__.py`, `services/construction/tests/test_construction.py`, `state.json`,
  `.omo/`, `.playwright-mcp/`, `reports/`, `scripts/quality/`,
  `services/{construction,document,erp,field-dx,workflow}/tests/test_quality_*.py` ほか。
  → **construction / document / erp / field-dx / workflow は他 teammate の作業が進行中**であり、
  本レポートの該当記載は陳腐化している可能性がある。

主要ファイルのスナップショット MD5（照合可能）:

| ファイル | MD5 |
|---|---|
| `services/advanced/src/api/predictive.py` | `b15fca57e2675679c99b5995be9550bd` |
| `services/safety/src/api/incidents.py` | `6dc00b94d23fdc3153cadb8293a6eff4` |
| `services/erp/src/api/costs.py` | `ee7e2bbc8be35dbb5f071f5b3f9e98d7` |
| `services/field-dx/src/api/reports.py` | `4926fd585e8c75326601b99b688e0c01` |
| `services/construction/src/api/methods.py` | `fd017fb3bfb646d17eb2474efa8fa173` |
| `services/workflow/src/api/workflows.py` | `07efbfecf68d98f2ea406ee3012bd833` |

## 1. 手法（再現手順）

1. `services/*/src/api/*.py` 全ファイルを Python `ast` で解析し、`@router.{get,post,put,patch,delete}` を全件抽出（**463ルート / 22サービス**）。
2. 各ルートについて、シグネチャおよびデコレータの `Depends(...)` から
   (a) 認証依存の有無、(b) ロール/パーミッション検査の有無、
   (c) `organization_id: UUID | None = Query(None)` の有無と**その値がサービス層へ渡されているか**、
   (d) `organization_id = body.organization_id` の有無、を機械判定。
3. `services/*/src/services/*.py` を解析し、ID 指定系関数（`get_*_by_id` / `update_*` / `delete_*` 等）が
   `organization_id` を受領し **かつ** クエリで絞り込んでいるかを判定。
4. ルート→サービス関数の呼び出しを解決し、ID 指定ルートのうちサービス層に組織検査が無いものをカウント。
5. 機械判定の誤検出を排除するため、代表ファイルを**実読**して確認（§7 参照）。
6. `services/*/tests/*.py` を検索し、テナント越境を守るテストの有無のみを確認（テストは実行していない）。

> 本レポートの数値はすべて**実際に数えた結果**であり概算ではない。概算を用いた箇所はその旨明記する。

## 2. サービス別サマリ表

「認証欠落」= `get_current_user` 等の依存も `dependencies=[...]` のガードも無いルート。health / login / refresh /
logout / mfa/verify / token 交換 / 署名検証付き webhook は**正当な公開**として除外済み。
「クエリ由来org(実使用)」= `organization_id: UUID | None = Query(None)` を**実際にサービス層へ渡している**ルート。
「ボディ由来org」= `organization_id = body.organization_id` で作成するルート。
「ロール検査」= `require_permission` / `require_role` / `_require_management` を伴うルート。

| サービス | ルート数 | 認証欠落 | クエリ由来org(実使用) | ボディ由来org | ロール検査 |
|---|---|---|---|---|---|
| advanced | 25 | 0 | 4 | 0 | 0 |
| ai | 16 | 0 | 0 | 0 | 0 |
| analytics | 20 | 0 | 3 | 0 | 0 |
| auth | 32 | 0 | 0 | 2 | 16 |
| automation | 23 | 0 | 3 | 0 | 0 |
| autonomous | 54 | 0 | 7 | 0 | 0 |
| bim | 16 | 0 | 0 | 1 | 0 |
| construction | 33 | 0 | 3 | 0 | 0 |
| document | 12 | 0 | 0 | 0 | 0 |
| erp | 22 | 0 | 2 | 0 | 0 |
| field-dx | 21 | 0 | 3 | 0 | 0 |
| gis | 21 | 0 | 0 | 3 | 0 |
| iot | 19 | 0 | 2 | 1 | 0 |
| maintenance | 19 | 0 | 3 | 4 | 0 |
| mcp | 1 | 0 | 0 | 0 | 0 |
| notification | 13 | 0 | 0 | 0 | 0 |
| partner | 20 | 0 | 0 | 0 | 0 |
| platform | 16 | 0 | 0 | 3 | 0 |
| safety | 15 | 0 | 3 | 3 | 0 |
| security | 17 | 0 | 3 | 3 | 0 |
| vision | 15 | 0 | 3 | 3 | 0 |
| workflow | 33 | 0 | 0 | 0 | 0 |
| **合計** | **463** | **0** | **39** | **23** | **16** |

> 「ボディ由来org」は機械抽出で 25 件だったが、workflow の 2 件は実読の結果いずれも 403 で拒否する
> 安全な実装と判明したため除外した（C-3 の「誤検出の訂正」参照）。**確定値 23 件**。

補足（表中に現れないが測定した事項）:

- **ID 指定ルートでサービス層に組織検査が無いもの: 76 件**（内訳: construction 13 / erp 11 / analytics 9 / partner 9 /
  maintenance 8 / field-dx 6 / safety 5 / security 5 / vision 5 / ai 3 / document 2）。
- **ロール/パーミッション検査が無いルート: 447 / 463 件**（検査がある 16 件は**すべて auth サービス**）。
- サービス層の「ID 指定系」関数で組織スコープが無いもの: **131 件**（スコープありは 13 件）。
- `if organization_id:`（None のとき絞り込みを**行わない**）パターン: サービス層で **42 箇所**。
- サービスをまたぐ `organization_id` の**常時比較**（`is not None`）は 8 箇所のみ。

## 3. 欠陥候補リスト

重大度は CHARTER §5 の定義に従う。

### 🔴 Critical

#### C-1. 一覧系 39 ルートが「クエリ由来 organization_id」を採用し、省略時に全テナントを返す
- **症状**: `GET ...?organization_id=<他社>` で他テナントの一覧が取得できる。`organization_id` を**省略**すると
  組織フィルタが一切かからず、**全テナントの行が返る**（越境読み取り）。
- **根拠**: `services/advanced/src/api/predictive.py:62`（`organization_id: UUID | None = Query(None)`）→
  `services/advanced/src/api/predictive.py:73-81`（`organization_id=organization_id` をそのまま渡す）→
  `services/advanced/src/services/advanced_service.py:445-449`（`if organization_id:` の条件付きフィルタ）。
  同型の実例: `services/safety/src/api/incidents.py:68` → `services/safety/src/services/safety_service.py:336-337`、
  `services/erp/src/api/ledger.py:53` → `services/erp/src/services/ledger_service.py:35-36`、
  `services/erp/src/api/invoices.py:36` → `services/erp/src/services/invoice_service.py:43`。
- **該当 39 ルートの全件**: 付録 A。
- **影響**: 他社の工事・原価・台帳・請求・労災・点検・脆弱性・設備データが読み放題。Q2 の根本違反。
- **対処方針（監査所見）**: クエリ引数を廃止し、`workflow` と同様に**トークン由来 org を強制**し、
  トークンに org が無ければ 403 を返す（`_organization_id` 方式）。

#### C-2. ID 指定 76 ルートがサービス層まで含めて組織検査を行わない（越境の読み・更新・削除）
- **症状**: 他テナントのレコード ID を指定するだけで GET/PUT/PATCH/DELETE が成功する。
- **根拠（実読で確認済みの代表）**:
  - `services/advanced/src/services/advanced_service.py:415-421`（`get_predictive_model_by_id`: `where(id == record_id)` のみ）
  - `services/advanced/src/services/advanced_service.py:483-492`（`delete_predictive_model`: 組織検査なしで `db.delete`）
  - `services/safety/src/services/safety_service.py:349-354`（`get_safety_incident_by_id`）
  - `services/safety/src/services/safety_service.py:357`（`update_safety_incident`）
  - `services/analytics/src/services/analytics_service.py:23-24`（`get_datasource`: `await db.get(DataSource, datasource_id)` のみ）
  - `services/bim/src/services/bim_service.py:102-104`（`get_bim_model`）、`107-110`（`update_bim_model`）
  - `services/maintenance/src/services/maintenance_service.py:81-86`（`get_disaster_report_by_id`）
  - `services/security/src/services/policy_service.py:63-68`（`get_policy_by_id`）
  - `services/vision/src/services/vector_service.py:48-53`（`get_vector_index_by_id`）
  - `services/partner/src/services/partner_service.py:24-31`（`get_partner_by_id`）
- **該当 76 ルートの例**: 付録 B（サービス別の件数は §2 補足）。
- **影響**: テナント越境の**書き込み・削除**を含む。データ破壊に直結（Critical）。
- **対処方針**: サービス層の ID 系関数に `organization_id` を必須引数として追加し、
  `WHERE id = :id AND organization_id = :org` にする。ルートで org を必ずトークンから渡す。

#### C-3. 作成系 23 ルートがボディの `organization_id` をそのまま保存する
- **症状**: リクエストボディの `organization_id` を書き換えるだけで、**任意のテナント宛にレコードを作成**できる。
- **根拠（例）**:
  - `services/safety/src/api/incidents.py:43`（`create_incident`）→ 同 `:56` で `organization_id=body.organization_id`
  - `services/security/src/api/policies.py:35` → 同ファイルで `body.organization_id`
  - `services/maintenance/src/api/disasters.py:68`、`services/maintenance/src/api/maintenance.py:41`
  - `services/vision/src/api/vectors.py:38`、`services/platform/src/api/iot_mgmt.py:42`、`services/gis/src/api/sites.py:80`
  - `services/auth/src/api/users.py:94`（`organization_id=body.organization_id`）— ただし
    `require_permission("users","create")` 付き（受理権限は必要）。それでも**呼び出し元の組織との一致検査は無い**。
  - `services/auth/src/api/roles.py:63`（同様。`require_permission("roles","create")` 付き、組織一致検査なし）
- **全 23 件**: 付録 C。
- **影響**: 他テナント領域へのデータ注入、テナント境界の汚染。
- **対処方針**: ボディの `organization_id` を無視（または不一致なら 403）し、トークン由来 org を強制。
  `workflow/src/api/cases.py:69-76` が正しい実装例（`body.organization_id != organization_id` なら 403）。
- **誤検出の訂正（実読で確認）**: 機械抽出では 25 件だったが、`workflow` の 2 件は**実読の結果いずれも安全**と判明し除外した。
  - `services/workflow/src/api/workflows.py:266-276`（`create_definition`）: `_require_management(current_user)` に加え、
    `body.organization_id != organization_id` なら **403**（`workflows.py:272-276`）。
  - `services/workflow/src/api/workflows.py:389-397`（`create_instance`）: 同様に不一致なら **403**（`workflows.py:394-397`）。
  → **確定値 23 件**。

#### C-4. 承認の偽装（実行者をボディ／クエリから受け取る）
- **症状**: 承認者をリクエスト引数で指定でき、トークン本人と一致しなくても承認が成立する。
- **根拠**:
  - `services/field-dx/src/api/reports.py:113`（`approved_by: UUID = Query(...)`）→ 同 `:121`
    `field_service.approve_daily_report(db, report, approved_by)` → 承認者が**クエリ引数**で決まる。
  - `services/erp/src/api/costs.py:88`（`cost_service.approve_cost(db, cost, body.approved_by)`）→
    スキーマは `services/erp/src/schemas/schemas.py:166`（`approved_by: UUID` 必須）。
    サービス側 `services/erp/src/services/cost_service.py:72-74` で
    `cost.status = "approved"` / `cost.approved_by = approved_by` を保存。
- **影響**: 承認の否認不能性が破綻（CHARTER §5 の Critical 定義「承認の偽装」に該当）。
- **対処方針**: `workflow/src/api/workflows.py:837`（`user_id=UUID(current_user.sub)`）と同様にトークン sub を採用。
- **参考（修正済み）**: `services/construction/src/api/methods.py:131` は監査中に `_actor_id(user)` へ修正された。
  ただし同ルートは `get_method(db, method_id)` に組織検査が無く C-2 が残存。

### 🟠 High

#### H-1. auth 以外の全サービスでロール/パーミッション検査が実装されていない（447/463 ルート）
- **症状**: 認証（誰か）は行うが**認可（何をしてよいか）を行わない**。`get_current_user` さえ通れば
  任意のロールのユーザーが管理操作・削除・承認を実行できる。
- **根拠（測定）**: `require_permission` / `require_role` / `_require_management` の利用は **auth サービスの 16 ルートのみ**。
  `grep -rn "require_permission" services/ | grep -v "^services/auth/"` の結果は **0 件**。
- **影響**: 権限昇格（CHARTER §5 High）。例: `services/advanced/src/api/predictive.py:128`（DELETE）は
  `_current_user=Depends(get_current_user)` のみで、ロール不問で削除可能。

#### H-2. 実行者・報告者がボディ由来（9 箇所）→ 証跡の否認不能性が破綻
- **根拠**:
  - `services/safety/src/api/incidents.py:56`（`reported_by=body.reported_by`）、同 `:119`（`investigated_by=body.investigated_by`）
  - `services/safety/src/api/hazards.py:51`（`reported_by=body.reported_by`）
  - `services/safety/src/api/inspections.py:53`、`:121`（`inspector_id=body.inspector_id`）
  - `services/maintenance/src/api/disasters.py:81`（`reported_by=body.reported_by`）、同 `:179`（`created_by=body.created_by`）
  - `services/maintenance/src/api/maintenance.py:59`、`:129`（`performed_by=body.performed_by`）
- **影響**: 労災・点検・災害記録の報告者を詐称できる。法定記録の証跡として信頼できない。

#### H-3. `require_permission` が共有パッケージ化されておらず、他サービスから利用不能
- **事実**:
  - 実体は `services/auth/src/services/permission_service.py:43` の `user_has_permission` を
    `services/auth/src/middleware/auth_middleware.py:97-128` が DB 参照して判定する。
    **auth サービスの DB スキーマ（Permission / RolePermission / UserRole）に依存**する。
  - `packages/auth-core/construction_enterprise_os_auth/__init__.py:149-159` にも `require_permission` があるが、
    実装は「`admin` ロール以外は必ず 403」という**スタブ**（コメントに「本実装ではスコープベースの簡易チェック」と明記）。
    つまり他サービスがこれを使うと**全リクエストが 403 になる**。
  - 各サービスの `main.py` は `configure_auth(...)` を呼ぶが（例 `services/bim/src/main.py:31-37`）、
    ルートは `from ..middleware.auth import get_current_user`（例 `services/bim/src/api/elements.py:10`）を
    使っており、**auth-core の `get_current_user` はルート保護に使用されていない**（実質デッドコード）。
  - `configure_auth` は try/except ImportError で囲まれ、失敗しても `pass`（`services/bim/src/main.py:38-39`）。
- **結論（事実）**: 他サービスが `require_permission` を使っていないのは、共有可能な形で提供されておらず、
  共有版は deny-all スタブであるため。**構造的な欠陥**であり、各サービスの実装漏れだけではない。

#### H-4. 認証ミドルウェアが 22 コピー・10 変種に分裂（修正が波及しない）
- **測定**: `services/*/src/middleware/auth.py` は **22 ファイル / 10 種類の MD5**。
- **変種グループ**:
  | MD5(先頭8) | サービス |
  |---|---|
  | `7fe86663` | ai, bim, document, gis, platform |
  | `f4ce5fb8` | analytics, construction, erp, field-dx |
  | `2f54c557` | maintenance, safety, security, vision |
  | `0e836261` | automation, autonomous, iot |
  | `e7d1f554` | advanced |
  | `5ea75872` | notification |
  | `c265a52b` | partner |
  | `1d9fb13b` | mcp |
  | `fc4ec5a3` | workflow |
  | `feab682f` | gateway |
- **実害（観測）**: construction の承認者修正が `f4ce5fb8` グループの 1 サービスにのみ適用され、
  同じグループの analytics / erp / field-dx には波及していない（`erp/src/api/costs.py:88`、`field-dx/src/api/reports.py:113` が未修正）。
- **変種間の差分（実読）**: `TokenData` が `@dataclass`（bim 系）と `pydantic.BaseModel`（automation 系）で異なる。
  `get_current_client`（M2M）を持つのは advanced / automation / autonomous / iot / auth のみで、
  他サービスでは M2M トークンの扱いが未定義。エラー `detail` も dict（`{"code": ...}`）と文字列で不統一。
  メッセージも日本語（bim 系）と英語（maintenance 系）が混在。

### 🟡 Medium

#### M-1. 4 サービスが生の `JWT_PUBLIC_KEY` を参照し、開発/テスト環境で空鍵検証になる
- **根拠**: `jwt.decode` へ渡す鍵が
  - `settings.jwt_public_key`（プロパティ経由・フォールバックあり）: **18 サービス**
  - `settings.JWT_PUBLIC_KEY`（生フィールド・フォールバックなし）: `services/analytics/src/middleware/auth.py:29`,
    `services/construction/src/middleware/auth.py:29`, `services/erp/src/middleware/auth.py:29`,
    `services/field-dx/src/middleware/auth.py:29` の **4 サービス**
- **理由**: `services/analytics/src/config.py:25`（`JWT_PUBLIC_KEY: str = ""`）と `:27-31`（プロパティは空なら
  `"dev-only-do-not-use-in-production"` を返す）。生フィールド参照はこのプロパティを迂回するため、
  `ENVIRONMENT` が `development`/`test` のとき**空文字列の鍵で HMAC 検証**する。
- **影響の限定**: `services/analytics/src/config.py:39-46` の起動ガードは非 dev/test で空鍵・dev 鍵を拒否するため、
  **本番では両経路が一致する**。したがって影響は開発/テスト環境に限られる。ただしその 4 サービスだけが
  空鍵で偽造可能なトークンを受理する状態は、環境間の信頼境界の不整合である。
- **未確認**: `ENVIRONMENT` の本番値、および空鍵時に PyJWT が例外を出すかは**未実行のため未確認**。

#### M-2. JWT ライブラリが 2 系統混在
- `packages/auth-core` は `python-jose[cryptography]`（`packages/auth-core/pyproject.toml`、
  `.../__init__.py:19`）。
- 各サービスのローカルミドルウェアは `PyJWT`（例 `services/bim/src/middleware/auth.py:8-9`
  `import jwt` / `from jwt import InvalidTokenError as JWTError`）。
- **影響**: 検証セマンティクス（クレーム検証の既定値・例外型）が一致する保証が無く、
  auth-core へ統合する際の挙動差リスク。`maintenance` 系変種は明示的な
  `options={"verify_exp": True}` を削除している（`services/maintenance/src/middleware/auth.py:37` 周辺）。
  なお PyJWT は `exp` を既定で検証するため、**これ自体は失効無視の欠陥ではない**（誤断定を避けるため明記）。

#### M-3. エラー応答形式の不統一（エラー表示不備）
- dict 形式 `{"code": "...", "message": "..."}`（例 `services/bim/src/middleware/auth.py:51`）と
  文字列 `detail="WBSアイテムが見つかりません"`（例 `services/construction/src/api/wbs.py:82`）が混在。
  401/403 の判別やクライアント側ハンドリングがサービスごとに異なる。

#### M-4. トークンに org が無い場合に 403 ではなく「空結果」を返す sentinel 実装
- **根拠**: `services/construction/src/api/wbs.py:23-27`、`services/document/src/api/documents.py:42-43`
  （`UUID(user.org) if user.org else UUID(int=0)`）。
- **影響**: 組織情報の無いトークンが 403 にならず、**全ゼロ UUID でフィルタされて空配列**が返る。
  fail-closed ではあるが、設定不備が「データが無い」ように見え、検知が遅れる。
  `workflow` は 403 を返す実装（`services/workflow/src/api/workflows.py:93-104`）であり、望ましい側。

#### M-5. field-dx の品質テストのみ xfail が無く、テストスイートが赤になる
- `services/field-dx/tests/test_quality_tenant_isolation.py` は `test_defect_*` で仕様準拠の期待を assert するが
  **`xfail` マーカーが 0 件**（`grep -c xfail` = 0）。ファイル冒頭 `:1-15` に「失敗 = 実装欠陥」と明記。
- 一方 construction / document / erp は `xfail(strict=True)` を使用
  （例 `services/construction/tests/test_quality_tenant_isolation.py:46`、
  `services/document/tests/test_quality_approval_flow.py:175`、`services/erp/tests/test_quality_costing.py:197`）。
- **影響**: 方針の不統一。field-dx は「赤いテスト」として欠陥を証跡化し、他は xfail で緑を保つ。
  どちらも証跡として妥当だが、`pytest` の pass/fail を品質ゲートに使う際に解釈が分かれる。
- **未確認**: 実際に失敗するかは**テスト未実行のため未確認**（CHARTER §4 に従い、未実行を成功と書かない）。

#### M-6. サービス層で組織スコープが無い ID 系関数が 131 件
- 測定方法: `services/*/src/services/*.py` の `get/update/delete/fetch/find/...*_id` 系関数のうち、
  `organization_id` を受領してクエリで絞り込んでいないもの。スコープありは 13 件のみ。
- うち API ルートから露出しているものが C-2 の 76 件。残りは内部関数・別経路（未確認分を含む）。

### 🔵 Low / ⚪ Info

- **L-1（Info・問題なしの確認）**: 内部系エンドポイントは適切に保護されている。
  `services/document/src/api/internal.py:100,135` は `dependencies=[Depends(require_internal_api_key)]`（同 `:44-60`）と
  `_get_authorized_document` による `X-Organization-ID` 境界チェックを併用。
  `services/workflow/src/api/workflows.py:115,124,133` は `require_internal_job_key`。
  `services/auth/src/api/internal.py:29` は `require_internal_api_key`。
  `services/notification/src/api/notifications.py:56` は `require_internal_api_key`。
  `services/notification/src/api/webhooks.py:101` は HMAC-SHA256 署名検証（同 `:107-113`）。
  → **機械検出で「未保護」と出たものは全て誤検出であり、実際の欠陥ではない。**
- **L-2（Info）**: `services/partner/src/api/health.py:19` は `@router.get("")`（`main.py` 側で `prefix="/health"`）。
  ヘルスチェックとして正当な公開。同ファイル `:21-26` は DB 到達性を確認し 503 を返す実装。
- **L-3（Info）**: `services/logs/` にはソースコードが存在しない（`auth-18002.log` と `.pytest_cache` のみ、
  `*.py` 0 件）。24 サービス中の 1 つが実装を持たない。
- **L-4（Info）**: `services/gateway/` は `src/routes/proxy.py` のみで `src/api/*.py` を持たない（プロキシ専用）。
- **I-1（未確認）**: `services/auth/src/services/token_exchange_service.py:169-180` は audience が
  `MCP_AUDIENCE` の場合 `client_credentials` 無しでもトークンを発行する（クライアント認証は
  `UPSTREAM_EXCHANGE_AUDIENCE` の方向のみ必須）。ファイル冒頭は ADR-0003 を参照しているため
  **設計意図と推定されるが、ADR-0003 本文を読んでいないため仕様適合は未確認**。
  subject token 自体の署名検証（`decode_subject_token`）は行われており、無条件のトークン発行ではない。

## 4. 既存テストによる保護状況（有無のみ／実行はしていない）

対象: `services/*/tests/*.py`（測定時 **156 ファイル**）。

> ⚠️ この「越境テストあり」列は **キーワード（`other_org` / `cross_tenant` / `other_tenant` / `越境` /
> `tenant_isolation` / `other_organization`）による下限値**であり、内容を精読した全件判定ではない。
> 例: 監査中に追加された `services/bim/tests/test_quality_tenant_isolation.py` は 389 行で
> `organization` を 29 回含むが、上記キーワードを含まないためこの列では 0 と数えられる。
> **「0」は「越境テストが無い」の証明ではなく、上記キーワードを持つテストが無いことのみを意味する。**
> また bim / gis は監査中にテストファイルが増えた（bim 6→8、gis 7→8）ため、下表は 08:45 時点の値である。

| サービス | テストファイル数 | `organization` に言及 | 越境テストあり |
|---|---|---|---|
| advanced | 4 | 1 | **0** |
| ai | 6 | 1 | 1 |
| analytics | 4 | 1 | **0** |
| auth | 17 | 5 | **0** |
| automation | 4 | 1 | **0** |
| autonomous | 6 | 1 | **0** |
| bim | 8 | 1 | **0**（注） |
| construction | 8 | 4 | 3 |
| document | 10 | 5 | 2 |
| erp | 8 | 4 | 2 |
| field-dx | 7 | 3 | 1 |
| gateway | 6 | 0 | **0** |
| gis | 8 | 2 | **0**（注） |
| iot | 6 | 1 | **0** |
| maintenance | 5 | 1 | **0** |
| mcp | 12 | 0 | **0** |
| notification | 8 | 0 | **0** |
| partner | 4 | 1 | **0** |
| platform | 5 | 1 | **0** |
| safety | 5 | 1 | **0** |
| security | 5 | 1 | **0** |
| vision | 5 | 1 | **0** |
| workflow | 10 | 4 | 2 |

- 上記キーワード基準で**越境テストが確認できたのは 6 サービス**（construction / document / erp / field-dx /
  workflow / ai）。C-1〜C-4 の欠陥を持つ 39+76+23 ルートのうち、キーワード基準でテストが確認できるのは
  construction / document / erp / field-dx / workflow の範囲のみ。
- 残り **advanced, analytics, automation, autonomous, bim, gis, iot, maintenance, partner, platform, safety,
  security, vision の 13 サービス**はキーワード基準で 0 件。ただし bim は監査中に
  `test_quality_tenant_isolation.py`（389 行・`organization` 29 箇所）が追加されており、
  **13 サービス全てが未保護であるとは断定しない**。各サービスの実態は当該担当のレポートを参照。
- 既存の「あるべき姿」テストは field-dx の `test_defect_approver_identity_comes_from_query_not_token`
  （`services/field-dx/tests/test_quality_tenant_isolation.py:330-350`）などが本監査の C-4 と一致しており、
  **独立した二経路で同じ欠陥が確認できた**。
- これらのテストは**未実行**。pass/fail は未確認であり、成功として扱わない。

## 5. 監査で「安全」と確認した実装（対照群）

テナント分離の**参照実装**は `services/workflow/`。他サービスの修正時の手本として価値がある。

- `services/workflow/src/api/workflows.py:93-104`（`_organization_id`: トークンに org が無ければ 403）
- `services/workflow/src/api/workflows.py:307-315` / `:443-451`
  （クエリ org とトークン org の不一致を 403。クエリは**制約の追加のみ**で、権限拡大には使えない）
- `services/workflow/src/api/cases.py:69-76`（ボディ org とトークン org の不一致を 403）
- `services/workflow/src/api/workflows.py:837`（承認者 `UUID(current_user.sub)` をトークンから取得）
- `services/construction/src/api/wbs.py:42-58`（クエリ `organization_id` を**無視**し `_org_id(user)` を渡す。
  API 契約上は引数が残るが、越境には使えない）
- `services/security/src/api/policies.py:49`, `:125`（`approved_by=UUID(current_user.sub)`）
- `services/document/src/api/internal.py:44-60`, `:63-`（内部 API キー + 組織ヘッダ境界チェック）
- `services/notification/src/api/webhooks.py:107-113`（HMAC 署名検証）

## 6. 未確認事項（推測で断定していない項目）

1. **各欠陥の実挙動は未実行**。本監査はソース静的解析 + 実読であり、HTTP リクエストによる再現は行っていない。
   C-1〜C-4 の「200 が返る」等は実装コードからの帰結であり、実行確認は別途必要。
2. **本番環境の設定値**（`ENVIRONMENT`, `JWT_PUBLIC_KEY` の実値、`INTERNAL_API_KEY` の設定有無）は未確認。
   `INTERNAL_API_KEY` が未設定の場合、内部系は `services/auth/src/api/internal.py:20-25` の実装により
   403 で fail-closed になる（これは読み取れた事実）。
3. **DB スキーマ/RLS の有無**。PostgreSQL の Row Level Security やテナント用ビューが
   マイグレーションで定義されているかは未確認。もし RLS があれば C-1/C-2 の実害は軽減されうる。
   → 本レポートは**アプリケーション層の実装**のみを根拠としている。
4. **ADR-0003 の内容**（token exchange のクライアント認証要件）は本文未読のため I-1 は判定不能。
5. **`docs/architecture/ADR-0001` 等の仕様文書**は他 teammate が参照しているが、本監査では
   「組織スコープはトークン由来であるべき」という CHARTER §3 Q2 の基準のみを用いた。
6. **services 以外の経路**（`services/gateway/src/routes/proxy.py` のプロキシ認可、
   `services/mcp/src/middleware/mcp_guard.py`）は本タスクの走査対象外。未確認。
7. **他 teammate の進行中の修正**により、construction / document / erp / field-dx / workflow の
   記載は既に陳腐化している可能性がある（§0 参照）。

## 7. 付録 A — C-1: クエリ由来 `organization_id` を実使用する 39 ルート（全件）

| ファイル:行 | メソッド パス | 関数 |
|---|---|---|
| `services/advanced/src/api/design_review.py:57` | GET (root) | `list_reviews` |
| `services/advanced/src/api/inspections_ai.py:63` | GET (root) | `list_inspections` |
| `services/advanced/src/api/marine.py:63` | GET (root) | `list_marine` |
| `services/advanced/src/api/predictive.py:62` | GET (root) | `list_models` |
| `services/analytics/src/api/datasources.py:37` | GET /datasources | `list_datasources` |
| `services/analytics/src/api/pipelines.py:37` | GET /pipelines | `list_pipelines` |
| `services/analytics/src/api/reports.py:38` | GET /reports | `list_reports` |
| `services/automation/src/api/rules.py:49` | GET (root) | `list_rules` |
| `services/automation/src/api/tasks.py:51` | GET (root) | `list_tasks` |
| `services/automation/src/api/triggers.py:46` | GET (root) | `list_triggers` |
| `services/autonomous/src/api/agents.py:47` | GET (root) | `list_agents` |
| `services/autonomous/src/api/controls.py:42` | GET (root) | `list_pending_commands` |
| `services/autonomous/src/api/digital_twins.py:48` | GET (root) | `list_twins` |
| `services/autonomous/src/api/marine_robots.py:50` | GET (root) | `list_marine_robots` |
| `services/autonomous/src/api/operations.py:51` | GET (root) | `list_operations` |
| `services/autonomous/src/api/simulations.py:43` | GET (root) | `list_simulations` |
| `services/autonomous/src/api/tasks.py:41` | GET (root) | `list_tasks` |
| `services/construction/src/api/methods.py:46` | GET /methods | `list_methods` |
| `services/construction/src/api/resources.py:33` | GET /resources | `list_resources` |
| `services/construction/src/api/schedule.py:32` | GET /schedules | `list_schedules` |
| `services/erp/src/api/invoices.py:36` | GET /invoices | `list_invoices` |
| `services/erp/src/api/ledger.py:53` | GET /ledger | `list_ledgers` |
| `services/field-dx/src/api/progress.py:149` | GET /progress | `list_progress` |
| `services/field-dx/src/api/quality.py:126` | GET /quality | `list_quality_checks` |
| `services/field-dx/src/api/reports.py:36` | GET /reports | `list_reports` |
| `services/iot/src/api/alerts.py:55` | GET /alert-rules | `list_alert_rules` |
| `services/iot/src/api/devices.py:78` | GET (root) | `list_devices` |
| `services/maintenance/src/api/disasters.py:92` | GET /disasters | `list_disasters` |
| `services/maintenance/src/api/inspections.py:63` | GET /inspections | `list_inspections` |
| `services/maintenance/src/api/maintenance.py:66` | GET /records | `list_records` |
| `services/safety/src/api/hazards.py:61` | GET /hazards | `list_hazards` |
| `services/safety/src/api/incidents.py:68` | GET /incidents | `list_incidents` |
| `services/safety/src/api/inspections.py:63` | GET /inspections | `list_inspections` |
| `services/security/src/api/incidents.py:73` | GET /incidents | `list_incidents` |
| `services/security/src/api/policies.py:55` | GET /policies | `list_policies` |
| `services/security/src/api/vulnerabilities.py:56` | GET /vulnerabilities | `list_vulnerabilities` |
| `services/vision/src/api/image_ai.py:49` | GET /vision/analyses | `list_analyses` |
| `services/vision/src/api/ocr.py:72` | GET /ocr/results | `list_ocr_results` |
| `services/vision/src/api/vectors.py:55` | GET /vectors/indices | `list_indices` |

## 8. 付録 B — C-2: ID 指定ルートで組織検査が無いもの（サービス別件数と例）

合計 **76 件**。

| サービス | 件数 | 例（ファイル:行 → 呼び出される未スコープ関数） |
|---|---|---|
| construction | 13 | `services/construction/src/api/methods.py:69` GET `/methods/{method_id}` → `get_method` |
| erp | 11 | `services/erp/src/api/costs.py:42` GET `/ledger/{ledger_id}/costs` → `get_ledger`, `list_costs` |
| analytics | 9 | `services/analytics/src/api/datasources.py:60` GET `/datasources/{datasource_id}` → `get_datasource` |
| partner | 9 | `services/partner/src/api/contracts.py:94` GET `/{contract_id}` → `get_contract_by_id` |
| maintenance | 8 | `services/maintenance/src/api/disasters.py:136` PUT `/disasters/{disaster_id}` → `update_disaster_report` |
| field-dx | 6 | `services/field-dx/src/api/quality.py:154` PUT `/quality/{check_id}` → `get_quality_check`, `update_quality_check` |
| safety | 5 | `services/safety/src/api/incidents.py:106` PUT `/incidents/{incident_id}` → `update_safety_incident` |
| security | 5 | `services/security/src/api/policies.py:76` GET `/policies/{policy_id}` → `get_policy_by_id` |
| vision | 5 | `services/vision/src/api/vectors.py:74` GET `/vectors/indices/{index_id}` → `get_vector_index_by_id` |
| ai | 3 | `services/ai/src/api/prompts.py:132` DELETE `/prompts/{template_id}` → `delete_template` |
| document | 2 | `services/document/src/api/documents.py:268` DELETE `/{document_id}` → `soft_delete_document` |

## 9. 付録 C — C-3: ボディ由来 `organization_id` の作成ルート（23 件）

| ファイル:行 | パス | 関数 |
|---|---|---|
| `services/auth/src/api/roles.py:63` | POST (root) | `create_role_endpoint`（`require_permission` あり／組織一致検査なし） |
| `services/auth/src/api/users.py:94` | POST (root) | `create_user`（同上） |
| `services/bim/src/api/pointcloud.py:33` | POST (root) | `create_pointcloud` |
| `services/gis/src/api/areas.py:67` | POST (root) | `create_hazard_zone` |
| `services/gis/src/api/infrastructure.py:70` | POST (root) | `create_infrastructure` |
| `services/gis/src/api/sites.py:80` | POST (root) | `create_site` |
| `services/iot/src/api/alerts.py:30` | POST /alert-rules | `create_alert_rule` |
| `services/maintenance/src/api/disasters.py:68` | POST /disasters | `create_disaster` |
| `services/maintenance/src/api/disasters.py:162` | POST /disasters/{disaster_id}/recovery-plans | `create_recovery_plan` |
| `services/maintenance/src/api/inspections.py:43` | POST /inspections | `create_inspection` |
| `services/maintenance/src/api/maintenance.py:41` | POST /records | `create_record` |
| `services/platform/src/api/iot_mgmt.py:42` | POST /dashboards | `create_dashboard` |
| `services/platform/src/api/iot_mgmt.py:126` | POST /device-groups | `create_device_group` |
| `services/platform/src/api/viewer.py:42` | POST /configs | `create_viewer_config` |
| `services/safety/src/api/hazards.py:38` | POST /hazards | `create_hazard` |
| `services/safety/src/api/incidents.py:43` | POST /incidents | `create_incident` |
| `services/safety/src/api/inspections.py:43` | POST /inspections | `create_inspection` |
| `services/security/src/api/incidents.py:53` | POST /incidents | `create_incident` |
| `services/security/src/api/policies.py:35` | POST /policies | `create_policy` |
| `services/security/src/api/vulnerabilities.py:36` | POST /vulnerabilities | `create_vulnerability` |
| `services/vision/src/api/image_ai.py:32` | POST /vision/analyze | `analyze_image` |
| `services/vision/src/api/ocr.py:54` | POST /ocr/process | `process_ocr` |
| `services/vision/src/api/vectors.py:38` | POST /vectors/indices | `create_index` |

> **除外（実読で安全と確認）**: workflow の `create_definition`（`workflows.py:266-276`）と
> `create_instance`（`workflows.py:389-397`）は、いずれも `body.organization_id != organization_id` のとき
> **403 を返す**ため一覧から除外した。`create_definition` は `_require_management(current_user)` も併せて実施。

## 10. 結論（優先順位付けへの示唆）

- **最優先**: C-2（ID 指定の越境書き込み・削除 76 ルート）と C-3（任意テナントへの作成 23 ルート）。
  読み取り（C-1）より破壊性が高く、13 サービスにテストが皆無。
- **次点**: C-4（承認偽装）。`field-dx` と `erp` の 2 箇所は承認フローの中核。
- **構造課題**: H-3 / H-4（認可機構が共有されておらず 22 コピーに分裂）。
  個別修正は同じ欠陥を 10 変種へ繰り返し適用する必要があり、`construction` の実例が示すとおり波及漏れが起きる。
  共有認可パッケージ（org スコープ必須化 + 権限判定のサービス間契約）の整備が根本対策。
- **優先順位付けの網羅性根拠**: 本棚卸しは 463 ルートを機械的に全件分類しているため、
  「テスト対象フローの選定漏れ」を防ぐ根拠として使える。
