> ⚠️ **基点更新**: 本提案は Core `v0.7.0`（commit `0e5e3a4e74ceb98e5ee3746ac678fb0f6d8b0b1d`）を基点とする。
> `mcp-allowlist.yaml` と `tools/tests/test_tool_def_hash.py` は cleanly 適用できるが、
> `tiers.yaml` と `CHANGELOG.md` は hunk が一致しないため
> [REBASE-v0.7.0.md](./REBASE-v0.7.0.md) の手順で手作業適用する。

## 目的
CEOS（Construction-Enterprise-OS）の読み取り専用 MCP ツール 5 件を Core の契約・Allowlist に登録し、MCAH / Tool Gateway が検証可能な形で参照できるようにする。CEOS 側は PR #94（Construction-Enterprise-OS）で Core 規約（JCS × x-mirai）のハッシュへ整合済み。

## 変更
| ファイル | 内容 |
|---|---|
| `approval-tiers/tiers.yaml` | 操作カテゴリ `record.read: R0`（業務記録の参照。書込み・確定を伴わない）を追加 |
| `contracts/mcp-tools/ceos.json` | CEOS の Core 形式契約（5 ツール、`x-mirai: {effect: read, operation: record.read, tier: R0}`） |
| `registries/mcp-allowlist.yaml` | `ceos` サーバー（trust T0 / surfaces [dev_harness] / audience `api://ceos-mcp` / timeout_s 15） |
| `tools/tests/test_tool_def_hash.py` | ceos 契約ハッシュ＝Allowlist 登録値の検査 |
| `CHANGELOG.md` | Unreleased / Added |

## レビューで判断が必要な点（提案値）
1. **操作カテゴリ名 `record.read`**：既存の汎用カテゴリ（`document.search` 等）に合わせた汎用名。CEOS 固有名（例 `ceos.record.read`）が望ましければ変更する。
2. **`trust: T0`**：MCIP と同じ自社システムとして扱う。
3. **`surfaces: [dev_harness]` のみ**：CEOS は現時点で JWT の audience（`api://ceos-mcp`）を検証していないため、本番 MCAH（`mcah_production`）は audience 検証の確定後に別 PR で追加する。
4. **`scopes` 未設定**：CEOS のユーザートークンは roles ベースで、スコープ体系が未定義のため。

## テスト（ローカル実測、origin/main a888d5b 基点）
- `make check` OK / `make lint` OK / `make test` 116 passed, 8 skipped / `make policy` coverage 100%
- `make vectors` pass（Python 27 / Node 11）/ `make mutation` OK / `make validate-contracts` OK
- `make compat-strict` OK、`make compat` 判定 **minor**（ツール追加・operation 追加のみ）
- 負例: ceos.json の description 改ざんで `[VA-03-3] 定義ハッシュ不一致` を検出

## セキュリティ
Secret・実データなし。読み取り専用（R0）のみ。書込み・承認系ツールは含まない。

## 利用側への影響 / 後続
- 追加のみ（MINOR）。既存の利用側への影響なし。
- CEOS 側は Core のリリース後に `x-mirai.operation=record.read` を付与し、固定参照（`contracts/harness-core.lock.json`）を新版へ更新する（ハッシュは本 PR の登録値と一致する見込み）。

## Rollback
本 PR の revert（追加のみのため影響なし）。

🤖 Generated with [Claude Code](https://claude.com/claude-code)
