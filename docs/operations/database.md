# データベース運用（dev / stg / prod）

- 最終更新: 2026-10-14（すべて実測。推測は「未確認」と明記する）
- 採用決定: `MCDX-ADR-0003`（本番 DB はホストの PostgreSQL。マネージド DB を新規採用しない）
- 上位仕様: `docs/architecture/CloudflarePostgreSQLGitHub自動化仕様.md`（v2: Neon 廃止）

> **Neon は使いません。** 2026-09-13 の仕様改定で廃止され、現在の本番もホスト PostgreSQL である
> （後述の実測を参照）。`neon-database.md` は履歴として残しているが内容は無効である。

## 1. 環境ごとの実体（2026-10-14 実測）

| 環境 | DB | 接続先 | スキーマ | 備考 |
|---|---|---|---|---|
| dev | compose の `postgres`（`postgis/postgis:16-3.4`） | `postgres:5432`（コンテナ内） | マイグレーション適用後の集合 | `scripts/db/init/01-init.sql` は**スキーマのみ**。シードは `make db-seed` + `python -m src.seed` |
| **stg** | **ホスト PostgreSQL 18** クラスタ `18/infra_stg` | `127.0.0.1:55438`（ホスト限定） | `ceos_stg` に 22 / 98 テーブル | `docs/operations/staging.md` |
| **prod** | **ホスト PostgreSQL 16.14** | `127.0.0.1:5432` / `construction_os` | 3 / 16 テーブル | systemd `construction-os-auth.service` の実行中プロセスの `DATABASE_URL` を実測 |

補足（実測の根拠）:

- prod の接続先は `systemctl cat construction-os-auth.service` と
  `/proc/<pid>/environ` の `DATABASE_URL`（`postgresql+asyncpg://construction_os_app@127.0.0.1:5432/construction_os`）
  から確認した。ロールは `construction_os_app`。
- prod の DB 版は `SELECT version()` → `PostgreSQL 16.14`。
- prod のスキーマは 3 件 / 16 テーブルのみで、**全サービスのスキーマは配備されていない**
  （稼働しているのは auth 相当だけである）。
- prod の API は native systemd（`ENVIRONMENT=production`）で、
  `/home/kensan/.local/share/construction-os/releases/<commit>/` のリリース用 worktree から起動する。

## 2. 決定との差分（記録）

| # | 内容 | 状態 |
|---|---|---|
| 1 | `MCDX-ADR-0003` は本番 DB を **PostgreSQL 18** と定めるが、実際の本番は **16.14**。 | **未解消**。移行するか `Deviates-from` を宣言するかはオーナー判断（`MCDX-ADR-0003` 影響欄が「ローカル ADR に Deviates-from と移行期限を書く」と定めている） |
| 2 | prod の Cloudflare Tunnel は systemd unit（`construction-os-api-cloudflared.service`）が **inactive/dead** で、代わりに systemd 管理外の `cloudflared` プロセスが動いている。 | **未解消**。ホスト再起動で API 公開が落ちる（unit を `enable --now` するか、手動プロセスをやめる） |
| 3 | dev の DB は PostgreSQL **16**（compose のイメージ）。 | 設計どおり（dev は本番構成の再現を目的にしない）。stg はホスト PG18 を使う |

## 3. ロールとスキーマの正本

- **DB ロールの払い出しの正本は `Mirai-Platform-Infra` の `db/roles.yaml`。**
  本リポジトリでロールを発番しない（stg の `ceos_stg_*` は stg 専用 DB のもので、
  同台帳の `database: mirai` とは別）。
- **スキーマの正本は各サービスのマイグレーション**（`services/<name>/migrations/*.sql`、
  `auth` / `workflow` は alembic）。`01-init.sql` にここに無いスキーマを足してはならない
  （`scripts/db/check_service_ddl_coverage.py` が検査する）。

## 4. バックアップと復旧

| 対象 | 手段 | 状態 |
|---|---|---|
| stg（`ceos_stg`） | pgBackRest stanza `infra_stg`（`/etc/pgbackrest/infra-stg.conf`）。full / diff / WAL アーカイブ | 稼働。最新 diff は日次で取得成功を実測 |
| stg の論理復旧訓練 | `scripts/stg/restore_drill.sh` | 実施済み（別 DB へ復元して照合） |
| stg の PITR 訓練 | `pgbackrest restore` | **未実施**。stanza の `pg1-path` を書き換える破壊的操作であり、他システムと共有するクラスタでは Human Gate |
| prod（`construction_os`） | **未確認** | バックアップの有無・復旧手順を本リポジトリでは確認していない。`IT-BCP-ITSCM-System` の責務（`MCDX-ADR-0003` 決定 4 の影響欄） |

## 5. stg のセットアップと運用

`docs/operations/staging.md` を参照。要点のみ:

```bash
scripts/stg/gen_stg_env.sh      # ~/.config/ceos/stg.env (0600)
scripts/stg/bootstrap_stg_db.sh # DB とロール（ceos_stg / ceos_stg_app / _migrator / _audit_reader）
scripts/stg/migrate_stg.sh      # スキーマ適用（SQL + alembic）
scripts/stg/seed_stg.sh         # 合成データ
scripts/stg/up.sh               # スタック起動
scripts/stg/status.sh           # 状態の要約
```
