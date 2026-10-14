> # ⚠️ この文書は無効である（2026-10-14 追記）
>
> ここに書かれている Neon は **2026-09-13 の仕様改定で廃止**され、
> 現在の本番 DB は**ホスト PostgreSQL** である（`construction-os-auth.service` の
> 実行中プロセスの `DATABASE_URL` が `127.0.0.1:5432/construction_os` を指すことを実測）。
> 採用決定は `MCDX-ADR-0003`、現行の実測は [`database.md`](./database.md) を参照すること。
> 以下は**履歴としてのみ**残している。

---

# Neon データベース運用(検証DB・Migration・Seed)

> 本プロジェクトの PostgreSQL は **Neon** を正本とします。
> 検証は「空の検証用ブランチ」に対して Migration → Seed を再実行して行います。

## 1. Neon プロジェクト構成

| 項目 | 値 |
|---|---|
| プロジェクト名 | `construction-enterprise-os` |
| プロジェクトID | `lucky-art-65407624` |
| リージョン | aws-us-west-2 |
| メインブランチ | `main`(br-shiny-pond-af5wfq1z) |
| 検証用ブランチ | `verify-001`(br-wandering-water-afhmiate) — 使い捨て |
| 既定DB | `neondb` |
| ロール | `neondb_owner` |

接続文字列は Neon コンソール / `neonctl connection-string` から取得し、
**リポジトリへはコミットしない**こと(`.env` 等の gitignore 済みファイルに保持)。

## 2. 空の検証DBへの再実行手順(完了条件: 再実行可能)

### 2.1 検証用ブランチを空にする

Neon コンソールまたは API で、親(main)から新規ブランチを作成、
または既存の検証ブランチをリセット:

```bash
# neonctl 例
neonctl branches create --name verify-001 --project-id lucky-art-65407624
neonctl branches reset verify-001 --project-id lucky-art-65407624  # 既存ブランチの初期化
```

### 2.2 Migration 実行

```bash
cd services/auth
export DATABASE_URL='postgresql+asyncpg://neondb_owner:*****@<branch-host>.us-west-2.aws.neon.tech/neondb?ssl=require'
python -m alembic upgrade head
```

### 2.3 Seed 実行(冪等)

```bash
python -m src.seed
```

2回目実行しても件数が増えないこと(冪等)を確認する。

### 2.4 検証クエリ

```sql
SELECT 'organizations' AS t, count(*) FROM auth.organizations
UNION ALL SELECT 'users', count(*) FROM auth.users
UNION ALL SELECT 'roles', count(*) FROM auth.roles
UNION ALL SELECT 'permissions', count(*) FROM auth.permissions
UNION ALL SELECT 'audit_logs', count(*) FROM auth.audit_logs;
```

期待値(seed 完了直後): organizations=2 / users=1 / roles=7 / permissions=43 / audit_logs=1

## 3. 本番DB(main ブランチ)への適用

```bash
export DATABASE_URL='postgresql+asyncpg://neondb_owner:*****@<main-host>-pooler.us-west-2.aws.neon.tech/neondb?ssl=require'
python -m alembic upgrade head && python -m src.seed
```

## 4. 実装上の注意(2026-08-18 修正済み)

空DBから再実行可能にするため、以下の修正を加えた。

1. **`services/auth/alembic/env.py`**
   - バージョンテーブル格納先スキーマ `auth` を実行前に作成(`CREATE SCHEMA IF NOT EXISTS auth`)。
   - `CREATE TYPE AS ENUM` は拡張クエリプロトコル(Parse)で型を先に生成してしまう
     (PostgreSQL 既知の挙動)ため、マイグレーション用接続は
     `prepared_statement_cache_size=0` を付与。

2. **`services/auth/alembic/versions/001_initial_auth.py`**
   - `sa.Enum` → `postgresql.ENUM(..., create_type=False)` に変更。
     `op.execute` で明示作成した ENUM を `create_table` が再作成して
     「type already exists」になるのを防止。

3. **`services/auth/src/models/base.py`**
   - 接続イベントで `SET search_path TO auth, public`。
     asyncpg の `server_settings` は環境(Neon 等)で無視されるため、
     ENUM 非修飾キャスト(`$1::org_type`)を解決するために必要。

## 5. 未対応・残存リスク

- auth 以外のサービス(document/erp 等)は現状モデル定義が未整備。
  MVP では auth(認証・権限・監査)を DB 正本とし、業務データは
  各サービス API のモック/インメモリ実装を利用する。
- ロール/パーミッションの追加変更は migration 追加(002 以降)で対応すること。

## 6. 接続文字列の注意 (2026-08-20 追記)

Neon ダッシュボードが提示する接続 URI を **そのまま `.env` に貼らないこと**。
ダッシュボードは `?sslmode=require&channel_binding=require` を付与するが、
`postgresql+asyncpg://` では SQLAlchemy がクエリパラメータを asyncpg の
`connect()` へそのまま渡すため、いずれも `TypeError: connect() got an
unexpected keyword argument ...` となり **DB アクセスが全滅する**。

- 正: `postgresql+asyncpg://<user>:<pw>@<host>/neondb?ssl=require`
- 誤: `...?sslmode=require` / `...?channel_binding=require`

**発覚しにくい理由**(2026-09-18 更新): 以前は `/health` と
`/api/v1/health/services` が DB に触れず 200 を返していたため、DB 断を
ヘルスチェックで検知できなかった。現在は **全サービスの `/health` が
`SELECT 1` を実行し、DB へ到達できなければ 503 を返す**ため、
`/health` で DB 断を検知できる。`/api/v1/health/services` も auth 自身の
状態を実 DB で判定する。

なお DB への到達性とスキーマの有無は別である。テーブル未作成でも
`SELECT 1` は成功するため、スキーマ適用状況は
[`schema-bootstrap.md`](./schema-bootstrap.md) の手順で確認すること。
接続文字列の誤り(上記 `sslmode` 等)は `/health` の 503 として現れる。

