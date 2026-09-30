# CEOS MCP Service（読み取り専用 / 第1増分）

CEOS が正本を持つ **工程・原価・契約** データを、Model Context Protocol（MCP）の
**読み取り専用ツール**として公開するサービス。MCIP / MCAH は Tool Gateway 経由で本サービスを消費する。

- 設計判断: [`docs/architecture/ADR-0002-ceos-mcp-readonly-publication.md`](../../docs/architecture/ADR-0002-ceos-mcp-readonly-publication.md)
- 責任範囲: [`docs/architecture/ADR-0001-ceos-responsibility-boundary.md`](../../docs/architecture/ADR-0001-ceos-responsibility-boundary.md)
- 状態: 検証ビルド（PoC）。本番稼働は宣言しない。

## 1. スコープ

- 公開するのは **読み取り専用（R0 / effect=read / HTTP GET）の 5 ツールのみ**。
- 書き込み・承認・支払・確定・削除（R2/R3/R4）のツールは公開しない。
- モデル鍵・LLM 呼び出し・承認ロジックは保持しない（MCAH の責務）。
- 既存サービス・スキーマ・DB は変更しない（追加のみ）。

## 2. 公開ツール（5 件）

| ツール名 | 上流エンドポイント | 必須引数 |
| --- | --- | --- |
| `ceos.wbs.get_tree` | GET `/api/v1/construction/wbs/tree` | `project_id` |
| `ceos.schedule.get_gantt` | GET `/api/v1/construction/projects/{project_id}/gantt` | `project_id` |
| `ceos.cost.list` | GET `/api/v1/erp/ledger/{ledger_id}/costs` | `ledger_id` |
| `ceos.ledger.get_summary` | GET `/api/v1/erp/ledger/summary` | なし |
| `ceos.contract.list` | GET `/api/v1/erp/invoices` | なし |

各ツールは `name` / `title` / `description` / `inputSchema`（JSON Schema）/
`annotations`（`readOnlyHint=true` 等）/ `x-mirai`（`effect="read"`, `tier="R0"`）と、
次の 2 つの固定ハッシュを持つ（いずれも RFC 8785 JCS 正規化 JSON の SHA-256）。

| ハッシュ | 対象 | 用途 |
| --- | --- | --- |
| `definition_sha256` | Mirai-Harness-Core 規約の対象キー（name・title・description・inputSchema・outputSchema・annotations・x-mirai） | Core Allowlist 登録値と同一。説明文の書換え（記述汚染）を検知 |
| `binding_sha256` | name と上流（service・method・path） | CEOS 内部の上流差替えを検知（Core 規約の対象外） |

**いずれかのハッシュ欠落・不一致、禁止 effect、非 GET、R0 以外、readOnlyHint と effect の矛盾が
あるとレジストリはロードを拒否する**（サーバーは起動しない）。

### 2.1 Core 形式のツール契約と固定参照

- Core 形式の契約 [`contracts/mcp-tools/ceos.json`](../../contracts/mcp-tools/ceos.json) は
  レジストリから生成する（`python -m src.tools.contract --write ../../contracts/mcp-tools/ceos.json`）。
  CI（`tests/test_contract_export.py`）がレジストリとの差分を検出する。
- Core v0.6.0 は [`contracts/harness-core.lock.json`](../../contracts/harness-core.lock.json) で
  タグ・commit・ファイル SHA-256 を固定し、`tests/test_core_conformance.py` が
  「CEOS のハッシュ実装＝Core `tool_def_hash.py`」「Core 登録済み mcip ハッシュの再現」
  「`registries/systems.yaml` の ceos 識別子一致」を検査する。
- 同テストは、契約から作る Allowlist 登録項目（`name` / `effect` / `tier` / `definition_sha256`）を
  vendored の Core `schemas/registry/mcp-allowlist.schema.json`（JSON Schema）で検証する。
  サーバー単位の `trust` / `surfaces` / `scopes` は Core 判断待ちのため検証対象外。
- `x-mirai.operation` は Core 承認階層表に CEOS 用カテゴリが無いため未設定（ADR-0002 未決事項）。
- 証跡（`core.evidence.*`）は ADR-0001 により MCIP が正本で、CEOS は証跡レコードを出力しない
  （監査ログはテキストのみ）ため照合対象なし。HTTP エラー形式の Core 整合は ADR-0002 未決事項を参照。

> **上流パスの確認結果（deviation）**
> 指示上の `ceos.cost.list` は `GET /api/v1/erp/costs` とされていたが、
> `services/erp/src/api/costs.py` を確認したところ当該パスは存在せず、
> 原価明細の読み取りは `GET /api/v1/erp/ledger/{ledger_id}/costs` のみである。
> 存在しないパスを公開すると常に 404 になるため、実在する読み取りルートへ対応付けた。
> ツール名と役割は変えていない。

## 3. トランスポート

- 公式 MCP Python SDK（`mcp==1.30.0`。1.28.1 未満は既知脆弱性のため使用しない）の低レベル `Server` と
  `StreamableHTTPSessionManager` による **MCP over Streamable HTTP**。
- エンドポイント: `POST /mcp/`（`initialize` / `tools/list` / `tools/call`）。
- 既定は `stateless`（各リクエスト独立、読み取り専用のため再開不要）。
- ツール一覧は MCP の `Tool` として `name` / `title` / `description` / `inputSchema` と
  注釈（`readOnlyHint=true`, `destructiveHint=false`, `idempotentHint=true`, `openWorldHint=false`）を返す。
  これらは `contracts/mcp-tools/ceos.json` と同一値である（`x-mirai` は契約側のみに持つ）。

## 4. 認証

- `services/construction` と同じ JWT/OIDC パターン。Bearer トークン必須。
- 欠落・不正・期限切れは `401`、ユーザートークン以外は `403`（ASGI ガードで強制）。
- 呼び出し元の `Authorization` ヘッダーを上流サービスへそのまま転送し、
  最終的な認可（組織・案件・ロール）は上流に委ねる。

## 5. キルスイッチ（fail-closed）

| 環境変数 | 既定 | 意味 |
| --- | --- | --- |
| `MCP_ENABLED` | `1`（有効） | `0` で MCP サーバー全体を停止（`503`）。 |
| `MCP_TOOL_ALLOWLIST` | 空 | 空は登録済み全ツールを許可。設定時は列挙ツールのみ許可。未登録・非列挙ツールは拒否。 |

- 許可リスト未設定でも、未登録ツールは常に拒否する。
- 拒否は `tools/call` 応答の `isError=true` として返す（黙って通さない）。

## 6. 監査ログ

- `tools/call` ごとに `caller`（sub）・`tool`・`latency_ms`・`result`（result_code）・`http_status` を
  logger `ceos_mcp.audit` へ INFO で記録する。
- 応答本文（業務データ）は INFO では記録しない。
- result_code: `OK` / `SERVER_DISABLED` / `TOOL_NOT_FOUND` / `TOOL_NOT_ALLOWED` /
  `TOOL_ARGUMENT_INVALID` / `UPSTREAM_ERROR` / `UPSTREAM_UNAVAILABLE` / `INTERNAL_ERROR`。

## 7. 設定（環境変数）

| 変数 | 既定 |
| --- | --- |
| `HOST` / `PORT` | `0.0.0.0` / `8022` |
| `JWT_PUBLIC_KEY` / `JWT_ALGORITHM` | `development`/`test` 以外では必須 / `HS256` |
| `CONSTRUCTION_SERVICE_URL` | `http://localhost:8016` |
| `ERP_SERVICE_URL` | `http://localhost:8020` |
| `UPSTREAM_TIMEOUT_SECONDS` | `10.0` |
| `MCP_STATELESS` | `1` |

## 8. 実行と検証

```bash
cd services/mcp
pip install -r requirements.txt -r requirements-dev.txt

# lint / 型 / テスト
ruff check .
mypy src/
pytest tests/ -p no:flask

# 起動（開発）
uvicorn src.main:app --host 0.0.0.0 --port 8022
```

- 上流サービスが起動していない場合、実接続テスト（`tests/test_upstream_live.py`）は
  自動的にスキップされる（`live_upstream` マーカー）。
- ヘルスチェック: `GET /health`（認証不要。有効状態と登録ツール名のみを返す）。

## 9. 非対象（第2増分以降 / 別 ADR）

- 書き込み・承認・確定ツール（R2/R3/R4）
- OAuth 2.1 のフルフロー / 動的クライアント登録
- SBOM・成果物署名
- MCIP 側のツール登録・Tool Gateway 連携の実装
