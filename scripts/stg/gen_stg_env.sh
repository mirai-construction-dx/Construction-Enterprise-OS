#!/usr/bin/env bash
# stg 用の秘密ファイル ~/.config/ceos/stg.env を生成する。
#
# 設計: docs/architecture/ADR-0005-staging-environment.md §5
#   - 値はリポジトリへ入れない。ホストの 0600 ファイルを唯一の正本とする。
#   - 既存ファイルは --force なしでは上書きしない（鍵のローテートを事故らせない）。
#
# 使い方:
#   scripts/stg/gen_stg_env.sh [--force]
#
# 生成後、ACCESS 関連と DB パスワードは bootstrap_stg_db.sh が埋める。
set -euo pipefail

TARGET_DIR="${HOME}/.config/ceos"
TARGET="${TARGET_DIR}/stg.env"
FORCE=0

for arg in "$@"; do
  case "$arg" in
    --force) FORCE=1 ;;
    -h | --help)
      sed -n '2,14p' "${BASH_SOURCE[0]}"
      exit 0
      ;;
    *)
      echo "unknown option: $arg" >&2
      exit 2
      ;;
  esac
done

if [ -e "$TARGET" ] && [ "$FORCE" != "1" ]; then
  echo "既に存在する: $TARGET" >&2
  echo "置き換えると stg の鍵がローテートし、稼働中の stg が再起動まで動き続けます。" >&2
  echo "意図している場合だけ --force を付けてください。" >&2
  exit 1
fi

umask 077
mkdir -p "$TARGET_DIR"

rand_hex() { openssl rand -hex "$1"; }

# JWT は HS256 の共有鍵（本番で RS256 化するまでの暫定。ADR-0005 §5）。
# **HS256 では署名鍵と検証鍵が同一でなければならない。**
# 別値にすると「ログインは 200 でトークンも出るが、認証付き API が必ず 401」になる
# （2026-10-14 実測。scripts/stg/e2e_stg.sh の api.spec.ts が検出した）。
# RS256 へ移行するときは JWT_PUBLIC を別値（公開鍵）にする。
JWT_SECRET="$(rand_hex 32)"
JWT_PRIVATE="$(rand_hex 32)"
JWT_PUBLIC="$JWT_PRIVATE"

cat >"$TARGET" <<EOF
# Construction-Enterprise-OS STAGING secrets — $(date -Iseconds)
# 生成: scripts/stg/gen_stg_env.sh
# このファイルは mode 0600。リポジトリ・ログ・チャットへ内容を出さない。

# --- データベース（ホスト PostgreSQL 18 / クラスタ 18/infra_stg, port 55438） ---
STG_DB_NAME=ceos_stg
STG_DB_APP_ROLE=ceos_stg_app
STG_DB_MIGRATOR_ROLE=ceos_stg_migrator
STG_DB_AUDIT_ROLE=ceos_stg_audit_reader
# bootstrap_stg_db.sh が実パスワードで書き換える
STG_DB_APP_PASSWORD=__FILLED_BY_BOOTSTRAP__
STG_DB_MIGRATOR_PASSWORD=__FILLED_BY_BOOTSTRAP__
STG_DB_AUDIT_PASSWORD=__FILLED_BY_BOOTSTRAP__
STG_DATABASE_URL=postgresql+asyncpg://ceos_stg_app:__FILLED_BY_BOOTSTRAP__@10.201.0.1:55438/ceos_stg
STG_DB_ADMIN_URL=postgresql://postgres@127.0.0.1:55438/ceos_stg
STG_MIGRATION_DATABASE_URL=postgresql+asyncpg://ceos_stg_migrator:__FILLED_BY_BOOTSTRAP__@10.201.0.1:55438/ceos_stg

# --- JWT（stg 専用） ---------------------------------------------------------
STG_JWT_ALGORITHM=HS256
STG_JWT_SECRET_KEY=${JWT_SECRET}
STG_JWT_PRIVATE_KEY=${JWT_PRIVATE}
STG_JWT_PUBLIC_KEY=${JWT_PUBLIC}

# --- ミドルウェア -------------------------------------------------------------
STG_RABBITMQ_DEFAULT_USER=ceos_stg
STG_RABBITMQ_DEFAULT_PASS=$(rand_hex 24)
STG_MINIO_ROOT_USER=ceos_stg
STG_MINIO_ROOT_PASSWORD=$(rand_hex 24)
STG_INTERNAL_API_KEY=$(rand_hex 32)

# --- 公開入口（Access はオペレーターが埋める） --------------------------------
STG_PUBLIC_BASE_URL=https://construction-os-stg.mirai-dx-platform.com
STG_ACCESS_TEAM_DOMAIN=__FILLED_BY_OPERATOR__
STG_ACCESS_AUD=__FILLED_BY_OPERATOR__

# --- スモークテスト -----------------------------------------------------------
STG_SMOKE_ADMIN_EMAIL=stg-admin@stg.mirai-dx-platform.com
STG_SMOKE_ADMIN_PASSWORD=$(rand_hex 16)
STG_SMOKE_BASE_URL=http://127.0.0.1:19500
EOF

chmod 600 "$TARGET"
echo "生成した: $TARGET (mode $(stat -c '%a' "$TARGET"))"
echo "残作業: scripts/stg/bootstrap_stg_db.sh を実行して DB パスワードを確定させる。"
