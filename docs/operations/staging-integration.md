# Staging 環境のリポジトリ間連携 — 実測レジスタ

- 対象: `mirai-construction-dx` 配下の主要リポジトリ
- 基準日: 2026-10-14
- 正本: 本ファイル（CEOS 側の視点）。全社台帳は
  `Mirai-Construction-DX-Portfolio/catalog/repositories.yaml`、
  System Registry は `Mirai-Platform-Infra/systems.yaml`。

## 0. この文書の読み方

各行は「**実測**（コマンドで確認した）」か「**設計**（文書にあるだけ）」かを `根拠` 列で区別する。
未確認を成功として書かない（`AGENTS.md` §4.7）。

## 1. 各リポジトリの Staging 有無（2026-10-14 実測）

| リポジトリ | stg 環境 | 実体 | 根拠 |
|---|---|---|---|
| **Construction-Enterprise-OS**（CEOS） | **構築中** | ホスト PG18 `ceos_stg` + compose スタック + Pages `construction-os-stg` + Access | 本リポジトリ `docs/operations/staging.md`（実測） |
| Construction-Site-Spatial-Platform（CSSP） | あり（第 1 段完了 / 第 2 段途中） | Pages `cssp-stg` + Access + DNS `3dgs-stg` + `compose.yaml`（name `cssp-stg`） | CSSP `docs/stg/stage2-runbook.md` |
| Mirai-Platform-Infra | 基盤のみ | PG18 クラスタ `18/infra_stg`（port 55438）。`tools/check_deploy_readiness.py --environment stg` は **NOT_READY（4 件欠落）** | 同コマンドの実測 |
| Civil-Docs-Platform | なし | `CDP_ENV` は `dev` と非 dev のみ。`deploy/local` / `deploy/prod` / `deploy/onprem` の 3 系統 | CDP `docs/adr/ADR-0007`・`ADR-0008` |
| Mirai-Construction-Information-Platform | なし | dev / 本番（`mcip_mvp`）+ 検証 DB。native systemd | MCIP `README.md`・`docs/architecture/PostgreSQL運用仕様.md` |
| Mirai-Construction-Agent-Harness | なし | `MCAH_PROFILE` = `dev` / `onprem`（未知は非 dev の fail-closed） | MCAH `docs/adr/0037` |
| Mirai-Architecture-Decisions | —（規範のみ） | staging 分離を明示的に命じる ADR は**存在しない** | `adr/` 全 9 件の実測 |
| Mirai-Harness-Core | —（契約正本） | Core 契約の版が 4 系統に分裂（0.6.0 / 0.7.0 / 0.1.0 / 未宣言） | `Mirai-Platform-Infra/docs/inter-repo-integration-register.md` |

**結論**: 全社で stg を持っているのは CSSP と CEOS だけである。
「stg を分離せよ」と命じる全社 ADR は無く、CEOS の分離は
`MCDX-ADR-0002`（本番の新規 Docker 禁止）・`MCDX-ADR-0003`（本番 DB と入口）・
`MCDX-ADR-0004`（マージとリリース）に **Conforms-to で従う**形で自リポジトリ ADR として定めた。

## 2. CEOS stg が実際に接続している相手

| 相手 | 接続の実体 | 状態 | 根拠 |
|---|---|---|---|
| **Mirai-Platform-Infra**（DB 正本） | ホスト PG18 クラスタ `18/infra_stg` の DB `ceos_stg` を system of record にする | **稼働** | `db-bridge` が `10.201.0.1:55438` → `127.0.0.1:55438` を転送。auth の `GET /health` が 200 |
| Mirai-Platform-Infra（System Registry） | `systems.yaml` に `id: ceos`（type `domain-product`, production true）が登録済み | **登録済み** | 同ファイル 66-71 行 |
| Mirai-Platform-Infra（DB ロール台帳） | `db/roles.yaml` は `database: mirai` の台帳。CEOS の stg は**別 DB `ceos_stg`** のため未掲載 | **未登録** | 同ファイル実測 |
| Mirai-Platform-Infra（deploy 前提ゲート） | `envs/stg/releases.yaml` が無く `NOT_READY` | **未充足** | `tools/check_deploy_readiness.py --environment stg` |
| **Mirai-Construction-DX-Portfolio**（catalog） | `repo_key: ceos` に Pages `construction-os-web` / `construction-os-mvp` の deployments が `observed` で登録済み。stg は追加依頼中 | **追加中** | `catalog/repositories.yaml` |
| **Cloudflare**（入口） | Pages `construction-os-stg` + Access アプリ。DNS CNAME は未作成 | **一部未完了** | `docs/operations/staging.md` §6 |
| **Mirai-Harness-Core**（契約） | `contracts/harness-core.lock.json` が v0.6.0 を pin。Infra / MCIP / IT-BCP は 0.7.0 | **不一致** | 同ファイル実測 |
| **CSSP** | CSSP `docs/adr/0005-integration-policy.md` が CEOS を read 系 MCP 契約 `ceos.json` の相手と定める。第 1 期は接続ゼロ | **設計のみ** | CSSP 同ファイル |
| MCIP / MCAH | `docs/integration-map.md` に `runtime_api → mcah`、`mcp_tool_gateway → mcip` の設計がある。実装接続は無し | **設計のみ** | Portfolio `docs/integration-map.md` |

**CEOS stg が他リポジトリへ与える影響は無い。** 接続はすべて片方向（CEOS が使う側）であり、
他リポジトリが CEOS stg の DB・ポート・Pages を参照する経路は現時点で存在しない。

## 3. 他リポジトリと共有している「環境の決め事」

CEOS stg は CSSP stg の家族パターンに揃えた。次は両者で同じである。

| 決め事 | 値 |
|---|---|
| ホスト名 | `<name>-stg.mirai-dx-platform.com`（CSSP は `3dgs-stg`、CEOS は `construction-os-stg`） |
| 静的画面 | Cloudflare Pages（本番とは別プロジェクト） |
| 入口の保護 | Cloudflare Access（環境ごとに別アプリ。`bypass` / `everyone` を置かない） |
| 秘密の置き場所 | `~/.config/<repo>/stg.env`（mode 0600）。リポジトリ・CI へ置かない |
| 受信ポート | loopback のみ。LAN へ開かない。外部公開は Tunnel に限る |
| DB の分離 | 環境ごとに別 DB / 別ロール |
| 環境識別子 | `APP_ENV=staging` / `ENVIRONMENT=staging` |
| 画面の取り違え防止 | stg 側にマーカーを置く（CSSP は `EXPORT_WATERMARK=STAGING`、CEOS は Pages の `/STAGING`） |

このパターンは文書化されていない。**CEOS の ADR-0005 が初めて明文化した**ので、
他リポジトリが stg を作るときはこれを参照できる。
全社 ADR へ昇格させるかは `Mirai-Architecture-Decisions` の判断事項である（§5-1）。

## 4. CEOS 側の残作業（連携に効くもの）

| # | 内容 | 相手 | 種別 |
|---|---|---|---|
| 1 | ロール `ceos_stg_*` を Infra の台帳へ登録する | Mirai-Platform-Infra | 台帳整合 |
| 2 | `envs/stg/releases.yaml` に載せるための release 工程（`v*` タグ・digest 固定イメージ・署名/来歴・ITSM 番号） | Mirai-Platform-Infra + 変更管理 | 要人間判断（MCDX-ADR-0004 決定 4） |
| 3 | Core 契約を 0.6.0 → 0.7.0 へ上げる | Mirai-Harness-Core | 契約更新 |
| 4 | read 系 MCP 契約 `ceos.json` を stg で公開し CSSP へ渡す | Construction-Site-Spatial-Platform | 連携実装 |
| 5 | Portfolio catalog へ stg deployment を登録する | Mirai-Construction-DX-Portfolio | 台帳整合 |
| 6 | stg の Pages/Tunnel を CDP・MCIP と共有するか、リポジトリごとに分けるか | 全社 | 要判断 |
| 7 | stg クラスタの自動起動（`UnitFileState=disabled`）と `pgaudit` の導入 | Mirai-Platform-Infra | Infra 側の未決 B-2 |

## 5. 判断が必要な事項（AI が決めない）

1. **stg の家族パターンを全社 ADR にするか。** CEOS は `MCDX-ADR-0002/0003/0004` に従う形で
   ローカル ADR を作った。全社で統一するなら `Mirai-Architecture-Decisions` に新 ADR が要る。
2. **stg へ人の承認を要求するか。** 中央ポリシー v2 と `MCDX-ADR-0004` はコードの自動マージを認めるが、
   `MCDX-ADR-0004` 決定 3 は「公開 DNS・custom domain・production route」を Approval PR の対象にしている。
   `construction-os-stg.mirai-dx-platform.com` の DNS 追加はこれに該当しうる。
   本作業では**オーナーが本セッションで stg 構築を明示的に委譲した**ことを根拠に実施範囲としたが、
   継続運用の扱い（今後の stg ドメイン追加を AI が行ってよいか）は決めておく必要がある。
3. **Core 契約の版をどこへ揃えるか。** 0.6.0 のままか 0.7.0 へ上げるか。
4. **Mirai-Platform-Infra の merge-gate を維持するか。** 同リポジトリの `AGENTS.md` は
   中央ポリシー v3 §10 の Repo 限定除外により、人間の `/merge Y|N` を最終判断にしている（施行前）。
   本作業でも同リポジトリへの PR は**自動マージしない**。
