# AI Provider への送信を機密区分で制御する設計案（ADR-0008 の残課題）

- 状態: **設計案（未承認）**。コードは変更していない。採択はオーナー
- 日付: 2026-10-28
- 関連: [ADR-0008](../architecture/ADR-0008-ai-provider-direct-call-interim.md)（照合表「送るのは internal 以下のデータだけ」）、[ADR-0001](../architecture/ADR-0001-ceos-responsibility-boundary.md)、[ADR-0004](../architecture/ADR-0004-tenant-isolation-enforcement.md)、MCDX-ADR-0005、MCDX-ADR-0007
- 対象: `services/ai`（/chat・/chat/stream・/complete・/rag/search・/rag/generate・/embeddings・/embeddings/search）

## 1. 目的

ADR-0008 の照合表で唯一「未充足」のまま残っている条件「送るのは internal 以下のデータだけ」を満たすための設計を決める。
本文書は案であり、実装は採択後に別 PR で行う。

## 2. 実測（2026-10-28、`main` `2cac35f`）

### 2.1 CEOS のデータに機密区分は無い

| 確認したこと | 結果 |
| --- | --- |
| `services/*/src/models` に機密区分の列（classification・confidential・security level 等）があるか | **無い**。近いものは `services/platform` のダッシュボードの `is_public`（公開ダッシュボードの可否）だけで、データの機密区分ではない |
| AI サービスの保存データ（`embeddings`・`knowledge_base`・`prompt_templates`） | 区分の列は無い。`embeddings` は `organization_id`・`source_type`・`source_id`・`metadata`（JSONB）を持つ |
| AI サービスの要求スキーマ（`ChatRequest`・`CompletionRequest`・`RAG*Request`・`Embedding*Request`） | 区分を受け取る欄は無い |
| 区分の語彙がリポジトリ内にあるか | 取り込み済みの Core 契約（`contracts/vendor/harness-core/v0.6.0/schemas/common/defs.schema.json` の `classification`）にだけある。CEOS のコードからは参照されていない |
| 既存の送信前の保護 | `masking_service.py` がメールアドレスと電話番号を置換する（/chat・/chat/stream・/complete のみ。RAG と埋め込みには無い）。組織によるデータの分離（ADR-0004）はある |

### 2.2 Core の機密区分の語彙（v0.8.0）

CEOS が取り込んでいる v0.6.0 と、最新の公開版 v0.8.0 で語彙は同じである。

| 区分 | 順位 | 名称 | モデルへの送信（Core の定義） |
| --- | --- | --- | --- |
| `PUBLIC` | 0 | 公開 | 可 |
| `INTERNAL` | 1 | 社内 | 可 |
| `CONFIDENTIAL` | 2 | 社外秘 | マスキング後のみ |
| `HIGHLY_CONFIDENTIAL` | 3 | 極秘 | 不可（承認階層 R4 `model_send.highly_confidential`） |

Core のモデル呼び出しポリシーは、送信する資料のうち最も高い区分（`classification_max`）で判定し、区分が不明な場合は拒否する（fail closed）。

### 2.3 送信前に判定すべき箇所

外部送信は `services/send_audit.audited_send()` の 1 か所に集約されている（PR #236）。ただし「何を送るか」は経路ごとに決まるため、区分の判定は経路側で行い、`audited_send()` で最終確認する二段構えにする。

| 経路 | 送る内容 | 区分の由来（案） | 判定箇所（案） |
| --- | --- | --- | --- |
| /chat・/chat/stream | 利用者の入力、組織のプロンプトテンプレート | 利用者の入力は申告値（要求に `classification` を追加）。テンプレートは保存時の区分 | `api/llm.py`、`mask_messages` の直前 |
| /complete | テンプレート＋変数展開結果 | テンプレートの区分と変数の申告値の最大 | 同上 |
| /rag/search | 検索語（埋め込みの生成） | 検索語の申告値 | `api/rag.py`、`semantic_search` の前 |
| /rag/generate | 検索語＋**検索で得た文書の断片** | 申告値と、取得した断片の区分の最大 | `RAGService.generate_with_context` の LLM 呼び出し前（断片が確定した後） |
| /embeddings（登録） | 登録する本文 | 登録時に指定する区分（`embeddings` に列を追加して保存） | `api/embeddings.py`、`store_embedding` の前 |
| /embeddings/search | 検索語 | 検索語の申告値 | `api/embeddings.py`、`vector_search` の前 |

## 3. 設計案

### 3.1 判定の規則（Core の定義に合わせる）

送信直前に、送る資料の区分の最大値 `classification_max` を求め、次のとおり扱う。

| `classification_max` | 直接呼び出し（本 ADR の暫定例外の範囲） |
| --- | --- |
| `PUBLIC`・`INTERNAL` | 送信してよい（既存のマスキングは引き続き適用） |
| `CONFIDENTIAL` | **送信しない**（403）。Core の定義ではマスキング後に送れるが、暫定例外は「internal 以下」に限る（MCDX-ADR-0005 決定 2）ため、Gateway 経由に移るまでは送らない |
| `HIGHLY_CONFIDENTIAL` | 送信しない（403）。Gateway 経由でも送らない |
| 不明・未指定 | **送信しない**（403、fail closed） |

- 拒否は送信前に行い、`ceos_ai.audit` に `result=refused` と区分（値だけ）を記録する。本文は記録しない。
- モック応答の経路は外部送信が無いため、区分の判定を省略してよい（ただし不明値の入力検証は行う）。

### 3.2 区分の持ち方

1. **語彙は Core から取る。** 取り込み済みの Core 契約の `classification` 列挙を正とし、CEOS で独自の値を作らない（MCDX-ADR-0007）。
2. **要求で申告する。** /chat・/complete・/rag/*・/embeddings/search の要求に `classification`（任意）を追加する。未指定は「不明」として扱う。ただし既存の呼び出し元を壊さないよう、移行期間は設定（例: `AI_DEFAULT_INPUT_CLASSIFICATION`、既定は無し＝不明）で既定値を与えられるようにする。本番相当の環境では既定値を置かない。
3. **保存データに区分を持たせる。** `embeddings` と `prompt_templates` に `classification` 列を追加する（additive。既存行は NULL＝不明として扱い、送信しない）。RAG の断片は保存時の区分を引き継ぐ。
4. **上位サービスの区分を引き継ぐ。** 文書・原価・契約など他サービスのデータを埋め込みへ登録する場合は、登録元が区分を指定する。登録元が区分を持たない間は、登録元ごとに既定の区分を設定で決める（例: 契約・原価は `CONFIDENTIAL`）。

### 3.3 二重化

- 経路側の判定（3.1）に加え、`audited_send()` に `classification_max` を必須引数として渡し、`INTERNAL` を超える値や未指定なら送信せずに例外にする。経路側の判定漏れがあっても外部へ出ないようにする。

### 3.4 テスト方針

- 区分 4 値＋不明×経路 7 つで、送信の可否と応答コード、外部送信の件数（httpx の送信を差し替えて計数）を検証する。
- RAG の生成で、`CONFIDENTIAL` の断片が 1 つでも混ざると生成の送信が行われないことを検証する。
- 既存の行（区分 NULL）が送信されないことを検証する。

## 4. 未決点（オーナーの判断が要る）

| # | 論点 | 選択肢 |
| --- | --- | --- |
| Q1 | 区分の申告を必須にするか | (a) 必須（未指定は 400） (b) 任意で、未指定は不明＝拒否 (c) 移行期間だけ設定で既定値を与える（本案は b＋c） |
| Q2 | 既存の埋め込み・テンプレート（区分 NULL）の扱い | (a) 送信しない（本案） (b) 一括で区分を付け直す手順を用意する |
| Q3 | CEOS の業務データ（工程・原価・契約）の既定の区分 | 契約・原価を `CONFIDENTIAL`、工程を `INTERNAL` とする案。機密区分の全社的な対応付け（MCDX-ADR-0007）の採択に従う |
| Q4 | 利用者の申告をどこまで信用するか | 申告値は下げる方向にだけ使わせない（保存データの区分より低い値は無視して保存データの区分を使う） |
| Q5 | `CONFIDENTIAL` をマスキング後に送る経路を持つか | 暫定例外の間は持たない（本案）。Gateway 経由に移った後は Gateway 側のポリシーに従う |
| Q6 | 拒否時の応答コード | 403（区分による拒否）とし、503（環境による無効）と区別する案 |

## 5. 実装の順序（採択後）

1. 語彙の読み込みと判定関数（Core 契約の列挙を読む。単体テスト）
2. `embeddings`・`prompt_templates` への `classification` 列の追加（additive migration）
3. 要求スキーマへの `classification` の追加と、経路ごとの判定
4. `audited_send()` での最終確認と、監査への区分の記録
5. ADR-0008 の照合表の更新
