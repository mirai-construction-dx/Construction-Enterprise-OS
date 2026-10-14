#!/usr/bin/env bash
# stg の JWT 鍵を、アルゴリズムに整合した形で作り直す（ローテーション）。
#
# 背景（2026-10-14 実測）:
#   auth は `jwt.encode(..., settings.jwt_private_key, algorithm=settings.JWT_ALGORITHM)` で署名し、
#   `jwt.decode(..., settings.jwt_public_key, algorithms=[...])` で検証する。
#   `JWT_ALGORITHM=HS256`（共有鍵）のときは **署名鍵と検証鍵が同一でなければならない**。
#   `gen_stg_env.sh` の初版は 3 つとも別の乱数を入れており、
#   「ログインは 200 でトークンも出るが、認証付き API が必ず 401」になっていた。
#   `scripts/stg/e2e_stg.sh`（Playwright の api.spec.ts）が 401 を検出して判明した。
#
#   RS256（公開鍵暗号）へ移行するときは private/public を別値にする。
#   本スクリプトは `STG_JWT_ALGORITHM` を見て自動で切り替える。
#
# 使い方:
#   scripts/stg/rotate_stg_jwt.sh            # 鍵を作り直す（既存トークンは無効になる）
#   scripts/stg/rotate_stg_jwt.sh --show     # 現在のアルゴリズムと鍵の一致だけ確認する
set -euo pipefail

ENV_FILE="${HOME}/.config/ceos/stg.env"
SHOW_ONLY=0
[ "${1:-}" = "--show" ] && SHOW_ONLY=1

if [ ! -f "$ENV_FILE" ]; then
  echo "NG: $ENV_FILE が無い。scripts/stg/gen_stg_env.sh を実行すること。" >&2
  exit 1
fi

alg="$(grep -m1 '^STG_JWT_ALGORITHM=' "$ENV_FILE" | cut -d= -f2-)"
alg="${alg:-HS256}"
priv="$(grep -m1 '^STG_JWT_PRIVATE_KEY=' "$ENV_FILE" | cut -d= -f2-)"
pub="$(grep -m1 '^STG_JWT_PUBLIC_KEY=' "$ENV_FILE" | cut -d= -f2-)"

echo "== stg JWT 鍵の整合確認 =="
echo "アルゴリズム: ${alg}"
if [ "$priv" = "$pub" ]; then
  echo "署名鍵と検証鍵: 一致"
else
  echo "署名鍵と検証鍵: 不一致"
fi

case "$alg" in
  HS*)
    if [ "$priv" = "$pub" ]; then
      echo "OK: HS* では一致が必要。満たしている。"
      [ "$SHOW_ONLY" = "1" ] && exit 0
      echo "（--show ではないのでローテーションする）"
    else
      echo "NG: HS* では一致が必要。不一致のため認証付き API は 401 になる。" >&2
    fi
    ;;
  RS* | ES* | PS*)
    echo "OK: 非対称アルゴリズムでは別値でよい。"
    ;;
  *)
    echo "警告: 未知のアルゴリズム ${alg}。" >&2
    ;;
esac

[ "$SHOW_ONLY" = "1" ] && exit 0

echo
echo "== 鍵をローテーション =="
new_priv="$(openssl rand -hex 32)"
new_secret="$(openssl rand -hex 32)"
case "$alg" in
  HS*)
    new_pub="$new_priv" # HS* は共有鍵。同一値を検証にも使う
    ;;
  *)
    # 非対称の場合は RSA 鍵対を作る（将来の RS256 移行用）
    tmp="$(mktemp -d)"
    openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:2048 -out "${tmp}/priv.pem" 2>/dev/null
    openssl rsa -in "${tmp}/priv.pem" -pubout -out "${tmp}/pub.pem" 2>/dev/null
    new_priv="$(tr -d '\n' <"${tmp}/priv.pem")"
    new_pub="$(tr -d '\n' <"${tmp}/pub.pem")"
    rm -rf "$tmp"
    ;;
esac

umask 077
tmp="$(mktemp)"
sed \
  -e "s|^STG_JWT_PRIVATE_KEY=.*|STG_JWT_PRIVATE_KEY=${new_priv}|" \
  -e "s|^STG_JWT_PUBLIC_KEY=.*|STG_JWT_PUBLIC_KEY=${new_pub}|" \
  -e "s|^STG_JWT_SECRET_KEY=.*|STG_JWT_SECRET_KEY=${new_secret}|" \
  "$ENV_FILE" >"$tmp"
chmod 600 "$tmp"
mv "$tmp" "$ENV_FILE"
echo "更新した: $ENV_FILE (mode $(stat -c '%a' "$ENV_FILE"))"

echo
echo "== 反映（auth / gateway を再作成） =="
echo "次を実行すること:"
echo "  scripts/stg/compose.sh up -d --force-recreate auth gateway"
echo "  scripts/stg/smoke.sh"
echo "  scripts/stg/e2e_stg.sh"
echo "注意: 既存のアクセストークンはすべて無効になる。"
