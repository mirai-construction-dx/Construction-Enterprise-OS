# 2026-10-14 再開時レビュー — 第30バッチは未完了

## 15:50 JST 修正・回帰検証の追記

以下はこのターンでの新しい検証結果。下記の初回レビューは履歴として保持する。

- 基盤ガードは「非消費の証明」から静的依存棚卸しの変更ゲートへ作り直した。document→MinIO と Kibana→Elasticsearch を実依存と明記。event-core を走査から除外せず import / alias / helper / factory 呼び出しも棚卸しする。動的呼び出し・一般的な到達性・非Python・packaging metadata全体は射程外。
- `mem_limit` 非対応の説明を撤回。deploy形式は今回の静的方針。単位なしmemory=bytes、0/負数/非有限CPU・不正構造・空servicesを検出し、G14をmainに接続。
- 秘密検査は安全性証明ではないと明記。PEM自己マッチ・不正YAML・git追跡取得失敗・意味的gitignoreチェックを修正。ホストはstatのみ、内容未読。不在はNOT_CHECKED。`.gitignore`に`.env.*`とexample例外を追加。
- Makefile に secrets-hygiene / static-guard-tests を追加、repo-invariantsとrepo-invariants-ciに接続。設置待ちworkflowは未設置のまま（CI実行済みとはしない）。
- オフラインガード回帰 **39件成功**（infra9 / memory11 / secrets19）、3ガードexit0、staging guards **17/17 PASS**、git diff --check exit0。
- auth: 既存の固定依存仮想環境で **108 passed**。bcrypt 3.2.2 / FastAPI 0.141.1を確認。以前のホストPythonの失敗とは環境が異なるため、本体欠陥の修正と主張しない。初回のSQLite試行はaiosqlite不在で13 collection errors、成功扱いしない。
- gateway: テストの実上流接続を合成ConnectErrorで遮断し、呼び出し回数・GET・URL・Authorizationを包括例外の外で確認。最終 **91 passed**（auth仮想環境を使用）。
- notification: ホストPythonで **26 passed**。専用venv不在の初回exit127は記録。既存環境を使用しておりクリーン依存インストール回帰は未実施。
- 3サービスはENVIRONMENT=test、合成URL `postgresql+asyncpg://synthetic:synthetic@127.0.0.1:1/synthetic`、plugin自動読込無効・pytest_asyncioを明示。DBの変更操作なし。既存のdeprecation/AsyncMock警告は残る。
- 独立レビューで3件（秘密ガード配線・回帰網配線・proxy内部assertの吸収）を指摘し修正。再レビューではその3件に残ブロッカーなし。

**残件:** 資源上限は仮値・稼働環境未適用・負荷妥当性未確認。クリーン依存回帰と全repo-invariants実行未実施。ci-hardening.mdの旧件数一覧は未更新。新規6ガード/テストと本記録は未追跡のため人間のコミット時に取りこぼさないこと。commit/push/mergeは本ターンでは行っていない。

## 状態（初回レビュー時）

- 再開時の `origin/main` は `99a2740`（API Tunnel の PR #201 が反映済み）。
- PR #202（連携レジスタ更新）を作成し auto-merge を登録した。最終マージ状態は本記録時点では未確認。
- 現在のブランチは `auto/ceos-integration-register`。第30バッチの変更は未コミット。
- staging status の再実行は exit 0、スモーク 12 PASS / 0 FAIL、32 コンテナ起動を報告した。
- 元の staging guards は16件通過。追加ガードが exit 0 でも、以下の誤判定があるため受入済みとはしない。

## 独立レビューで確定した修正必須事項

1. **MinIO はテスト専用ではない。** document の main の起動処理は `initialize_bucket()` を呼ぶ。upload / versions / download と internal API も storage_service / canonical_storage を通じて S3 クライアントを使う。`check_infra_consumers.py` の非消費という説明・例外表・成功表示は誤り。
2. **`mem_limit` 非対応という主張は証明していない。** このセッションの compose probe は s1 (`deploy.resources.limits`) だけを起動した。s2 (`mem_limit`) の実行時検証は行っていない。Docker の `--memory` 検証は compose の比較検証ではない。`deploy.resources.limits` へ統一する設計と、他方式が効かないという主張は区別すること。
3. **Kafka の間接依存はガードで捕捉できない。** `construction_enterprise_os_event_core.publisher` の import 名に `aiokafka` は含まれない。event-core を走査から除外し、クライアント import の存在だけ確認しても、サービスが publish を開始したことは検出できない。
4. **メモリ単位の解釈が誤り。** `check_memory_limits.py` は単位なし数値を MiB と解釈しているが、Docker のメモリ値は bytes。0 / 負数 / 非有限 CPU も検査する必要がある。
5. **新規 G-14 は定義のみ。** main からの呼び出し・変異試験を確認するまで有効とはしない。
6. **秘密検査の成功表示は射程が広すぎる。** PEM 検出は検査スクリプト自身の文字列や資料でも反応し得る。追跡ファイル検査は未追跡の新規検査ファイルを含まない。全ての秘密がリポジトリ外にあることの証明ではない。
7. **資源上限は稼働コンテナへ未適用。** credential を含む再作成操作が拒否され、既存 stg コンテナは再作成していない。設定追加と実稼働の上限適用を混同しない。
8. **実行中のサービスを制限する前に使用量を確認する。** 現在の既定上限は仮値。特に機械学習・画像処理サービスを一律768MiBに制限する受入根拠は無い。

## テスト結果（成功扱いしない）

ホスト Python で最初の試行は auth 13件 / notification 5件の collection error、gateway 1 failed / 90 passed。
`DATABASE_URL` を除いた再試行:

- auth: **3 failed / 105 passed**（パスワード関連等。根本原因未確定）
- gateway: **1 failed / 90 passed**（502本文をJSONとして解釈できない）
- notification: **26 passed**

gateway の単独失敗は変更前 `99a2740` でも再現した。auth は変更前との比較が未実施。
上記のテストは redis が導入済みのホスト Python を使っており、requirements から削除した後のクリーン環境試験にはならない。
シェルの `pytest | tail` は pytest の失敗終了コードを隠していた。今後は pipefail またはパイプ無しで終了コードを記録する。

## 次手

- 新規3ガードを未受入ドラフトとして扱い、誤った成功表示を直す。
- import 数だけで非消費を証明せず、document→MinIO の実依存と event-core の到達経路を区別する。
- `mem_limit` の説明訂正と単位・範囲テストを実施する。
- 資源上限・dev環境変数参照への変更は別の責任単位として評価し、必要な環境変数とクリーン環境回帰を確認する。
- AGENTS.md §4.8 と中央ポリシーの Git 操作規則の関係を確認してから commit / branch操作を行う。現時点では追加のGit変更操作を行わない。
- DNS / Human Gate / CI 設置の既存ブロッカーは、以前の権限不足記録を現在の権限と混同せず必要時に再確認する。

本記録は途中経過。第30バッチ完了、全テスト成功、実稼働適用済みとは宣言しない。
