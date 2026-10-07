# [🔒 QA-AIBoundary] 建設土木AI機能「AI入力境界」品質レビュー

- **担当**: teammate `qa-ai-boundary`（読み取り専用レビュアー）
- **作業ディレクトリ**: `/home/kensan/Projects/Mirai-Construction-DX/Construction-Enterprise-OS`
- **対象**: `services/ai/src/**`, `services/vision/src/**`, `services/mcp/src/**`, `contracts/mcp-tools/ceos.json`, 仕様書, 既存テスト
- **準拠**: `reports/quality-tests/CHARTER.md`（Q7「AI入力境界」を主軸、Q1/Q2 に跨る）
- **方法**: ソースコード・仕様書の**読解のみ**。実 HTTP・外部 Provider・MCP・本番DB・実サービスへの接続は**一切行っていない**。
- **実施日時**: 2026-10-07

## 0. 本レポートの限界（先に明示）

1. **テストを実行していない。** 担当の書き込み権限は `reports/quality-tests/qa-ai-boundary.md` の1ファイルのみであり、`pytest` 実行は `__pycache__` / `.pytest_cache` を `services/**` 配下に生成するため、CHARTER §1-1/§1-7 の「read のみ」制約を守る目的で**意図的に実行していない**。
   → CHARTER §4 が要求する「pytest 実出力（pass/fail/skip）」は**本レポートには無い**。実装は Lead へ引き継ぐ（§6）。
2. 本レポートに **pass / 成功 と記載した項目は無い**。確認できたのは**コード上の事実**のみである。
3. 別リポジトリ（MCAH / MCIP / Mirai-Harness-Core）側の実装は**未確認**であり、責務分界の最終判断はできない。該当箇所は「未確認」と明記する。
4. 規格・法令・契約条件の創作は行っていない。引用した仕様要求は本リポジトリ内の文書のみを根拠とする。

---

## 1. 調査項目ごとの結果

### 項目1. 外部 LLM/Provider 呼び出しの実装有無と、テスト時に外部へ出ないことの担保

**確認できた事実（根拠付き）**

| # | 事実 | 根拠 |
|---|---|---|
| 1-1 | 実 Provider は `httpx.AsyncClient` で `POST {base_url}/chat/completions` を実行する（ストリーミング含む） | `services/ai/src/services/llm_service.py:41-50, 64-68, 85-105` |
| 1-2 | 既定の接続先は `https://api.openai.com/v1`、鍵は `LLM_API_KEY` | `services/ai/src/config.py:26-29` |
| 1-3 | Embedding も実 HTTP（`POST {base_url}/embeddings`） | `services/ai/src/services/embedding_service.py:29-38, 54-62, 75-83` |
| 1-4 | Provider 選択は **`LLM_API_KEY` の真偽のみ**。未設定（既定 `""`）なら `MockLLMProvider` / `use_mock=True` | `services/ai/src/api/llm.py:23-29`, `services/ai/src/api/rag.py:28-38, 52, 98`, `services/ai/src/api/embeddings.py:35-36, 73` |
| 1-5 | AI テストの `conftest.py` には autouse fixture が無く、環境変数を強制していない | `services/ai/tests/conftest.py:1-18` |
| 1-6 | AI テストの `app` fixture は `get_db` のみ差し替える。ネット遮断（socket 禁止 / httpx transport 差し替え）は無い | `services/ai/tests/test_ai.py:77-97` |
| 1-7 | 既存の `/chat` テストは Mock 応答文字列を assert する。`LLM_API_KEY` が設定されていれば**実送信後に**失敗する（＝送信を防がない） | `services/ai/tests/test_ai.py:247-261` |
| 1-8 | Vision 側に外部 AI Provider 呼び出しは無い（OCR/画像解析は DB CRUD のみ。解析結果は空 dict で保存） | `services/vision/src/services/ocr_service.py`, `services/vision/src/services/image_analysis_service.py`, `services/vision/src/api/image_ai.py:37-44` |
| 1-9 | MCP テストは `httpx.MockTransport` で外部を遮断している（参考: 良い実装例） | `services/mcp/tests/test_audience_exchange.py:30-47, 179-183` |

**未確認**
- CI / ローカルで `LLM_API_KEY` が実際に未設定であること（`.env`・CI 変数定義を確認していない。リポジトリ内 grep では `LLM_API_KEY` の設定ファイルは見つからず）。
- `services/gateway` 経由の呼び出しに外部送信の追加経路があるか（ゲートウェイは対象外のため未精査）。

**欠陥候補**

| 重大度 | 症状 | 根拠 |
|---|---|---|
| **Medium** | テスト時の外部非到達が「環境変数が空であること」に依存しており、テストコード側で強制されていない。`LLM_API_KEY` が設定された環境では `/chat` `/chat/stream` `/complete` `/rag/generate` `/embeddings` が実 Provider へ送信する（テストは落ちるが、**送信は既に発生している**）。CHARTER §1-3「ネットワーク呼び出しを行うコードは mock で遮断する」に不適合。 | `services/ai/src/api/llm.py:23-29`, `services/ai/tests/conftest.py:1-18`, `services/ai/tests/test_ai.py:77-97, 247-261` |

---

### 項目2. 入力の機密区分・マスキング（PII/個人情報/機密）処理の有無と、生データがプロンプトへ入る経路

**確認できた事実（根拠付き）**

| # | 事実 | 根拠 |
|---|---|---|
| 2-1 | `services/ai/src`, `services/vision/src`, `services/mcp/src` に **mask / PII / redact / anonymize / 個人情報 / 機密 の実装は 0 件**（grep 一致は MCP のコメント1件のみ） | `services/mcp/src/tools/policy.py:48`（コメント）, 他は全 grep 一致なし |
| 2-2 | 機密区分フィールド自体が存在しない。AI の入力スキーマに `confidentiality` / `sensitivity` 相当の項目は無い | `services/ai/src/schemas/__init__.py:88-100, 109-114, 123-136, 153-168` |
| 2-3 | 生データ経路①: チャット本文が無加工で Provider へ渡る | `services/ai/src/api/llm.py:39`（`messages` 生成）→ `:71`（`llm.complete`） |
| 2-4 | 生データ経路②: DB の RAG チャンク本文が無加工で user プロンプトへ埋め込まれる | `services/ai/src/services/rag_service.py:22-29`（テンプレート）→ `:91-99` → `:101-106` |
| 2-5 | 生データ経路③: `/embeddings` の `content` が無加工で外部 embeddings API へ送られる | `services/ai/src/api/embeddings.py:39-49` → `services/ai/src/services/embedding_service.py:103-109, 75-83` |
| 2-6 | 生データ経路④: プロンプトテンプレート本文（`system_prompt` / `user_prompt_template`）が無加工で Provider へ渡る | `services/ai/src/api/llm.py:55, 170`, `services/ai/src/services/rag_service.py:76-77, 96-99` |
| 2-7 | Vision OCR は抽出原文をそのまま保存・返却する（`file_key`, `language` のみ受領。サニタイズ無し） | `services/vision/src/services/ocr_service.py:26-42`, `services/vision/src/api/ocr.py:34-50` |
| 2-8 | 仕様は Masking と機密区分別の送信制御を**要求している** | `docs/みらい建設土木DX・AI統合基盤 全体構成 V3.5.html:166`（Masking: 社外秘はここを通してから送信）, `:272`（社外秘：Maskingを通してから送信／**極秘：モデルに送信しない**）, `:443`（R4: **極秘文書のモデル送信**は禁止）, `:558-559` |
| 2-9 | 仕様上 Masking は MCAH の責務として図示されている。CEOS の AI は独立サービスとして `/api/v1/ai`（port 8005）に直接公開される | `docs/みらい建設土木DX・AI統合基盤 全体構成 V3.5.html:163-166, 430, 523`, `docs/api/overview.md:16, 61-63` |

**未確認**
- CEOS の AI API が本番で MCAH を経由せずに直接呼ばれうるか（呼び出し元の構成が別リポジトリのため未確認）。
- 文書取込（`services/document`, Data Ingestion）側で機密区分を付与しているか（本担当の対象外）。

**欠陥候補**

| 重大度 | 症状 | 根拠 |
|---|---|---|
| **High** | 機密区分・マスキングが AI/Vision に一切実装されていない。仕様が「モデルに送信しない」と定める**極秘**文書であっても、チャット本文・RAG チャンク・埋め込み投入・プロンプトテンプレートの4経路で外部モデルへ送信できる。仕様不適合（CHARTER §1-5「テストを通すために仕様を曲げない」の逆方向＝実装が仕様に未達）。 | `services/ai/src/api/llm.py:39, 71`, `services/ai/src/services/rag_service.py:22-29, 101-106`, `services/ai/src/api/embeddings.py:39-49`, `docs/みらい建設土木DX・AI統合基盤 全体構成 V3.5.html:166, 272, 443` |

---

### 項目3. RAG の引用・根拠提示と、根拠なし生成の扱い

**確認できた事実（根拠付き）**

| # | 事実 | 根拠 |
|---|---|---|
| 3-1 | 既定 system prompt は「参照情報に無い内容は『わかりません』」「どの部分に基づいたか明示」と**指示**している | `services/ai/src/services/rag_service.py:17-20` |
| 3-2 | 既定 user テンプレートは `[出典 {{ loop.index }}] {{ chunk.content }}` を `質問:` の**前に**素の形で埋め込む | `services/ai/src/services/rag_service.py:22-29` |
| 3-3 | 生成は `llm_provider.complete(...)` の戻り値を**そのまま**返す。引用の有無・妥当性を検証しない | `services/ai/src/services/rag_service.py:101-108` |
| 3-4 | `sources` は「検索で取得したチャンク」そのもの。回答がどの出典を用いたかは追跡していない | `services/ai/src/services/rag_service.py:108`, `services/ai/src/api/rag.py:124-135` |
| 3-5 | **検索結果が 0 件でも生成する。** 空リストのまま `generate_with_context` を呼び、`success: true` / `answer` を返す（`sources: []`）。拒否・警告・`grounded` フラグの分岐は無い | `services/ai/src/api/rag.py:101-119, 137-143`, `services/ai/src/services/rag_service.py:84-108` |
| 3-6 | チャンク本文の区切り・エスケープ・無害化は無い（プロンプトインジェクションの受け皿。項目5 参照） | `services/ai/src/services/rag_service.py:22-29, 92-94` |

**未確認**
- フロントエンドが `sources: []` を「根拠なし」として警告表示するか（`apps/web/src/lib/api/ai.ts:18-27` に `RagResult.sources` はあるが、UI の分岐は未精査）。
- 仕様書に「根拠なし生成を拒否せよ」という明文要求があるか（V3.5 には RAG の根拠提示に関する明文を見出せなかった → **未確認**。したがって本項は仕様違反ではなく**品質リスク**として報告する）。

**欠陥候補**

| 重大度 | 症状 | 根拠 |
|---|---|---|
| **High** | 根拠ゼロでも回答を生成して `success: true` で返す。API 利用側が `sources` の空を自ら確認しない限り、根拠のない回答を「通常の回答」として扱ってしまう。建設業務では法令・基準・数量の判断に流用されうる。 | `services/ai/src/api/rag.py:101-119, 137-143` |
| **Medium** | 回答中の引用番号（`[出典 n]`）と `sources` 配列の整合を検証していない。LLM が実在しない出典番号を書いても検知できない。 | `services/ai/src/services/rag_service.py:101-108`, `services/ai/src/api/rag.py:124-135` |

---

### 項目4. 人間確認の強制 — AI 出力が確定処理に直結できるか

**確認できた事実（根拠付き）**

| # | 事実 | 根拠 |
|---|---|---|
| 4-1 | AI サービスのルーターは health / llm / embeddings / rag / prompts / ocr / models のみ。**承認・数量確定・設計適合判定・出来高確定のエンドポイントは存在しない** | `services/ai/src/main.py:68-74` |
| 4-2 | Vision のルーターは ocr / image_ai / vectors / health のみ | `services/vision/src/main.py:63-66` |
| 4-3 | WebUI の AI 画面 7 ページに `approve` / `submit` / `finalize` への接続は無い（一致1件は表示文言「竣工検査日程の早期確定を推奨」） | `apps/web/src/app/(dashboard)/ai/construction/page.tsx:99`, 他6ページは該当なし |
| 4-4 | 一方で「候補提示のみ」を**コードで強制する仕組みも無い**。応答は任意文字列（`content: str` / `answer: str`）で、`requires_human_approval` 等のフラグやスキーマ制約が無い | `services/ai/src/schemas/__init__.py:103-120, 171-174` |
| 4-5 | MCP は R2/R3/R4 を公開しない（型・検証の両面で拒否） | `services/mcp/src/tools/models.py:17-29`, `services/mcp/src/tools/registry.py:96-117`, `docs/architecture/ADR-0002-ceos-mcp-readonly-publication.md:22-23` |
| 4-6 | 仕様: 重要判断は R0〜R4 と Human-in-the-Loop で管理。**R4 = AI単独では実行しない**（出来形・数量・積算・契約・出来高の最終確定、根拠のない法令・基準判定、画像のみの最終品質判定、極秘文書のモデル送信） | `docs/みらい建設土木DX・AI統合基盤 全体構成 V3.5.html:97, 443` |
| 4-7 | 仕様: R4 は Policy Engine が常に拒否し Tool Allowlist に登録しない。承認結果の正本は MCIP 側 | `docs/みらい建設土木DX・AI統合基盤 全体構成 V3.5.html:443, 333, 388` |
| 4-8 | 仕様: 「AI回答記録」は MCIP が追記専用で保持し、削除不可（J-SOX / ISO 27001 の証跡） | `docs/みらい建設土木DX・AI統合基盤 全体構成 V3.5.html:149, 318` |
| 4-9 | **CEOS の AI サービスには AI 回答の永続記録・監査ログが無い。** `Message` モデルは定義されているが、監査目的の追記専用記録として使われていない | `services/ai/src/api/llm.py:76-83, 189-196`（応答のみ返す）, `services/ai/src/models/__init__.py:118-121`（`Message` 定義） |

**未確認**
- MCAH / MCIP 側で R4 拒否と HITL が実際に実装されているか（**別リポジトリのため未確認**）。
- CEOS の AI API が MCAH を経由せずに直接呼ばれた場合、上記 Policy Engine の統制が及ぶか（構成上、`/api/v1/ai` は Gateway 直下に公開されており、MCAH を必須とする強制は CEOS 側コードには見当たらない）。

**欠陥候補**

| 重大度 | 症状 | 根拠 |
|---|---|---|
| **Info（未確認）** | CEOS の AI API 自体は確定操作を露出しておらず、現状のコードに「AI 出力→確定」の直結経路は**存在しない**。ただしそれは「候補提示のみに制限されている」からではなく、**単に接続が未実装**だからである。防護（候補専用スキーマ・人間承認必須フラグ）が無いため、将来接続時に R4 制約を破る余地が残る。MCAH 側の統制実装は未確認。 | `services/ai/src/main.py:68-74`, `services/ai/src/schemas/__init__.py:171-174`, `docs/みらい建設土木DX・AI統合基盤 全体構成 V3.5.html:443` |
| **Medium** | 仕様が要求する「AI回答記録」の追記専用永続化が CEOS の AI サービスに無い。AI 応答が呼び出し元に返るだけで、後から「いつ・誰が・どのモデルに・何を問い、何が返ったか」を検証できない（証跡欠落の予備軍）。 | `services/ai/src/api/llm.py:76-83, 189-196`, `docs/みらい建設土木DX・AI統合基盤 全体構成 V3.5.html:149, 318` |

---

### 項目5. プロンプトインジェクション対策

**確認できた事実（根拠付き）**

| # | 事実 | 根拠 |
|---|---|---|
| 5-1 | **間接インジェクション経路**: OCR 原文 → 埋め込み登録 → ベクトル検索 → RAG プロンプトへ素のまま挿入、が成立する。途中に無害化・区切り・指示無効化が一切無い | `services/vision/src/api/ocr.py:41` → `services/ai/src/api/embeddings.py:44` → `services/ai/src/services/embedding_service.py:118` → `:145-163` → `services/ai/src/services/rag_service.py:22-29, 92-94` |
| 5-2 | 既定 system prompt は参照情報を**信頼する前提**で書かれており、参照情報内の指示に従わない旨の防御文が無い | `services/ai/src/services/rag_service.py:17-20` |
| 5-3 | チャンク本文は「質問」より**前**に配置されるため、後置の指示より優先されうる位置関係になっている | `services/ai/src/services/rag_service.py:22-29` |
| 5-4 | **テンプレートインジェクション（別種）**: `jinja2.Template(...)` を**非サンドボックス**で使用。テンプレート本文は DB 由来 | `services/ai/src/api/llm.py:48-53, 102-107, 163-167`, `services/ai/src/services/rag_service.py:91-94` |
| 5-5 | テンプレート本文は `POST/PUT /api/v1/ai/prompts` で**任意文字列**として保存できる（`system_prompt: str`, `user_prompt_template: str` に長さ・内容制約なし） | `services/ai/src/api/prompts.py:24-40, 103-128`, `services/ai/src/schemas/__init__.py:45-46, 56-57` |
| 5-6 | テンプレート CRUD の認可は `get_current_user` のみ。**ロール/スコープ要求が無い**（任意の認証済みユーザーが作成・更新・削除可能） | `services/ai/src/api/prompts.py:27, 49, 84, 107, 134` |
| 5-7 | MCP のツール説明文は固定ハッシュでピン留めされ、改変するとレジストリのロードが失敗する（fail-closed）。説明文汚染は検知可能 | `services/mcp/src/tools/registry.py:126-147`, `services/mcp/src/tools/definitions.py:28-47` |
| 5-8 | 既存テストにプロンプトインジェクション / SSTI の検証は無い | `services/ai/tests/test_ai.py` 全 500 行, `services/vision/tests/test_vision.py` 全 608 行 に該当テストなし |

**未確認**
- 外部モデル側（OpenAI/Anthropic）のプロンプト防御に依存する設計方針なのか（仕様書に明文を見出せず → **未確認**）。
- MCP 経由で AI に文書を取り込む経路の有無（現行 MCP 5 ツールはすべて読み取りで、AI への投入経路は無い）。

**欠陥候補**

| 重大度 | 症状 | 根拠 |
|---|---|---|
| **Critical** | **プロンプトテンプレート経由の任意コード実行（SSTI）。** 認証済みユーザーが `POST /api/v1/ai/prompts` で `{{ ''.__class__.__mro__[1].__subclasses__() }}` 等の Jinja2 式を含むテンプレートを保存し、`POST /api/v1/ai/complete`（または `/chat`, `/rag/generate`）を呼ぶと、非サンドボックスの `jinja2.Template` がそれを評価する。AI サービスプロセス内の任意式評価に到達しうる。CHARTER §5 の Critical 定義（テナント越境・認証回避）には厳密には該当しないが、**任意コード実行＝権限昇格を超える**ため同等以上として扱う。 | `services/ai/src/api/prompts.py:24-40`（制約なし）, `services/ai/src/schemas/__init__.py:45-46`（制約なし）, `services/ai/src/api/llm.py:48-53, 163-167`（非サンドボックス render） |
| **High** | 間接プロンプトインジェクション（文書/OCR 経由）に対する無害化が無い。悪意ある文書を投入 → 検索ヒット → プロンプト内の指示が上書きされうる。RAG の回答は「根拠に基づく」体裁で返るため、利用者が注入を検知しにくい。 | `services/ai/src/services/rag_service.py:22-29, 92-94, 101-106` |
| **Medium** | プロンプトテンプレートの作成・更新が任意の認証ユーザーに開放されている（最小権限の原則に反する）。SSTI の到達可能性を広げる要因。 | `services/ai/src/api/prompts.py:27, 49, 84, 107, 134` |

---

### 項目6. 認証・テナント境界

**確認できた事実（根拠付き）**

| # | 事実 | 根拠 |
|---|---|---|
| 6-1 | AI: org はトークンの `org` クレーム由来。ただし**欠落時は `UUID(int=0)`（全ゼロUUID）へフォールバック**する。org を持たないトークンは全て同一テナントに集約される | `services/ai/src/api/llm.py:43, 97, 150`, `services/ai/src/api/rag.py:47, 93`, `services/ai/src/api/embeddings.py:32, 69`, `services/ai/src/api/prompts.py:30, 52, 87, 110, 137` |
| 6-2 | 既存テストの `_auth_headers` は**常に `org` を付与**するため、上記フォールバックは未検証 | `services/ai/tests/test_ai.py:105-121` |
| 6-3 | AI: `DELETE /api/v1/ai/embeddings/{source_type}/{source_id}` は **org を一切考慮しない**。サービス層の DELETE も `source_type` と `source_id` のみで絞る | `services/ai/src/api/embeddings.py:107-120`（`org_id` を計算していない）, `services/ai/src/services/embedding_service.py:179-190` |
| 6-4 | AI: RAG のプロンプトテンプレート取得が **org 非スコープ**。`generate_with_context` には `organization_id` 引数自体が存在しない | `services/ai/src/services/rag_service.py:71-80`（`select` に org 条件なし）, `:61-70`（シグネチャ）, `services/ai/src/api/rag.py:111-119`（org を渡していない） |
| 6-5 | AI: 一方 `/chat` `/complete` `/prompts/*` は `PromptService.get_template(db, id, org_id)` を通り org スコープされる | `services/ai/src/api/llm.py:44-46, 151`, `services/ai/src/services/prompt_service.py:143-154` |
| 6-6 | AI: ベクトル検索は `organization_id` が渡れば `AND organization_id = :org_id` を付ける（渡されない場合は全件） | `services/ai/src/services/embedding_service.py:154-159` |
| 6-7 | AI / Vision の `decode_token` は `aud` / `iss` を検証しない（AI は `verify_exp` を明示） | `services/ai/src/middleware/auth.py:27-32`, `services/vision/src/middleware/auth.py:33-48` |
| 6-8 | 仕様がこの欠落を認識している: 「全サービスの検証は PyJWT で audience を指定していない」「auth が発行するアクセストークンに `aud` が無い（同じトークンで MCP も全業務 API も呼べる）」 | `docs/architecture/ADR-0003-mcp-audience-token-exchange.md:14-18` |
| 6-9 | Vision: `organization_id` が**リクエストボディ由来**（`OCRProcessRequest`, `ImageAnalyzeRequest`, `VectorIndexCreate` で必須フィールド） | `services/vision/src/schemas/__init__.py:20-24, 55-58, 78-83`, `services/vision/src/api/ocr.py:59-67`, `services/vision/src/api/image_ai.py:37-44`, `services/vision/src/api/vectors.py:43-50` |
| 6-10 | Vision: 一覧取得は `organization_id` が**任意のクエリ引数**で、未指定なら絞り込みなし（全テナント） | `services/vision/src/api/ocr.py:71-89`, `services/vision/src/api/image_ai.py:48-66`, `services/vision/src/api/vectors.py:54-70`; サービス層 `services/vision/src/services/ocr_service.py:53-60`, `image_analysis_service.py:45-52`, `vector_service.py:38-43`（いずれも `if organization_id:`） |
| 6-11 | Vision: 単体取得・更新・削除は **org 条件なし**。ID を知っていれば他テナントの資源を取得・更新・削除できる | `services/vision/src/api/ocr.py:92-104`, `image_ai.py:69-81`, `vectors.py:73-118`; `ocr_service.py:65-68`, `image_analysis_service.py:57-62`, `vector_service.py:48-53, 76-80` |
| 6-12 | Vision: `GET /vision/ocr/tasks` は org 引数すら取らず、全テナントの OCR 結果を返す | `services/vision/src/api/ocr.py:107-133` |
| 6-13 | MCP: Bearer 必須・`type=user` 必須（401/403）で fail-closed。キルスイッチ `MCP_ENABLED` も 503 で強制 | `services/mcp/src/middleware/mcp_guard.py:46-111`, `services/mcp/src/tools/policy.py:20-41` |
| 6-14 | MCP: `MCP_REQUIRE_AUDIENCE=False` が既定。`aud` 無しトークンも受理する（ADR-0003 の Phase 設計どおり） | `services/mcp/src/config.py:43-44`, `docs/architecture/ADR-0003-mcp-audience-token-exchange.md:41-42, 56-59` |
| 6-15 | MCP: 上流へは呼び出し元の Authorization をそのまま転送し、**上流側の認可に委ねる**設計 | `services/mcp/src/services/upstream.py:1-5, 53-55` |
| 6-16 | MCP: 引数はスキーマ検証後、パス埋め込みは `quote(..., safe="")`、それ以外はクエリへ回される | `services/mcp/src/tools/executor.py:52-78, 106-118` |
| 6-17 | **上流 ERP が org 認可をしていない**: `GET /api/v1/erp/invoices` は `organization_id` を**クエリ引数**で受け、トークンは `_user` として**未使用** | `services/erp/src/api/invoices.py:36-52`（`:37` クエリ, `:51` `_user`） |
| 6-18 | **上流 ERP の絞り込みは任意**: `organization_id` 未指定なら `WHERE` 句が付かず**全テナント**を返す | `services/erp/src/services/invoice_service.py:40-55` |
| 6-19 | MCP `ceos.contract.list` は `organization_id` を**入力引数として公開**し、上流のクエリへそのまま渡る | `contracts/mcp-tools/ceos.json:5-55`（`:11-15`）, `services/mcp/src/tools/definitions.py:168-219`（`:178-182`） |
| 6-20 | MCP `ceos.ledger.get_summary` は引数なしで「**全社の**工事台帳 財務サマリー」を返す | `services/mcp/src/tools/definitions.py:149-167`（`:153`）, `contracts/mcp-tools/ceos.json:102-121` |

**未確認**
- `ceos.cost.list` の上流 `GET /api/v1/erp/ledger/{ledger_id}/costs` が `ledger_id` のテナント帰属を検証するか（**未確認**。ERP の当該ハンドラを精読していない）。
- `ceos.wbs.get_tree` / `ceos.schedule.get_gantt` の上流 `services/construction` が `project_id` のテナント帰属を検証するか（**未確認**）。
- `ceos.ledger.get_summary` の上流 `GET /api/v1/erp/ledger/summary` がトークン org で絞るか（**未確認**）。
- Gateway 層で `/api/v1/erp` に対する org 強制が行われているか（**未確認**。ゲートウェイは本担当の対象外）。

**欠陥候補**

| 重大度 | 症状 | 根拠 |
|---|---|---|
| **Critical** | **MCP / ERP 経由のテナント越境読み取り。** `ceos.contract.list` を `organization_id` **省略**で呼ぶと上流が WHERE 句を付けず**全テナントの契約・請求**を返す。`organization_id=<他テナント>` を指定すればそのテナントの請求を取得できる。MCP は「上流の認可に委ねる」設計だが、上流が認可していないため境界が成立していない。 | `contracts/mcp-tools/ceos.json:11-15`, `services/mcp/src/tools/definitions.py:178-182`, `services/mcp/src/tools/executor.py:106-118`, `services/mcp/src/services/upstream.py:1-5`, `services/erp/src/api/invoices.py:36-52`, `services/erp/src/services/invoice_service.py:40-55` |
| **Critical** | **AI: 埋め込みのテナント越境削除。** `DELETE /api/v1/ai/embeddings/{source_type}/{source_id}` は org を考慮せず削除する。source_id を知る他テナントのユーザーが、対象テナントの RAG インデックスを破壊できる（データ破壊）。 | `services/ai/src/api/embeddings.py:107-120`, `services/ai/src/services/embedding_service.py:179-190` |
| **Critical** | **Vision: 書き込み先テナントのボディ上書き。** `POST /api/v1/vision/ocr/process`・`/vision/analyze`・`/vectors/indices` は `body.organization_id` をそのまま保存先に使う。トークン org との一致検証が無い。 | `services/vision/src/schemas/__init__.py:21, 56, 79`, `services/vision/src/api/ocr.py:61`, `services/vision/src/api/image_ai.py:39`, `services/vision/src/api/vectors.py:45` |
| **Critical** | **Vision: 全テナント読み取り。** 一覧は `organization_id` 省略で全件、単体取得は org 条件なし。OCR 原文（請求書・契約書・仕様書の本文＝個人情報・機密を含みうる）を他テナントが取得できる。 | `services/vision/src/api/ocr.py:71-104, 107-133`, `services/vision/src/services/ocr_service.py:45-68` |
| **High** | **AI: RAG のプロンプトテンプレート越境参照。** `prompt_template_id` に他テナントの ID を指定すると、その `system_prompt` が使われ、`PromptTemplateResponse` 相当のフィールドが RAG 生成に流用される。org 条件が SQL に無い。 | `services/ai/src/services/rag_service.py:61-80`, `services/ai/src/api/rag.py:111-119` |
| **High** | **AI: org クレーム欠落時の全ゼロUUID 集約。** org を持たない（またはクレーム欠落の）トークンが全員 `UUID(int=0)` の同一テナントを共有し、互いのプロンプトテンプレートと埋め込みを読み書きできる。 | `services/ai/src/api/llm.py:43, 97, 150`, `services/ai/src/api/prompts.py:30` |
| **Medium** | **AI / Vision が `aud` / `iss` を検証しない。** audience 分離が未成立のため、MCP 用トークンと業務API用トークンが相互に使える（ADR-0003 が明示的に認識済み・Phase 導入待ち）。 | `services/ai/src/middleware/auth.py:27-32`, `services/vision/src/middleware/auth.py:33-48`, `docs/architecture/ADR-0003-mcp-audience-token-exchange.md:14-18` |
| **Medium** | MCP `ceos.ledger.get_summary` が「全社」サマリーを引数なしで公開する。組織を跨いだ財務情報（売上・原価・利益）が単一の読み取りツールで取得できる。org スコープの要否は仕様未確認だが、少なくとも越境防止の明示的手段が無い。 | `services/mcp/src/tools/definitions.py:149-167` |

---

### 項目7. 入力サイズ・ファイル種別・レート制限

**確認できた事実（根拠付き）**

| # | 事実 | 根拠 |
|---|---|---|
| 7-1 | `ChatMessage.content` に長さ上限なし。`ChatRequest.messages` に要素数上限なし | `services/ai/src/schemas/__init__.py:88-94` |
| 7-2 | `EmbeddingRequest.content` に長さ上限なし | `services/ai/src/schemas/__init__.py:123-129` |
| 7-3 | RAG の `query` は `min_length=1` のみで上限なし（`RAGSearchRequest`, `RAGGenerateRequest`） | `services/ai/src/schemas/__init__.py:153-168` |
| 7-4 | 上限が定義されているのは `chunk_size`(100-2000) / `chunk_overlap`(0-500) / `top_k`(1-100, 1-20) / `max_tokens`(1-32000) / `temperature`(0-2) のみ | `services/ai/src/schemas/__init__.py:98-99, 113-114, 128-129, 134, 155, 162, 167-168` |
| 7-5 | Vision の `file_key` は `max_length=1000`、`language` は `max_length=10`、`extracted_text` は API 入力に無い | `services/vision/src/schemas/__init__.py:20-24, 55-58` |
| 7-6 | **ファイルアップロードは未実装。** `services/ai`, `services/vision` に `UploadFile` / `File(` は 0 件。Vision OCR は `file_key`（文字列）を保存するだけ | grep 一致 0 件, `services/vision/src/api/ocr.py:53-68` |
| 7-7 | **レート制限は未実装。** `services/ai/src`, `services/vision/src` に rate-limit / slowapi / limiter / throttle の実装は 0 件 | grep 一致 0 件 |
| 7-8 | AI / Vision のアプリは CORS ミドルウェアのみを追加し、レート制限やボディサイズ制限を追加しない | `services/ai/src/main.py:60-66`, `services/vision/src/main.py:55-61` |
| 7-9 | Vision のベクトル検索・索引登録は**実体のないスタブ**（検索は固定 mock を返し、索引登録は件数カウンタを増やすだけ） | `services/vision/src/services/vector_service.py:95-107`, `services/vision/src/api/vectors.py:138-179` |

**未確認**
- Gateway / 逆プロキシ層でのボディサイズ上限・レート制限の有無（**未確認**。`services/gateway` は本担当の対象外）。
- 本番構成（Cloudflare）側の WAF / Rate Limiting ルール（**未確認**）。

**欠陥候補**

| 重大度 | 症状 | 根拠 |
|---|---|---|
| **Medium** | 入力サイズが無制限のまま外部 Provider へ転送される。巨大な `content` / `messages` / `query` により、外部 API コスト増、タイムアウト、メモリ圧迫（DoS）が成立しうる。CHARTER §Q8「境界値」の観点で未整備。 | `services/ai/src/schemas/__init__.py:88-94, 123-129, 153-168` |
| **Medium** | AI / Vision サービス内にレート制限が無い。認証済みユーザーが無制限に外部 LLM 呼び出しを誘発できる（コスト・可用性）。 | `services/ai/src/main.py:60-66`, `services/vision/src/main.py:55-61`, grep 一致 0 件 |
| **Low** | Vision のベクトル検索が固定 mock を返すため、`/vectors/search` が実データを返していると誤認されうる（表示・UX の不整合）。 | `services/vision/src/services/vector_service.py:95-107` |

---

### 項目8. MCP ツール定義が読み取り専用に限定されているか

**確認できた事実（根拠付き）**

| # | 事実 | 根拠 |
|---|---|---|
| 8-1 | 公開ツールは **5 件のみ**、すべて `effect="read"`, `tier="R0"`, `upstream_method="GET"` | `services/mcp/src/tools/definitions.py:50-219` |
| 8-2 | レジストリが `write/propose/approve/finalize/delete/pay/external_send` を**明示的に拒否** | `services/mcp/src/tools/models.py:27-29`, `services/mcp/src/tools/registry.py:96-102` |
| 8-3 | `R0` 以外の tier を拒否 | `services/mcp/src/tools/registry.py:107-111` |
| 8-4 | GET 以外の method を拒否 | `services/mcp/src/tools/registry.py:113-117` |
| 8-5 | `readOnlyHint` と `effect` の矛盾を拒否 | `services/mcp/src/tools/registry.py:126-129` |
| 8-6 | 定義ハッシュ（`definition_sha256` / `binding_sha256`）を固定。欠落・不一致でロード失敗（fail-closed） | `services/mcp/src/tools/registry.py:131-147`, `services/mcp/src/tools/definitions.py:28-47` |
| 8-7 | 契約 JSON（`contracts/mcp-tools/ceos.json`）とレジストリのドリフトを CI で検査。5 ツールすべて `readOnlyHint: true`, `x-mirai.effect: "read"`, `tier: "R0"` | `contracts/mcp-tools/ceos.json:45-54, 91-100, 111-120, 140-149, 169-178`, `docs/architecture/ADR-0002-ceos-mcp-readonly-publication.md:41-58`, `services/mcp/tests/test_contract_export.py` |
| 8-8 | キルスイッチとツール許可リストが fail-closed で強制される | `services/mcp/src/tools/policy.py:20-41`, `services/mcp/src/middleware/mcp_guard.py:46-60` |
| 8-9 | `tools/list` は無効時に空配列を返す（存在秘匿） | `services/mcp/src/api/mcp.py:81-89` |
| 8-10 | 監査ログに `caller`(sub) / `tool` / `latency` / `result` / `http_status` を記録し、**トークン本文・業務データは記録しない** | `services/mcp/src/api/mcp.py:114-124`（`:127` のコメント含む） |
| 8-11 | 未定義引数を拒否（`additionalProperties: false`）し、`per_page` は最大100で検証 | `services/mcp/src/tools/executor.py:64-68, 96-102` |

**未確認**
- Core Allowlist（`registries/mcp-allowlist.yaml`）に登録されたハッシュが現行定義と一致するか（CI 検査の実効性は実行していないため**未確認**）。

**欠陥候補**

| 重大度 | 症状 | 根拠 |
|---|---|---|
| — | **本項目は仕様どおり実装されている。** 書き込み・承認・確定操作の露出は無く、型・検証・ハッシュ固定・キルスイッチの多層で fail-closed が成立している。欠陥は検出しなかった。 | `services/mcp/src/tools/registry.py:92-147`, `services/mcp/src/tools/policy.py:20-41` |
| （項目6 へ） | ただし**引数経由の越境**（`organization_id` / `ledger_id` / `project_id` のテナント帰属検証が上流に無い）は項目6 の Critical として残る。読み取り専用であることは「越境しないこと」を意味しない。 | `services/mcp/src/tools/definitions.py:178-182`, `services/erp/src/services/invoice_service.py:40-55` |

---

## 2. 欠陥サマリ（重大度順）

| # | 重大度 | 症状（要約） | 主な根拠 |
|---|---|---|---|
| D1 | **Critical** | プロンプトテンプレートの Jinja2 非サンドボックス render による SSTI（任意コード実行）。任意の認証ユーザーが作成可能 | `services/ai/src/api/prompts.py:24-40`, `services/ai/src/api/llm.py:48-53, 163-167` |
| D2 | **Critical** | MCP / ERP 経由のテナント越境読み取り（`ceos.contract.list` の `organization_id` が未検証・省略時は全件） | `contracts/mcp-tools/ceos.json:11-15`, `services/erp/src/services/invoice_service.py:40-55` |
| D3 | **Critical** | AI: 埋め込みのテナント越境削除（DELETE に org 条件なし） | `services/ai/src/api/embeddings.py:107-120`, `services/ai/src/services/embedding_service.py:179-190` |
| D4 | **Critical** | Vision: 書き込み先 `organization_id` のボディ上書き | `services/vision/src/api/ocr.py:61`, `image_ai.py:39`, `vectors.py:45` |
| D5 | **Critical** | Vision: 全テナント読み取り（一覧は org 未指定で全件、単体取得は org 条件なし、`/vision/ocr/tasks` は org 引数なし） | `services/vision/src/api/ocr.py:71-133`, `services/vision/src/services/ocr_service.py:45-68` |
| D6 | **High** | AI: RAG のプロンプトテンプレート越境参照（SQL に org 条件なし） | `services/ai/src/services/rag_service.py:61-80` |
| D7 | **High** | AI: org クレーム欠落トークンが `UUID(int=0)` に集約 | `services/ai/src/api/llm.py:43, 97, 150` |
| D8 | **High** | 機密区分・マスキングが皆無。仕様が「モデルに送信しない」とする極秘文書が4経路で外部送信可能 | `services/ai/src/api/llm.py:39, 71`, `docs/みらい建設土木DX・AI統合基盤 全体構成 V3.5.html:166, 272, 443` |
| D9 | **High** | RAG が根拠ゼロでも回答を生成し `success: true` で返す | `services/ai/src/api/rag.py:101-119, 137-143` |
| D10 | **High** | 間接プロンプトインジェクション（OCR/文書 → RAG プロンプト）に無害化なし | `services/ai/src/services/rag_service.py:22-29, 92-94` |
| D11 | **Medium** | テスト時の外部非到達が環境変数依存（テスト側で強制していない） | `services/ai/tests/conftest.py:1-18`, `services/ai/src/api/llm.py:23-29` |
| D12 | **Medium** | 引用番号と `sources` の整合検証なし | `services/ai/src/services/rag_service.py:101-108` |
| D13 | **Medium** | AI 回答の追記専用永続記録（仕様の「AI回答記録」）が無い | `services/ai/src/api/llm.py:76-83, 189-196`, `docs/...V3.5.html:149, 318` |
| D14 | **Medium** | 入力サイズ上限なし（`content` / `messages` / `query`） | `services/ai/src/schemas/__init__.py:88-94, 123-129, 153-168` |
| D15 | **Medium** | レート制限なし | `services/ai/src/main.py:60-66`, `services/vision/src/main.py:55-61` |
| D16 | **Medium** | `aud` / `iss` 未検証（ADR-0003 で認識済み・Phase 待ち） | `services/ai/src/middleware/auth.py:27-32`, `services/vision/src/middleware/auth.py:33-48` |
| D17 | **Medium** | プロンプトテンプレート CRUD にロール要求なし | `services/ai/src/api/prompts.py:27, 49, 84, 107, 134` |
| D18 | **Medium** | `ceos.ledger.get_summary` が引数なしで全社財務サマリーを公開 | `services/mcp/src/tools/definitions.py:149-167` |
| D19 | **Low** | Vision のベクトル検索が固定 mock を返す | `services/vision/src/services/vector_service.py:95-107` |
| — | **Info（未確認）** | 項目4: AI 出力→確定処理の直結経路は現状なし。ただし防護機構も無く、MCAH 側の R4 強制は未確認 | `services/ai/src/main.py:68-74`, `docs/...V3.5.html:443` |

---

## 3. 追加テストとして書くべきシナリオ案（10 件）

各 1 行。テストファイル配置案付き。**担当は `services/**` に書けないため、実装は Lead へ引き継ぐ。**

1. **外部送信ゼロの強制** — `LLM_API_KEY` にダミー値を設定した状態で `/chat` `/complete` `/rag/generate` `/embeddings` を呼び、httpx transport 差し替えにより**外部 HTTP リクエストが 0 件**であることを assert する（`get_settings.cache_clear()` を併用）／`services/ai/tests/test_ai_input_boundary.py`
2. **入力サイズ上限の回帰** — `ChatMessage.content` / `EmbeddingRequest.content` / `RAGGenerateRequest.query` に上限超過入力を与え 422 を要求する（現状は素通りするため failing test として起票。無制限を合格扱いしない）／`services/ai/tests/test_ai_input_boundary.py`
3. **根拠ゼロ時の RAG 生成抑止** — 検索結果 0 件で `/rag/generate` を呼び、回答を返さない（または `grounded: false` を返す）ことを要求する／`services/ai/tests/test_ai_input_boundary.py`
4. **引用整合（citation integrity）** — 回答中の `[出典 n]` が `sources` の要素数を超えないことを検証する／`services/ai/tests/test_ai_input_boundary.py`
5. **テンプレートの Jinja2 危険式が評価されない** — `{{ ''.__class__.__mro__ }}` を含むテンプレートを保存して `/complete` を呼び、評価されず 400/422 になること（`SandboxedEnvironment` 化の回帰）／`services/ai/tests/test_ai_prompt_security.py`
6. **プロンプト CRUD の権限制限** — ロール不足トークンで `POST/PUT/DELETE /api/v1/ai/prompts` が 403 になることを要求する／`services/ai/tests/test_ai_prompt_security.py`
7. **org クレーム欠落の拒否** — `org` を含まないトークンで `/chat` `/rag/generate` `/embeddings` を呼び 403 になること（`UUID(int=0)` フォールバック禁止）／`services/ai/tests/test_ai_tenant_boundary.py`
8. **埋め込み削除のテナント分離** — `DELETE /api/v1/ai/embeddings/{source_type}/{source_id}` が他テナントの行を削除しないこと（DELETE 文に org 条件が入ることをキャプチャして assert）／`services/ai/tests/test_ai_tenant_boundary.py`
9. **他テナントの prompt_template_id 拒否** — `/complete` と `/rag/generate` に他テナントのテンプレート ID を渡し、404 になり応答本文に他テナントの `system_prompt` が混入しないことを assert する／`services/ai/tests/test_ai_tenant_boundary.py`
10. **Vision / MCP のテナント境界** — (a) トークン org と異なる `body.organization_id` での `POST /api/v1/vision/ocr/process` が 403、(b) `GET /api/v1/vision/ocr/results` が自テナント分のみ、(c) `ceos.contract.list` が `organization_id` 省略時も上流スタブでトークン org を強制し越境しないこと／`services/vision/tests/test_vision_tenant_boundary.py` と `services/mcp/tests/test_mcp_upstream_tenant_scope.py`

---

## 4. テスト実装の実現可能性評価（担当が `services/**` に書けない前提での設計妥当性）

| 項目 | 評価 | 根拠・注意点 |
|---|---|---|
| AI: `TestClient` + `dependency_overrides` 方式 | **実装可能** | 既存 `services/ai/tests/test_ai.py:77-102` の `app` / `client` fixture をそのまま流用できる |
| AI: 外部送信ゼロの検証（シナリオ1） | **実装可能（要注意）** | `_get_llm_provider()` は `get_settings()`（`lru_cache`）を呼ぶため、`monkeypatch.setenv` 後に `get_settings.cache_clear()` が必須（`services/ai/src/config.py:41-54`）。httpx 側は `OpenAICompatibleProvider._get_client` を patch するか、送信を捕捉する独自 transport を注入する。冪等な `settings` モジュール定数（`llm_service.py:12`, `embedding_service.py:14`）も import 時に確定している点に注意 |
| AI: Jinja2 SSTI 検証（シナリオ5） | **実装可能** | `POST /api/v1/ai/prompts` → `POST /api/v1/ai/complete` の2リクエストで到達する。DB は `get_db` override でモック可。**ただし `PromptService.get_template` が org スコープするため、同一 org のトークンで作成・取得する必要がある**（`prompt_service.py:143-154`） |
| AI: テナント分離（シナリオ7-9） | **実装可能** | 既存の `_auth_headers(user_id, org_id)` が任意 org のトークンを作れる（`test_ai.py:105-121`）。`org` 省略版ヘルパの追加が必要 |
| Vision: テナント分離（シナリオ10a/10b） | **実装可能** | 既存 `services/vision/tests/test_vision.py` は `mock_jwt` + `dependency_overrides[get_db]` 方式（`:55-65`）。同型で追加できる |
| MCP: 上流越境（シナリオ10c） | **実装可能** | `set_upstream_client()`（`services/mcp/src/services/upstream.py:98-101`）でスタブに差し替え可能。`services/mcp/tests/helpers.py` に既存ヘルパがある |
| シナリオ2（サイズ上限） | **現状は必ず失敗する** | 上限が未実装のため。CHARTER §1-4/§1-5 に従い、**テストを緩めて通すのではなく、仕様要求として failing test を起票し欠陥として扱う**方針を推奨 |
| シナリオ3（根拠ゼロ抑止） | **仕様根拠が未確定** | 「根拠なし生成を拒否せよ」という明文を V3.5 に見出せなかった。**期待値（拒否 or `grounded:false` フラグ）を Lead が確定してから**テスト化すべき（推測で仕様を作らない） |
| シナリオ8（DELETE 文のキャプチャ） | **実装可能** | `AsyncMock` の `execute` 呼び出し引数から `text()` を検査する。既存 `MockScalarResult` を流用可（`test_ai.py:13-42`） |
| CHARTER §4 の「pytest 実出力」 | **担当は出せない** | §0-1 のとおり。Lead が実装・実行して証跡を貼る必要がある |

---

## 5. 未確認事項（一覧）

1. CI / ローカルで `LLM_API_KEY` が未設定であること（外部送信ゼロの前提条件）。
2. `services/erp` の `GET /ledger/{ledger_id}/costs` が `ledger_id` のテナント帰属を検証するか（`ceos.cost.list` の越境可否）。
3. `services/erp` の `GET /ledger/summary` がトークン org で絞るか（`ceos.ledger.get_summary` の越境可否）。
4. `services/construction` の `GET /wbs/tree` / `GET /projects/{project_id}/gantt` が `project_id` のテナント帰属を検証するか。
5. Gateway / 逆プロキシ / Cloudflare 層でのボディサイズ上限・レート制限。
6. MCAH / MCIP 側での R4（Human-in-the-Loop）強制と AI 回答記録の実装。
7. CEOS の AI API が本番で MCAH を経由せず直接呼ばれうるか（Masking 迂回の成立条件）。
8. `contracts/vendor/harness-core/v0.6.0/registries/mcp-allowlist.yaml` の登録ハッシュと現行定義の一致（CI 検査の実効性）。
9. Core Allowlist との突合結果（CI を実行していないため）。
10. 仕様書における「RAG の根拠なし生成」の期待挙動（明文が見出せず）。

---

## 6. Lead への引き継ぎ事項

1. **最優先で修正すべきは D1（SSTI）と D2〜D5（テナント越境）。** いずれもコード上の根拠が明確で、追加テストで再現可能。
2. D1 の修正方向: `jinja2.sandbox.SandboxedEnvironment` への置換、またはテンプレート本文の許可構文の制限＋プロンプト CRUD へのロール要求追加。
3. D2〜D5 の修正方向: (a) MCP の `organization_id` 引数を廃止しトークン org を強制、(b) 上流 ERP の `list_invoices` をトークン org でスコープ、(c) AI の DELETE に org 条件追加、(d) Vision の `organization_id` をボディから廃しトークン由来に変更、(e) Vision の全取得系に org 条件を必須化。
4. D6〜D10 は仕様適合（Masking・根拠提示・入力境界）として設計判断が必要。**CHARTER §1-5 に従い、仕様を曲げて通さないこと。**
5. 本レポートは**設計までが成果物**。`services/**` へのテスト実装と `python3 -m pytest tests/ -q -p no:cacheprovider` の実出力取得は Lead の作業範囲。
