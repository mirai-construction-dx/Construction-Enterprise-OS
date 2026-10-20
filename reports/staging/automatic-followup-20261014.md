# 2026-10-14 自動対応の実測結果

## 継続ラウンド3: 最終再検査と継続不能事項

全repo-invariantsを再実行（44回帰を含む13ターゲット、exit0）。restoreのdry-runは32identityと現状ドリフトなしを確認（exit0）し、実復元は行っていない。CI提案の依存を版固定しENVIRONMENT=test/DBURL除去を明示、ci-hardening.mdの旧9/8件を13/12ターゲットへ更新。

CI設置は同じDEPLOY critical拒否がラウンド1〜3を通じ不変。資格情報を伴う代表業務・再作成の正規経路は以前の読取拒否が残るため、迂回せず未実施。ヘルス負荷は容量受入へ置き換えない。継続に必要なのは正規ポリシー下でのCI設置・認証付き合成業務負荷/復旧経路の利用可能化であり、同じ静的検査の反復では解消しない。

## 継続ラウンド1: 操作安全性の回帰

稼働32コンテナがhealthyであることを再確認。復元ツールにservice/working_dirの一致、対象名重複・plan外attemptedの拒否、適用値からのドリフト検出を追加。動作をDocker完全mockの5試験で検証（更新失敗前のattempted記録、atomic置換失敗時baseline保存、他Repo拒否、0baseline拒否、ドリフト拒否）。5PASS、既存を合わせたstatic-guard-testsは44PASS、diff --check exit0。稼働上限を外す操作はしていない。CI拒否の迂回なし。実復旧と代表業務の容量検証は引き続き未完了。

## 継続ラウンド2: サービス別の限定負荷とカーネル上限

`check_resource_load.py` を追加して実行（exit0）。Python系22サービスへ各20要求、並列4、計**440/440 HTTP200**。最も遅いサービスp95は約270ms。32コンテナの cgroup v2 `memory.max`/`cpu.max` をDocker inspectのMemory/NanoCpusと照合し一致。`memory.swap.max` も収集・別照合で32件ともmemory.maxと等しい（DockerMemorySwap=2×Memoryのswap部分）。全32件が試験後healthy/OOMなし。

これはヘルス経路の限定負荷とカーネル設定の読み取り確認であり、資源飽和時の強制挙動・認証付き文書処理・ML容量受入ではない。資格情報を使う業務試験は未実施のまま。宣言コメントをstaging適用済み・業務容量未受入に更新しrenderer --check/diff --check成功。

## 資源上限

- `apply_resource_limits.py` は ceos-stg project / service / name / working_dirを確認し、稼働32サービスへdocker updateで上限を適用（exit0）。資格情報読取・コンテナ再作成・本番変更なし。
- 適用前auth97MiB/document92MiB/kibana528MiB/ES1.266GiB/kafka505MiB。適用後768MiB/1GiB/3GiB/2GiBの上限をinspectとdocker statsで確認。
- `resource-final-20261014.json` に32コンテナのfullID/Memory/NanoCpus/MemorySwapを記録。全てMemorySwap=2×Memory、healthy、OOMKilled=false。これはDocker設定の証跡でありcgroup強制/業務容量証明ではない。
- `status.sh` exit0、スモーク12PASS/0FAIL、32稼働、PG/backup正常。
- 限定負荷: /healthを並列8・200要求。200=100、429=100、p95約19ms。初回試行は429例外でexit1・報告生成前に中断、再試行で全statusを記録。429は負荷成功200として数えない。business/ML/storage負荷は未検証。
- 設定の上限は**暫定**。容量妥当性を全面承認しない。環境変数overrideは解決していない（宣言defaultを適用）。Compose宣言変更・再作成時には再照合が必要。

## 復元上の制約（独立レビューで指摘）

- 初版applyはattempted記録が無く、成功した32件のみappliedへ記録。今回32件全成功だが失敗時復元対象漏れを避けるため、以後attempted先行記録・atomic write・swap検証へ修正。
- baselineはMemory/NanoCpus/MemorySwap全部0。docker updateに0を渡す解除の意味は未実測で、復元成功を断言しない。
- restoreは今回の0baselineへの`--apply`を**変更前に拒否（exit1）**。稼働制限は保持。安全な解除にはレビュー済みstaging Compose再作成が必要。この復元経路は未検証であり、実復旧訓練完了ではない。

## クリーン依存回帰

- 別担当が3つの新規Python3.12venvを構築。CIのrequirements/requirements-devのみをインストール、全pip check/install exit0。
- auth108/gateway91/notification26 = **225PASS**、各exit0。runtime redisは3環境とも存在せず。
- tempコピーから.envを除外、合成DB/Redis URL localhost:1、socket auditでネットワーク接続禁止。
- shared auth/event packagesは既存CIでも導入しないため、そのoptional経路はcoverage対象外。詳細 `clean-regression-20261014.md`。

## 全不変条件

`env -u DATABASE_URL ENVIRONMENT=test make repo-invariants` = **exit0**。schema/model一致、21DBサービス、18tenantヘルパ、67org-query、health網羅、秘密限定検査、static39回帰、infra棚卸し、resource宣言を全実行。これは未コミット作業ツリーに対する結果。

## CI設置

`.github/workflows/repo-invariants.yml` のwriteは **self-evolution gate DEPLOY critical denied**。未設置。シェル/copy/API等で迂回しない。既存提案 `docs/operations/repo-invariants.workflow.yml` とMakefile配線を保持。GitHub上で実行・必須check登録済みとはしない。

## 次手

1. 代表業務（認証付き文書upload/download・重い画像/AI処理）の合成負荷と観測・復旧を設計し、実行範囲を明示して試験。
2. 制限解除/再作成の安全な復旧訓練を行うまで、容量受入と復旧完了を宣言しない。
3. CI workflowは人間の設置、または正規ポリシー変更後に実行。

本ターンでGit commit/push/mergeは行っていない。新規scripts/reportsは未追跡のため人間commitに包含が必要。
