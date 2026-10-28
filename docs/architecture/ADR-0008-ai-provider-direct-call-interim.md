# ADR-0008: AI サービスの LLM Provider 直接呼び出しを期限付きの暫定例外とし、全社 Model Gateway 経由へ移す

Deviates-from: MCDX-ADR-0005 — `services/ai` が OpenAI 互換 API（既定は OpenAI）を直接呼ぶ実装を持つ。全社 Model Gateway の契約が公開されるまでの暫定例外とし、期限は 2026-12-25（提案値）。

- 状態: **proposed（未承認）**。オーナーの承認前であり、採択された決定ではない
- 承認: **未承認**（承認者・承認日は空欄）
  - 承認者:
  - 承認日:
- 日付: 2026-10-28
- 見直し期限: 2026-12-25（提案値）
- 決定者: 提案（本セッション）。採択はオーナー
- 関連: MCDX-ADR-0005、MCDX-ADR-0006、MCDX-ADR-0007、[ADR-0001](ADR-0001-ceos-responsibility-boundary.md)、[ADR-0004](ADR-0004-tenant-isolation-enforcement.md)

## 背景

全社 ADR MCDX-ADR-0005（proposed）は、Domain Product が AI Provider を直接呼ばず、全社の Model Gateway を経由することを求める。
Gateway の契約が公開されるまでの暫定例外は、条件を満たしたうえでローカル ADR に `Deviates-from` を書くこととしている。
CEOS はその例外 ADR を持っていなかった。

### 実装の実測（2026-10-28、`origin/main` `0c6a3a6`）

| 箇所 | 内容 |
| --- | --- |
| `services/ai/src/config.py` | `LLM_BASE_URL`（既定 `https://api.openai.com/v1`）、`LLM_API_KEY`（既定は空）、`LLM_DEFAULT_MODEL`、`LLM_EMBEDDING_MODEL` を環境変数から読む |
| `services/ai/src/services/llm_service.py` `OpenAICompatibleProvider` | `httpx` で `{LLM_BASE_URL}/chat/completions` を直接呼ぶ（通常・ストリーム）。`Authorization: Bearer <LLM_API_KEY>` |
| `services/ai/src/services/embedding_service.py` `EmbeddingService` | 同じ `LLM_BASE_URL` の `/embeddings` を直接呼ぶ |
| `services/ai/src/api/llm.py`（`/chat`・`/chat/stream`・`/complete`） | `LLM_API_KEY` があれば `OpenAICompatibleProvider`、無ければ `MockLLMProvider` |
| `services/ai/src/api/rag.py`（`/rag/search`・`/rag/generate`）、`api/embeddings.py` | 同じく `LLM_API_KEY` の有無で実呼び出しとモックを切り替える |

- Provider: OpenAI 互換 API なら何でも呼べる（`LLM_BASE_URL` で切り替え）。既定は OpenAI。SDK は使わず HTTP で直接呼ぶ。
- 抽象化: `LLMProvider` 抽象クラスがあり、呼び出し側は抽象に依存している。Gateway 用の実装を 1 つ足せば差し替えられる構造になっている。
- 有効化の条件: `LLM_API_KEY` が空でないこと**だけ**。実行環境（`ENVIRONMENT`）は見ていない。明示的な停止スイッチは無い。
- 既定: キーが空ならモック応答（外部送信なし）。
- 送る内容: 利用者のチャット本文、組織のプロンプトテンプレート、RAG では検索で得た文書の断片、埋め込みでは登録する本文。
- マスキング: `/chat`・`/chat/stream`・`/complete` はメールアドレスと電話番号を送信前に置換する（`masking_service.py`）。**RAG の生成と埋め込みには適用されていない**。
- テナント分離: すべてのエンドポイントがトークンの組織でスコープする（ADR-0004）。
- 監査: Provider への送信を記録する監査イベントは無い。
- 配備の実態（リポジトリ内の定義で確認できた範囲）: `docker-compose.yml`（開発）と `docker-compose.stg.yml`（staging）の `ai` サービスには `LLM_API_KEY` を渡していないため、どちらもモック応答で動く。本番の公開面は静的な Web（Pages）であり、`services/ai` を本番で動かしている定義はリポジトリ内に無い。

### MCDX-ADR-0005 決定 2 の条件との照合

| 条件 | 現状 | 判定 |
| --- | --- | --- |
| 本番相当の環境では無効 | `services/provider_policy.py` の `resolve_llm_mode()` に一本化。`ENVIRONMENT` が development / test / docker 以外ではキーがあっても 503（明示フラグ `ALLOW_DIRECT_LLM_IN_NONDEV`、既定 false の場合だけ許可。stg・本番の定義には入れない） | 充足（PR #235） |
| 既定は `disabled` | キーが空ならモック | 充足 |
| Gateway が使えないときに直接呼び出しへ切り替えない | Gateway の経路がまだ無いため、切り替えも無い | 充足（経路追加時に再確認） |
| 送るのは internal 以下のデータだけ | 区分による送信制御は無い。RAG・埋め込みはマスキングも無い | **未充足** |
| 監査に Provider 名を残す | 送信の監査が無い | **未充足** |
| 期限 2026-12-25 | 本 ADR で提案 | 本 ADR で充足（承認後） |

### Gateway 経由へ移せるか

移せる。根拠は次のとおり。

- 呼び出しは `LLMProvider` 抽象と `EmbeddingService` の 2 か所に集約されている。Gateway 用の `LLMProvider` 実装と埋め込みクライアントを足し、選択の分岐（`_get_llm_provider`・`_get_rag_service`・`_get_embedding_service`）を変えれば移行できる。
- 送信形式は OpenAI 互換の chat completions と embeddings で、Gateway 側が同じ形式を受けるなら、`LLM_BASE_URL` を Gateway に向けるだけで経路を移せる可能性がある（認証方式が合う場合）。
- 移行を止めている条件は本リポジトリの外にある。全社 Model Gateway の Domain Product 向け契約（エンドポイント・認証・版管理）が公開されていない（MCDX-ADR-0005 決定 4）。契約が無いまま独自に接続を作ることは MCDX-ADR-0006 の暫定規則に反するため、採らない。

## 候補と評価

| 観点 | A: 期限付きの暫定例外とし、不足条件を是正する | B: 直接呼び出しの実装を撤去し、モックだけにする | C: Gateway への接続を先に独自実装する |
| --- | --- | --- | --- |
| MCDX-ADR-0005 との整合 | △（期限と条件付き） | ◎ | ✕（契約が無い） |
| 既存機能への影響 | 現状どおり（どの環境もキー無しでモック） | 開発環境で実 LLM を使った検証ができなくなる | なし |
| 移行のしやすさ | 抽象を残せる | 移行時に作り直し | — |

## 決定（提案）

案 A を提案する。オーナーの承認までは決定ではない。

### 暫定例外の範囲

- 対象は `services/ai` の `OpenAICompatibleProvider` と `EmbeddingService` に限る。他のサービスに LLM の直接呼び出しを足さない。

### 例外を続けるための是正（別 PR で行う。本 PR はコードを変更しない）

1. **本番相当の環境では無効にする。** `ENVIRONMENT` が開発・テスト以外の場合は、`LLM_API_KEY` があっても直接呼び出しを拒否する（モックへ黙って切り替えず、503 を返す）。→ PR #235 で実施（判定は呼び出しのたびに `resolve_llm_mode()` で行う）。
2. **明示的な有効化にする。** キーの有無だけで有効にせず、Provider の選択（例: `LLM_PROVIDER=disabled|openai_compatible_direct|gateway`、既定 `disabled`）を必須にする。
3. **送る範囲を internal 以下に限る。** RAG の生成と埋め込みにもマスキングを適用する。機密区分（MCDX-ADR-0007）の対応付けが決まるまで、非本番では顧客データ・個人情報を入力しない。
4. **監査に Provider 名を残す。** 送信ごとに Provider 名・モデル名・組織・操作を記録する（本文は記録しない）。
5. Gateway が使えないときに直接呼び出しへ切り替える実装を作らない（fail closed）。

### 終了条件（Gateway 経由への移行）

1. 全社 Model Gateway の Domain Product 向け契約が版付きで公開されること（MCDX-ADR-0005 決定 4）。
2. 上記の後、Gateway 用の `LLMProvider` 実装と埋め込みクライアントを足し、`OpenAICompatibleProvider` の直接呼び出しと、本リポジトリでの Provider キーの保管をやめる。本番の secret の追加・削除は Approval PR で行う。

### 見直し

- 期限 2026-12-25（提案値）までに終了条件 1 が満たされない場合は、例外の継続か案 B への切り替えを改めて判断し、本 ADR を更新する。

## 影響

- 本 PR は文書の追加だけで、動作は変わらない。
- 承認されると、是正 1〜4 を別 PR で実装する。現在の配備定義ではキーが無いため、是正による利用者への影響は無い見込み。

## 未確認事項

- リポジトリ外で `services/ai` に `LLM_API_KEY` を渡して動かしている環境があるか。
