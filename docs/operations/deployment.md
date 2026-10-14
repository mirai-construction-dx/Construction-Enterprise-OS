# デプロイ・ドメイン運用

## 1. ドメイン方針(2026-08-18 確定)

| 用途 | サブドメイン | 状態 |
|---|---|---|
| 本番環境 | `construction-os.mirai-dx-platform.com` | 新規取得・CNAME 設定済み |
| MVPプロトタイプ | `construction-os-mvp.mirai-dx-platform.com` | 新規取得・CNAME 設定済み |

- 親ドメイン `mirai-dx-platform.com` は Cloudflare(取得済み・active、zone: `e375e651e49a40801a305b89e297bff0`)。
- DNS: Pages カスタムドメインとして管理(CNAME + プロキシ)。

## 2. デプロイアーキテクチャ(家族パターン準拠)

既存プロジェクト(OBCDA/PIMM/CEOP)のパターンを踏襲:

| 層 | 方式 |
|---|---|
| フロントエンド | Cloudflare Pages(`construction-os-web` / `construction-os-mvp`) |
| バックエンド API | FastAPI サービス群を docker-compose で稼働 + Cloudflare Tunnel で公開(CEOP 方式) |
| データベース | **ホスト PostgreSQL**（実測: PG 16.14 / `construction_os`）。`MCDX-ADR-0003` は PG18 を定めており差分あり — `database.md` 参照 |

## 3. 現在の構成(2026-08-18 実施済み)

| 項目 | 値 |
|---|---|
| Pages プロジェクト(MVP) | `construction-os-mvp` → `construction-os-mvp.pages.dev` |
| Pages プロジェクト(本番) | `construction-os-web` → `construction-os-web.pages.dev` |
| MVP カスタムドメイン | `construction-os-mvp.mirai-dx-platform.com` → CNAME `construction-os-mvp.pages.dev` |
| 本番カスタムドメイン | `construction-os.mirai-dx-platform.com` → CNAME `construction-os-web.pages.dev` |
| MVP コンテンツ | `webui/`(OpenDesign ハンドオフ)を `index.html` としてデプロイ |
| 自動デプロイ | `.github/workflows/pages-deploy.yml`(main への `webui/**` push で MVP と本番の両 Pages へ deploy) |
| GitHub Secrets | `CLOUDFLARE_API_TOKEN` / `CLOUDFLARE_ACCOUNT_ID` |

## 4. デプロイ対象プロジェクト(2026-08-18 拡張)

`pages-deploy.yml` は matrix(`construction-os-mvp` / `construction-os-web`)で
**MVP と本番の両プロジェクトへ同一内容を自動デプロイ**する。

- 本番(`construction-os-web`)は MVP フェーズではプロトタイプ(webui)を配信。
- 本番検証: `https://construction-os.mirai-dx-platform.com` で
  ヘルスチェック(HTTP 200)・主要画面・E2E を確認済み。

## 5. 手動デプロイ(MVP WebUI)

```bash
CLOUDFLARE_API_TOKEN=*** CLOUDFLARE_ACCOUNT_ID=4f1e888469df7e0b896bb4e211b12633 \
  wrangler pages deploy .deploy-webui --project-name construction-os-mvp --branch main
```

※ `.deploy-webui` の準備は `.github/workflows/pages-deploy.yml` の
「Prepare deploy directory」ステップと同一手順。本番へは
`--project-name construction-os-web` で同一内容をデプロイする。

## 6. ロールバック方針

- Pages: 直前の正常デプロイメントへ Rollback(Cloudflare API `POST /deployments/{id}/rollback` 対応済み)
- Tunnel: コンテナのタグ指定による再起動
- DB: ホスト PostgreSQL。stg は pgBackRest（stanza `infra_stg`）で PITR 可能。本番の復旧手順は未確認（`database.md` §4）

## 6.5 Staging(stg)環境

本番前の検証環境は `construction-os-stg` として分離している。

- 設計: [`ADR-0005`](../architecture/ADR-0005-staging-environment.md)
- 構築手順・運用手順: [`staging.md`](./staging.md)
- スタック: `docker-compose.stg.yml`（`scripts/stg/render_stg_compose.py` の生成物）
- DB: ホスト PostgreSQL 18 クラスタ `18/infra_stg` の `ceos_stg`
- 入口: Cloudflare Pages + Access（DNS レコードは未設定。`staging.md` §6.0）

**stg へのマージ契機は `main` へのマージである。** prod への反映は別の Human Gate とする。

## 7. 未実施(次フェーズ)

- [ ] 本番(`construction-os-web`)への Next.js ビルドデプロイ(現状は MVP プロトタイプを配信)
- [ ] 全サービス群の docker-compose 稼働 + Tunnel 複数ホスト ingress 化(現状は auth サービスのみ)
- [ ] Cloudflare Access による認証ゲート(MVP は公開、本番は Access 適用)

## 8. API 公開(2026-08-18 構築・HTTPS 検証済み)

### 8.1 Cloudflare Tunnel(auth サービス)

| 項目 | 値 |
|---|---|
| API 公開ホスト | `api.construction-os.mirai-dx-platform.com`(HTTP、エッジ証明書は未発行) |
| トンネル名 | `construction-os-api`(ID: d844edf7-c62c-4098-b6d5-5ba58ea027a9) |
| ローカル設定 | `~/.cloudflared/construction-os-api-config.yml`(認証情報はリポジトリ外) |
| 転送先 | `http://127.0.0.1:18002`(auth サービス。**native systemd** `construction-os-auth.service`、`ENVIRONMENT=production`、DB はホスト PostgreSQL `construction_os`) |
| 起動方法 | `cloudflared tunnel --config ~/.cloudflared/construction-os-api-config.yml run construction-os-api` |

### 8.2 Pages Function プロキシ(HTTPS 経由の API 公開)

`webui/functions/api/[[path]].ts` が **両 Pages プロジェクト**の
`/api/v1/*` を Tunnel 経由で auth サービスへ転送する
(本番・MVP ドメインの HTTPS で API・認証・DB 接続を利用可能)。

- デプロイ時は `functions/` がビルドされるよう、デプロイステップを
  `working-directory: .deploy-webui` + `wrangler pages deploy .` としている
  (wrangler は functions/ をカレントディレクトリ基準で検出するため)。
  親ディレクトリから `.deploy-webui` を引数にすると Functions が
  ビルドされず `/api/*` が SPA フォールバックになる(PF-001 で修正)。

### 8.3 HTTPS 検証結果(2026-08-18、本番ドメイン)

| 確認項目 | 結果 |
|---|---|
| `GET /api/v1/health/services` | ✅ 全サービス healthy(auth 12ms 等) |

> **注 (2026-09-18)**: 当時の `/health` は DB 到達性を確認せず常に 200 を返していた。
> 現在は DB へ到達できない場合 503 を返す。詳細は [`health-checks.md`](./health-checks.md) を参照。

| `POST /api/v1/auth/login`(環境変数 ADMIN_EMAIL の値) | ✅ JWT 発行(roles: admin) |
| `GET /api/v1/users`(Bearer) | ✅ シード済み管理ユーザーを返却（2026-08-18 時点の記録。当時は Neon 接続だったが現在はホスト PostgreSQL） |
| `GET /api/v1/roles?organization_id=...`(Bearer) | ✅ 7ロール + 権限を返却 |
| 認証なしアクセス | ✅ 401(認証ガード fail-closed) |
| 誤パスワード | ✅ 401 |
| WebUI(`/`・SPA フォールバック含む) | ✅ HTTP 200 |

※ 本番 API 化の際は、サービス群の docker-compose 稼働 + 複数ホストの ingress へ拡張する。
