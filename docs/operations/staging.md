# Staging（stg）環境 — 設計と運用手順

- 正本: 本ファイル（手順）、`docs/architecture/ADR-0005-staging-environment.md`（決定）
- リポジトリ間連携: `docs/operations/staging-integration.md`
- 対象: Construction-Enterprise-OS（CEOS）
- 最終更新: 2026-10-21

## 1. 全体像

```text
開発者 / CI (main へマージ)
        │
        │  .github/workflows/staging-deploy.yml
        ▼
Cloudflare Pages `construction-os-stg`
  ├─ https://construction-os-stg.mirai-dx-platform.com   ← Cloudflare Access で保護
  │                                                        （未構成: §6 の残作業）
  └─ /api/* → Pages Functions → stg の API 入口（**本番を向けない**。§6.5）
                 └─ https://construction-os-stg-api.mirai-dx-platform.com（未構成: §6.4）
                      └─ Cloudflare Tunnel `construction-os-stg-api`（本番と別）

本ホスト（staging スタック, docker compose）
  ├─ gateway      127.0.0.1:19500   ← stg の API Tunnel の転送先（未構成）
  ├─ web          127.0.0.1:19530
  ├─ 22 サービス  127.0.0.1:19501-19521
  ├─ redis        127.0.0.1:19540
  ├─ rabbitmq     127.0.0.1:19541-19542
  ├─ kafka        127.0.0.1:19543
  ├─ elasticsearch 127.0.0.1:19544
  ├─ kibana       127.0.0.1:19545
  ├─ minio        127.0.0.1:19546-19547
  └─ db-bridge    10.201.0.1:55438 → 127.0.0.1:55438

ホスト PostgreSQL 18 クラスタ `18/infra_stg`（Mirai-Platform-Infra 管理）
  └─ データベース `ceos_stg`（stg の system of record）
```

**公開ポートは 1 つも LAN に出ない。** すべて `127.0.0.1` バインドであり、
外部からの入口は Cloudflare（Pages / Tunnel + Access）だけである（ADR-0005 §3）。

## 2. なぜ compose の override ではなく生成物なのか

`docker compose -f docker-compose.yml -f docker-compose.stg.yml` は使わない。
compose は `ports` を**加算**でマージするため、override では開発用の `0.0.0.0:8000` を
除去できず、stg を起動すると開発用ポートが LAN に露出する。
`depends_on` の除去も anchor 展開後の構造に対して行う必要がある。

そのため `docker-compose.stg.yml` は `scripts/stg/render_stg_compose.py` が
`docker-compose.yml` から**決定論的に生成**する。手で編集しない。
生成器は次を機械的に拒否する。

- stg ポートが未登録の新規サービス（`STG_PORTS` への登録漏れ検出）
- 開発用の既定資格情報（`construction-os_dev` / `minioadmin` / `dev-only`）の残存

CI（`scripts/stg/check_staging_guards.py`）が再生成内容との一致を検査するので、
`docker-compose.yml` だけ変更して stg を更新し忘れる事故は起きない。

## 3. セットアップ（初回のみ）

```bash
cd Construction-Enterprise-OS

# 1. stg の秘密ファイルを生成（~/.config/ceos/stg.env, mode 0600）
scripts/stg/gen_stg_env.sh

# 2. ホスト PostgreSQL 18 に stg の DB とロールを作成
#    （クラスタ 18/infra_stg が online であること。Mirai-Platform-Infra 管轄）
scripts/stg/bootstrap_stg_db.sh

# 3. スキーマを適用（22 SQL マイグレーション + auth/workflow の alembic）
scripts/stg/migrate_stg.sh

# 4. 合成データを投入（管理ユーザ・組織・ロール。stg はホスト PG なので
#    scripts/db/init/01-init.sql の自動実行が無い。§4.1 参照）
scripts/stg/seed_stg.sh

# 5. スタック起動
scripts/stg/up.sh
```

前提: ホスト PostgreSQL 18 クラスタ `18/infra_stg` は
**自動起動が無効（`UnitFileState=disabled`）** である。ホスト再起動後は手動で起動する。

```bash
sudo pg_ctlcluster 18 infra_stg start
```

## 4. 日常操作

```bash
sudo systemctl start ceos-stg    # systemd 経由で起動(infra/systemd/ceos-stg.service)
sudo systemctl stop ceos-stg     # systemd 経由で停止(ボリュームは保持)
scripts/stg/up.sh                 # 起動 + health 待ち
scripts/stg/up.sh --build         # イメージ再ビルドして起動
scripts/stg/down.sh               # 停止（ボリュームは保持）
scripts/stg/down.sh --purge       # 停止 + stg ボリューム削除
scripts/stg/compose.sh ps         # 状態
scripts/stg/compose.sh logs -f gateway
scripts/stg/compose.sh exec auth sh
scripts/stg/migrate_stg.sh        # スキーマ適用（冪等）
scripts/stg/seed_stg.sh           # 最小限の合成データ投入（管理ユーザ・ロール）
scripts/stg/smoke.sh              # スモークテスト
scripts/stg/restore_drill.sh      # 復旧訓練（論理バックアップから別DBへ戻して照合）
scripts/stg/e2e_stg.sh            # API の Playwright E2E を stg に向けて実行
scripts/stg/rollback_drill.sh     # 停止→復帰のロールバック訓練
scripts/stg/failure_drill.sh      # DB 到達不能時の縮退と復旧の訓練
scripts/stg/upstream_failure_drill.sh  # 上流 1 サービス停止時の縮退と復旧の訓練
scripts/stg/e2e_webui_stg.sh     # stg が配る WebUI 成果物をローカルで E2E
python3 scripts/stg/gen_release_manifest.py --check   # release 前提の充足状況
scripts/stg/status.sh            # 状態の要約（異常があれば非ゼロ終了）
scripts/stg/check_gateway_upstreams.sh  # ゲートウェイ全ルートの到達性
scripts/stg/run_mcp_live_tests.sh    # CI が skip する上流結合テストを stg で実行
python3 scripts/stg/check_business_roundtrip.py  # 業務 API の書込→読取→テナント分離
python3 scripts/stg/check_mcp_e2e.py  # MCP の初期化・一覧・実呼び出し
scripts/stg/rotate_stg_jwt.sh     # JWT 鍵の整合確認とローテーション
python3 scripts/stg/check_staging_guards.py   # 統制の検査
python3 scripts/stg/render_stg_compose.py --check
```

### 4.1 シードが必要な理由

開発環境では compose の postgres コンテナが `scripts/db/init/01-init.sql` を
`docker-entrypoint-initdb.d` として自動実行する（**スキーマ作成のみ**。§6 の dev 起動不能の項を参照）。
**stg はホスト PostgreSQL 18 を使うため、この初期化は走らない。**
`migrate_stg.sh` はスキーマだけを作るので、そのままでは `auth.users` が 0 行で
ログインできず、E2E も通らない（2026-10-14 実測）。`seed_stg.sh` が
`python -m src.seed` を実行して管理ユーザ・組織・ロールを投入する。

> **注意（RFC 2606）**: `stg-admin@example.invalid` のような予約ドメインは
> pydantic の `EmailStr`（email-validator）が special-use として **422** で拒否する。
> stg の合成アカウントは `stg-admin@stg.mirai-dx-platform.com`
> （プロジェクト自身のドメイン上に存在しないローカル部）を使う。実在の連絡先ではない。

### 4.2 復旧訓練（`restore_drill.sh`）が行うこと / 行わないこと

- **行う**: `ceos_stg` を `pg_dump -Fc` で論理バックアップし、別名の訓練用 DB へ
  `pg_restore` して、スキーマ数・テーブル数・主要表の行数を本番（= stg）と突き合わせ、
  訓練用 DB を削除する。**破壊的操作は行わない。**
- **行わない**: `pgbackrest restore` は実行しない。あれは stanza の `pg1-path` を
  書き換える破壊的操作であり、`18/infra_stg` クラスタは他システムの `mirai` DB と
  共有している。誤ると稼働中のデータを失う。**PITR の復旧訓練はホスト管理者の
  立会いの下で行う Human Gate の操作である**（§8）。
- `pg_dump` は PATH 上の 17 系ではなく **クラスタと同じ 18 系**
  (`/usr/lib/postgresql/18/bin`) を使う。17 系だとバージョン不一致で中断する（実測）。

### 4.3 JWT 鍵はアルゴリズムに整合させる（HS256 では署名鍵＝検証鍵）

auth は `jwt.encode(..., settings.jwt_private_key, algorithm=settings.JWT_ALGORITHM)` で署名し、
`jwt.decode(..., settings.jwt_public_key, algorithms=[...])` で検証する。
**`JWT_ALGORITHM=HS256`（共有鍵）のときは署名鍵と検証鍵が同一でなければならない。**

`gen_stg_env.sh` の初版は 3 つの鍵に別々の乱数を入れており、
**「ログインは 200 でトークンも出るが、認証付き API が必ず 401」**になっていた
（2026-10-14 実測）。スモークテストはこれを検出できず、
`scripts/stg/e2e_stg.sh`（Playwright `e2e/api.spec.ts` の
「JWT で users / roles が取得できる」）が 401 を出して判明した。

- 確認だけする: `scripts/stg/rotate_stg_jwt.sh --show`
- 作り直す: `scripts/stg/rotate_stg_jwt.sh` → `scripts/stg/compose.sh up -d --force-recreate auth gateway`
- RS256 へ移行するときは `JWT_PUBLIC` を別値（公開鍵）にする。スクリプトは
  `STG_JWT_ALGORITHM` を見て自動で切り替える。

`db-bridge` は `network_mode: host` のため `construction-net` のサービス名解決に載らない。
コンテナからは **ゲートウェイ IP `10.201.0.1:55438`** を使う（`DATABASE_URL` に埋め込み済み）。
また `db-bridge` の bind 先は `construction-net` のゲートウェイであるため、
**このネットワークを作るサービスと同時に起動する必要がある**。
`scripts/stg/up.sh` は全サービスを起動するので問題ないが、
`scripts/stg/compose.sh up -d db-bridge` を単独で実行すると
「Address not available」で再起動を繰り返す（`up -d redis db-bridge` のように
ネットワークに接続するサービスを 1 つ以上含めること）。

## 5. stg と dev / prod の違い

| 項目 | dev | stg | prod |
|---|---|---|---|
| `ENVIRONMENT` | `docker` | `staging` | （未定。`production` を想定） |
| API ドキュメント (`/docs`) | 有効 | **無効**（development 以外は `None`） | 無効 |
| JWT 鍵 | 開発用既定鍵を許容 | **専用鍵必須**（既定鍵だと起動失敗） | 専用鍵必須 |
| DB | compose 内 PostgreSQL 16 | **ホスト PostgreSQL 18 `ceos_stg`** | ホスト PostgreSQL 18 |
| 公開ポート | `0.0.0.0:8000` 等 | `127.0.0.1:19xxx` のみ | Tunnel のみ |
| 公開入口 | なし | Pages + Tunnel/Access | Pages + Tunnel/Access |

`ENVIRONMENT=staging` は各サービスの `get_settings()` が
「`development` / `test` 以外なら開発用既定鍵で起動を中止する」判定に引っかかる。
stg でこの統制を緩めないこと（`scripts/stg/check_staging_guards.py` の G-7 が検査する）。

## 6. 現状と残作業（2026-10-14 実測）

| 項目 | 状態 | 根拠 |
|---|---|---|
| stg 設計の正本 | 完了 | `docs/architecture/ADR-0005-staging-environment.md` |
| stg compose 生成と統制検査 | 完了 | `scripts/stg/check_staging_guards.py` **11/11 PASS**（G-9 / G-10 を追加。§6.9・§6.10） |
| **イメージの再現性** | 完了（欠陥を検出して修正） | `minio/minio:latest` を dev と stg が配っていた。**可変タグは再現性を壊す**（同じ手順で作り直しても別の環境になる）。稼働していた実体（`RELEASE.2025-09-07T16-13-09Z`）に固定し、G-9 で可変タグを禁止した。§6.9 |
| **基盤サービスの再起動方針** | 完了（欠陥を検出して修正） | redis / rabbitmq / kafka / elasticsearch / kibana / minio に `restart` が無く（compose の既定は `no`）、**落ちても誰も起こさない**状態だった（アプリ 26 件には方針があり、基盤 6 つには無いという非対称）。stg 生成器が全サービスへ `unless-stopped` を与え、G-10 で漏れを検査する。§6.10 |
| ホスト PG18 `ceos_stg` | 完了 | 20 サービススキーマ / 93 テーブルを作成（`migrate_stg.sh` 全 22 SQL + auth/workflow の alembic が成功） |
| postgis / pgvector | 完了 | `postgresql-18-postgis-3` / `postgresql-18-pgvector` を導入し `ceos_stg` へ CREATE EXTENSION（`roles.yaml` の宣言と一致した） |
| db-bridge（loopback 転送） | 完了 | `10.201.0.1:55438` LISTEN / health healthy |
| auth の DB 到達 | 完了 | `GET /health` → 200（DB 不通なら 503） |
| stg 統制の実効性 | 完了 | `/docs`・`/redoc`・`/openapi.json` → 404、`/api/v1/users` → 401、開発用既定鍵では起動を拒否（実測） |
| 合成データ | 完了 | `seed_stg.sh` で users=1 / roles=7 / organizations=1（`notification.notification_templates` は 11 行をサービスが自動投入） |
| **ログインの疎通** | 完了 | `POST /api/v1/auth/login` が gateway 経由で 200 + アクセストークン発行（実測） |
| 復旧訓練（論理） | 完了 | `restore_drill.sh` — `ceos_stg` を別DBへ復元し、スキーマ 21 / テーブル 93 / 主要表の行数が一致。訓練用DBは削除済み |
| ロールバック訓練 | 完了 | `scripts/stg/rollback_drill.sh` — 全 31 コンテナを停止し、同じリビジョンで復帰させ、health と smoke 10/10 を確認（2026-10-14）。**前リビジョンのイメージへ戻す訓練は digest 固定の release 工程が前提で未整備**。記録: `reports/staging/rollback-20261014.md` |
| **障害訓練（上流 1 サービス停止）** | 完了 | `scripts/stg/upstream_failure_drill.sh` — 対象（既定 `vision`）を止め、D-1 ゲートウェイは 200 のまま / D-2 集約ヘルスが**そのサービスだけ**を unhealthy と報告 / D-3 無関係な上流は 19ms で応答 / **D-4 停止した上流へは 504 を 3.0 秒で返す（ハングしない）** / D-5 他のコンテナは落ちない / D-6・D-7 復旧後に healthy とスモーク 12/12。`STG_DRILL_SERVICE` で対象を変えられる（`erp` でも実測済み）。記録: `reports/staging/upstream-failure-20261014.md`。§6.14 |
| **障害訓練（DB 断）** | 完了 | `scripts/stg/failure_drill.sh` — `db-bridge` を止めて DB 到達不能を作り、`auth /health` が **503** に縮退（fail-closed）し、gateway は 200 のまま、再起動ループに入るコンテナは無く、復旧後に auth が自動で 200 に戻り smoke 12/12 が通ることを実測。記録: `reports/staging/failure-20261014.md` |
| WebUI 成果物の E2E | 完了 | `scripts/stg/e2e_webui_stg.sh` — Pages が配る単一 HTML をPages と同じ SPA フォールバックでローカル配信し、`mvp.spec.ts` + `crud.spec.ts` が **34 passed / 6 skipped / 0 failed**。**デプロイ前に成果物を検証する**経路になった（従来は本番 URL 直叩き） |
| release マニフェスト | **NOT_READY（5 件）** | `gen_release_manifest.py --check` — RELEASE_TAG / SEMVER / ATTESTATION_WORKFLOW / IMAGE_DIGESTS / ITSM_CHANGE が未充足。`CORE_VERSION` と `DEPLOY_HOSTS` は充足。**創作せずに停止する**（Release は Human Gate） |
| GitHub Environment `staging` | 完了 | `gh api .../environments` に `staging` と `production`（既存） |
| 状態監視（手動） | 完了 | `scripts/stg/status.sh` — クラスタ / db-bridge / コンテナ / スモーク / DB の中身（users 0 行の検出）/ pgBackRest を 1 コマンドで要約し、異常時は非ゼロ終了。cron・systemd timer から呼べる（実測: 全項目 OK / exit 0） |
| **状態監視（常設）** | 完了 | 上記は「誰かが叩いたときだけ」走っており、**timer は 1 つも無かった**（2026-10-14 実測: `systemctl list-timers --all \| grep -i ceos` → 0 件）。`scripts/stg/monitor.sh` と `infra/systemd/ceos-stg-status.{service,timer}` を追加し、5 分ごとに検査するようにした。§6.6 |
| **監視の通知経路** | 口を用意（送信先は未設定） | 失敗は journald と systemd の `failed` に残るだけで**誰にも届かなかった**。`CEOS_STG_ALERT_WEBHOOK` があれば初回と 1 時間ごとに POST し、無ければその事実をログに明示する。**現時点で送信先は未設定**である。§6.11 |
| ゲートウェイルーティング | 完了 | `scripts/stg/check_gateway_upstreams.sh` — **21 上流すべて**の `/health` に到達（ルート定義 30 件）＋ 外側から実測済み 14 ルートが応答。従来は auth 系しか見ておらず、他 20 サービスへのルートは未検証だった |
| **集約ヘルスの網羅** | 完了（欠陥を検出して修正） | `GET /api/v1/health/services` は **3 件しか見ていなかった**のに「全サービス healthy」と表示されていた（21 上流のうち 17 は対象外）。stg で `vision` を止めても `overall: healthy` のままだった。全上流（20 ＋ auth 自身 = 21）へ広げ、`scripts/ci/check_health_coverage.py`（`make health-coverage`）で網羅を検査する。§6.12 |
| **ダッシュボードの状態表示** | 完了（欠陥を検出して修正） | 画面は `"running"` / `"operational"` だけを正常として扱っていたため、API が返す `"healthy"` が**「警告」と黄色**で表示されていた。レイテンシも API の `latency_ms` ではなく存在しない `latency` を読んでいたため**一度も表示されていなかった**。写像を `lib/service-health.ts` へ切り出して 12 テストで固定した。§6.13 |
| **上流 1 サービスの停止** | 完了（欠陥を検出して修正） | `vision` 停止中も `gis` は 19ms で応答し、**巻き込みは無い**。当初は**停止した上流への要求が 502 を返すまで 16.1 秒**かかった。原因は HTTP タイムアウトではなく**名前解決**（停止したコンテナは Docker DNS が答えられず外部リゾルバへ転送されて約 16 秒でタイムアウトする）。**全サービスの静的 IP ＋ gateway の `extra_hosts` ＋ 接続タイムアウトの分離**で **504 / 3.0 秒**に短縮（G-11 で再発防止）。§6.14 |
| **MCP の実呼び出し** | 完了 | 未認証 401 / `initialize` / `tools/list` が契約と一致 / `tools/call` が上流から実データを取得。初回は `CONSTRUCTION_SERVICE_URL` / `ERP_SERVICE_URL` を compose で渡しておらず、`tools/call` が `isError: true`（「上流サービスに到達できません。」）を返していた。**`result` が返ること自体を成功とみなす検査は見逃す**ため、`isError` を不合格にする |
| **CI が skip するテストの実行** | 完了 | `services/mcp/tests/test_upstream_live.py` は上流へ TCP 到達できないと **CI では常に skip** される。stg では上流が動いているので `scripts/stg/run_mcp_live_tests.sh` で実行できる。実行したところ、テストヘルパーが固定鍵で署名しており**実環境では必ず INVALID_TOKEN になる**ことが判明した（修正済み。live 2 passed / MCP 全体 95 passed） |
| **業務 API の往復** | 完了 | `scripts/stg/check_business_roundtrip.py` — 管理ユーザでログインし、`POST /api/v1/erp/ledger` で合成台帳を作成 → 読み戻し → 集計反映 → スコープ確認（B-5 / B-5b / B-5c）→ SQL で 1 行だけ削除。再実行しても残留行 0 件。**これまで業務サービスへの書込みは一度も通っていなかった** |
| **テナント分離（本来の試験）** | 完了（欠陥を検出して作り直した） | 旧 B-5 は「別組織を要求しても返らない」を**分離の証拠として表示していたが、根拠が無かった**（使用トークンが `roles: ['admin']` で、`scope_org()` は admin に要求組織をそのまま返す設計。0 件は「他組織にデータが無い」だけ）。非 admin の経路は stg に該当ユーザーが居らず**一度も実行されていなかった**。`scripts/stg/check_tenant_isolation.py` を追加し、現場組織の非 admin ユーザーで T-1〜T-5（陽性対照つき）を実測。§6.8 |
| **mobile の実行形態** | 完了 | 旧版は `output: 'export'` と書きながら `next dev`（開発サーバ）で配信しており、stg が本番の実行形態を練習していなかった（§9 D-1）。2 ステージビルドにして静的エクスポート `out/` を 依存ゼロの `serve.mjs` で配信する。smoke の S-10 が `x-ceos-static-export` で回帰検査する |
| kibana の healthcheck | 完了 | 未定義で `status.sh` の healthy 判定対象外だった（§9 D-3）。公式イメージの `curl` で `/api/status` を叩く healthcheck を追加（start_period 180s）。**全 32 コンテナが healthy** になった |
| **systemd 管理** | 完了 | `infra/systemd/ceos-stg.service` を追加し `/etc/systemd/system/` へ設置。`systemctl start/stop` で 32 コンテナの起動・停止を実測（停止後 0 個 → 起動後 32 個、smoke 12/12）。**enable は保留**（stg の DB クラスタが disabled のため、B-2 の決定と同時に判断する） |
| **dev の compose 起動不能** | 完了 | `scripts/db/init/01-init.sql` が initdb 時点で `INSERT INTO auth.organizations` を実行しており、表はマイグレーションが作るため空 DB で必ず失敗していた（`psql -v ON_ERROR_STOP=1` → exit 3）。docker-entrypoint は `ON_ERROR_STOP=1` なので **dev の compose は初回起動できなかった**。DDL とシードを分離し（`scripts/db/seed/00-bootstrap.sql` / `make db-seed`）、あわせて ENUM 列（`org_type` / `org_status`）の暗黙キャスト不能も修正した |
| **erp の基盤 DDL** | 完了 | `services/erp` は `MetaData(schema="erp")` のモデルを持つのに、`src/models/__init__.py` が空で metadata に登録されず、生成器の TARGETS からも漏れていた。そのため `erp` スキーマが stg に存在せず `/api/v1/erp/ledger/summary` が 500（`UndefinedTableError: erp.project_ledger`）。両方修正し 5 テーブルを作成、両エンドポイントが 200 になった |
| **Web → API プロキシ** | 完了 | `apps/web` は `output: "standalone"` のため `rewrites()` が**ビルド時**に確定し、Docker の runtime `API_GATEWAY` が効かない。ビルド引数で渡さないと`http://localhost:9000` が焼き込まれ `/api/*` が **500** になる（2026-10-14 実測）。`build.args.API_GATEWAY` を追加して修正し、smoke の S-9 で回帰検査する |
| PITR 復旧訓練（pgBackRest） | **未実施** | stanza `infra_stg` は `status: ok`（最新 diff 2026-10-14 02:30）。`pgbackrest restore` は `migrated` を書き換える破壊的操作のため Human Gate（§4.2） |
| Pages プロジェクト `construction-os-stg` | 完了 | id `eeb3c5fd-e463-4245-a57d-6fffe32dbb96` / `construction-os-stg.pages.dev` / production_branch `main` |
| Cloudflare Access アプリ | 完了 | id `f2939b1b-93b2-41a9-ab77-38a9fad953bc`（self_hosted / policy 1 件: allow = メール 1 件 ＋ メールドメイン `mirai-const.co.jp` / `bypass` 0 件。2026-10-14 実測） |
| Pages カスタムドメインのバインディング | 作成済み（pending） | id `aa3ac4c2-a329-42eb-8bfd-3158d57934e7` / `verification_data.error_message="CNAME record not set"` |
| **DNS CNAME `construction-os-stg`** | **未完了（ブロッカー 1）** | 使用可能な資格情報に Zone→DNS→Edit が無く `10000: Authentication error` |
| **CI ワークフローの設置** | **未完了（ブロッカー 2）** | ハーネスポリシーが `.github/workflows/**` への書込を DEPLOY(critical) として拒否。内容は `docs/operations/staging-deploy.workflow.yml` に確定済み |
| **Pages から本番 API への越境** | 完了（欠陥を検出して修正） | 共有 `webui/functions` が本番 API を向いており、stg へそのまま配ると越境した（実測）。`scripts/stg/render_pages_functions.py` で描画し、`scripts/stg/check_pages_upstream.py` で不変条件化した。§6.5 |
| Cloudflare Tunnel（API 公開） | **リポジトリ側は完了／有効化は未実施** | unit（`infra/systemd/construction-os-stg-api-cloudflared.service`）と準備スクリプト（`scripts/stg/prepare_api_tunnel.sh`、既定は dry-run）を追加。**トンネルの作成・DNS ルート・有効化は未実施**（DNS 権限が無い）。ホストに `cloudflared` は導入済み。値を 4 か所で突き合わせる G-13 を追加。§6.4 |
| 全スタックの起動 | 完了 | `scripts/stg/compose.sh up -d` で 31 コンテナが Up（30 healthy + kibana。kibana は healthcheck 未定義） |
| スモークテスト | 完了 | `scripts/stg/smoke.sh` が **9/9 PASS**（gateway / auth / web / 401 / docs無効 / ログイン / トークン / db-bridge / DB 到達） |
| **API E2E** | 完了 | `scripts/stg/e2e_stg.sh` — Playwright `e2e/api.spec.ts` が **16/16 PASS**（desktop/mobile）。この E2E が JWT 鍵の不整合（ログインは 200 だが認証付き API が 401）を検出した。§4.3 |
| **MCP サービス** | 完了 | `services/mcp` は実装も契約 `contracts/mcp-tools/ceos.json` もあったが compose に無く起動していなかった。compose へ追加し、公開ツール 5 件が契約と一致することを S-8 で検査（読み取り専用 R0 のみ） |
| アプリロールのスキーマ権限 | 完了 | `scripts/stg/grant_stg_privileges.sh`（全スキーマへ USAGE と DML） |
| stg クラスタの自動起動 | 未対応（Infra 側） | `UnitFileState=disabled`。ホスト再起動後は手動起動が要る |

### 6.0 ブロッカー 1: DNS レコード作成（要: Zone→DNS→Edit 権限）

```bash
ZONE_ID=e375e651e49a40801a305b89e297bff0
curl -sS -X POST \
  -H "Authorization: Bearer $CLOUDFLARE_API_TOKEN" -H "Content-Type: application/json" \
  "https://api.cloudflare.com/client/v4/zones/$ZONE_ID/dns_records" \
  -d '{"type":"CNAME","name":"construction-os-stg","content":"construction-os-stg.pages.dev","proxied":true,"ttl":1,"comment":"CEOS staging frontend"}'
```

### 6.2 ブロッカー 2: CI ワークフローの設置（ポリシー上の制約）

本セッションのハーネスポリシー（Self-Evolution Policy Gate）は
`.github/workflows/**` への AI からの書込を `DEPLOY`（critical）として**常時拒否**する。
CI 定義の変更は高影響であり、AI が単独で設置しないための統制である。

内容は `docs/operations/staging-deploy.workflow.yml` に確定させてある。設置は次の 1 コマンド。

```bash
cp docs/operations/staging-deploy.workflow.yml .github/workflows/staging-deploy.yml
git add .github/workflows/staging-deploy.yml
git commit -m "ci(stg): staging への自動デプロイを追加する"
git push origin <branch>
```

設置後は通常の PR フロー（Required Checks PASS 後に squash 自動マージ）に乗る。

### 6.3 参考: 拡張の導入（実施済み）

```bash
sudo apt-get install -y postgresql-18-postgis-3 postgresql-18-pgvector
# bootstrap_stg_db.sh が ceos_stg へ CREATE EXTENSION IF NOT EXISTS する
scripts/stg/bootstrap_stg_db.sh
```

Mirai-Platform-Infra の `db/roles.yaml` は
`extensions: [vector, postgis, pg_trgm, pgaudit, pg_stat_statements]` を宣言していたが、
**実クラスタには postgis と vector が入っていなかった**（2026-10-14 実測）。
本作業で導入し、台帳の宣言と実体を一致させた。`pgaudit` は未導入である。

### 6.4 Cloudflare Tunnel（API を stg ドメインで公開する場合）

`docs/operations/deployment.md` §8 と同じ家族パターンで、
`~/.cloudflared/construction-os-stg-api-config.yml` を作り、
転送先を `http://127.0.0.1:19500`（stg の gateway）にする。
既存の `construction-os-api` トンネルとは**別トンネル**にすること
（stg と prod で入口を共有しない）。

| 項目 | 値 |
|---|---|
| stg の API 公開ホスト | `construction-os-stg-api.mirai-dx-platform.com` |
| 転送先 | `http://127.0.0.1:19500`（gateway。22 サービスへパスで振り分ける） |
| トンネル名 | `construction-os-stg-api`（**本番の `construction-os-api` と別**） |
| ローカル設定 | `~/.cloudflared/construction-os-stg-api-config.yml`（認証情報はリポジトリ外） |

このホストは `staging-deploy.workflow.yml` の `STG_API_UPSTREAM` と
**同じ値でなければならない**。

#### リポジトリ側の正本（2026-10-14 追加）

以前は §6.4 の文章だけで、**systemd unit も生成手順も無かった**。DNS が解けた
瞬間に有効化できるよう、正本をリポジトリに置いた。

| 実体 | 役割 |
|---|---|
| `scripts/stg/prepare_api_tunnel.sh` | 設定の生成・トンネルの作成・unit の設置・**DNS ルートのコマンド表示**。既定は `--dry-run`（何も書き換えず、生成される設定と実行するコマンドを表示する） |
| `infra/systemd/construction-os-stg-api-cloudflared.service` | トンネルを systemd 管理下で動かす unit（**正本はリポジトリ**。手で `/etc` を編集しない） |

```bash
scripts/stg/prepare_api_tunnel.sh                  # 何をするかを見る（書き換えない）
scripts/stg/prepare_api_tunnel.sh --apply          # 設定とトンネルを用意する
scripts/stg/prepare_api_tunnel.sh --apply --install-unit   # unit も設置する（sudo）
```

**DNS ルートはこのスクリプトでは実行しない**（Zone→DNS→Edit 権限が必要。§6.0）。
`--apply` は最後に `cloudflared tunnel route dns construction-os-stg-api …` を
表示して止まる。unit も `enable` しない（有効化は §6.4 の前提が整ってから）。

値は **4 か所**（文書・`staging-deploy.workflow.yml`・スクリプト・compose）に現れる。
片方だけ直すと静かに食い違うため、`scripts/stg/check_staging_guards.py` の
**G-13** が突き合わせる（転送先ポート = stg compose の gateway の公開ポート /
公開ホスト = `STG_API_UPSTREAM` / 公開ホストが §6.4 に記載されていること）。

### 6.5 stg から本番 API への越境を塞ぐ（2026-10-14 実測の欠陥）

`webui/functions/api/[[path]].ts`（Cloudflare Pages Function）は
`/api/*` を**単一の固定アップストリーム**へ無条件に転送し、その値は**本番 API** である。

```ts
const target = new URL(`https://construction-os-api.mirai-dx-platform.com/api/${path}`);
```

prod の Pages（`construction-os-web`）と stg の Pages（`construction-os-stg`）は
この 1 ファイルを共有する。したがって `staging-deploy.workflow.yml` が
`webui/functions` をそのままコピーして `construction-os-stg` へ配ると、
**stg の画面が本番 API を叩く**。実測（workflow と同一手順で組み立てた
`.deploy-webui` に対して）:

```
$ grep -c construction-os-api.mirai-dx-platform.com .deploy-webui/functions/api/[[path]].ts
2       # 本番 API ホスト
$ grep -c construction-os-stg .deploy-webui/functions/api/[[path]].ts
0       # stg ホスト
```

`ADR-0005` §3（stg と prod で入口を共有しない）と §8-5
（stg から prod の DB・DNS・secret へ触れない）に反する。
**preflight は DNS と Access しか見ないため、DNS ブロッカーが解けた瞬間に
越境したまま「緑で」デプロイされ得た**（人の記憶では止まらない）。

対策:

| 層 | 対策 |
|---|---|
| デプロイ時 | `scripts/stg/render_pages_functions.py` が `STG_API_UPSTREAM` へ描画し直す。本番ホストを入口に指定すると**描画せずに終了コード 2**、描画後に本番ホストが残っても**出力を削除して終了コード 2** |
| デプロイ定義 | `webui/functions` のベタコピーを廃止。描画ステップと「本番の入口が 0 件」の検査ステップを追加 |
| 不変条件 | `make stg-pages-upstream`（`scripts/stg/check_pages_upstream.py`）。C-1〜C-6 を検査し、**陽性対照（stg 入口で描画 → 本番ホスト 0 件）と陰性対照（本番入口 → 拒否）を毎回実行する** |

```bash
# 手動でデプロイする場合も、functions/ をそのままコピーしない
python3 scripts/stg/render_pages_functions.py \
  --src webui/functions \
  --dst .deploy-webui/functions \
  --upstream https://construction-os-stg-api.mirai-dx-platform.com
make stg-pages-upstream
```

### 6.6 stg の健全性を常時検査する（2026-10-14 追加）

`scripts/stg/status.sh` は「cron・systemd timer から呼べる」と書いてあったが、
**timer は 1 つも無く**（`systemctl list-timers --all | grep -i ceos` → 0 件）、
検査は誰かが叩いたときだけ走っていた。stg は常時監視されていなかった。

| 実体（正本は `infra/systemd/`） | 役割 |
|---|---|
| `scripts/stg/monitor.sh` | 判定を持つ本体。unit に shell を書かない |
| `infra/systemd/ceos-stg-status.service` | `monitor.sh` を oneshot で実行する |
| `infra/systemd/ceos-stg-status.timer` | 5 分ごと（`OnCalendar=*:0/5` / `RandomizedDelaySec=20s`）に起動する |

```bash
sudo install -m 644 infra/systemd/ceos-stg-status.service /etc/systemd/system/
sudo install -m 644 infra/systemd/ceos-stg-status.timer   /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now ceos-stg-status.timer

systemctl list-timers ceos-stg-status     # NEXT を確認
journalctl -u ceos-stg-status -n 50
tail -40 ~/.local/state/ceos-stg/status.log
```

判定（`monitor.sh`）:

1. `ceos-stg.service` が **active でなければ検査を省略**して 0 を返す。
   「止まっていること」は `ceos-stg.service` の状態で見える。ここで失敗を積むと、
   停止が常態のときに失敗が常態化して本当の異常が埋もれる
   （スタックを自動起動するかは Infra の未決 B-2 と同時に決める。
   `ceos-stg.service` は enable していない）。
2. active なら `status.sh` を実行し、**その終了コードをそのまま返す**。
   異常を握りつぶさないため、systemd が `failed` として記録する。
3. 実行のたびに日時と要約を `~/.local/state/ceos-stg/status.log` へ追記する
   （journald だけでは「いつから異常か」を追いにくい）。4000 行を超えたら直近だけ残す。

実測（2026-10-14）:

```
$ systemctl list-timers ceos-stg-status
NEXT                         LEFT      UNIT                  ACTIVATES
Wed 2026-10-14 12:15:08 JST  2min 15s  ceos-stg-status.timer ceos-stg-status.service

$ sudo systemctl start ceos-stg-status
  Process: … (code=exited, status=0/SUCCESS)
  OK  : 32 コンテナ / スモーク 12/12 / 22 schemas / 98 tables / pgBackRest ok

# 陰性対照: status.sh が 3 を返す差し替えで monitor.sh が 3 を返す（握りつぶさない）
# 陽性対照: 0 を返す差し替えで 0
```

### 6.7 Pages の公開面（`*.pages.dev` と ACME）

2026-10-14 に Cloudflare の公式文書と既存構成を突き合わせた結果である。

**1. `*.pages.dev` は「既定では」Access の対象にならない（記述の是正）**

`staging-deploy.workflow.yml` には「pages.dev は Cloudflare の制約により Access の対象にできない」
と書いてあったが、これは**不正確**である。公式文書の表現は次のとおり。

- プロジェクト設定の **Enable access policy** が守るのは**プレビューのみ**
  （`373f31e2.<project>.pages.dev` のようなもの）。
- **`*.pages.dev` 本体**を守る手順は Known issues に記載がある
  （<https://developers.cloudflare.com/pages/platform/known-issues/#enable-access-on-your-pagesdev-domain>）:
  `Enable access policy` → 作成された Access アプリの `Manage` → **Public hostname の Subdomain から
  ワイルドカード `*` を削除**して保存 → プレビュー用のポリシーを作り直す。

したがって `construction-os-stg.pages.dev` を公開のままにするのは**制約ではなく選択**である。
守る場合の副作用: `*.pages.dev` に Access を掛けると**プレビューURLの保護が外れる**ため、
手順どおり `*.<project>.pages.dev` のポリシーを作り直す必要がある。

**2. カスタムドメインの検証には ACME パスの許可が要る（文書化されたリスク）**

公式文書は「Cloudflare が `http://{domain}/.well-known/acme-challenge/*` を検証できないと
カスタムドメインは verify されない。Access か Worker がそのパスを許可していること」と述べている。
本 stg の Access アプリ（allow = メール 1 件 ＋ メールドメイン）には**そのパスを許可する設定が無い**。

ただし**実測ではこれが障害になっていない**:

| ドメイン | DNS | HTTP | Access の ACME 許可 |
|---|---|---|---|
| `3dgs-stg.mirai-dx-platform.com`（CSSP stg・稼働中の前例） | 解決する | **302**（Access が遮断） | **無し**（同じ構成） |
| `construction-os-stg.mirai-dx-platform.com` | **解決しない** | 到達不能 | 無し |
| `construction-os-stg.pages.dev` | 解決する | **522**（デプロイ未実施） | — |

つまり CSSP stg は ACME 許可が無いまま動作している。**未解明のまま「問題ない」と断定しない。**
DNS（ブロッカー 1）を解消した後、カスタムドメインが `pending` から進まない場合は、
この ACME パスの許可（Access の `bypass` に `/.well-known/acme-challenge/*` を追加）を
最初に疑うこと。**現時点では「文書化されたリスク」であって「実測した欠陥」ではない。**

### 6.8 テナント分離は「測れていなかった」（2026-10-14 の検出）

`check_business_roundtrip.py` の B-5 は
「別組織を要求してもトークンの組織の行だけが返る」と表示し、`MCDX-ADR-0004` の
テナント分離の証拠として扱われていた。**しかし根拠が無かった。**

このスクリプトが使うのは stg の管理ユーザで、そのトークンは `roles: ['admin']` である。
`services/erp/src/middleware/tenant.py` の `scope_org()` は
**admin には要求された組織をそのまま返す**（クロス組織アクセスは設計）。
したがって「他組織を要求 → 0 件」は「**他組織にデータが無い**」だけである。

実測（2026-10-14、管理ユーザ）:

| 要求 | 結果 | 意味 |
|---|---|---|
| パラメータ無し | 200 / 1 件（自分の行を含む） | 正常 |
| 自分の組織を指定 | 200 / 1 件 | 正常 |
| 他組織を指定 | 200 / **0 件** | **admin のクロス組織仕様が効いているだけ** |

さらに B-5 の判定は**逆**だった。正しい実装（パラメータを無視して JWT の org を使う）なら
自分の行が返るはずで、それを B-5 は「FAIL」としていた。

**本来の分離は非 admin でしか測れない。** ところが stg には管理ユーザ 1 人しかおらず、
非 admin の経路は**一度も実行されていなかった**（`auth.users` = 1 行）。
つまり「分離を検証した」という記録は、**検証していないものを検証したと書いていた**。

対策: `scripts/stg/check_tenant_isolation.py` を追加し、現場組織の非 admin ユーザーで実測する。

| 検査 | 内容 |
|---|---|
| T-0 | 分離試験用の非 admin ユーザー（現場組織 / role なし）を冪等に用意する |
| T-1 | 非 admin でログインでき、トークンに admin が含まれない |
| T-2a | **陽性対照**: 管理ユーザの一覧には検体が含まれる（これが無いと T-2 は何も測っていない） |
| T-2 | 本社組織の行が現場組織のユーザーに見えない |
| T-3 | 他組織を要求すると **403 ORG_FORBIDDEN**（クエリ） |
| T-4 | 他組織を指定した作成は **403 ORG_FORBIDDEN**（ボディ） |
| T-5 | 後始末（検体を 1 行削除） |

erp の台帳 API は権限チェックを持たず `get_current_user` と `scope_org()` / `create_org()`
だけで守られているため、403 の理由が「権限不足」と混同されない（**エラーコードで判別する**）。

実測（2026-10-14）:

```
$ python3 scripts/stg/check_tenant_isolation.py
PASS: T-1 非 admin でログインできた（org=20000000-…-0004 / roles=[]）
PASS: T-2a 管理ユーザの一覧には検体が含まれる（1 件）
PASS: T-2 本社組織の行は見えない（現場組織のユーザーの一覧 0 件）
PASS: T-3 他組織の要求は 403 ORG_FORBIDDEN で拒否された
PASS: T-4 他組織への作成は 403 ORG_FORBIDDEN で拒否された
PASS: T-5 検体を削除した
OK: テナント分離を**非 admin の経路で**実測した（T-1〜T-5）。
```

**これが stg でテナント分離が実測できた最初の記録である。**

限界（正直な記録）:

- 対象は **erp の台帳 API のみ**。同じ `tenant.py` を持つ他 17 サービスの **API は未検証**である。
  ただし **ヘルパの振る舞いは全 18 サービスで検証済み**になった（下記）。
- 分離試験用ユーザーのパスワードは**合成の定数**である（stg 専用。実在の資格情報ではない）。

#### 18 個の複製を「振る舞い」で検査する

`tenant.py` は **18 サービスに複製**され、2026-10-14 の実測で**5 変種に分裂**していた
（差分は `is_cross_org_admin` の `user.roles` と `(user.roles or [])` の 1 点。
各サービスの `TokenData` は常にリストを供給するため**現時点で実害は無い**）。
テキストの一致を求めると正当な差分（import 元・コメント）まで落ちるので、
`scripts/security/check_tenant_helper_conformance.py` が**分離に効く振る舞い**を直接叩く。

| 検査 | 内容 |
|---|---|
| H-1 | `token_org` / `scope_org` / `create_org` が import できる（できない場合は FAIL。黙って飛ばさない） |
| H-2 | 非 admin ＋ 組織未指定 → 自分の組織が返る |
| H-3 | 非 admin ＋ 他組織を要求 → **403 ORG_FORBIDDEN** |
| H-4 | 非 admin ＋ 他組織へ作成 → **403 ORG_FORBIDDEN** |
| H-5 | 非 admin ＋ 自組織へ作成 → 自分の組織が返る |
| H-6 / H-7 | admin ＋ 未指定 → `None`（全組織） / admin ＋ 他組織 → その組織（設計どおり） |
| H-8 / H-9 | 組織クレームが無い / UUID でない → **403 ORG_REQUIRED / ORG_INVALID**（fail closed） |
| H-10 | `tenant.py` を持たず `organization_id` を参照するサービスは**理由つきで宣言**されている |

実測（2026-10-14）: **18 サービスすべてが H-1〜H-9 に適合**（`make tenant-conformance`）。
H-10 で `mcp` / `workflow` / `auth` を宣言した（それぞれ理由はスクリプト内）。

- `workflow` は `src/api/workflows.py` の `_organization_id()` で**独自に**同等の統制を持つ。
  ただし **admin でも他組織を拒否する**（erp の `scope_org()` は admin にクロス組織を許す）。
  厳しい側なので穴ではないが、**同じ役割でサービスごとに権限が異なる**ことは記録に値する。
- `mcp` は組織スコープを実装せず、**呼び出し元の Authorization をそのまま上流へ渡す**。
  バイパスしないことを実測した（audience 束縛トークンの交換は
  `services/auth/src/services/token_exchange_service.py:108-112` が
  `sub` / `org` / `roles` / `scopes` を被交換トークンから引き継ぎ、権限を昇格させない）。
- `gateway` / `notification` は `organization_id` を参照しない（組織単位のデータを持たない）。

#### 67 のエンドポイントがヘルパを通しているかを AST で検査する

18 個のヘルパが正しくても、**エンドポイントがそれを使っていなければ**意味がない。
`scripts/security/check_org_query_scoping.py` が
「クエリで `organization_id` を受ける関数」を構文木で探し、
その名前の**すべての使用が `scope_org` / `create_org` の引数である**ことを要求する。

実測（2026-10-14）:

```
$ python3 scripts/security/check_org_query_scoping.py
Q-1 クエリで organization_id を受けるエンドポイント: 67 件
  免除 auth:list_notification_recipients（internal）
  免除 workflow:list_definitions（own-guard）
  免除 workflow:list_instances（own-guard）
Q-4 宣言された免除: 3 件（3 件が実在を確認）
OK: クエリの organization_id はすべてスコープされている（67 件・免除 3 件）
```

**67 件すべてが規約どおり**だった。免除した 3 件は次の理由で、いずれも**宣言が実体と合うことを毎回検証する**（Q-4）。

| 免除 | 種別 | 理由 |
|---|---|---|
| `workflow:list_definitions` / `list_instances` | `own-guard` | 独自の `_organization_id()` で JWT の org を取り、不一致を 403 `ORG_FORBIDDEN` で拒否する。関数ソースに `ORG_FORBIDDEN` が無ければ FAIL にする |
| `auth:list_notification_recipients` | `internal` | `/internal/...` は組織を**指定して**利用者を引くサービス間 API。利用者向けの分離対象ではない |

**検査が空回りしていないことを毎回確認する**（Q-2 陰性対照＝生の使用を検出できる、
Q-3 陽性対照＝正しい使用を誤検出しない）。

変異試験（実測）:

| 変異 | 結果 |
|---|---|
| `document` の一覧で `scope_org(token_data, organization_id)` を `organization_id` に変える | **NG** — `Q-1 document:235 list_documents() が scope_org を通さずに使っている` |
| 実在しない免除を宣言する | **NG** — `Q-4 宣言 document:list_documents が実在しない（免除が陳腐化している）` |

限界: 見るのは**クエリ引数**だけである。リクエスト**本文**の `organization_id`
（`body.organization_id`）は属性アクセスであり、正当な読み出し（レスポンス整形・
保存値の参照）と区別が難しいため対象外にした。

### 6.9 イメージの再現性（可変タグの排除）

2026-10-14 の実測で、`docker-compose.yml`（正本）と `docker-compose.stg.yml`（生成物）の
両方に **`minio/minio:latest`** があった。`latest` は**可変**であり、
**同じ手順で作り直しても別の環境になる**。staging の役割は
「本番前に同じものをもう一度試すこと」であるため、これは目的そのものを損なう。

実測（2026-10-14）:

| 項目 | 値 |
|---|---|
| stg compose のイメージ指定 | 7 件（`db-bridge` は digest 固定、他はバージョンタグ、`minio` だけ `latest`） |
| 稼働していた MinIO の実体 | `minio/minio:latest` → `minio version RELEASE.2025-09-07T16-13-09Z (commit-id=07c3a429…)` |
| その RepoDigest | `minio/minio@sha256:14cea493d9a34af32f524e538b8346cf79f3321eff8e708c1e2960462bd8936e` |

対策:

1. `docker-compose.yml` の `minio` を**稼働していた実体のバージョン**
   （`minio/minio:RELEASE.2025-09-07T16-13-09Z`）へ固定した。**挙動は変わらない**
   （付与したタグが稼働中イメージと同じ ID であることを実測して確認）。
2. `scripts/stg/check_staging_guards.py` に **G-9**（可変タグの禁止）を追加した。

再作成の実測（固定が「見た目だけ」でないことの確認）:

```
$ scripts/stg/compose.sh up -d minio
 Container ceos-stg-minio  Recreated / Started
$ docker ps --filter name=ceos-stg-minio
 ceos-stg-minio  minio/minio:RELEASE.2025-09-07T16-13-09Z  Up (healthy)
$ scripts/stg/status.sh
 OK: 32 コンテナ / スモーク 12/12 / 22 schemas / 98 tables / pgBackRest ok   # exit 0
```

負の対照: `docker-compose.yml` を `:latest` に戻して再生成すると
**`FAIL: G-9 … 可変タグ: ['minio=minio/minio:latest']`** で非ゼロ終了する。

限界（正直な記録）:

- G-9 が禁じるのは `latest` とタグ無しだけである。`redis:7-alpine` のような
  **バージョンタグも可変**だが、digest 固定は release 工程（マニフェストの
  `IMAGE_DIGESTS` = 未充足）の領分であり、ここでは要求していない。
  現時点で digest 固定なのは `db-bridge`（`alpine/socat@sha256:…`）のみ。
- 本環境からは Docker レジストリへ到達できず（`pull access denied`）、
  固定タグが上流に存在することを**ここでは検証していない**。
  ホストには同一イメージへ付けたタグがあるため再作成は成立する。

### 6.10 基盤サービスの再起動方針（落ちても誰も起こさない問題）

2026-10-14 の実測で、stg compose の 32 サービスのうち **26 件に
`restart: unless-stopped` があり、残り 6 件（`redis` / `rabbitmq` / `kafka` /
`elasticsearch` / `kibana` / `minio`）には方針が無かった**。
docker compose の既定は `restart: no` なので、これらが落ちると
**誰かが `compose up` するまで止まったまま**になる。

しかも非対称である — **アプリ 26 件には方針があり、基盤 6 つには無い**。
基盤が落ちればアプリは連鎖的に機能しなくなるため、優先度はむしろ基盤の方が高い。

いちばんの問題は「気づけないこと」である。監視（§6.6）は 5 分ごとに状態を見るが、
**通知経路が無い**ため、失敗は journald と systemd の failed に残るだけである
（§6.11 で扱う）。

対策: `scripts/stg/render_stg_compose.py` が stg の**全サービス**へ
`unless-stopped` を与える（明示がある場合はそれを尊重する）。
`docker-compose.yml`（dev・正本）は変更していない — dev では開発者が明示的に
止めることが多く、stg 固有の運用方針だからである。
`scripts/stg/check_staging_guards.py` の **G-10** が漏れを検査する。

実測（2026-10-14）:

| 段階 | `redis` | `minio` | `auth` |
|---|---|---|---|
| 修正前（稼働中コンテナ） | `no` | `no` | `unless-stopped` |
| 修正後（再作成後） | `unless-stopped` | `unless-stopped` | `unless-stopped` |

```
$ scripts/stg/compose.sh up -d        # 6 つの基盤サービスが再作成された
 Container ceos-stg-redis / kafka / elasticsearch / kibana / minio / rabbitmq  Healthy
$ docker inspect ceos-stg-redis --format '{{.HostConfig.RestartPolicy.Name}}'
 unless-stopped
$ scripts/stg/status.sh
 OK: 32 コンテナ / スモーク 12/12 / 22 schemas / 98 tables / pgBackRest ok   # exit 0
```

負の対照: 生成器の付与を外して再生成すると
**`FAIL: G-10 … 方針が無いサービス: ['elasticsearch', 'kafka', 'kibana', 'minio', 'rabbitmq', 'redis']`**
で非ゼロ終了する。

限界: `unless-stopped` は**コンテナの再起動**を保証するだけで、
「何度も落ちる」「起動しない」状態を検知して人へ伝える仕組みではない（§6.11）。
`compose down` や systemd の `ExecStop`（`scripts/stg/down.sh`）では停止したままになる
（これは意図どおり）。

### 6.11 監視の通知経路（失敗が誰にも届かない問題）

§6.6 で監視を 5 分ごとに回すようにしたが、**失敗は journald と systemd の `failed` に
残るだけで、誰にも届かなかった**。§6.10 の「基盤が落ちても誰も起こさない」と同根である。

`scripts/stg/monitor.sh` に通知の口を用意した。

| 項目 | 内容 |
|---|---|
| 送信先 | 環境変数 `CEOS_STG_ALERT_WEBHOOK`（任意）。**資格情報ファイルは読まない** |
| 送る条件 | 失敗の**初回**と、その後 **1 時間ごと**（5 分 × 12）。5 分ごとに同じ警報を並べると本当の変化が埋もれる |
| 未設定のとき | **何もしないが、その事実を `status.log` に明示する**（「送ったつもり」を作らない） |
| 状態 | `~/.local/state/ceos-stg/consecutive_failures` に連続失敗回数。成功で 0 に戻る |
| 検査結果 | **通知の成否で終了コードを変えない**（通知の障害が検査を壊さない） |

送信先の設定（オペレーター）:

```bash
sudo install -d -m 755 /etc/ceos
printf 'CEOS_STG_ALERT_WEBHOOK=%s\n' 'https://hooks.example.com/services/XXX' \
  | sudo tee /etc/ceos/stg-alert.env >/dev/null
sudo chmod 600 /etc/ceos/stg-alert.env
sudo systemctl restart ceos-stg-status.timer   # 次回実行から読まれる
```

`ceos-stg-status.service` が `EnvironmentFile=-/etc/ceos/stg-alert.env`
（先頭の `-` は「無くても失敗しない」）で読む。

#### 通知の落とし穴（実測で見つけた）

最初の実装は `curl` の**終了コードだけ**で成否を判定していた。ところが
**本環境のプロキシは到達不能な宛先へ 502 を返し、そのとき curl は 0 で終わる**（実測）:

```
$ curl -sS -o /dev/null -w '%{http_code}' --max-time 5 -X POST -d '{}' http://127.0.0.1:9/
502        # ← 到達できないのに curl の終了コードは 0
$ NO_PROXY=127.0.0.1 curl … http://127.0.0.1:9/
curl: (7) Failed to connect        # プロキシを使わないと初めて失敗が見える
```

そのため **HTTP ステータスまで見て 2xx のときだけ「送信した」**と記録するように直した。

検証（ローカルの HTTP サーバを送信先にした実測）:

| 場合 | 期待 | 結果 |
|---|---|---|
| 到達できる送信先（初回の失敗） | 1 件送る | `ALERT 送信した（連続 1 回 / http=200）` / 受信 1 件 |
| 同じ送信先（2 回目の失敗） | 送らない（間隔内） | 受信 1 件のまま |
| 連続 12 回目の失敗 | 送る | `ALERT 送信した（連続 12 回）` / 受信 2 件 |
| 到達できない送信先 | 失敗として記録し、**検査結果は変えない** | `ALERT 送信に失敗した（http=502）` / exit 3 のまま |
| 送信先が未設定 | 何もせず、その事実を残す | `ALERT 通知先が未設定…` |
| 検査が成功 | 連続失敗回数を戻す | `consecutive_failures` が空になる |

限界（正直な記録）:

- **現時点で通知先は設定されていない。** したがって失敗は依然として
  journald と `status.log` に残るだけで、人へは届かない。
  上の手順で送信先を設定すれば機能する（本番の webhook はこの環境から検証していない）。
- 通知の宛先・文面・エスカレーションは**運用の設計判断**であり、ここでは口を用意しただけである。

### 6.12 集約ヘルスが「全サービス」と言いながら 3 件しか見ていなかった

`GET /api/v1/health/services`（auth サービス）は `HEALTH_SERVICE_URLS` に並べた先だけを
プローブし、その範囲で `overall` を返す。2026-10-14 の実測では、その中身は
**3 件（document / workflow / notification）だけ**で、**ゲートウェイの上流 21 件のうち
17 件を見ていなかった**。

にもかかわらず:

| 提示していたもの | 記述 |
|---|---|
| `docs/operations/deployment.md` | 「✅ **全サービス** healthy(auth 12ms 等)」 |
| `docs/operations/api-auth-db-verification.md` | 「✅ **全サービス** healthy」 |
| `apps/web` のダッシュボード（`common/page.tsx`） | この endpoint を表示する |

——と、**「全サービス」として提示されていた**。見ていないサービスが落ちても
`overall: healthy` のままなので、**緑を見て安心する**構造になっていた
（§6.10「落ちても誰も起こさない」の裏返しで、「落ちても緑に見える」）。

**実測（stg）**:

| 操作 | 修正前 | 修正後 |
|---|---|---|
| `vision` を停止する | `overall: healthy` のまま（vision は対象外） | `overall: **unhealthy**` / `vision: unhealthy (2024ms)` |
| 復旧する | — | `overall: healthy` に戻る |

対策:

1. `docker-compose.yml` の `auth.HEALTH_SERVICE_URLS` を **3 件 → 20 件**
   （ゲートウェイの全上流から `auth` 自身を除いたもの）へ広げた。
   `auth` 自身は従来どおり DB 到達性で判定する。
2. `scripts/ci/check_health_coverage.py` を追加し、**ゲートウェイの上流と
   ヘルス対象の差**を機械的に検査する（`make health-coverage` /
   `make repo-invariants`）。上流に無いホストの混入（残骸）も検出する。
3. 古い検証記録には「当時プローブしていた範囲の結論である」注記を付けた
   （記録を書き換えず、誤読を防ぐ）。

実測（2026-10-14）:

```
$ curl -sS http://127.0.0.1:19500/api/v1/health/services
overall: healthy / サービス数: 21
名前: auth, advanced, ai, analytics, automation, autonomous, bim, construction,
      document, erp, field-dx, gis, iot, maintenance, notification, partner,
      platform, safety, security, vision, workflow

$ python3 scripts/ci/check_health_coverage.py
C-1 ゲートウェイの上流: 21 件 / C-2 auth が実際に叩く先: 20 件
C-3 見ていない上流: 0 件 / C-4 上流に無いホスト: 0 件
OK: ゲートウェイの全上流を網羅している（20 + 自身 = 21 サービス）
```

変異試験: `vision` を一覧から落とすと C-3 が `['vision']` を名指しして非ゼロ終了、
上流に無い `retired` を混ぜると C-4 が検出する。復元後に md5 一致を確認済み。

限界: この endpoint が見るのは**各サービスの `/health`（DB 到達性）だけ**である
（スキーマの有無・依存先の状態・非同期処理の滞留は対象外。`health-checks.md` 参照）。
全上流を 2 秒タイムアウトで並列にプローブするため、**多数が停止しているときは
応答に約 2 秒かかる**（実測: 1 件停止で 2024ms）。

### 6.13 ダッシュボードが健全なサービスを「警告」と表示していた

§6.12 で集約ヘルスが 21 サービスを返すようにした結果、**web のダッシュボード
（`/common` の「システムステータス」）の表示の食い違いが見えるようになった**。

| 項目 | API が返す値 | 画面が読んでいた値 | 結果 |
|---|---|---|---|
| 状態 | `status: "healthy"` | `"running"` / `"operational"` だけを正常扱い | **健全でも「警告」と黄色**で表示 |
| レイテンシ | `latency_ms: 12`（数値） | `latency`（存在しないフィールド） | **一度も表示されない** |

つまり「**全部が黄色で警告**」に見え、レイテンシ欄は常に空だった。
API の語彙は `healthy` / `degraded` / `unhealthy` であり、
`running` / `operational` は画面側が想定していた別の語彙である。

対策:

1. 写像とレイテンシの取り出しを `apps/web/src/lib/service-health.ts` へ切り出した。
   3 段階（`healthy` / `degraded` / `down`）へ写し、未知の語彙は `down`（fail-closed）とする。
2. `apps/web/src/lib/__tests__/service-health.test.ts` で固定した
   （12 テスト。以前は page.tsx に直書きでテストが無く、食い違いが残っていた）。
3. 画面は `svc.level` を使い、未知の状態を赤で表示する。

検証（実測）:

```
$ cd apps/web && pnpm typecheck   → 成功
$ pnpm lint                      → No ESLint warnings or errors
$ pnpm test                      → 21 files / 245 passed（追加前は 233）

$ 変異試験: toHealthLevel から "healthy" の判定を外す（旧実装へ戻す）
  → 3 failed（service-health.test.ts）。復元後に md5 一致を確認
```

限界（正直な記録）:

- 残置の `SERVICES_DISPLAY`（PostgreSQL / Redis / MinIO / Kafka）は
  **API のサービス名（auth 等）と一致しないため実際には効いていない**
  （`type` 欄は常に空）。モックを表示していないことは確認したが、
  死んだコードとして残っている。ハードウェア/ミドルウェアの状態を出したいなら
  別の情報源が要る（この endpoint はアプリケーションサービスしか返さない）。
- 画面の**実描画**（ブラウザ）では確認していない。確認したのは
  「API の応答」「写像の単体テスト」「型・lint・テスト」までである。

### 6.14 上流 1 サービスの停止（縮退の実測）

`scripts/stg/failure_drill.sh` は **DB 到達不能**（`db-bridge` 断）だけを扱っていた。
上流の**業務サービスが 1 つ落ちた**ときの挙動を実測した（2026-10-14）。

| 観点 | 実測 | 判定 |
|---|---|---|
| 巻き込み（カスケード） | `vision` 停止中も `gis` のルートは **22ms で応答** | **良好**。ゲートウェイは上流 1 つの停止に巻き込まれない |
| ゲートウェイ自身 | `/health` は 200 のまま | 良好 |
| 検知 | 集約ヘルスが `overall: unhealthy` / `vision: unhealthy (2024ms)` | 良好（§6.12 の修正後） |
| **停止した上流への応答** | **16.1 秒待って 502**（`BAD_GATEWAY`） | **課題**（下記） |
| 復旧 | `start` で 22ms 応答に戻り、集約ヘルスも `healthy` に復帰 | 良好 |

#### 16 秒の正体は HTTP タイムアウトではない（DNS である）

ゲートウェイの上流タイムアウトは `ProxyService` の既定値 **30.0 秒にハードコード**され、
環境ごとに変えられなかった（テスト名は `uses configured timeout` と言っていたが、
実際は既定値を書いているだけで `settings` を変えても追随しなかった）。
そこで `UPSTREAM_TIMEOUT_SECONDS` として**設定へ出した**（既定 30.0 で挙動は不変）。

**しかしこれを 5 秒にしても 16 秒は変わらなかった**（実測）。原因は HTTP ではなく
**名前解決**である:

```
# vision を停止した状態で、gateway コンテナ内から
getaddrinfo("vision", 8000)  → gaierror: Temporary failure in name resolution  16149ms
connect(("vision", 8000), 1) → 同じ gaierror                                   16127ms

# 起動中の名前（gis）は 6ms で解決する
```

`/etc/resolv.conf` は Docker の `127.0.0.11`（`ExtServers: [192.168.245.11, 118.238.201.33]`）。
**起動中のコンテナは Docker DNS が即答するが、停止したコンテナは Docker DNS が答えられず
外部リゾルバへ転送され、そこでタイムアウトする**（約 16 秒）。
httpx の `timeout` はこの名前解決を制限しない。

**つまり「タイムアウトを短くする」では直らない。** 名前解決そのものを避ける必要がある。

#### 対策（2026-10-14 に実施）

原因は名前解決なので、**上流を DNS で引かない**ようにした。

| 対策 | 実装 |
|---|---|
| 全サービスへ**静的 IP** を払い出す | `render_stg_compose.py` が名前の昇順で `10.201.0.10` から決定論的に割り当てる（`.1` はネットワークゲートウェイ、`.2-.9` は予約） |
| ゲートウェイの `/etc/hosts` に上流を固定する | gateway に `extra_hosts` を付け、**全サービス**を名前で引けるようにする（DNS を経由しない） |
| 接続タイムアウトを読み取りと分ける | `UPSTREAM_CONNECT_TIMEOUT_SECONDS`（既定 3 秒）。読み取りは `UPSTREAM_TIMEOUT_SECONDS`（既定 30 秒）のまま |

**静的 IP だけでは悪化した。** 名前解決が即時になっても、相手が居ない IP への
**接続がハング**し、読み取りタイムアウト（30 秒）まで待たされた（実測）。
3 つ目（接続タイムアウトの分離）と**組にして初めて** 16 秒が消える。

実測（`vision` を停止した状態、認証付きの要求）:

| 段階 | `/api/v1/vision/health` | 同時刻の `/api/v1/gis/health` |
|---|---|---|
| 修正前 | **502 / 16,149 ms** | 404 / 22 ms |
| 静的 IP のみ | タイムアウト（20 秒超・応答なし） | — |
| **静的 IP ＋ 接続タイムアウト** | **504 / 3,019 ms** | 404 / 19 ms |

再発防止: `scripts/stg/check_staging_guards.py` の **G-11**（a: 全サービスが静的 IP を持つ /
b: IP が一意 / c: gateway の `extra_hosts` が全サービスを網羅する）。

限界: この実測は **1 サービス（`vision`）の停止**についてである。複数同時停止・
ネットワーク分断・コンテナの `OOMKilled` は未実施である。
`scripts/stg/upstream_failure_drill.sh` として自動化した（下記）。
`extra_hosts` を付けたのは**ゲートウェイだけ**であり、アプリが `redis` 等を
名前で引く経路は依然として DNS を通る（プロセス起動時の接続なので影響は小さいと
考えるが、未実測）。

#### 訓練としての自動化（`upstream_failure_drill.sh`）

手動で測っていた手順を `scripts/stg/upstream_failure_drill.sh` にした。
`failure_drill.sh`（DB 断）と対をなす。

```bash
scripts/stg/upstream_failure_drill.sh                       # 対象=vision / 対照=gis
STG_DRILL_SERVICE=erp STG_DRILL_CONTROL=gis scripts/stg/upstream_failure_drill.sh
```

| 判定 | 内容 |
|---|---|
| D-1 | ゲートウェイ自身の `/health` は 200 のまま |
| D-2 | 集約ヘルスが**そのサービスだけ**を unhealthy と報告し `overall` も unhealthy |
| D-3 | 無関係な上流（対照）のルートは素早く応答する（既定の閾値 2 秒未満） |
| D-4 | 停止した上流への**認証付き**要求が上限（既定 10 秒）内に 502/504 を返す |
| D-5 | 意図的に止めた対象以外に停止・再起動ループ入りしたコンテナが無い |
| D-6 | 復旧後に集約ヘルスが healthy に戻る |
| D-7 | 復旧後のスモークが全通過 |

実測（2026-10-14）:

```
PASS: D-1 ゲートウェイ自身の /health は 200 のまま（巻き込みなし）
集約ヘルス=unhealthy|21|vision
PASS: D-2 集約ヘルスが vision だけを unhealthy と報告し overall も unhealthy
PASS: D-3 無関係な上流（gis）は 19ms で応答（巻き込みなし）
PASS: D-4 停止した上流へは 504 を 3018ms で返す（ハングしない）
PASS: D-5 停止・再起動ループ入りしたコンテナは無い
PASS: D-6 復旧後に集約ヘルスが healthy に戻る
PASS: D-7 復旧後のスモークが全通過
OK: … 実測した。                                          # exit 0
```

判定が効いていることの確認:

| 確認 | 結果 |
|---|---|
| 上限を 2 秒に下げる（現状は 3.0 秒） | **D-4 が FAIL**（`504 3020`）し exit 1。**閾値が効いている** |
| 対象を `erp` に変える | D-2 / D-4 とも PASS（対象を差し替えられる） |

訓練は**対象サービスを必ず元に戻す**（`trap ... EXIT`）。中断しても復旧する。

### 6.16 2026-10-21 の再実測（第31バッチ）

第30バッチを main へ統合し（PR #207 / `bffa97d`）、稼働ツリーを main へ切り替えた。
以下は同日 06:48〜07:10 JST の実測である。

| 項目 | 実測 | 備考 |
|---|---|---|
| 稼働 stg | 32 コンテナ healthy / smoke 12 PASS 0 FAIL / 22 schemas 98 tables | `scripts/stg/status.sh` exit 0 |
| 監視 | `ceos-stg-status.timer` 5 分ごと / `Result=success` / `ExecMainStatus=0` | main 切替後に実行（#206 の解消） |
| 業務往復 | B-1〜B-6 PASS（合成 1 行を作成→読取→集計→削除、残留 0） | `check_business_roundtrip.py` |
| テナント分離 | T-1〜T-5 PASS（非 admin ＋ 陽性対照） | `check_tenant_isolation.py` |
| ゲートウェイ | 上流 21/21 到達 / 外側 16 ルート応答 | `check_gateway_upstreams.sh` |
| MCP 上流結合 | live_upstream 2 passed | #208 で `compose run` の静的 IP 衝突を修正 |
| 監視の通知 | 送信先は**未設定**（`CEOS_STG_ALERT_WEBHOOK` 不在） | 失敗は journald と `~/.local/state/ceos-stg/status.log` に残る |
| 公開入口 | フロント DNS **NXDOMAIN** / Pages **522** / API Tunnel **未作成** | 家族パターンの DNS 2 行が欠けている |

#### 公開入口のブロッカー（資格情報の権限）

読み取り専用の実測で、次のことが分かった。

- ゾーン `mirai-dx-platform.com` の DNS レコードは読める（112 件）。`construction-os*` は
  本番 api / 本番 web / mvp の 3 件で、**stg は 0 件**。
- `POST /zones/{id}/dns_records` は **403 / 10000（`dns.write` が必要）** で拒否された。
- Pages のプロジェクト/デプロイの読み取りは **403 / 10000（`page.read` が無い）**。
  `construction-os-stg.pages.dev` は全パス 522 であり、プロジェクトは存在するが
  配信中のデプロイが無い/不正である可能性が高い（断定はできない）。
- Access アプリ `construction-os-stg` は存在（policy 1 / bypass 0）。
  `construction-os-stg-api` の Access アプリは**無い**ため、Tunnel を開ける前に作成が必須。

必要なオーナー操作は `reports/staging/batch31-20261021.md` §2.2 に記載した。
**DNS と Pages を AI が実施したとは書かない**（権限が無く、迂回もしていない）。

### 6.17 監視そのものの死活（2026-10-21 追加）

`ceos-stg-status.timer` は 5 分ごとに `monitor.sh` を実行するが、**監視が止まったこと**は
誰も検査していなかった。timer が無効化・失敗・停止すると、stg の異常も静かに見えなくなる。

- 実体: `scripts/stg/check_monitoring_health.sh`
  - `ceos-stg-status.timer` が active か
  - `~/.local/state/ceos-stg/status.log` の最終実行が **15 分以内**か（timer は 5 分間隔）
  - `~/.local/state/ceos-stg/consecutive_failures` が **0** か
- 定期実行: `ceos-stg-watchdog.timer`（15 分ごと、`OnBootSec=5min` / `OnUnitActiveSec=15min`）。
  監視本体とは**別の timer** にして、片方の停止がもう片方を止めないようにする。
- 設置: `infra/systemd/ceos-stg-watchdog.{service,timer}` を `/etc/systemd/system/` へ。
- 実測（2026-10-21 07:53 JST）: 設置・`enable --now` 後、初回実行が
  `Result=success` / `ExecMainStatus=0`、次回 08:08。journal に 3 項目の OK が記録された。
- これは「監視が動いている」ことの検査であり、**stg の業務的な健全性の証明ではない**。
  stg 自体の異常は従来どおり `monitor.sh` が failed として記録する。

## 7. ロールバック

| 対象 | 手順 |
|---|---|
| フロント（Pages） | Cloudflare API `POST /accounts/{id}/pages/projects/construction-os-stg/deployments/{id}/rollback` で直前の正常デプロイへ戻す |
| API（compose） | `scripts/stg/compose.sh up -d --force-recreate <service>` で直前のイメージへ。イメージは digest 固定を推奨 |
| DB | ホスト PG18 の pgBackRest による PITR（Mirai-Platform-Infra `ops/stg-pg18.md`） |
| 全部 | `scripts/stg/down.sh` → 前リビジョンで `scripts/stg/up.sh --build` |

ロールバックは**訓練する**。実行記録は `reports/staging/` に残す（§6.15）。
4 本の訓練（`rollback_drill.sh` / `failure_drill.sh` / `restore_drill.sh` /
`upstream_failure_drill.sh`）それぞれに `<名前>-YYYYMMDD.md` を作る。

### 6.15 訓練の実行記録（文書が定めた証跡が残っていなかった）

`docs/operations/staging.md` は「実行記録は `reports/staging/rollback-YYYYMMDD.md` に
残す」と定めていたが、**`reports/staging/` は一度も作られておらず、記録は 1 件も
無かった**（2026-10-14 実測）。訓練そのものは実行されていた（§6 の表が実測を
引用している）のに、**証跡が残っていない**。

文書に書いてあるだけの運用は守られないので、記録を作り、**機械的に検査する**。

| 訓練 | 記録（命名規則） |
|---|---|
| `rollback_drill.sh` | `reports/staging/rollback-YYYYMMDD.md` |
| `failure_drill.sh` | `reports/staging/failure-YYYYMMDD.md` |
| `restore_drill.sh` | `reports/staging/restore-YYYYMMDD.md` |
| `upstream_failure_drill.sh` | `reports/staging/upstream-failure-YYYYMMDD.md` |

検査: `scripts/stg/check_staging_guards.py` の **G-12**。`scripts/stg/*_drill.sh`
それぞれに対応する記録が 1 件以上あることを要求する（訓練を足して記録を残さなければ
ガードが落ちる）。記録の**中身の正しさ**は見ていない（それは訓練の出力と人間の確認）。

2026-10-14 の記録: 4 本すべてを作成した。同日、静的 IP ＋ `extra_hosts` ＋
接続タイムアウト分離（PR #198）を入れたため、`failure` / `restore` / `rollback` は
**回帰確認**として再実行し、いずれも記録どおり PASS した。

## 8. 禁止事項

1. stg の `ENVIRONMENT` を `development` へ変えない（統制が無効になる）。
2. stg の port を `0.0.0.0` へ広げない。外部公開は Cloudflare 経由のみ（ADR-0005 §3）。
3. 証明書・秘密値をリポジトリ・ログ・Issue・チャットへ書かない。
4. **stg に実データ（顧客・個人・現場）を入れない。** 合成データのみ（`AGENTS.md` §4.4）。
5. stg から prod の DB・DNS・secret へ触れない。
6. `docker-compose.stg.yml` を手で編集しない（生成物。`render_stg_compose.py` を直す）。

## 9. stg で見つかった設計課題の記録

2026-10-14 時点で、stg の構築・検証を通じて検出した設計課題は**すべて解消済み**である
（D-1 mobile の実行形態 / D-2 dev 初期化とシードの二重管理 / D-3 kibana の healthcheck。
いずれも §6 の表に行がある）。再発防止は `make repo-invariants` と
`scripts/stg/check_staging_guards.py` が担う。
