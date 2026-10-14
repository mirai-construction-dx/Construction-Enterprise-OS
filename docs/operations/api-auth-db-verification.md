# API・認証・DB 接続の統合検証記録

> **注記（2026-10-14）**: 本文書は当時の検証記録であり、当時は DB に Neon を用いていた。
> Neon は 2026-09-13 の仕様改定で廃止され、現在の本番 DB はホスト PostgreSQL である
> （`MCDX-ADR-0003`。実測は [`database.md`](./database.md)）。記録の内容は当時のまま残す。


## 日時
- 2026-08-18(ラウンド2)

## 構成
- auth サービス(FastAPI)をローカル起動(port 18002)
- DB: **Neon `construction-enterprise-os` main ブランチ**(Migration 001 + Seed 適用済み)
- 検証: 実 HTTP リクエスト(ログイン → JWT → 認証付き API)

## 検証結果

| 確認項目 | エンドポイント | 結果 |
|---|---|---|
| ヘルスチェック | `GET /api/v1/health/services` | ✅ healthy(auth 12ms 等)。**当時の対象は 3 件のみ**（2026-10-14 注記参照） |
| 認証(ログイン) | `POST /api/v1/auth/login` | ✅ JWT 発行(roles: [admin]、org 付き) |
| 認可(トークン検証) | `GET /api/v1/users`(Bearer) | ✅ シード済み管理ユーザーを Neon から返却 |
| 認可(ロール) | `GET /api/v1/roles?organization_id=...`(Bearer) | ✅ admin ロール + 権限(users.read 等)を返却 |
| DB 接続 | 上記 API 経由 | ✅ 全て Neon(PostgreSQL 18)から応答 |

## ログイン資格情報(シード)

- メール: 環境変数 `ADMIN_EMAIL` で管理（2026-09-18 に平文記載を廃止）
- パスワード: 環境変数で管理（2026-09-18 に平文記載を廃止）

## 発見・修正した問題

1. **シード管理ユーザーのメールアドレスが `.local` ドメイン**のため、
   `EmailStr` 検証(Pydantic)でログイン API が 422 を返す不具合を発見。
   - 修正: `services/auth/src/seed.py` の `ADMIN_EMAIL` を
     環境変数 `ADMIN_EMAIL` の値へ変更し、既存 DB のレコードも UPDATE 済み（現行値は本書に記載しない）
   - auth サービス pytest 30件 PASS で回帰なし

## 残課題(次フェーズ)

- API の恒久公開: cloudflared Tunnel で
  `api.construction-os.mirai-dx-platform.com` 等を公開し、Preview 配下で API 確認
- WebUI のダミーデータ → auth API 実データへの接続
- 本番用 JWT 鍵・MFA・Secrets 管理の整備

## HTTPS 経由の検証(本番ドメイン、Pages Function プロキシ)

`https://construction-os.mirai-dx-platform.com/api/v1/*` を Pages Function
(`webui/functions/api/[[path]].ts`)が Cloudflare Tunnel
(`api.construction-os.mirai-dx-platform.com`、HTTP)へ転送する構成。

| 確認項目 | 結果 |
|---|---|
| `GET /api/v1/health/services`(HTTPS) | ✅ 全サービス healthy |

> **注 (2026-09-18)**: 当時の `/health` は DB 到達性を確認せず常に 200 を返していた。
> 現在は DB へ到達できない場合 503 を返す。詳細は [`health-checks.md`](./health-checks.md) を参照。

> **注 (2026-10-14)**: 上の「全サービス healthy」は**当時プローブしていた範囲**の結論である。
> 当時の対象は 3 件（document / workflow / notification）だけで、ゲートウェイの上流 21 件の
> うち 17 件を見ていなかった。現在は全上流を網羅し、`scripts/ci/check_health_coverage.py` が
> 網羅を検査する。詳細は [`health-checks.md`](./health-checks.md) §集約エンドポイント。

| `POST /api/v1/auth/login`(HTTPS) | ✅ JWT 発行(roles: admin) |
| `GET /api/v1/users`(Bearer・HTTPS) | ✅ シード済みユーザーを Neon から返却 |
| `GET /api/v1/roles`(Bearer・HTTPS) | ✅ 7ロール返却 |

※ トンネルホスト名(api.construction-os...)自体の HTTPS 証明書は
ゾーンの advanced 証明書パック追加が必要(ssl write 権限がトークンに無いため未実施)。
Pages Function 経由で本番ドメインの HTTPS から API を利用可能。
