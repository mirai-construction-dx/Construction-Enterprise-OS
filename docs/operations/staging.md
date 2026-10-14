# Staging（stg）環境 — 設計と運用手順

- 正本: 本ファイル（手順）、`docs/architecture/ADR-0005-staging-environment.md`（決定）
- リポジトリ間連携: `docs/operations/staging-integration.md`
- 対象: Construction-Enterprise-OS（CEOS）
- 最終更新: 2026-10-14

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
| stg compose 生成と統制検査 | 完了 | `scripts/stg/check_staging_guards.py` 9/9 PASS |
| ホスト PG18 `ceos_stg` | 完了 | 20 サービススキーマ / 93 テーブルを作成（`migrate_stg.sh` 全 22 SQL + auth/workflow の alembic が成功） |
| postgis / pgvector | 完了 | `postgresql-18-postgis-3` / `postgresql-18-pgvector` を導入し `ceos_stg` へ CREATE EXTENSION（`roles.yaml` の宣言と一致した） |
| db-bridge（loopback 転送） | 完了 | `10.201.0.1:55438` LISTEN / health healthy |
| auth の DB 到達 | 完了 | `GET /health` → 200（DB 不通なら 503） |
| stg 統制の実効性 | 完了 | `/docs`・`/redoc`・`/openapi.json` → 404、`/api/v1/users` → 401、開発用既定鍵では起動を拒否（実測） |
| 合成データ | 完了 | `seed_stg.sh` で users=1 / roles=7 / organizations=1（`notification.notification_templates` は 11 行をサービスが自動投入） |
| **ログインの疎通** | 完了 | `POST /api/v1/auth/login` が gateway 経由で 200 + アクセストークン発行（実測） |
| 復旧訓練（論理） | 完了 | `restore_drill.sh` — `ceos_stg` を別DBへ復元し、スキーマ 21 / テーブル 93 / 主要表の行数が一致。訓練用DBは削除済み |
| ロールバック訓練 | 完了 | `scripts/stg/rollback_drill.sh` — 全 31 コンテナを停止し、同じリビジョンで復帰させ、health と smoke 10/10 を確認（2026-10-14）。**前リビジョンのイメージへ戻す訓練は digest 固定の release 工程が前提で未整備** |
| **障害訓練（DB 断）** | 完了 | `scripts/stg/failure_drill.sh` — `db-bridge` を止めて DB 到達不能を作り、`auth /health` が **503** に縮退（fail-closed）し、gateway は 200 のまま、再起動ループに入るコンテナは無く、復旧後に auth が自動で 200 に戻り smoke 12/12 が通ることを実測 |
| WebUI 成果物の E2E | 完了 | `scripts/stg/e2e_webui_stg.sh` — Pages が配る単一 HTML をPages と同じ SPA フォールバックでローカル配信し、`mvp.spec.ts` + `crud.spec.ts` が **34 passed / 6 skipped / 0 failed**。**デプロイ前に成果物を検証する**経路になった（従来は本番 URL 直叩き） |
| release マニフェスト | **NOT_READY（5 件）** | `gen_release_manifest.py --check` — RELEASE_TAG / SEMVER / ATTESTATION_WORKFLOW / IMAGE_DIGESTS / ITSM_CHANGE が未充足。`CORE_VERSION` と `DEPLOY_HOSTS` は充足。**創作せずに停止する**（Release は Human Gate） |
| GitHub Environment `staging` | 完了 | `gh api .../environments` に `staging` と `production`（既存） |
| 状態監視（手動） | 完了 | `scripts/stg/status.sh` — クラスタ / db-bridge / コンテナ / スモーク / DB の中身（users 0 行の検出）/ pgBackRest を 1 コマンドで要約し、異常時は非ゼロ終了。cron・systemd timer から呼べる（実測: 全項目 OK / exit 0） |
| **状態監視（常設）** | 完了 | 上記は「誰かが叩いたときだけ」走っており、**timer は 1 つも無かった**（2026-10-14 実測: `systemctl list-timers --all \| grep -i ceos` → 0 件）。`scripts/stg/monitor.sh` と `infra/systemd/ceos-stg-status.{service,timer}` を追加し、5 分ごとに検査するようにした。§6.6 |
| ゲートウェイルーティング | 完了 | `scripts/stg/check_gateway_upstreams.sh` — **21 上流すべて**の `/health` に到達（ルート定義 30 件）＋ 外側から実測済み 14 ルートが応答。従来は auth 系しか見ておらず、他 20 サービスへのルートは未検証だった |
| **MCP の実呼び出し** | 完了 | 未認証 401 / `initialize` / `tools/list` が契約と一致 / `tools/call` が上流から実データを取得。初回は `CONSTRUCTION_SERVICE_URL` / `ERP_SERVICE_URL` を compose で渡しておらず、`tools/call` が `isError: true`（「上流サービスに到達できません。」）を返していた。**`result` が返ること自体を成功とみなす検査は見逃す**ため、`isError` を不合格にする |
| **CI が skip するテストの実行** | 完了 | `services/mcp/tests/test_upstream_live.py` は上流へ TCP 到達できないと **CI では常に skip** される。stg では上流が動いているので `scripts/stg/run_mcp_live_tests.sh` で実行できる。実行したところ、テストヘルパーが固定鍵で署名しており**実環境では必ず INVALID_TOKEN になる**ことが判明した（修正済み。live 2 passed / MCP 全体 95 passed） |
| **業務 API の往復** | 完了 | `scripts/stg/check_business_roundtrip.py` — 管理ユーザでログインし、`POST /api/v1/erp/ledger` で合成台帳を作成 → 読み戻し → 集計反映 → **別組織を要求しても返らない**（`MCDX-ADR-0004` のテナント分離）→ SQL で 1 行だけ削除、まで 6/6 PASS。再実行しても残留行 0 件。**これまで業務サービスへの書込みは一度も通っていなかった** |
| **mobile の実行形態** | 完了 | 旧版は `output: 'export'` と書きながら `next dev`（開発サーバ）で配信しており、stg が本番の実行形態を練習していなかった（§9 D-1）。2 ステージビルドにして静的エクスポート `out/` を 依存ゼロの `serve.mjs` で配信する。smoke の S-10 が `x-ceos-static-export` で回帰検査する |
| kibana の healthcheck | 完了 | 未定義で `status.sh` の healthy 判定対象外だった（§9 D-3）。公式イメージの `curl` で `/api/status` を叩く healthcheck を追加（start_period 180s）。**全 32 コンテナが healthy** になった |
| **systemd 管理** | 完了 | `infra/systemd/ceos-stg.service` を追加し `/etc/systemd/system/` へ設置。`systemctl start/stop` で 32 コンテナの起動・停止を実測（停止後 0 個 → 起動後 32 個、smoke 12/12）。**enable は保留**（stg の DB クラスタが disabled のため、B-2 の決定と同時に判断する） |
| **dev の compose 起動不能** | 完了 | `scripts/db/init/01-init.sql` が initdb 時点で `INSERT INTO auth.organizations` を実行しており、表はマイグレーションが作るため空 DB で必ず失敗していた（`psql -v ON_ERROR_STOP=1` → exit 3）。docker-entrypoint は `ON_ERROR_STOP=1` なので **dev の compose は初回起動できなかった**。DDL とシードを分離し（`scripts/db/seed/00-bootstrap.sql` / `make db-seed`）、あわせて ENUM 列（`org_type` / `org_status`）の暗黙キャスト不能も修正した |
| **erp の基盤 DDL** | 完了 | `services/erp` は `MetaData(schema="erp")` のモデルを持つのに、`src/models/__init__.py` が空で metadata に登録されず、生成器の TARGETS からも漏れていた。そのため `erp` スキーマが stg に存在せず `/api/v1/erp/ledger/summary` が 500（`UndefinedTableError: erp.project_ledger`）。両方修正し 5 テーブルを作成、両エンドポイントが 200 になった |
| **Web → API プロキシ** | 完了 | `apps/web` は `output: "standalone"` のため `rewrites()` が**ビルド時**に確定し、Docker の runtime `API_GATEWAY` が効かない。ビルド引数で渡さないと`http://localhost:9000` が焼き込まれ `/api/*` が **500** になる（2026-10-14 実測）。`build.args.API_GATEWAY` を追加して修正し、smoke の S-9 で回帰検査する |
| PITR 復旧訓練（pgBackRest） | **未実施** | stanza `infra_stg` は `status: ok`（最新 diff 2026-10-14 02:30）。`pgbackrest restore` は `migrated` を書き換える破壊的操作のため Human Gate（§4.2） |
| Pages プロジェクト `construction-os-stg` | 完了 | id `eeb3c5fd-e463-4245-a57d-6fffe32dbb96` / `construction-os-stg.pages.dev` / production_branch `main` |
| Cloudflare Access アプリ | 完了 | id `f2939b1b-93b2-41a9-ab77-38a9fad953bc`（self_hosted / allow 1 件のみ・`bypass` 0 件） |
| Pages カスタムドメインのバインディング | 作成済み（pending） | id `aa3ac4c2-a329-42eb-8bfd-3158d57934e7` / `verification_data.error_message="CNAME record not set"` |
| **DNS CNAME `construction-os-stg`** | **未完了（ブロッカー 1）** | 使用可能な資格情報に Zone→DNS→Edit が無く `10000: Authentication error` |
| **CI ワークフローの設置** | **未完了（ブロッカー 2）** | ハーネスポリシーが `.github/workflows/**` への書込を DEPLOY(critical) として拒否。内容は `docs/operations/staging-deploy.workflow.yml` に確定済み |
| **Pages から本番 API への越境** | 完了（欠陥を検出して修正） | 共有 `webui/functions` が本番 API を向いており、stg へそのまま配ると越境した（実測）。`scripts/stg/render_pages_functions.py` で描画し、`scripts/stg/check_pages_upstream.py` で不変条件化した。§6.5 |
| Cloudflare Tunnel（API 公開） | 未着手 | Tunnel 作成と `cloudflared` unit が必要。ホストに `cloudflared` は導入済み（`/usr/local/bin/cloudflared`）。stg の API ホストは `construction-os-stg-api.mirai-dx-platform.com`（§6.4） |
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
**同じ値でなければならない**（`make stg-pages-upstream` の C-3 が検査する）。

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

## 7. ロールバック

| 対象 | 手順 |
|---|---|
| フロント（Pages） | Cloudflare API `POST /accounts/{id}/pages/projects/construction-os-stg/deployments/{id}/rollback` で直前の正常デプロイへ戻す |
| API（compose） | `scripts/stg/compose.sh up -d --force-recreate <service>` で直前のイメージへ。イメージは digest 固定を推奨 |
| DB | ホスト PG18 の pgBackRest による PITR（Mirai-Platform-Infra `ops/stg-pg18.md`） |
| 全部 | `scripts/stg/down.sh` → 前リビジョンで `scripts/stg/up.sh --build` |

ロールバックは**訓練する**。実行記録は `reports/staging/rollback-YYYYMMDD.md` に残す。

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
