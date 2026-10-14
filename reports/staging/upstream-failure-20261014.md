# stg 上流停止訓練 — 2026-10-14

- 実行者: エージェント（自動）
- 対象リビジョン: `8d4bbd8`（`origin/main`）
- コマンド: `scripts/stg/upstream_failure_drill.sh`（対象=`vision` / 対照=`gis`）
- 結果: **PASS（exit 0）**

## 出力（実測）

```text
== stg 上流停止訓練（対象=vision / 対照=gis / 2026-10-14T14:22:40+09:00） ==

-- 1. 基準状態 --
ゲートウェイ /health=200
集約ヘルス（overall|サービス数|healthy 以外）=healthy|21|
対照 gis のルート=404 27

-- 2. vision を停止する --
OK: ceos-stg-vision は停止した

-- 3. 障害中の挙動 --
PASS: D-1 ゲートウェイ自身の /health は 200 のまま（巻き込みなし）
集約ヘルス=unhealthy|21|vision
PASS: D-2 集約ヘルスが vision だけを unhealthy と報告し overall も unhealthy
PASS: D-3 無関係な上流（gis）は 19ms で応答（巻き込みなし）
PASS: D-4 停止した上流へは 504 を 3018ms で返す（ハングしない）
PASS: D-5 （意図的に止めた vision 以外に）停止・再起動ループ入りしたコンテナは無い

-- 4. 復旧（vision を戻す） --
集約ヘルス=healthy|21|
PASS: D-6 復旧後に集約ヘルスが healthy に戻る
スモーク: 結果: PASS=12 FAIL=0
PASS: D-7 復旧後のスモークが全通過

結果: 基準 healthy|21| / 障害中 unhealthy|21|vision / 復旧後 healthy|21|
OK: 上流 1 サービスの停止で巻き込まれず、定義された応答を上限内に返し、復旧後に戻ることを実測した。
```

## 判定が効いていることの確認

| 確認 | 結果 |
|---|---|
| 上限を 2 秒に下げる（現状は接続タイムアウト 3.0 秒） | `FAIL: D-4 …（504 3020）` で **exit 1**。閾値が効いている |
| 対象を `erp` に変える | D-2 / D-4 とも PASS（対象を差し替えられる） |

## 補足（この訓練で分かったこと）

- 停止した上流への要求が **16.1 秒**かかっていたのは HTTP タイムアウトではなく
  **名前解決**（停止したコンテナは Docker DNS が答えられず外部リゾルバへ転送される）。
  静的 IP ＋ gateway の `extra_hosts` ＋ 接続タイムアウトの分離で **3.0 秒**になった。
  詳細は `docs/operations/staging.md` §6.14。
- 巻き込み（カスケード）は起きていない。無関係な上流は 19ms で応答した。
