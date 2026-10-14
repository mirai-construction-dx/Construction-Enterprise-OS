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
  └─ https://construction-os-stg.mirai-dx-platform.com   ← Cloudflare Access で保護
                                                          （未構成: §6 の残作業）

本ホスト（staging スタック, docker compose）
  ├─ gateway      127.0.0.1:19500   ← Cloudflare Tunnel の転送先（未構成）
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
scripts/stg/e2e_webui_stg.sh     # stg が配る WebUI 成果物をローカルで E2E
python3 scripts/stg/gen_release_manifest.py --check   # release 前提の充足状況
scripts/stg/status.sh            # 状態の要約（異常があれば非ゼロ終了）
scripts/stg/rotate_stg_jwt.sh     # JWT 鍵の整合確認とローテーション
python3 scripts/stg/check_staging_guards.py   # 統制の検査
python3 scripts/stg/render_stg_compose.py --check
```

### 4.1 シードが必要な理由

開発環境では compose の postgres コンテナが
`scripts/db/init/01-init.sql` を `docker-entrypoint-initdb.d` として自動実行する。
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
| WebUI 成果物の E2E | 完了 | `scripts/stg/e2e_webui_stg.sh` — Pages が配る単一 HTML をPages と同じ SPA フォールバックでローカル配信し、`mvp.spec.ts` + `crud.spec.ts` が **34 passed / 6 skipped / 0 failed**。**デプロイ前に成果物を検証する**経路になった（従来は本番 URL 直叩き） |
| release マニフェスト | **NOT_READY（5 件）** | `gen_release_manifest.py --check` — RELEASE_TAG / SEMVER / ATTESTATION_WORKFLOW / IMAGE_DIGESTS / ITSM_CHANGE が未充足。`CORE_VERSION` と `DEPLOY_HOSTS` は充足。**創作せずに停止する**（Release は Human Gate） |
| GitHub Environment `staging` | 完了 | `gh api .../environments` に `staging` と `production`（既存） |
| 状態監視 | 完了 | `scripts/stg/status.sh` — クラスタ / db-bridge / コンテナ / スモーク / DB の中身（users 0 行の検出）/ pgBackRest を 1 コマンドで要約し、異常時は非ゼロ終了。cron・systemd timer から呼べる（実測: 全項目 OK / exit 0） |
| PITR 復旧訓練（pgBackRest） | **未実施** | stanza `infra_stg` は `status: ok`（最新 diff 2026-10-14 02:30）。`pgbackrest restore` は `migrated` を書き換える破壊的操作のため Human Gate（§4.2） |
| Pages プロジェクト `construction-os-stg` | 完了 | id `eeb3c5fd-e463-4245-a57d-6fffe32dbb96` / `construction-os-stg.pages.dev` / production_branch `main` |
| Cloudflare Access アプリ | 完了 | id `f2939b1b-93b2-41a9-ab77-38a9fad953bc`（self_hosted / allow 1 件のみ・`bypass` 0 件） |
| Pages カスタムドメインのバインディング | 作成済み（pending） | id `aa3ac4c2-a329-42eb-8bfd-3158d57934e7` / `verification_data.error_message="CNAME record not set"` |
| **DNS CNAME `construction-os-stg`** | **未完了（ブロッカー 1）** | 使用可能な資格情報に Zone→DNS→Edit が無く `10000: Authentication error` |
| **CI ワークフローの設置** | **未完了（ブロッカー 2）** | ハーネスポリシーが `.github/workflows/**` への書込を DEPLOY(critical) として拒否。内容は `docs/operations/staging-deploy.workflow.yml` に確定済み |
| Cloudflare Tunnel（API 公開） | 未着手 | Tunnel 作成と `cloudflared` unit が必要。ホストに `cloudflared` は導入済み（`/usr/local/bin/cloudflared`） |
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
転送先を `http://127.0.0.1:19500` にする。既存の `construction-os-api` トンネルとは
**別トンネル**にすること（stg と prod で入口を共有しない）。

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
