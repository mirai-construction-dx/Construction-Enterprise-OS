# ADR-0005: Staging 環境（stg）を本番の前置き検証環境として分離する

- 状態: accepted
- 日付: 2026-10-14
- 決定者: オーナー全権委譲による CTO 代行（本セッション）
- 上位規範: `Conforms-to: MCDX-ADR-0002 / MCDX-ADR-0003 / MCDX-ADR-0004`
- 関連: `GITHUB_POLICY.md` v2、`docs/operations/deployment.md`、`docs/architecture/CloudflarePostgreSQLGitHub自動化仕様.md`

## 背景

Construction-Enterprise-OS（以下 CEOS）は、開発環境（`docker compose`、`ENVIRONMENT=docker`）と
本番（Cloudflare Pages `construction-os-web`）の 2 つしか持っていない。
間に検証環境が無いため、次の問題が実際に起きている。

1. **本番へ出る前に結合を確かめる場所が無い。** 23 の FastAPI サービスはそれぞれ独立した
   `pytest` を持ち CI も通るが、24 サービスを 1 つの DB・1 つのゲートウェイで同時に起動した
   状態は検証されない。`docker-compose.yml` はローカル開発用であり、本番構成ではない。
2. **本番と同一の DB 基盤で試せない。** 本番は MCDX-ADR-0003 により
   「ホストの PostgreSQL 18 + Cloudflare Tunnel/Access」を入口とするが、
   ローカル開発は compose 内の PostgreSQL 16 であり、バックアップ・PITR の検証ができない。
3. **ロールバック手順が本番で初めて実行される。** Pages のロールバックは
   `docs/operations/deployment.md` §6 に方針だけがあり、実行記録がない。
4. **姉妹リポジトリとの接続点が無い。** `Mirai-Platform-Infra` は
   `tools/check_deploy_readiness.py --environment stg` で環境別のデプロイ前提を検査するが、
   CEOS は `envs/stg/releases.yaml` にも `db/roles.yaml` にも登録されていない。

先行事例として `Construction-Site-Spatial-Platform`（CSSP）が
第 1 段（Pages `cssp-stg` + Access + DNS `3dgs-stg`）と
第 2 段（ローカル compose + Tunnel）の 2 段構築を実施しており、
命名・分離・秘密の置き場所の家族パターンが確立している。本書はそのパターンを CEOS に適用する。

## 決定

### 1. 環境は 3 つ（dev / stg / prod）とし、stg を本番の前置き検証環境とする

| 環境 | 実行基盤 | 入口 | DB | 用途 |
|---|---|---|---|---|
| dev | 手元の `docker compose` | なし（localhost のみ） | compose 内 PostgreSQL 16 | 実装・単体テスト |
| **stg** | **本ホストの systemd 管理下の compose スタック**（`infra/systemd/ceos-stg.service`） | `https://construction-os-stg.mirai-dx-platform.com`（Cloudflare Access） | **ホスト PostgreSQL 18 クラスタ `18/infra_stg`（port 55438, loopback）の `ceos_stg`** | 結合検証・リリース前確認・ロールバック訓練 |
| prod | Cloudflare Pages + Tunnel | `https://construction-os.mirai-dx-platform.com` | ホスト PostgreSQL 18 | 本番 |

### 2. stg の system of record はホスト PostgreSQL 18（MCDX-ADR-0003 決定 1 に従う）

- stg のリレーショナル DB は、`Mirai-Platform-Infra` が管理する
  ホスト PostgreSQL 18 クラスタ `18/infra_stg`（`localhost:55438`）上の
  **専用データベース `ceos_stg`** とする。開発用 compose の PostgreSQL は stg では使わない。
- これにより stg は pgBackRest による full/diff + WAL アーカイブ + PITR の
  復旧訓練対象に入る（`Mirai-Platform-Infra/ops/stg-pg18.md`）。
- DB のロール払い出しの正本は `Mirai-Platform-Infra` の `db/roles.yaml` である。
  CEOS は自前でロールを発番せず、Infra へ登録を依頼する（§4 の残課題）。
- リポジトリをまたいで DB へ直接接続しない（MCDX-ADR-0003 決定 2）。
  stg への接続は CEOS 自身のサービスに限る。

### 3. stg の公開入口は Cloudflare に限る（MCDX-ADR-0003 決定 3）

- 静的画面: Cloudflare Pages プロジェクト `construction-os-stg`
  （カスタムドメイン `construction-os-stg.mirai-dx-platform.com`）。
- API: Cloudflare Tunnel + Access。コンテナは**ホストの loopback のみ**にバインドし、
  新規の受信ポートを LAN へ開けない。
- `*.pages.dev` のプレビュー URL も Access の対象とする。
  Access が利用できない場合は、プレビューを**公開しない**（fail closed）。

### 4. `main` へのマージを stg 反映の契機とする（継続的デリバリー）

- `.github/workflows/staging-deploy.yml` が `main` への push（および `workflow_dispatch`）で
  Pages プロジェクト `construction-os-stg` へデプロイし、スモークテストを実行する。
- **prod への反映はこの workflow に含めない。** prod 反映は MCDX-ADR-0004 決定 4 により
  コードのマージとは別の Human Gate である。
- stg の反映に人の承認を要求しない。Required Checks が通った `main` の内容がそのまま stg になる。

### 5. stg の秘密はリポジトリに置かず、ホストの 0600 ファイルに置く

- `~/.config/ceos/stg.env`（mode 0600）を唯一の正本とする。
  リポジトリには**変数名だけ**を `.env.stg.example` として置く。
- CI は GitHub Secrets / GitHub Environment `staging` を使う。
- JWT 鍵は stg 専用に生成する。開発用既定鍵（`dev-only...`）は
  `ENVIRONMENT=staging` では起動時に拒否される（各サービスの `config.py`）。

### 6. stg は本番の fail-closed な統制をすべて有効にする

- `ENVIRONMENT=staging` は `development` / `test` のいずれでもないため、
  各サービスの「開発用既定鍵での起動禁止」「`/docs`・`/redoc` の無効化」が
  本番と同じように効く。stg で無効化を緩めない。

## 付記: systemd unit と enable の扱い（2026-10-14 実測で追加）

ADR 制定時点では「systemd 管理下」と書きながら、実体は `scripts/stg/up.sh` による
**手動起動のみ**だった。`infra/systemd/ceos-stg.service` を追加し、正本をリポジトリに置いたうえで
`/etc/systemd/system/` へ設置した。

    sudo install -m 644 infra/systemd/ceos-stg.service /etc/systemd/system/ceos-stg.service
    sudo systemctl daemon-reload
    systemctl start ceos-stg      # scripts/stg/up.sh --no-wait
    systemctl stop ceos-stg       # scripts/stg/down.sh（ボリュームは保持）

**`systemctl enable` は行っていない。** ホスト再起動時に stg の DB クラスタ
`postgresql@18-infra_stg.service` が起動しない設定（`UnitFileState=disabled`。
`Mirai-Platform-Infra` の未決 B-2）であるため、先にスタックだけを自動起動すると
起動時に失敗する。**B-2 の決定と同時に enable するか**を決める。
そのため unit は DB クラスタに `Requires` を付けず `After`（順序）だけを指定している。
DB が停止していれば `up.sh` が前提確認で非ゼロ終了し、systemd が `failed` として記録する。

## 影響

- `.env.example` の `ENVIRONMENT=docker` は dev 専用であることが明確になる。
- `docs/operations/deployment.md` の「未実施（次フェーズ）」のうち
  「全サービス群の docker-compose 稼働 + Tunnel 複数ホスト ingress 化」は
  stg で先に達成し、prod はその実績の上で判断する。
- `Mirai-Platform-Infra` の `envs/stg/releases.yaml` 作成には、
  digest 固定イメージ・`v*` タグ・署名/来歴・ITSM 変更番号が必要である。
  **これらは創作できない**ため、CEOS 側で release 工程を整えるまで登録しない
  （`AGENTS.md`「未確認を成功と記録しない」）。
- Cloudflare の DNS 追加は MCDX-ADR-0004 決定 3 の「公開 DNS・custom domain」に
  該当する。本作業はオーナーが本セッションで明示的に委譲した stg 公開に限り、
  **prod の DNS・route・secret には触れない**。

## 見直し条件

- `Mirai-Platform-Infra` の stg クラスタが本番相当の運用（自動起動・通知・別機器復元）に入ったとき。
- CEOS の prod 反映経路（GitHub Environment `production` + reviewer）を決めるとき。
- 組織ポリシーが stg の扱いを定めたとき。
