# 現場DX・GIS・BIM/CIM 品質テスト報告（task-4 / 担当: qa-field-spatial）

対象リポジトリ: `/home/kensan/Projects/Mirai-Construction-DX/Construction-Enterprise-OS`
対象サービス: `services/field-dx`（現場DX）, `services/gis`（GIS空間検索）, `services/bim`（BIM/CIM・点群）
準拠: [reports/quality-tests/CHARTER.md](reports/quality-tests/CHARTER.md)（全制約）

---

## 1. サマリ

| サービス | 既存テスト（変更なし） | 追加テスト | うち pass | うち fail（=検出欠陥） | skip |
|---|---|---|---|---|---|
| field-dx | 27 passed | 33 | 11 | **22** | 0 |
| gis | 30 passed | 35 | 15 | **20** | 0 |
| bim | 39 passed | 25 | 8 | **17** | 0 |
| **合計** | **96 passed** | **93** | **34** | **59** | **0** |

* 最終実行の実出力（3サービス一括）: **`22 failed, 38 passed` / `20 failed, 45 passed` / `17 failed, 47 passed`**（計 189 tests, skip 0）
* **fail 59 件はすべて「欠陥を検出するために仕様準拠の期待値を assert したテスト」の失敗**であり、
  テスト自体の誤り・環境不備ではない。各テストの docstring に欠陥IDと根拠（ファイル:行）を明記している。
* 既存テストは 1 件も変更・削除・skip 追加していない（回帰確認: field-dx 27 / gis 30 / bim 39 すべて pass）。
* **実装の修正は行っていない**（§7 に理由と最小修正案を記載）。

### 最重要（Critical）
1. **field-dx / GIS / BIM の主要な読み取り・書き込み API にテナント絞り込みが存在しない**（DEF-FLD-01〜16, DEF-GIS-01〜14, DEF-BIM-01〜12）。
2. **日報承認者がクエリ引数 `approved_by` で指定でき、トークン本人と一致しなくても承認が通る**（DEF-FLD-10）。

---

## 2. 対象フローと検証方法

| サービス | 対象フロー | 主なエンドポイント |
|---|---|---|
| field-dx | 出来形・進捗、品質チェック、作業日報、写真 | `GET/POST /api/v1/field/progress`, `/quality`, `/reports`, `/progress/{project_id}/summary`, `/quality/{project_id}/stats`, `/reports/{id}/approve` |
| gis | 現場、インフラ設備、危険区域、空間検索 | `GET/POST /api/v1/gis/sites`, `/sites/nearby`, `/sites/in-area`, `/infrastructure`, `/hazard-zones`, `/hazard-zones/intersecting/{site_id}` |
| bim | モデル、要素、点群 | `GET/POST /api/v1/bim/models`, `/bim/{model_id}/elements`, `/bim/elements/search`, `/bim/pointclouds` |

検証方法:
* 既存の `create_app()` + `dependency_overrides` + `TestClient` 方式を踏襲（`tests/conftest.py` は変更せず、fixture は各テストファイル内に自己完結で定義）。
* DB は `AsyncMock`。**テナント絞り込みの有無は、実行された SQLAlchemy 文の WHERE 句のみを対象に判定**した
  （SELECT 句の列一覧に `organization_id` が含まれるため全文一致では誤判定する）。
* 越境の読み書きは「他テナント（`ORG_B`）のレコードを返す mock」に対する応答コードで判定。
* fixture はすべて synthetic（UUID は `00000000-0000-0000-0000-0000000000xx`、座標は架空の 35.0/139.0 近傍）。
* 実 PostgreSQL・PostGIS・外部 Provider・ネットワークへは接続していない（§6 の但し書きを参照）。

---

## 3. 追加テスト一覧

### 3.1 field-dx

| ファイル | クラス | 内容 |
|---|---|---|
| `services/field-dx/tests/test_quality_tenant_isolation.py` | `TestTenantIsolationDefects`（17） | 一覧・単体取得・更新・提出・承認のテナント越境、body 由来 organization_id、承認者なりすまし、JWT 鍵解決 |
| 同上 | `TestTenantIsolationVerified`（3） | 未認証 401、非 user トークン 403、一覧 meta の一致 |
| `services/field-dx/tests/test_quality_units_coordinates.py` | `TestCalculationAndBoundaryDefects`（5） | 進捗率の範囲外・数量からの未算出、品質合否の申告依存、未判定の分母混入 |
| 同上 | `TestCalculationVerified`（7） | ゼロ除算回避、平均の決定性、丸めなしの記録 |
| 同上 | `TestPhotoMetadataGap`（1） | 写真メタデータ検証面の不在（未実装の記録） |

### 3.2 gis

| ファイル | クラス | 内容 |
|---|---|---|
| `services/gis/tests/test_quality_tenant_isolation.py` | `TestTenantIsolationDefects`（14） | 現場・設備・危険区域の一覧/取得/更新/削除、空間検索 3 種のテナント境界 |
| 同上 | `TestTenantIsolationVerified`（3） | 未認証 401、不正トークン 401、応答の organization_id 露出 |
| `services/gis/tests/test_quality_units_coordinates.py` | `TestCoordinateAndUnitDefects`（6） | 書き込み系の緯度経度範囲外、座標要素不足で 500、`radius_m` の geography キャスト欠落、bbox 逆転、危険度の辞書順ソート |
| 同上 | `TestCoordinateAndUnitVerified`（9） | 検索系の範囲検証 422（6 パターン）、SRID=4326 の明示、CRS 非露出の記録、area_sqm の申告依存 |

### 3.3 bim

| ファイル | クラス | 内容 |
|---|---|---|
| `services/bim/tests/test_quality_tenant_isolation.py` | `TestTenantIsolationDefects`（12） | モデル・要素・点群の一覧/取得/更新/削除、body 由来 organization_id |
| 同上 | `TestTenantIsolationVerified`（2） | 未認証 401、`/elements/search` 到達不能の前提記録 |
| `services/bim/tests/test_quality_units_coordinates.py` | `TestVersionAndRoutingDefects`（5） | ルーティング衝突、版番号の未採番、点群の版・元モデル紐付け・出典の欠落 |
| 同上 | `TestVersionAndStructureVerified`（6） | 版の往復一貫性、要素ツリー不在の記録、要素座標の非露出、WKT ヘルパーの未使用・検証欠落の記録 |

---

## 4. 実行コマンドと実出力（証跡）

### 4.1 変更前ベースライン（既存テストのみ）

```
$ cd services/field-dx && python3 -m pytest tests/ -q -p no:cacheprovider
27 passed, 1 warning in 11.87s

$ cd services/gis && python3 -m pytest tests/ -q -p no:cacheprovider
30 passed, 1 warning in 13.91s

$ cd services/bim && python3 -m pytest tests/ -q -p no:cacheprovider
39 passed, 1 warning in 2.77s
```

### 4.2 追加テスト込みの最終実行（実出力）

```
$ cd services/field-dx && python3 -m pytest tests/ -q -p no:cacheprovider
22 failed, 38 passed, 2 warnings in 4.24s

$ cd services/gis && python3 -m pytest tests/ -q -p no:cacheprovider
20 failed, 45 passed, 1 warning in 3.65s

$ cd services/bim && python3 -m pytest tests/ -q -p no:cacheprovider
17 failed, 47 passed, 1 warning in 3.42s
```

### 4.3 既存テストのみの回帰確認（無破壊の証跡）

```
$ cd services/field-dx && python3 -m pytest tests/test_field_dx.py tests/test_health_readiness.py tests/test_public_endpoint_authz.py -q -p no:cacheprovider
27 passed, 1 warning in 2.28s

$ cd services/gis && python3 -m pytest tests/test_gis.py tests/test_response_metadata.py tests/test_health_readiness.py tests/test_public_endpoint_authz.py -q -p no:cacheprovider
30 passed, 1 warning in 2.34s

$ cd services/bim && python3 -m pytest tests/test_bim.py tests/test_models_mapper.py tests/test_response_metadata.py tests/test_health_readiness.py -q -p no:cacheprovider
39 passed, 1 warning in 2.55s
```

### 4.4 失敗の代表的な assertion メッセージ（欠陥の直接証拠）

```
field-dx トークン org によるテナント絞り込みが WHERE 句に存在しない (全テナント横断の読み取り) / actual WHERE = ''
field-dx 承認者がクエリ引数で上書きされた: approved_by=00000000-...-0000000000ff (トークン sub=00000000-...-0000000000dd)
field-dx クエリ由来の organization_id がそのまま検索条件に使われている (テナント越境) / bound params = {'organization_id_1': UUID('00000000-0000-0000-0000-0000000000bb')}
field-dx 進捗率 150.0% を受理した（上限検証なし）: 201
field-dx 数量から進捗率が算出されていない: progress_percent=None
gis      緯度 999.0 を受理した（書き込み系の範囲検証なし）: 200
gis      座標要素不足の Point が 500 になった（IndexError 未処理）: 500
gis      radius_m に geography キャスト/球面距離関数が無い / actual SQL = ... WHERE ST_DWithin(gis.construction_sites.location, ST_GeomFromText(:ST_GeomFromText_1), :ST_DWithin_1) ...
gis      テナント絞り込みの無いクエリが存在する / actual WHERE = ['gis.construction_sites.id = :id_1', 'ST_Intersects(gis.hazard_zones.zone_area, :ST_Intersects_1) ORDER BY gis.hazard_zones.risk_level DESC']
bim      テナント絞り込みの無いクエリが存在する / actual WHERE = ['bim.bim_elements.model_id = :model_id_1', ...]
bim      要素検索が到達不能（ルーティング衝突）: status=422, body={'detail': [{'type': 'uuid_parsing', 'loc': ['path', 'element_id'], ... 'input': 'search' ...}]}
bim      版番号が採番・必須化されていない: version=None
bim      点群に生成版の項目が無い: keys=['accuracy_mm','bounding_box','capture_date','capture_method','coordinate_system','created_at','density','description','file_format','file_key','file_size','id','is_classified','is_colorized','metadata','name','organization_id','point_count','project_id','uploaded_by']
```

---

## 5. 欠陥一覧

重大度は CHARTER §5 に準拠（Critical=テナント越境の読み書き/認証回避/承認の偽装、High=証跡欠落/計算結果の誤り/データ破壊、Medium=境界値の誤り/エラー表示不備、Low=軽微）。

### 5.1 field-dx（22 件）

| ID | 症状 | 再現手順 | 根拠（ファイル:行） | 重大度 | 影響 | 修正 |
|---|---|---|---|---|---|---|
| DEF-FLD-01 | `GET /progress` が全テナント横断で読み取る | トークン org=A で `GET /api/v1/field/progress` → 生成 SQL の WHERE が空 | `src/api/progress.py:148-171`, `src/services/field_service.py:138-140` | Critical | 他社の出来形・進捗が閲覧可能 | なし |
| DEF-FLD-02 | `GET /quality` が全テナント横断 | org=A で `GET /api/v1/field/quality` | `src/api/quality.py:125-150`, `field_service.py:233-235` | Critical | 他社の品質検査結果が閲覧可能 | なし |
| DEF-FLD-03 | `GET /reports` が全テナント横断 | org=A で `GET /api/v1/field/reports` | `src/api/reports.py:35-59`, `field_service.py:44-46` | Critical | 他社の作業日報が閲覧可能 | なし |
| DEF-FLD-04 | `organization_id` クエリで他テナントを選択できる | org=A のトークンで `GET /progress?organization_id=<B>` → バインド値が B | `src/api/progress.py:150` | Critical | 1 パラメータで越境読み取り | なし |
| DEF-FLD-05 | 他テナントの出来形記録を ID 指定で取得 | `GET /progress/{他テナントのid}` → 200 | `src/api/progress.py:181-183`, `field_service.py:121-124` | Critical | 越境読み取り | なし |
| DEF-FLD-06 | 他テナントの出来形記録を更新 | `PUT /progress/{id}` → 200 | `src/api/progress.py:174-186` | Critical | 越境書き込み | なし |
| DEF-FLD-07 | 他テナントの日報を取得 | `GET /reports/{id}` → 200 | `src/api/reports.py:62-71` | Critical | 越境読み取り | なし |
| DEF-FLD-08 | 他テナントの日報を提出 | `POST /reports/{id}/submit` → 200 | `src/api/reports.py:89-104` | Critical | 他社の承認フローを進められる | なし |
| DEF-FLD-09 | 他テナントの日報を承認 | `POST /reports/{id}/approve` → 200 | `src/api/reports.py:107-123` | Critical | 越境承認 | なし |
| DEF-FLD-10 | 承認者がクエリ引数で決まる（なりすまし） | `POST /reports/{id}/approve?approved_by=<他人>` → `report.approved_by` が他人 | `src/api/reports.py:113` | Critical | 承認の否認不能性が破綻（Q6） | なし |
| DEF-FLD-11 | 作成 body の `organization_id` を無検証で採用 | `POST /progress` に他社 org → 201 | `src/schemas/__init__.py:77`, `src/api/progress.py:139-145` | Critical | 他社テナント宛の書き込み | なし |
| DEF-FLD-12 | 同上（日報） | `POST /reports` に他社 org → 201 | `src/schemas/__init__.py:13`, `src/api/reports.py:26-32` | Critical | 同上 | なし |
| DEF-FLD-13 | 同上（品質） | `POST /quality` に他社 org → 201 | `src/schemas/__init__.py:153`, `src/api/quality.py:111-122` | Critical | 同上 | なし |
| DEF-FLD-14 | 案件サマリにテナント検証なし | `GET /progress/{他社project}/summary` → 200、WHERE に org なし | `src/api/progress.py:189-198`, `field_service.py:171-177` | Critical | 他社案件の進捗集計が取得可能 | なし |
| DEF-FLD-15 | 品質統計にテナント検証なし | `GET /quality/{他社project}/stats` → 200 | `src/api/quality.py:168-177`, `field_service.py:269-275` | Critical | 他社案件の品質成績が取得可能 | なし |
| DEF-FLD-16 | 他テナントの品質チェックを更新 | `PUT /quality/{id}` → 200 | `src/api/quality.py:153-165` | Critical | 越境書き込み | なし |
| DEF-FLD-17 | JWT 検証鍵が空文字になり他サービスと非互換 | `settings.JWT_PUBLIC_KEY`（既定 ""）で `decode_token` を呼ぶ → 空鍵署名トークンを受理し、dev 既定鍵の正規トークンを拒否 | `src/middleware/auth.py:29`, `src/config.py:25-31`（比較: `services/gis/src/middleware/auth.py:29`, `services/bim/src/middleware/auth.py:29` は property を使用） | High | ENVIRONMENT=development/test で**空鍵トークンの偽造が通る**／auth 発行トークンを field-dx だけが拒否。本番は `src/config.py:39-46` の起動ガードで空鍵起動を防止 | なし |
| DEF-FLD-18 | 進捗率 100% 超を受理 | `POST /progress` `progress_percent=150.0` → 201 | `src/schemas/__init__.py:88` | Medium | 出来高指標の信頼性低下 | なし |
| DEF-FLD-19 | 進捗率の負値を受理 | `POST /progress` `progress_percent=-12.5` → 201 | `src/schemas/__init__.py:88` | Medium | 同上 | なし |
| DEF-FLD-20 | 出来形数量から進捗率を算出していない | `POST /progress` `planned=100, actual=50, progress_percent未指定` → `progress_percent=None` で保存 | `src/api/progress.py:139-145`, `field_service.py:111-118` | High | 数量と進捗率が独立申告となり出来高の正しさを担保できない（Q3） | なし |
| DEF-FLD-21 | 品質合否がクライアント申告で確定（測定値・規格値との突合なし） | `POST /quality` `is_conforming=true` かつ `measured_value` なし → 201 | `src/schemas/__init__.py:152-164`, `src/api/quality.py:116-122`, `field_service.py:205-212` | High | 合否の証跡が改ざん可能（Q6）。**閾値判定ロジックは実装されていない** | なし |
| DEF-FLD-22 | 未判定(`is_conforming=None`)を分母に含め適合率を過小算出 | 適合1件+未判定1件 → `conformance_rate=50.0`（期待は分母除外） | `src/services/field_service.py:277-289` | Medium | 検査未完の現場で品質成績が過小評価 | なし |

### 5.2 gis（20 件）

| ID | 症状 | 再現手順 | 根拠（ファイル:行） | 重大度 | 影響 | 修正 |
|---|---|---|---|---|---|---|
| DEF-GIS-01 | 現場一覧がテナント未分離 | org=A で `GET /api/v1/gis/sites` → WHERE に org なし | `src/api/sites.py:111-143` | Critical | 全社の現場座標・住所が漏洩 | なし |
| DEF-GIS-02 | `/nearby` がテナント未分離 | `GET /sites/nearby?lat=35&lng=139&radius_m=1000` | `src/api/sites.py:146-169` | Critical | 他社現場が検索結果に混入 | なし |
| DEF-GIS-03 | `/in-area` がテナント未分離 | `GET /sites/in-area?...` | `src/api/sites.py:172-198` | Critical | 同上 | なし |
| DEF-GIS-04 | 他テナントの現場を取得 | `GET /sites/{他社id}` → 200 | `src/api/sites.py:201-216` | Critical | 越境読み取り | なし |
| DEF-GIS-05 | 他テナントの現場を更新 | `PUT /sites/{id}` → 200 | `src/api/sites.py:219-251` | Critical | 越境書き込み | なし |
| DEF-GIS-06 | 他テナントの現場を削除 | `DELETE /sites/{id}` → 200 | `src/api/sites.py:254-271` | Critical | 越境削除（データ破壊） | なし |
| DEF-GIS-07 | 作成 body の org を無検証で採用 | `POST /sites` に他社 org → 200 | `src/schemas/__init__.py:61`, `src/api/sites.py:88-104` | Critical | 他社テナント宛の現場登録 | なし |
| DEF-GIS-08 | インフラ設備一覧がテナント未分離 | `GET /infrastructure` | `src/api/infrastructure.py:93-129` | Critical | 設備情報の漏洩 | なし |
| DEF-GIS-09 | `/near-site` が現場の所有組織を検証しない | `GET /infrastructure/near-site/{他社site}` → 200、現場取得 WHERE が `id` のみ | `src/api/infrastructure.py:132-163` | Critical | 他社現場周辺の設備が取得可能 | なし |
| DEF-GIS-10 | 他テナントの設備を取得 | `GET /infrastructure/{他社id}` → 200 | `src/api/infrastructure.py:166-181` | Critical | 越境読み取り | なし |
| DEF-GIS-11 | 危険区域一覧がテナント未分離 | `GET /hazard-zones` | `src/api/areas.py:91-123` | Critical | 危険区域情報の漏洩 | なし |
| DEF-GIS-12 | `/intersecting/{site_id}` が現場の所有組織を検証しない | `GET /hazard-zones/intersecting/{他社site}` → 200、2 クエリとも org 条件なし | `src/api/areas.py:126-162` | Critical | 他社現場と重畳する危険区域が取得可能 | なし |
| DEF-GIS-13 | 他テナントの危険区域を取得 | `GET /hazard-zones/{他社id}` → 200 | `src/api/areas.py:165-180` | Critical | 越境読み取り | なし |
| DEF-GIS-14 | 他テナントの危険区域を更新 | `PUT /hazard-zones/{id}` → 200 | `src/api/areas.py:183-211` | Critical | 越境書き込み | なし |
| DEF-GIS-15 | 書き込み系の緯度範囲検証なし | `POST /sites` `coordinates=[139.0, 999.0]` → 200 | `src/schemas/__init__.py:38-41`, `src/services/geo_service.py:32-52` | High | 範囲外座標が保存され、空間検索・距離計算が破綻 | なし |
| DEF-GIS-16 | 書き込み系の経度範囲検証なし | `POST /sites` `coordinates=[999.0, 35.0]` → 200 | 同上 | High | 同上 | なし |
| DEF-GIS-17 | 座標要素不足の Point で 500 | `POST /sites` `coordinates=[139.0]` → 500 | `src/services/geo_service.py:38` | Medium | 未処理例外（IndexError）が 500 になり監視ノイズ・情報漏洩面となる（Q8） | なし |
| DEF-GIS-18 | `radius_m`（メートル）に geography キャストが無い | `GET /sites/nearby?...&radius_m=1000` → 生成 SQL に geography/球面距離関数なし | `src/api/sites.py:154-162`, `src/api/infrastructure.py:150-156`, `src/models/__init__.py:35-40` | High | 半径が座標単位（SRID の単位）で評価され、意図した距離検索にならない恐れ。**度/メートルの数値的帰結は未確認**（§6） | なし |
| DEF-GIS-19 | 逆転した bbox（min>max）を受理 | `GET /sites/in-area?min_lat=36&max_lat=35&...` → 200 | `src/api/sites.py:172-198` | Medium | 自己交差 POLYGON による検索結果の不定化 | なし |
| DEF-GIS-20 | 危険区域の並びが severity ではなく文字列辞書順 | `order_by(risk_level.desc())` → `medium > low > high > critical` | `src/api/areas.py:156` | Medium | 最重要の `critical` が末尾に来る。**並び順の仕様は未確認** | なし |

### 5.3 bim（17 件）

| ID | 症状 | 再現手順 | 根拠（ファイル:行） | 重大度 | 影響 | 修正 |
|---|---|---|---|---|---|---|
| DEF-BIM-01 | モデル一覧がテナント未分離 | org=A で `GET /api/v1/bim/models` → WHERE に org なし | `src/services/bim_service.py:70-99`, `src/api/models.py:47-67` | Critical | 全社のモデル一覧が漏洩 | なし |
| DEF-BIM-02 | 他テナントのモデルを取得 | `GET /models/{他社id}` → 200 | `src/services/bim_service.py:102-104` | Critical | 越境読み取り | なし |
| DEF-BIM-03 | 他テナントのモデルを更新 | `PUT /models/{id}` → 200 | `src/services/bim_service.py:107-123` | Critical | 越境書き込み | なし |
| DEF-BIM-04 | 他テナントのモデルを削除 | `DELETE /models/{id}` → 200 | `src/services/bim_service.py:126-132` | Critical | 越境削除 | なし |
| DEF-BIM-05 | 作成 body の org を無検証で採用 | `POST /models` に他社 org → 200 | `src/schemas/__init__.py:42`, `src/services/bim_service.py:40-67` | Critical | 他社テナント宛のモデル登録 | なし |
| DEF-BIM-06 | 要素一覧が親モデルの所有組織を検証しない | `GET /bim/{他社model}/elements` → 200、WHERE は `model_id` のみ | `src/api/elements.py:30-64` | Critical | 他社モデルの要素情報が漏洩 | なし |
| DEF-BIM-07 | 他テナントの要素を取得 | `GET /bim/elements/{他社id}` → 200 | `src/api/elements.py:67-82` | Critical | 越境読み取り（要素に org 列が無く join も無い） | なし |
| DEF-BIM-08 | 点群一覧がテナント未分離 | `GET /bim/pointclouds` | `src/api/pointcloud.py:64-95` | Critical | 他社の点群メタデータが漏洩 | なし |
| DEF-BIM-09 | 他テナントの点群を取得 | `GET /pointclouds/{他社id}` → 200 | `src/api/pointcloud.py:98-113` | Critical | 越境読み取り | なし |
| DEF-BIM-10 | 他テナントの点群を更新 | `PUT /pointclouds/{id}` → 200 | `src/api/pointcloud.py:116-142` | Critical | 越境書き込み | なし |
| DEF-BIM-11 | 他テナントの点群を削除 | `DELETE /pointclouds/{id}` → 200 | `src/api/pointcloud.py:145-162` | Critical | 越境削除 | なし |
| DEF-BIM-12 | 点群作成 body の org を無検証で採用 | `POST /pointclouds` に他社 org → 200 | `src/api/pointcloud.py:32-61` | Critical | 他社テナント宛の点群登録 | なし |
| DEF-BIM-13 | 文書化された `/elements/search` がルーティング衝突で到達不能 | `GET /api/v1/bim/elements/search?q=wall` → 422（`element_id="search"` の UUID 変換失敗） | `src/api/elements.py:30`（`/{model_id}/elements`）, `:67`（`/elements/{element_id}`）, `:133`（`/elements/search`）, 契約: `docs/api/overview.md:87` | High | 要素検索機能が常に失敗。テナント検証も不能 | なし |
| DEF-BIM-14 | モデル版番号が採番・必須化されない | `POST /models`（version 未指定）→ 200, `version=null` | `src/schemas/__init__.py:50`, `src/services/bim_service.py:40-67` | Medium | モデル版の識別・改訂追跡ができない（Q5）。版体系の仕様は未確認 | なし |
| DEF-BIM-15 | 点群に「生成版」項目が無い | `POST /pointclouds` → 応答キーに version 系なし | `src/schemas/__init__.py:165-225`, `src/models/__init__.py:116-157` | Medium | 点群版と元モデル版の対応が取れない（Q5） | なし |
| DEF-BIM-16 | 点群と元モデルの紐付け項目が無い | 同上 | 同上 | Medium | 点群→モデルの追跡不能。出来形照合の証跡が途切れる（H9） | なし |
| DEF-BIM-17 | 点群に出典（元動画ID等）の項目が無い | 同上 | 同上（参考仕様: `docs/みらい建設土木DX・AI統合基盤 全体構成 V3.5.html:326`） | Medium | 由来追跡ができない（Q5）。本サービスでの必須性は未確認 | なし |

---

## 6. 仮説（H1–H10）の判定

| 仮説 | 判定 | 根拠 |
|---|---|---|
| **H1** field-dx の `/progress` `/quality` `/reports` が `organization_id` をクエリから受け取る→越境 | **確認（真）** | DEF-FLD-01〜04, 14, 15。`?organization_id=<他社>` の値がそのままバインド値になることを実測（`bound params` を assert） |
| **H2** 出来形数量・進捗率の計算と丸め（Decimal/float、ゼロ除算、100%超、負値） | **一部確認** | 100%超・負値を受理（DEF-FLD-18/19）。数量→進捗率の算出なし（DEF-FLD-20）。ゼロ除算は安全・決定性あり（検証済）。**丸め桁の仕様は未確認** |
| **H3** 品質チェックの合否閾値のハードコード／境界値 | **閾値ロジック自体が未実装** | 合否はクライアント申告の `is_conforming`（DEF-FLD-21）。「閾値ちょうど」の判定はコード上に存在せず**判定不能（未確認）** |
| **H4** 写真メタデータ（緯度経度・撮影時刻）の検証 | **検証不能（未実装）** | `src/api/photos.py:1`「現場写真 API — stub」、`:10-18` に入力面なし。範囲外座標・未来時刻の検証対象が存在しない |
| **H5** 緯度経度の範囲検証（-90..90 / -180..180） | **検索系は有効／書き込み系は欠落** | 検索系は `Query(ge=-90, le=90)` で 422（検証済）。書き込み系は `coordinates: Any` で lat=999/lon=999 を受理（DEF-GIS-15/16） |
| **H6** SRID/測地系の明示、距離・面積の単位の明示 | **コード上は 4326 を明示／応答に単位メタデータなし** | `src/models/__init__.py:35-40` 他で `srid=4326`、`geo_service.py:38-50` で `SRID=4326` 固定。応答 GeoJSON に CRS/単位は無い（GeoJSON は WGS84 固定のため欠陥とは断定せず）。**測地系規格（JGD2011/EPSG:6668 等）は未確認** |
| **H7** 空間検索のテナント境界と半径・範囲パラメータの境界値 | **境界なし／パラメータ検証は有効** | テナント境界なし（DEF-GIS-02/03/09/12）。`radius_m>0`・緯度経度範囲は 422（検証済）。bbox の大小関係は未検証（DEF-GIS-19） |
| **H8** モデルの版管理、要素ツリーの親子整合 | **版管理は欠落／要素ツリーは未実装** | 版は任意の自由文字列で採番なし（DEF-BIM-14）。`BIMElement` に親子参照が無く、循環参照・孤児の検証対象が存在しない（**該当なし**） |
| **H9** 点群の座標系・単位・出典、版と元モデルの紐付け | **一部欠落** | `coordinate_system` / `accuracy_mm`（精度）/ `capture_method` はあるが、**生成版・出典・元モデル紐付けが無い**（DEF-BIM-15/16/17）。単位はフィールド名のみ |
| **H10** `/bim/{model_id}/elements` `/elements/search` `/pointcloud` のテナント境界 | **境界なし（search は到達不能）** | DEF-BIM-01〜12。`/elements/search` はルーティング衝突で 422（DEF-BIM-13）のため、そのテナント検証は**不能（未確認）** |

---

## 7. 修正差分の要約

**実装の修正は行っていない（差分ゼロ）。** 追加したのは以下の新規テスト 6 ファイルのみで、既存ファイルは変更していない。

```
?? services/field-dx/tests/test_quality_tenant_isolation.py
?? services/field-dx/tests/test_quality_units_coordinates.py
?? services/gis/tests/test_quality_tenant_isolation.py
?? services/gis/tests/test_quality_units_coordinates.py
?? services/bim/tests/test_quality_tenant_isolation.py
?? services/bim/tests/test_quality_units_coordinates.py
```

理由（CHARTER §1.5「業務判定ロジックを緩めない」／タスク指示「迷う修正はせず欠陥報告」）:

1. **テナント境界の修正は API 契約の変更を伴う**。`TokenData.org` は `str` でモデルの `organization_id` は `UUID` であり、
   組織の導出規則（トークンの `org` クレームの解釈、`org` 欠落時、管理者のクロステナント参照の可否、
   既存クエリパラメータの後方互換）がリポジトリ資料からは確定できない。誤った規則で実装するとWebUI・API Gateway を含む
   既存呼び出しを壊すため、**設計判断として Lead に委譲**する。
2. `approved_by`（承認者）の扱いも同様に承認フローの契約変更であり、ロール要件（誰が承認できるか）が未定義。
3. 上記以外（進捗率の範囲制約、bbox の大小検証、点群の版項目追加等）もスキーマ／レスポンス契約の変更を伴うため、
   他担当（construction / document / erp 等）と同一ファイルを触る競合リスクを避け、報告に留めた。

**最小修正案**（Lead 判断用・未適用）:

| 欠陥 | 最小修正案 |
|---|---|
| DEF-FLD-01〜16 / DEF-GIS-01〜14 / DEF-BIM-01〜12 | 各 API の依存に `get_current_user` を渡し、`TokenData.org` を `UUID` として解析して全クエリの WHERE に `organization_id` を必須化する（クエリ引数の `organization_id` は廃止または一致検証）。 |
| DEF-FLD-10 | `approved_by` をクエリから削除し、`UUID(token_data.sub)` を使用する。 |
| DEF-FLD-17 | `settings.JWT_PUBLIC_KEY` → `settings.jwt_public_key`（property）へ統一（gis/bim と同一）。 |
| DEF-FLD-18/19 | `progress_percent: float \| None = Field(default=None, ge=0, le=100)`。 |
| DEF-FLD-20 | `actual/planned` から `progress_percent` を算出する（丸め桁は仕様確定後）。 |
| DEF-FLD-21 | `standard_value`/`measured_value` を数値化し、サーバ側で合否を判定（閾値は仕様確定後）。 |
| DEF-GIS-15/16 | 緯度経度の範囲を Pydantic バリデータで検証（Point/Polygon/LineString/MultiPoint 共通）。 |
| DEF-GIS-17 | `geo_service.geojson_to_wkt` で座標要素数を検証し 422 を返す。 |
| DEF-GIS-18 | `ST_DWithin(CAST(geom AS geography), CAST(pt AS geography), radius_m)` 等に変更（PostGIS 導入が前提）。 |
| DEF-GIS-19 | `min_lat <= max_lat` / `min_lng <= max_lng` を検証。 |
| DEF-GIS-20 | `case()` による severity ランクの明示順序に変更。 |
| DEF-BIM-13 | `search_elements` の登録を `get_element` より前に移す（またはパスを `/elements/search` から `/{model_id}/elements/search` 等へ変更）。 |
| DEF-BIM-14〜17 | `version` のサーバ採番、`PointCloud` への `version` / `source_model_id` / 出典項目の追加（必須性は仕様確定後）。 |

---

## 8. 検証済み（現状で仕様を満たす）事項

* **認証境界**: 3サービスとも未認証 401／不正トークン 401／`type != user` 403（field-dx の型判定は HTTP で確認）。
* **テナント絞り込み以外の権限制御**: 到達可能な全エンドポイントで `get_current_user` が依存に設定されている（未認証の固定データ露出は既存 `test_public_endpoint_authz.py` が担保）。
* **ゼロ除算の安全性**: `GET /progress/{project}/summary` は記録 0 件で `overall_progress=0.0`、`GET /quality/{project}/stats` は 0 件で `conformance_rate=0.0`。
* **計算の決定性**: 同一入力 → 同一出力（サマリの反復実行で一致）。
* **GIS 検索系の入力検証**: `/nearby` の lat/lng 範囲外（±91/±181）と `radius_m<=0`、`/in-area` の各値範囲外はいずれも 422 で DB に到達しない（6 パターンを確認）。
* **座標参照系のコード上の明示**: `ConstructionSite`/`Infrastructure`/`HazardZone` のジオメトリ列は `srid=4326`、WKT 生成も `SRID=4326` を明示。
* **BIM モデル版の往復一貫性**: `version` を指定した場合はレスポンスに保持される。
* **GIS 応答の監査可能性**: GeoJSON Feature の properties に `organization_id` が含まれる（越境時に影響範囲が追跡可能）。

---

## 9. 未確認・未実装・残課題

**未確認（資料・検証手段が無く判定しない。創作しない）**

1. **測地系規格**: JGD2011 / EPSG:6668 等の採用を示すリポジトリ内資料は発見できず。コード上の `srid=4326` のみが確認事実。
2. **距離・面積の単位保証**: `radius_m` / `area_sqm` / `accuracy_mm` はフィールド名のみで、応答に単位メタデータが無い。
   DEF-GIS-18 の「度として解釈される」という数値的帰結は、**QA 用 DB に PostGIS が導入されていないため実測できなかった**（`select * from pg_extension` は `plpgsql` のみ）。
   → コード上に geography キャストが無いことのみを証拠としている。
3. **丸め桁・適合率の分母定義**（field-dx）: 仕様資料が無いため良否を断定せず、現状挙動の記録に留めた（DEF-FLD-22 は「仕様未確認下での過小算出」として Medium）。
4. **危険区域の並び順**（DEF-GIS-20）: 期待順序を規定した資料は無い。コードの意図（`.desc()`）との矛盾のみを報告。
5. **BIM 点群の版・出典・元モデル紐付けの必須性**: `docs/…V3.5.html:326` は ArcSphere Civil Twin / MCIP・MCAH 側の保持項目であり、本サービスの必須要件として明記した資料は無い。
6. **写真メタデータ検証**（H4）: 入力面が存在しないため検証不能（未実装）。

**未実装（欠陥ではなく機能不在として報告）**

7. field-dx の写真 API は読取専用 stub（`src/api/photos.py`）。
8. BIM の要素ツリー（親子関係）は未実装（`BIMElement` に親子参照なし）。循環参照・孤児の検証は**該当なし**。
9. BIM の要素座標（`location POINTZ, srid=4326`）は API 応答に露出しない（`BIMElementResponse` に項目なし）ため、要素単位の座標系・単位は API から検証不能。
10. `/api/v1/bim/elements/search` は到達不能（DEF-BIM-13）のため、そのテナント検証は**不能**。

**残課題（環境）**

11. QA 用 PostgreSQL（`postgresql+asyncpg://ceos_qa@127.0.0.1:55432/ceos_qa`）には **PostGIS 拡張が無く、`gis` / `bim` / `field` スキーマも存在しない**（`pg_namespace` は `public` / `information_schema` / `construction` のみ）。
    → GIS・BIM・field-dx の **実 DB 結合検証は本タスクでは実施できていない**（未実施）。実 DB 統合検証は Lead の判断と PostGIS 導入が前提。
12. 3サービスで JWT 鍵解決が不一致（DEF-FLD-17）。統一後に「3サービスが同一トークンを受け入れる」相互運用テストを追加する必要がある。

---

## 10. 制約順守の確認

| 制約 | 状態 |
|---|---|
| 書込みは担当 scope のみ | 遵守（`services/{field-dx,gis,bim}/tests/**` に新規 6 ファイルのみ。`reports/quality-tests/qa-field-gis-bim.md` を作成） |
| `git add/commit/checkout/stash` 禁止 | 未実行（`git status` は参照のみ） |
| 既存テストを壊さない／緩和・skip・削除しない | 遵守（既存 96 tests すべて pass、既存ファイルは未変更） |
| 実データ・個人情報・実在構造物の座標を使わない | 遵守（UUID は `00000000-…-0000000000xx`、座標は架空の 35.0/139.0 近傍、氏名等は既存 mock のみ参照） |
| 外部 Provider / MCP / 本番 DB / 実サービスへ接続しない | 遵守（全テストが `AsyncMock` + `dependency_overrides`。PostGIS 確認の `SELECT` 1 件のみ QA 用エフェメラル DB へ読取専用で実行し、DDL・書込みは行っていない） |
| 座標系・規格を創作しない。判定不能は未確認 | 遵守（§9 に未確認事項を明示。JGD2011/EPSG:6668 等は一切断定していない） |
| 未実行・skip・未確認を成功と書かない | 遵守（skip 0。fail 59 を欠陥として明記。未確認は §9 に列挙し成功と記載していない） |
| 並列実行時の `-p no:cacheprovider` | 全実行で付与 |
