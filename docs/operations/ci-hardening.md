# CI 強化 手順書 — repo-invariants ゲートの追加

対象: `.github/workflows/repo-invariants.yml`（新規。設置待ちの定義は
[`repo-invariants.workflow.yml`](./repo-invariants.workflow.yml)）

- 最終更新: 2026-10-14（実測に合わせて全面改訂）
- ローカルの正本: `make repo-invariants` / `make repo-invariants-ci`（`Makefile`）

## 背景

`.github/workflows/` の 3 ワークフローは **`make` を一切呼んでいない**
（2026-10-14 実測: `grep -rn "make " .github/workflows/*.yml` → 0 件）。
そのため `make repo-invariants` の 9 検査は**ローカルでしか回っていない**。
人が実行し忘れれば「気付かず緑」のまま main へ入る。

| 検査 | CI での被覆（2026-10-14 実測） |
|---|---|
| `schema-check` | **被覆あり（間接）**: `ci.yml` の `python-checks` マトリクスが `generate_base_schema.py --check <service>` をサービス単位で実行 |
| `session-check` | **無し**（`get_db` の commit 欠落 = API は 201 を返すのに永続化されない） |
| `ddl-coverage` | **無し**（モデルを持つサービスの DDL 出所の欠落。`services/erp` で実際に発生し staging が `UndefinedTableError` になった） |
| `ci-coverage` | **無し**（マトリクスは手書き。`maintenance` / `security` / `vision` / `safety` で登録漏れが実際に起きた: Issue #137 / #152） |
| `docs-links` | **無し**（追跡下 Markdown の相対リンク。2026-10-14 に 24 件のリンク切れを検出した） |
| `stg-pages-upstream` | **無し**（stg の Pages が本番 API を向いていないか。2026-10-14 に越境欠陥を検出した） |
| `tenant-conformance` | **無し**（18 サービスに複製された `tenant.py` が同じ分離の振る舞いをするか。2026-10-14 追加） |
| `org-query-scoping` | **無し**（67 のエンドポイントがクエリの `organization_id` をテナントヘルパに通しているか。AST で検査。2026-10-14 追加） |
| `health-coverage` | **無し**（集約ヘルス `/api/v1/health/services` がゲートウェイの全上流を見ているか。2026-10-14 追加。3/21 しか見ていなかった） |

## CI に入れるもの / 入れないもの

**入れる: 依存の軽い 8 検査**（`make repo-invariants-ci`）

```
session-check / ddl-coverage / ci-coverage / docs-links / stg-pages-upstream /
tenant-conformance / org-query-scoping / health-coverage
```

必要な追加依存は **PyYAML**（`ci-coverage`）、**fastapi / PyJWT / pydantic-settings**
（`tenant-conformance` が各サービスの `src.middleware.tenant` を import するため。
`src/middleware/auth.py` と `src/config.py` が要求する外部依存の和集合。2026-10-14 実測）。
DB にも外部サービスにも接続しない。追加の secrets は不要。

**入れない: `schema-check`**

`scripts/db/generate_base_schema.py` は `emit_metadata()` で
`sys.executable -c EMITTER <service>` をサービスごとに起動し、その中で
`sqlalchemy` と `src.models`（＝各サービスの依存）を import する。
素のランナーには sqlalchemy が無いため、`make repo-invariants` をそのまま実行すると
**`schema-check` で必ず失敗する**。

CI では `python-checks` マトリクスがサービス単位で同じ検査を行っており、
**マトリクスへの登録漏れは `ci-coverage` が検出する**ため、全サービスの被覆は保たれる。

## 追加する変更（人間作業）

### 手順 1: ワークフローを設置する

```bash
cp docs/operations/repo-invariants.workflow.yml .github/workflows/repo-invariants.yml
git add .github/workflows/repo-invariants.yml
git commit -m "ci: repo-invariants ゲートを追加する"
git push origin <branch>   # 以降は通常の PR フロー（Required Checks PASS 後に squash 自動マージ）
```

### 手順 2: Required status checks に追加する

設置後の最初の実行で**実際に報告されたジョブ名を確認してから**
ruleset `central-auto-merge` の `required_status_checks` へ `repo-invariants` を追加する。

順序が重要である。**存在しないチェック名を必須にすると全 PR が恒久的にブロックされる**
（中央ポリシー §6「必須チェックは実在させる」）。

CI ワークフローの変更およびブランチ保護設定の変更は、エージェントの
self-evolution ポリシーゲートで拒否される（DEPLOY 相当の critical 操作）ため、人間が実施する。

## 旧版の誤り（記録）

2026-10-14 より前の本手順書には次の 2 つの誤りがあり、**そのとおりに実施すると
CI ジョブが失敗していた**。

| # | 旧版の記述 | 実測 |
|---|---|---|
| 1 | 検査を 4 件（schema-check / session-check / ddl-coverage / ci-coverage）と記載 | `docs-links`（ラウンド15 追加）と `stg-pages-upstream`（ラウンド18 追加）が抜けていた |
| 2 | `run: make repo-invariants` を実行する | `schema-check` が sqlalchemy と各サービスの依存を要求するため、依存を入れないジョブでは**必ず失敗する**。PyYAML も未導入だった |

## 適用後の確認

1. PR を作成し、`repo-invariants` ジョブが green になることを確認する。
2. 手順 2 のとおり Required checks へ追加し、以降の PR で必須になっていることを確認する。
3. 陰性対照: 追跡下の Markdown に存在しない相対リンクを 1 つ足すと
   `docs-links` が非ゼロで落ちることを PR 上で確認する
   （ローカルでは `make repo-invariants-ci` で同様に確認できる）。

## 参考

- ローカル実行（DB が要る 9 検査）: `env -u DATABASE_URL make repo-invariants`
  - 環境に他システムの `DATABASE_URL` があると `schema-check` が落ちる。
    `scripts/db/check_target_db.py` が DB 操作系のターゲットを守るが、
    `schema-check` 自体は環境の URL を読むため `env -u DATABASE_URL` を付ける。
- ローカル実行（依存の軽い 8 検査）: `make repo-invariants-ci`
- 検出器: `scripts/db/check_session_lifecycle.py` /
  `scripts/db/check_service_ddl_coverage.py` / `scripts/ci/check_coverage.py` /
  `scripts/docs/check_links.py` / `scripts/stg/check_pages_upstream.py` /
  `scripts/security/check_tenant_helper_conformance.py` /
  `scripts/security/check_org_query_scoping.py` /
  `scripts/ci/check_health_coverage.py`
- 品質テストランナー: `scripts/quality/run_quality_tests.sh`
  （各サービスの `tests/` に `test_quality_*.py` が含まれるため、`pytest tests/` で既に実行される）
