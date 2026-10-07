# QA-IoT 品質テスト報告 — services/iot

- 担当: `[🧪 QA-IoT]` / Task: `task-11`
- 日付: 2026-10-07 (Asia/Tokyo)
- 対象: `services/iot`（現場計測・監視: devices / sensors / telemetry / alerts / machines）
- 制約遵守: synthetic fixture のみ（UUID `...00aa`/`...00bb`、センサー値は架空）。
  外部 Provider / MQTT / 本番 DB / 実サービスへ**未接続**（DB は `AsyncMock`）。
  `git add/commit/checkout/stash` は**未実施**。
- 実装修正: **なし（0件）**。理由は §5。`services/iot/src/**` は無変更。

---

## 1. 仕様根拠

| 根拠 | 内容 |
|---|---|
| `docs/architecture/01-auth-platform.md:184-199` | JWT クレームに `sub`（user-uuid）と `org`（org-uuid） |
| `docs/architecture/04-common-platforms.md:181` | ログの `organization_id` はサービスが同定 |
| `docs/api/overview.md:57-59` | IoT の対象エンドポイント（`/alerts/{id}/acknowledge\|resolve` 等） |
| `services/document/src/api/documents.py:42-43,72-79` | 参照実装: 一覧は `organization_id` をクエリに持たずトークン由来 |
| `services/iot/migrations/000_base_schema.sql:61-77` | `iot.alert_history` に **`organization_id` 列が存在しない**（`device_id` FK も無い） |
| `services/iot/migrations/000_base_schema.sql` | RLS / POLICY なし（`grep -in "row level security\|policy\|rls"` が 0 件）→ アプリ層が唯一の境界 |
| `services/iot/src/schemas/__init__.py:162,168` | `condition` と `cooldown_minutes` は API 層で検証済み（＝境界値は仕様の一部） |
| `docs/**` | acknowledge→resolve の順序、battery 範囲、テレメトリ期間上限、単位必須の**明文仕様は見つからず** → 該当項目は「要判断」 |

> `organization_id` をクエリで受ける実装は iot 固有ではなく、erp / safety / construction など 40 超の API に同型が存在する（`grep -rn "organization_id: UUID | None = Query" services/*/src/api/*.py`）。

---

## 2. 追加テスト一覧

| ファイル | 内容 | テスト数 |
|---|---|---|
| `tests/quality_helpers.py` | 共通ヘルパー（mock DB / SQL 捕捉 / synthetic factory / API バインディング復元）。**新規** | — |
| `tests/test_quality_tenant_isolation.py` | ① org 境界（device / sensor / alert-rule / alert / telemetry）＋ ③ `alert_history` 構造欠落。**新規** | 28（pass 11 / xfail 17） |
| `tests/test_quality_alert_lifecycle.py` | ② アラート状態遷移 ＋ ④ テレメトリ境界 ＋ ⑤ heartbeat ＋ ⑥ 閾値境界。**新規** | 36（pass 27 / xfail 9） |

検証手法:
- 既存 `tests/test_iot.py` と同じ `create_app()` + `dependency_overrides` + `TestClient`。
- SQL は `db.execute` に渡された文を捕捉し `literal_binds` でコンパイルして **WHERE 句のみ** 検査。
- `alert_history` の構造欠落は `AlertHistory.__table__.columns` で直接検証。
- 純関数 `_evaluate_condition` / `check_alert_rules` は直接 import して検証。
- **既存テストの副作用対策**: `test_iot.py` は `src.api.devices.register_device` 等を
  `AsyncMock` に差し替えたまま後続テストへ残す。`quality_helpers.py` の autouse fixture
  `restore_api_bindings` が実行前に実関数へ戻す（ファイル実行順に依存しない）。
- 未修正の欠陥は `xfail(strict=True)`。**修正されると XPASS→FAIL** になり気付ける。
  xfail は「成功」ではない（本報告でも pass と区別して計上）。

---

## 3. 実行コマンドと実出力（証跡）

### 3.1 ベースライン（既存のみ）

```
$ cd services/iot && python3 -m pytest tests/ -q -p no:cacheprovider
26 passed, 1 warning in 2.03s
```

### 3.2 追加テスト（欠陥の観測）

```
$ python3 -m pytest tests/test_quality_tenant_isolation.py tests/test_quality_alert_lifecycle.py -q -p no:cacheprovider
38 passed, 26 xfailed, 1 warning in 4.34s

$ python3 -m pytest tests/test_quality_tenant_isolation.py tests/test_quality_alert_lifecycle.py -q -p no:cacheprovider --runxfail
26 failed, 38 passed, 1 warning in 3.67s     # ← xfail は全て本物の欠陥検知
```

`--runxfail` で観測した実際の失敗メッセージ（抜粋）:

```
E  AssertionError: デバイス一覧がテナントで絞られていない: ''
E  AssertionError: クエリ指定の他テナント 00000000-...-00bb で絞られた: "WHERE iot.devices.organization_id = '...00bb' ..."
E  AssertionError: 他テナント 00000000-...-00bb のデバイスを 200 で返した / 更新した / 削除した
E  AssertionError: ボディの他テナント 00000000-...-00bb が保存された: 00000000-...-00bb
E  AssertionError: 他テナント 00000000-...-00bb のセンサーを 200 で返した
E  AssertionError: アラートルール一覧がテナントで絞られていない: ''
E  AssertionError: アラート履歴がテナントで絞られていない: ''
E  AssertionError: 他テナント 00000000-...-00bb のグローバルルールでアラートが生成された: [...]
E  AssertionError: ルール評価がテナントで絞られていない: "WHERE ... is_active IS true AND ..."
E  AssertionError: 他テナント 00000000-...-00bb のテレメトリを 200 で返した
E  AssertionError: 他テナント 00000000-...-00bb の最新値を 200 で返した
E  AssertionError: 他テナント 00000000-...-00bb のデバイスへ 202 で取り込んだ
E  AssertionError: 未確認のアラートが 200 で解決された
E  AssertionError: 先の確認者 00000000-...-00ee が 00000000-...-00cc に上書きされた
E  AssertionError: 解決済みの resolved_at が 2026-10-07 ... に上書きされた
E  AssertionError: 解決済みアラートを 200 で確認できた
E  AssertionError: 不正な利用者IDが 500 になった
E  AssertionError: start > end が 200 で受理された
E  AssertionError: retired が online に変わった（200）
E  AssertionError: 範囲外の battery_level が 200 で受理された
E  AssertionError: 他テナント 00000000-...-00bb のデバイスを 200 で更新した（heartbeat）
```

### 3.3 最終（全件・回帰確認）

```
$ python3 -m pytest tests/ -q -p no:cacheprovider
64 passed, 26 xfailed, 1 warning in 4.16s
```

ファイル別:

| ファイル | 結果 |
|---|---|
| `tests/test_iot.py`（既存） | 22 passed |
| `tests/test_public_endpoint_authz.py`（既存） | 2 passed |
| `tests/test_health_readiness.py`（既存） | 1 passed |
| `tests/test_response_metadata.py`（既存） | 1 passed |
| `tests/test_quality_tenant_isolation.py`（新規） | 11 passed, 17 xfailed |
| `tests/test_quality_alert_lifecycle.py`（新規） | 27 passed, 9 xfailed |
| **合計** | **64 passed, 26 xfailed, 0 failed, 0 error, 0 skipped** |

既存 26 件は無変更・全 pass（回帰なし）。`skip` は 0 件。

---

## 4. 欠陥一覧

重大度は CHARTER §5 に準拠。**修正は 0 件**（理由は §5）。

| ID | 症状（要約） | 重大度 | 修正 |
|---|---|---|---|
| DEF-01a | `GET /devices` が org 省略時に全テナントを返す | **Critical** | なし |
| DEF-01b | `GET /devices` がクエリ指定の他テナント org を信頼 | **Critical** | なし |
| DEF-02a | `GET /devices/{id}` に組織検査なし（他テナント閲覧） | **Critical** | なし |
| DEF-02b | `PUT /devices/{id}` に組織検査なし（他テナント改ざん） | **Critical** | なし |
| DEF-02c | `DELETE /devices/{id}` に組織検査なし（他テナント削除） | **Critical** | なし |
| DEF-03a | `POST /devices` がボディの `organization_id` を保存（テナント偽装） | **Critical** | なし |
| DEF-04a | `GET /devices/{id}/sensors` に組織検査なし | **Critical** | なし |
| DEF-04b | `POST /devices/{id}/sensors` に組織検査なし（他テナントへ追加） | **Critical** | なし |
| DEF-05a | `GET /alert-rules` が org 省略時に全テナントを返す | **Critical** | なし |
| DEF-05b | `GET /alert-rules` がクエリ指定 org を信頼 | **Critical** | なし |
| DEF-05c | `POST /alert-rules` がボディの `organization_id` を保存 | **Critical** | なし |
| DEF-06a | `GET /alerts` が org で絞れない（`alert_history` に組織列が無い） | **Critical** | なし |
| DEF-06b | `device_id IS NULL` のグローバルルールが**他テナントのデバイスにも適用** | **Critical** | なし |
| DEF-06c | ルール評価クエリが `organization_id` で絞られていない | **Critical** | なし |
| DEF-07a | `GET /telemetry/{device_id}` に組織検査なし | **Critical** | なし |
| DEF-07b | `GET /telemetry/{device_id}/latest` に組織検査なし | **Critical** | なし |
| DEF-07c | `POST /telemetry/ingest` がデバイス所有組織を検証しない（他テナント書込） | **Critical** | なし |
| DEF-08a | 未 acknowledge のアラートを resolve できる（順序の欠落） | High | なし |
| DEF-08b | 二重 acknowledge で先の確認者が上書きされる（証跡破壊） | High | なし |
| DEF-08c | 解決済みアラートの再 resolve で `resolved_at` が上書き（非冪等） | High | なし |
| DEF-08d | 解決済みアラートを後から acknowledge できる（状態逆行） | High | なし |
| DEF-08e | token `sub` が UUID でないと 500（未処理 `ValueError`） | Medium | なし |
| DEF-09a | `start_time > end_time` を検証せず 200（境界値の誤り） | Medium | なし |
| DEF-10a | heartbeat が `retired` デバイスを無条件で `online` に復帰 | Medium | なし |
| DEF-10b | `battery_level` の範囲検証がなく 150 等が受理 | Medium | なし |
| DEF-10c | heartbeat に組織検査なし（他テナント機の状態変更） | **Critical** | なし |

### 参考観測（未確認・要判断。テストは現状動作の記録）

| ID | 内容 | 重大度 |
|---|---|---|
| OBS-01 | `resolve` が実行者を記録しない（`resolved_by` 列なし）＝ 証跡欠落 | High（要判断） |
| OBS-02 | `/machines` `/sensors`(stub) は org 概念が無く 2 テナントで同一応答（実データ化時に漏えい） | High（要判断） |
| OBS-03 | テレメトリの `unit` が任意（欠測可）で、センサー定義単位との整合検査なし | Medium（要判断） |
| OBS-04 | テレメトリの期間上限なく 1970→2999 を受理。未来時刻も受理 | Medium（要判断） |
| OBS-05 | tz 無しの naive datetime を受理 | Medium（要判断） |
| OBS-06 | `eq` は浮動小数の厳密比較（`0.1+0.2 != 0.3`）、`inf`/`nan` の扱いが未規定 | Medium（要判断） |
| OBS-07 | `TelemetryQueryParams` スキーマが未使用（デッドコード） | Low |

---

## 5. 修正の有無と理由（**修正 0 件**）

| 対象 | 判断 |
|---|---|
| DEF-06a（`alert_history` に組織列が無い） | **列追加＝スキーマ変更**のため CHARTER/task 指示により実施せず。要判断。 |
| DEF-06b/06c（ルール評価の組織絞り込み） | 修正には「デバイスの所有組織を引いてからルールを絞る」追加クエリが必要。既存 `test_cooldown_logic` が `db.execute` の呼び出し順に依存しており、無変更では回帰する。仕様（グローバルルールの意図）も未定義のため要判断。 |
| DEF-01〜05, 07, 10c（org 境界） | 全エンドポイントへ組織検査を追加する横断変更。最小修正の範囲を超え、他チームの同型実装との整合も必要。要判断。 |
| DEF-08a〜08d（状態遷移） | 「未 ack の resolve を 400 にするか 409 か」「二重 ack を冪等にするか拒否するか」が**仕様未定義**。勝手に決めると業務条件を曲げるため実施せず。要判断。 |
| DEF-08e（非 UUID sub で 500） | 期待値（401/403）は明確だが、修正には認証ミドルウェア共通の ID 正規化方針が必要。要判断。 |
| DEF-09a（start>end） | 400/422 のどちらを返すか、`start==end` を許すかが未定義。要判断。 |
| DEF-10a/10b（retired 復帰・battery 範囲） | 「-1 を不明値として許すか」等の運用規約が未定義。要判断。 |

**したがって `services/iot/src/**` は 1 バイトも変更していない。** 既存 26 テストも無変更で全 pass。
テストが欠陥を固定し続けるため、修正時は `xfail(strict=True)` が XPASS→FAIL となり、修正者が必ず気付ける。

---

## 6. 各欠陥の詳細（症状 / 再現手順 / 根拠 / 影響）

### DEF-01a / 01b — デバイス一覧のテナント越境
- **再現**: token `org=...00aa` で `GET /api/v1/iot/devices` → 発行 SQL の WHERE が空。
  `?organization_id=...00bb` → WHERE に `...00bb` が入る。
- **根拠**: `src/api/devices.py:85,89-97`、`src/services/device_service.py:61-63`（`if organization_id:`）、`src/schemas/__init__.py:40`。
- **影響**: 全組織のデバイス（設置場所・シリアル・最終通信）が閲覧可能。RLS が無いため他層の防御もない。

### DEF-02a/b/c — デバイス個別 CRUD のテナント越境
- **再現**: `get_device_by_id`/`update_device`/`delete_device` が PK のみで取得。他テナント実体を返す状態で
  `GET`→200、`PUT`→200、`DELETE`→200（`db.delete` 実行）。
- **根拠**: `src/api/devices.py:121,138,154`、`src/services/device_service.py:31-37,76-80,93-100`。
- **影響**: 他テナント機の閲覧・改ざん・**削除**（現場監視の停止）。

### DEF-03a — 作成時テナント偽装
- **再現**: body `organization_id=...00bb` で `POST /devices` → 保存実体の組織が `...00bb`。
- **根拠**: `src/api/devices.py:73`（`body.model_dump()` をそのまま渡す）、`src/services/device_service.py:15-16`。
- **影響**: 任意組織のデバイスを登録でき、被害テナントの一覧・アラート評価に混入する。

### DEF-04a/04b — センサー子リソースのテナント越境
- **再現**: `GET /devices/{他テナントdevice}/sensors` → 200 でセンサー一覧。
  `POST /devices/{他テナントdevice}/sensors` → 201 で追加。
- **根拠**: `src/api/sensors.py:28,44`、`src/services/device_service.py:126-131,146-149`（デバイスの組織を見ない）。
- **影響**: 他テナントの計測点定義の閲覧・追加。

### DEF-05a/b/c — アラートルールのテナント越境
- **再現**: `GET /alert-rules`（org 無し）→ WHERE に組織条件なし。`?organization_id=...00bb` → その org で絞る。
  `POST /alert-rules` body org `...00bb` → そのまま保存。
- **根拠**: `src/api/alerts.py:36-37,57,62-64`、`src/services/alert_service.py:127-139`（`if organization_id:`）。
- **影響**: 他テナントの監視閾値・通知設定の閲覧／作成。

### DEF-06a — `alert_history` の構造的テナント分離不能（③）
- **症状**: `AlertHistory` に `organization_id` 列が無く（`src/models/__init__.py:122-146`、
  `services/iot/migrations/000_base_schema.sql:61-77`）、`GET /alerts` も組織パラメータを持たない
  （`src/api/alerts.py:68-78`）。`get_alert_history` は severity/device/acknowledged のみで絞る
  （`src/services/alert_service.py:142-172`）。
- **再現**: `GET /api/v1/iot/alerts?organization_id=...00bb` → 200、発行 SQL に組織条件が入らない。
- **影響**: アラート（発火履歴には現場の異常・設備状態が含まれる）が**構造的に**テナント分離できない。
  `device_id` FK すら無いため JOIN による回避もスキーマ上は保証されない。

### DEF-06b — グローバルルールの他テナント適用（③の実害）
- **再現**: `organization_id=...00bb`, `device_id=None` のルールを返す状態で
  `check_alert_rules(device_id=<ORG_A のデバイス>, value=35)` → アラートが生成される（`db.add` 呼び出し）。
- **根拠**: `src/services/alert_service.py:48-55`（`is_active` / `metric_name` / `device_id 一致 or NULL` のみ。**組織条件なし**）。
- **影響**: 他テナントが作ったグローバル閾値でアラートが発火／抑制される。通知先・重大度も相手の設定に従う。

### DEF-06c — ルール評価クエリの組織欠落
- **根拠**: 同上。発行 SQL の WHERE に `organization_id` が無いことをテストで固定。

### DEF-07a/b/c — テレメトリのテナント越境
- **再現**: `GET /telemetry/{他テナントdevice}` → 200 で計測値。`/latest` も同様。
  `POST /telemetry/ingest`（client token `org=...00aa`）に `device_id=...00bb` → 202 で受理。
- **根拠**: `src/services/telemetry_service.py:55-59`（device_id と時刻のみ）, `:69-76`（生 SQL, device_id のみ）,
  `:14-44`（所有組織の検証なし）、`src/api/telemetry.py:35,65,98`。
- **影響**: 他テナントの計測値（出来形・環境・設備稼働）の閲覧と、**他テナント時系列への書込**。
  書込はアラート評価にも波及する。

### DEF-08a〜08d — アラート状態遷移（②）
- **症状**:
  - 未 acknowledge（`acknowledged_at IS NULL`）でも `POST /alerts/{id}/resolve` が 200。
  - 既に `acknowledged_by=USER_B` のアラートを USER_A が acknowledge → 上書き。
  - `resolved_at` 設定済みでも再 resolve → `resolved_at` を現在時刻で上書き。
  - `resolved_at` 設定済みでも acknowledge 可能（状態逆行）。
- **根拠**: `src/services/alert_service.py:96-110`（状態チェックなしで代入）, `:113-124`（同）,
  `src/api/alerts.py:103-133`。
- **影響**: 「誰がいつ確認し、いつ収束したか」の証跡が壊れる。未確認のまま収束扱いにでき、監査・是正の追跡が不能。
- **要判断**: 期待挙動（409 か 400 か、冪等か拒否か）が仕様に無い。

### DEF-08e — 不正な `sub` で 500
- **再現**: `sub="not-a-uuid"` で `POST /alerts/1/acknowledge` → 500（`UUIDType(current_user.sub)` の `ValueError`）。
- **根拠**: `src/api/alerts.py:110-111`。
- **影響**: 入力起因の 500（内部エラー扱い）。監視ノイズになり、正しい 401/403 を返さない。

### DEF-09a — `start_time > end_time`
- **再現**: `GET /telemetry/{device}?start_time=2026-05-02T00:00:00Z&end_time=2026-05-01T00:00:00Z` → 200（空配列）。
- **根拠**: `src/api/telemetry.py:58-59`（必須だが順序検証なし）、`src/services/telemetry_service.py:57-58`。
- **影響**: 誤指定がエラーにならず「データ欠測」と誤認される。運用時の原因切り分けを誤らせる。
- **正の対照**: 範囲は両端包含（`>=` / `<=`）で、`limit` は 1..10000 に制限されている（テストで固定）。

### DEF-10a — heartbeat による retired 復帰
- **再現**: `status="retired"` のデバイスへ `POST /devices/{id}/heartbeat` → 200、`status="online"`。
- **根拠**: `src/services/device_service.py:111-113`（無条件に `status="online"`）。
- **影響**: 廃止・撤去済みデバイスが監視対象に復帰し、稼働台数・状態が誤る。要判断（退役の扱いが未定義）。

### DEF-10b — battery_level の範囲外
- **再現**: `POST /devices/{id}/heartbeat` body `{"battery_level": 150}` → 200。
- **根拠**: `src/schemas/__init__.py:61-64`（`int | None`、`ge/le` なし）、`:56,91`。
- **影響**: 残量が 100% 超で保存され、電池切れ予測が誤る。要判断（-1 を不明値に使う規約の有無）。

### DEF-10c — heartbeat のテナント越境
- **再現**: client token `org=...00aa` で他テナント `device_id=...00bb` へ heartbeat → 200、相手の `battery_level` が更新。
- **根拠**: `src/services/device_service.py:103-123`、`src/api/devices.py:163-177`。
- **影響**: 他テナント機の状態改ざん（`online/offline` 誤判定、電池値の汚染）。

---

## 7. PASS したが欠陥の不存在を意味しないテスト（構造証跡）

以下は「現状の事実」を固定するテストで、**PASS は安全性の証明ではない**。対応する欠陥は §4 の xfail で示す。

- `test_alert_history_model_has_no_organization_column` — 組織列・`resolved_by` 列が無いことを固定（DEF-06a/OBS-01 の根拠）。
- `test_machines_return_identical_data_for_two_tenants` / `test_standalone_sensors_return_identical_data_for_two_tenants` — 2 テナントで同一応答（OBS-02 の根拠）。
- `test_huge_time_range_is_accepted` / `test_naive_datetime_is_accepted` / `test_ingest_accepts_missing_unit` / `test_ingest_accepts_future_timestamp` — 現状動作の記録（OBS-03/04/05）。
- `test_float_equality_is_not_exact` / `test_infinity_triggers_gt` — 現状動作の記録（OBS-06）。
- `test_cooldown_boundary_suppresses_at_exact_elapsed` — `created_at >= now - cooldown` の境界セマンティクスを固定。
- `test_resolve_records_no_resolver_identity` — `resolve` が実行者を残さない事実を固定（OBS-01）。

---

## 8. 未確認事項・残課題（成功と書かない）

1. **acknowledge→resolve の正しい順序と競合時の扱い**が仕様に無い（DEF-08a〜08d）。人の判断が必要。
2. **グローバルアラートルール（`device_id IS NULL`）の意図**が不明。全社共通ルールとして意図的に全テナント適用なら欠陥ではないが、その場合もテナント分離の方針明記が必要（DEF-06b）。
3. **`alert_history` の組織列追加**はスキーマ変更。マイグレーション手順と既存データの移行方針が必要（DEF-06a）。
4. **battery_level の正規範囲**（0–100 か、-1 を不明値に許すか）が未定義（DEF-10b）。
5. **テレメトリの期間上限・未来時刻の扱い・単位必須化**が未定義（OBS-03/04）。
6. **API Gateway 側でのテナント強制**は未検証（本サービス内に遮断が無いことは確認済み）。
7. **実 DB（PostgreSQL 55432）での統合検証は未実施**。本報告の DB は `AsyncMock`。
   実 DB の制約・NULL 挙動（`alert_history.device_id` が FK でない等）は Lead の統合検証に委ねる。
8. **既存テストの副作用**: `test_iot.py` が `src.api.*` のモジュール属性を `AsyncMock` に差し替えたままにする（後始末なし）。本追加テストは autouse fixture で復元して耐性を持たせたが、**既存テスト自体の改善は未実施**。
9. xfail 26 件は**未修正の欠陥**であり成功ではない。`skip` は 0 件。

---

## 9. 再現コマンド

```bash
cd services/iot
# 全件
python3 -m pytest tests/ -q -p no:cacheprovider

# 欠陥が本物か確認（xfail を通常実行して失敗理由を見る）
python3 -m pytest tests/test_quality_tenant_isolation.py tests/test_quality_alert_lifecycle.py \
  -q -p no:cacheprovider --runxfail
```
