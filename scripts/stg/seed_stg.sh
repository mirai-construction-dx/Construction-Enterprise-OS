#!/usr/bin/env bash
# stg の `ceos_stg` に最小限の合成データを投入する。
#
# なぜ必要か:
#   開発環境では compose の postgres コンテナが `scripts/db/init/01-init.sql` を
#   docker-entrypoint-initdb.d として自動実行する。しかし stg はホスト PostgreSQL 18 を
#   使うため、その初期化は走らない。`migrate_stg.sh` はスキーマだけを作るので、
#   そのままでは `auth.users` が 0 行でログインできず、E2E も通らない
#   （2026-10-14 実測: 復旧訓練で auth.users = 0 行）。
#
# 何を入れるか:
#   `python -m src.seed`（auth サービス）が作る管理ユーザ・組織・ロールのみ。
#   **合成データだけを入れる。** 本番・顧客・現場の実データは絶対に入れない
#   （AGENTS.md §4.4 / ADR-0005 §8）。
#
# 使い方:
#   scripts/stg/seed_stg.sh
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ENV_FILE="${HOME}/.config/ceos/stg.env"

if [ ! -f "$ENV_FILE" ]; then
  echo "NG: $ENV_FILE が無い。scripts/stg/gen_stg_env.sh を実行すること。" >&2
  exit 1
fi

# stg の合成管理ユーザ。メールアドレスは秘密ではないので定数として持つ。
# 注意: @example.invalid / @example.com は RFC 2606 の予約ドメインであり、pydantic の
# EmailStr（email-validator）が special-use として 422 で拒否する（2026-10-14 実測）。
# そのためプロジェクト自身のドメイン上に存在しないローカル部を使う。実在の連絡先ではない。
ADMIN_EMAIL="${STG_ADMIN_EMAIL:-stg-admin@stg.mirai-dx-platform.com}"
ADMIN_PASSWORD="$(grep -m1 '^STG_SMOKE_ADMIN_PASSWORD=' "$ENV_FILE" | cut -d= -f2-)"

if [ -z "$ADMIN_PASSWORD" ]; then
  echo "NG: $ENV_FILE に STG_SMOKE_ADMIN_PASSWORD が無い。" >&2
  exit 1
fi

case "$ADMIN_EMAIL" in
  stg-admin@*.mirai-dx-platform.com)
    echo "OK: 合成データ用のメールアドレス（${ADMIN_EMAIL}）を使う"
    ;;
  *)
    echo "警告: ${ADMIN_EMAIL} は想定した合成ドメインではない。" >&2
    echo "      stg へ実在の連絡先を入れないこと（AGENTS.md §4.4）。" >&2
    ;;
esac

echo "== stg のシード投入 =="
# 既に投入済みでも冪等（seed.py は upsert 相当）。
"$REPO_ROOT/scripts/stg/compose.sh" run --rm --no-deps \
  -e "ADMIN_EMAIL=${ADMIN_EMAIL}" \
  -e "ADMIN_PASSWORD=${ADMIN_PASSWORD}" \
  --entrypoint python auth -m src.seed

echo
echo "== 管理ユーザのメールアドレスを正規化 =="
# seed.py は管理ユーザを「固定 UUID」で引くため、ADMIN_EMAIL を変えても既存行の
# メールアドレスを更新しない（2026-10-14 実測: .invalid のまま残り、ログインが 401）。
# 環境変数を変えたときに古いアドレスが残らないよう、stg 側で冪等に揃える。
PORT="${STG_PG_PORT:-55438}"
DB_NAME="${STG_DB_NAME:-ceos_stg}"
sudo -n -u postgres psql -p "$PORT" -d "$DB_NAME" -q -c \
  "UPDATE auth.users SET email = '${ADMIN_EMAIL}', updated_at = now() WHERE id = '00000000-0000-0000-0000-000000000002' AND email <> '${ADMIN_EMAIL}'"
echo "  OK: ${ADMIN_EMAIL}"

echo
echo "== 実測（auth.users / auth.roles） =="
sudo -n -u postgres psql -p "$PORT" -d "$DB_NAME" -tAc \
  "SELECT 'users=' || (SELECT count(*) FROM auth.users) || ' roles=' || (SELECT count(*) FROM auth.roles) || ' organizations=' || (SELECT count(*) FROM auth.organizations)"
sudo -n -u postgres psql -p "$PORT" -d "$DB_NAME" -tAc "SELECT 'admin email=' || email FROM auth.users ORDER BY 1"
echo "完了。次: scripts/stg/smoke.sh および E2E"
