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

# 4. スタック起動
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
scripts/stg/smoke.sh              # スモークテスト
python3 scripts/stg/check_staging_guards.py   # 統制の検査
python3 scripts/stg/render_stg_compose.py --check
```

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
| ホスト PG18 `ceos_stg` | 完了 | 22 スキーマ / 93 テーブルを作成（`migrate_stg.sh` 全 22 SQL + auth/workflow の alembic が成功） |
| postgis / pgvector | 完了 | `postgresql-18-postgis-3` / `postgresql-18-pgvector` を導入し `ceos_stg` へ CREATE EXTENSION（`roles.yaml` の宣言と一致した） |
| db-bridge（loopback 転送） | 完了 | `10.201.0.1:55438` LISTEN / health healthy |
| auth の DB 到達 | 完了 | `GET /health` → 200（DB 不通なら 503） |
| stg 統制の実効性 | 完了 | `/docs`・`/redoc`・`/openapi.json` → 404、`/api/v1/users` → 401、開発用既定鍵では起動を拒否（実測） |
| Pages プロジェクト `construction-os-stg` | 完了 | id `eeb3c5fd-e463-4245-a57d-6fffe32dbb96` / `construction-os-stg.pages.dev` / production_branch `main` |
| Cloudflare Access アプリ | 完了 | id `f2939b1b-93b2-41a9-ab77-38a9fad953bc`（self_hosted / allow 1 件のみ・`bypass` 0 件） |
| Pages カスタムドメインのバインディング | 作成済み（pending） | id `aa3ac4c2-a329-42eb-8bfd-3158d57934e7` / `verification_data.error_message="CNAME record not set"` |
| **DNS CNAME `construction-os-stg`** | **未完了（ブロッカー 1）** | 使用可能な資格情報に Zone→DNS→Edit が無く `10000: Authentication error` |
| **CI ワークフローの設置** | **未完了（ブロッカー 2）** | ハーネスポリシーが `.github/workflows/**` への書込を DEPLOY(critical) として拒否。内容は `docs/operations/staging-deploy.workflow.yml` に確定済み |
| Cloudflare Tunnel（API 公開） | 未着手 | Tunnel 作成と `cloudflared` unit が必要 |
| 全スタックの起動 | 完了 | `scripts/stg/compose.sh up -d` で 31 コンテナが Up（29 healthy + kibana / 起動直後 2 件） |
| スモークテスト | 完了 | `scripts/stg/smoke.sh` が **7/7 PASS**（gateway / auth / web / 401 / docs無効 / db-bridge / DB 到達） |
| アプリロールのスキーマ権限 | 完了 | `scripts/stg/grant_stg_privileges.sh`（全 22 スキーマへ USAGE と DML） |
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
