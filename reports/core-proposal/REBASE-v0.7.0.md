# 提案パッチの v0.7.0 基準への再適用ノート

対象: `reports/core-proposal/0001-feat-CEOS-MCP-Allowlist-record.read.patch`
基点の更新: Core `origin/main a888d5b`（提案作成時） → **`v0.7.0`（commit `0e5e3a4e74ceb98e5ee3746ac678fb0f6d8b0b1d`）**

## 1. 実測した適用可否（Core 作業ツリーは変更していない）

`git -C Mirai-Harness-Core apply --check <patch>` の結果:

| ファイル | 判定 |
|---|---|
| `registries/mcp-allowlist.yaml` | ✅ **cleanly 適用可** |
| `tools/tests/test_tool_def_hash.py` | ✅ **cleanly 適用可** |
| `contracts/mcp-tools/ceos.json` | ✅ 新規ファイル（`/dev/null` 起点）のため適用可 |
| `approval-tiers/tiers.yaml` | ❌ hunk 不一致（v0.7.0 で `ledger.issue.preview: R0` が追加されたため） |
| `CHANGELOG.md` | ❌ hunk 不一致（Core 側で CHANGELOG が更新されたため） |

> Core の作業ツリーには 98 件の未コミット変更があるため、`--check`（書込みなし）のみで判定した。

## 2. 手作業で適用する差分（2 ファイル）

### `approval-tiers/tiers.yaml`

`operations:` ブロックの `ledger.issue.preview: R0` の**直後**に 1 行追加する。

```yaml
  record.read: R0  # 業務記録（工程・原価・契約等）の参照。書込み・確定を伴わない
```

v0.7.0 時点の該当箇所:

```yaml
operations:  # 操作カテゴリ → 階層（ツールの x-mirai.operation から参照）
  document.search: R0
  answer.grounded: R0
  ledger.issue.preview: R0  # …（v0.7.0 で追加）
+ record.read: R0
  draft.create: R1
```

### `CHANGELOG.md`

`Unreleased` の `Added` に次を追加する。

```markdown
- feat(allowlist): CEOS（Construction-Enterprise-OS）の読み取り専用 MCP ツール 5 件を登録
```

## 3. 判断が必要な点（提案値・再掲）

1. 操作カテゴリ名 `record.read`（CEOS 固有名 `ceos.record.read` が望ましければ変更）
2. `trust: T0`（MCIP と同じ自社システム扱い）
3. `surfaces: [dev_harness]` のみ（CEOS が audience `api://ceos-mcp` を検証するまで本番 MCAH は追加しない）
4. `scopes` 未設定（CEOS のトークンは roles ベースでスコープ体系が未定義）

## 4. CEOS 側の現状（本ノート作成時点）

- Core 固定参照は **v0.7.0** へ更新済み（`contracts/harness-core.lock.json`）
- CEOS の 5 ツールは `effect=read` / `tier=R0` / `upstream_method=GET` で、書込み・承認・確定を含まない
- `x-mirai.operation` は**未設定**（Core 側に CEOS 用カテゴリが無いため）。本提案が受理された後、
  次の MAJOR で `record.read` を付与して定義ハッシュを再計算する想定

## 5. 検証手順（提案先で実行）

```bash
git apply --check reports/core-proposal/0001-feat-CEOS-MCP-Allowlist-record.read.patch
# 上記 2 ファイルを手作業で適用した後
make check && make test && make validate-contracts && make compat
```
