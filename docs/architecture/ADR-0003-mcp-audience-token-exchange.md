# ADR-0003: MCP の audience 分離とトークン交換（RFC 8693）

- **状態**: Proposed（Approval PR：認証方式の変更）
- **日付**: 2026-09-23
- **対象リポジトリ**: Construction-Enterprise-OS（CEOS）
- **関連**: [ADR-0002: CEOS MCP サーバーの読み取り専用公開](./ADR-0002-ceos-mcp-readonly-publication.md)、
  Mirai-Harness-Core `registries/systems.yaml`（`ceos.audience = api://ceos-mcp`）

## 背景

Mirai-Harness-Core のシステム台帳は CEOS MCP の audience を `api://ceos-mcp` と定める。
一方、CEOS の現状は次のとおりで、audience による分離が成立していない。

| #   | 現状                                                             | 問題                                                           |
| --- | ---------------------------------------------------------------- | -------------------------------------------------------------- |
| 1   | auth が発行するアクセストークンに `aud` が無い（有効期限 60 分） | 同じトークンで MCP も全業務 API も呼べる                       |
| 2   | MCP は受け取ったトークンをそのまま construction / erp へ転送する | MCP 経由の呼び出しを上流で区別できない                         |
| 3   | 全サービスの検証は PyJWT で audience を指定していない            | `aud` 付きトークンは**全サービスで拒否**される（PyJWT の仕様） |

3 のため「MCP だけで `aud=api://ceos-mcp` を必須にする」と、現行トークンは 401 になり、
`aud` 付きトークンを発行しても上流への転送が失敗する。MCP 側の検査だけでは導入できない。

## 検討した選択肢

| 案  | 内容                                                   | 評価                                                                                                           |
| --- | ------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------- |
| A   | 上流サービスが `api://ceos-mcp` も受け入れる           | MCP 用トークンで業務 API を直接呼べてしまい、分離の意味が無い。**不採用**                                      |
| B   | 全トークンに `aud=[ceos-api, api://ceos-mcp]` を付ける | 全トークンがどこでも有効なままで、実質的な分離にならない。**不採用**                                           |
| C   | **トークン交換（RFC 8693）**                           | MCP 用トークンは MCP でのみ有効。上流用トークンは MCP がクライアント認証して交換した場合だけ得られる。**採用** |

## 決定

### 1. auth にトークン交換エンドポイントを追加する

`POST /api/v1/auth/token`（`application/x-www-form-urlencoded`、
`grant_type=urn:ietf:params:oauth:grant-type:token-exchange`）。応答・エラーは RFC 6749/8693 形式
（`Cache-Control: no-store`）。次の 2 方向のみを許可し、それ以外の `audience` は `invalid_target` で拒否する。

| 方向             | `audience`          | subject_token の条件                    | クライアント認証                                                         | 発行されるトークン                                             |
| ---------------- | ------------------- | --------------------------------------- | ------------------------------------------------------------------------ | -------------------------------------------------------------- |
| ① MCP 用の取得   | `api://ceos-mcp`    | `aud` 無しの通常ユーザートークン        | 不要（権限を狭めるだけのため）                                           | `aud=api://ceos-mcp`、既定 10 分                               |
| ② 上流用への交換 | `urn:ceos:upstream` | `aud=api://ceos-mcp` のユーザートークン | **必須**（`ApiClient`・active・スコープ `token-exchange:ceos-upstream`） | `aud` 無し（既存上流と互換）、`act.sub=<client_id>`、既定 5 分 |

共通の制約:

- subject_token は署名・有効期限・`iss`・`type=user` を検証する。`act` を持つトークン（交換済み）は再交換できない。
- 発行トークンの有効期限は **subject_token の有効期限を超えない**（交換による延命を防ぐ）。
- 成否を監査ログ（`auth.token.exchange`）に記録する。トークン本体・クライアント秘密は記録しない。
- キルスイッチ `TOKEN_EXCHANGE_ENABLED`（既定 **false**）。無効時は `unsupported_grant_type` を返す。
- **内部ネットワークからの利用に限定**する。gateway は `^/api/v1/auth` を auth へ転送するため、
  公開パスに入れないだけでは有効な JWT を持つ外部呼び出し元が到達できる。そこで gateway の
  `INTERNAL_ONLY_PATHS` で `/api/v1/auth/token` を認証の有無に関わらず 404 で遮断する。外部公開は別判断。

### 2. MCP は audience を検証し、上流呼び出しでトークンを交換する

| 受信トークン         | `MCP_REQUIRE_AUDIENCE=false`（既定）   | `MCP_REQUIRE_AUDIENCE=true` |
| -------------------- | -------------------------------------- | --------------------------- |
| `aud=api://ceos-mcp` | 受理 → ②で交換したトークンで上流を呼ぶ | 同左                        |
| `aud` 無し（従来）   | 受理 → 従来どおり転送                  | **401**                     |
| 別の `aud`           | **401**                                | **401**                     |

- ②の交換にはクライアント資格情報 `MCP_EXCHANGE_CLIENT_ID` / `MCP_EXCHANGE_CLIENT_SECRET`
  （Secrets で注入。ログ・応答に出さない）を使う。未設定で `aud` 付きトークンを受けた場合は、
  上流を呼ばずに拒否する（fail-closed）。
- 交換トークンはキャッシュしない（呼び出しごとに取得。有効期限が短く、キャッシュの失効管理を持ち込まないため）。

## 段階導入

| 段階                    | 内容                                                                                                                      | 判断者                           |
| ----------------------- | ------------------------------------------------------------------------------------------------------------------------- | -------------------------------- |
| Phase 0（本 ADR の PR） | コードを追加。`TOKEN_EXCHANGE_ENABLED=false` / `MCP_REQUIRE_AUDIENCE=false` のため**挙動は現状と同一**                    | Approval PR（Y/N）               |
| Phase 1                 | auth で交換を有効化。MCP 用 `ApiClient`（スコープ `token-exchange:ceos-upstream`）を登録し、資格情報を本番 Secrets に設定 | 人間（production secret の追加） |
| Phase 2                 | 呼び出し元（MCAH / MCIP Tool Gateway）が①で取得したトークンを使うことを確認後、`MCP_REQUIRE_AUDIENCE=true`                | 人間                             |
| Phase 3                 | Core Allowlist の `ceos.surfaces` に `mcah_production` を追加（Core への提案 PR）                                         | Core CODEOWNERS                  |

ロールバックはいずれもフラグを戻すだけでよい（DB migration なし）。

## 結果（Consequences）

- **正**: MCP 用トークンは他の全 CEOS サービスで無効になる（PyJWT が `aud` 付きトークンを拒否するため、
  既存サービスの改修が不要）。上流用トークンは MCP のクライアント認証なしに得られない。
  上流用トークンの有効期限は 60 分 → 5 分に短縮され、`act` で MCP 経由と識別できる。
- **負**: 呼び出しごとに auth への交換リクエストが 1 回増える（内部通信・数 ms 想定）。
  auth が停止すると MCP（`aud` 付きトークン）も停止する。
- **境界への影響**: ADR-0001 / ADR-0002 の責任境界は変えない。

## 未決・確認事項

- ①を外部（MCAH / MCIP）から呼ぶ経路（gateway 公開 or Tool Gateway 経由）と、呼び出し元の認証方式（OAuth 2.1 フルフロー）
- 上流サービス側で `act` を監査ログに記録するか
- アクセストークンの失効（現状はリフレッシュトークンのみ失効可能）
