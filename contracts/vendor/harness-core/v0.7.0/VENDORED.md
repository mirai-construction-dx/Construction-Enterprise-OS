# Vendored snapshot: Mirai-Harness-Core v0.7.0

このディレクトリは `Mirai-Harness-Core` のタグ `v0.7.0`
（commit `0e5e3a4e74ceb98e5ee3746ac678fb0f6d8b0b1d`）から、CEOS の MCP ツール契約を
Core 規約に照合するために必要なファイルを **無改変で** コピーしたものである。

| ファイル | 用途 |
| --- | --- |
| `tools/tool_def_hash.py` | ツール定義ハッシュの Core 規約（RFC 8785 JCS × 対象キー）。CEOS 実装との一致検査に使う |
| `contracts/mcp-tools/mcip.json` | Core 登録済みツール契約。ハッシュ実装の golden vector |
| `registries/mcp-allowlist.yaml` | 上記 golden vector の登録ハッシュ |
| `registries/systems.yaml` | システム台帳（`ceos` の `mcp_server_id` / `audience`） |
| `approval-tiers/tiers.yaml` | 承認階層（R0〜R4）と操作カテゴリ |
| `schemas/registry/mcp-allowlist.schema.json` | Allowlist 登録時の effect/tier 制約 |
| `VERSION` | Core の版 |

## 改変禁止

各ファイルの SHA-256 は `contracts/harness-core.lock.json` に固定され、
`services/mcp/tests/test_core_conformance.py` が CI で照合する。手編集は検査で失敗する。
Core への変更はコピーを改変せず、Core リポジトリへの提案（PR）で行う
（Core `docs/consumer-guide.md` §8）。

## なぜ vendoring か（暫定）

Core の配布（GitHub Release / GHCR / PyPI 互換フィード）は未公開（Core O-03 / O-04）で、
`mhc pull` による正規取込みがまだ成立しない。稼働中の Core リポジトリをパス参照する暗黙依存を
避けるため、MCAH（`vendor/harness-core/38d3501/`）と同じくタグ固定のスナップショットで固定する。

## 更新・ロールバック

- 更新: Core 側で新タグを確認 → 新ディレクトリ `v<新版>/` に同じファイル群をコピー →
  `harness-core.lock.json` の `core_version` / `source` / `files` / `vendor_dir` を更新 → CI 通過を確認。
- ロールバック: `harness-core.lock.json` を旧版へ戻す（旧ディレクトリは残す）。

## 置き換え条件

Core が署名付きリリース成果物を公開した時点で、`mhc pull` / `mhc verify` と
`contracts.lock.json` による正規方式へ移行し、本ディレクトリを廃止する。
