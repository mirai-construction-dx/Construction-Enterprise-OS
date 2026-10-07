# CI 強化 手順書 — repo-invariants ゲートの追加

対象: `.github/workflows/ci.yml`

## 背景

`python-checks` はサービス単位のマトリクスで `generate_base_schema.py --check <service>` を
実行しているが、次の 2 点は CI で検出できていない。

1. **マトリクス未登録サービス / サービス横断の DDL 乖離**（`--check` を引数なしで全走査しないと拾えない）
2. **`get_db` の commit 欠落による「書込み消失」**（API は 200/201 を返すのに永続化されない）

後者は過去に `maintenance` / `security` / `vision` / `safety` で実際に発生した
（Issue #137 / #152）。ローカルでは `make repo-invariants` で検出できるが、CI に
ゲートが無いため再発を自動検知できない。

## 現状の CI 構成

| ジョブ | 内容 |
|---|---|
| `python-checks` (matrix) | ruff / mypy / pytest / `generate_base_schema.py --check <service>` |
| `mcp-checks` | services/mcp の ruff / mypy / pytest |
| `packages-checks` / `web-api-contract` / `frontend-checks` | 各領域 |
| `security-scan` | pip-audit + Trivy |
| `docker-build-*` | イメージビルド |

`check_session_lifecycle.py`（repo-invariants の後半）を実行するジョブが無い。

## 追加する変更（人間作業）

`.github/workflows/ci.yml` の `python-checks` ジョブの直後（`mcp-checks` の直前）に、
以下を追加する。

```yaml
  # ============================================
  # リポジトリ不変条件 (matrix では検出できない「気付かず緑」を防ぐ)
  # ============================================
  # get_db の commit 欠落による「書込み消失」を静的に検出する（DB 不要）。
  # サービス単位の python-checks では、他サービスや未登録サービスの漏れを拾えない。
  repo-invariants:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1

      - name: Setup Python
        uses: actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97 # v7.0.0
        with:
          python-version: "3.12"

      - name: Repository invariants (DDL sync + session lifecycle)
        run: make repo-invariants
```

`make repo-invariants` は次を実行する（`Makefile`）。

- `schema-check`: `python3 scripts/db/generate_base_schema.py --check`（全サービス走査）
- `session-check`: `python3 scripts/db/check_session_lifecycle.py`（get_db の commit 欠落検出）

いずれも DB・外部サービスへ接続しない静的検査であり、追加の secrets は不要。

## 適用後の確認

1. PR を作成し、`repo-invariants` ジョブが green になることを確認する
   （現状の main ではローカル実行で `✅ リポジトリ不変条件 OK`）。
2. ブランチ保護の Required status checks に `repo-invariants` を追加する
   （Settings → Branches → Branch protection rules）。
   - CI ワークフローの変更およびブランチ保護設定の変更は、エージェントの
     self-evolution ポリシーゲートで拒否される（DEPLOY 相当の critical 操作）ため、
     人間が実施する。

## 参考

- ローカル実行: `make repo-invariants`
- 検出器: `scripts/db/check_session_lifecycle.py`, `scripts/db/generate_base_schema.py`
- 品質テストランナー: `scripts/quality/run_quality_tests.sh`
  （各サービスの `tests/` に `test_quality_*.py` が含まれるため、`pytest tests/` で既に実行される）
