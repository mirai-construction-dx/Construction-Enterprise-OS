# ヘルスチェックの意味（2026-09-18 改訂）

## 現状

**全 20 サービス（gateway を除く）の `GET /health` は DB へ `SELECT 1` を実行し、
到達できなければ `503` を返す。**

```sh
curl -s -o /dev/null -w '%{http_code}\n' http://localhost:8000/health   # 200
# DB を止めると 503 {"detail":"database unavailable"}
```

`docker-compose.yml` の healthcheck は各サービスの `/health` を叩くため、
**DB 断でコンテナが unhealthy になる**。以前は 19 サービスが到達性を確認せず
常に 200 を返していたため、`restart: unless-stopped` も healthcheck も
DB 断を検知できず、監視として機能していなかった。

## 判定の意味

| 応答 | 意味 |
|---|---|
| `200 {"status":"healthy"}` | プロセスが応答し、DB へ到達できている |
| `503 {"detail":"database unavailable"}` | DB へ到達できない（接続文字列の誤り・DB 停止・ネットワーク遮断） |

`/health` は **DB への到達性のみ**を見る。次は検知しない。

- **スキーマの有無**: `SELECT 1` はテーブルを参照しないため、マイグレーション未適用でも 200 になる。適用状況は [`schema-bootstrap.md`](./schema-bootstrap.md) で確認する
- **依存先（MinIO / Redis 等）の状態**: 現在は DB のみ
- **非同期処理の滞留**: キューやバックグラウンドジョブは対象外

## 集約エンドポイント

`GET /api/v1/health/services`（auth サービス）は次を返す。

- 自身（auth）の状態を **実 DB で判定**（以前は無条件 `healthy` と自己申告していた）
- `HEALTH_SERVICE_URLS` に並べた各サービスを実 HTTP でプローブし、**実測レイテンシ**（`latency_ms`）を返す（以前は常に 0）
- 1つでも `unhealthy` があれば `overall` は `unhealthy`

### ⚠️ この endpoint は「見た範囲」の結論である（2026-10-14 是正）

`overall` は **`HEALTH_SERVICE_URLS` に入っている先だけ**の結論である。
2026-10-14 の実測では **3 件（document / workflow / notification）しか入っておらず**、
ゲートウェイの上流 **21 件のうち 17 件を見ていなかった**。
それにもかかわらず文書とダッシュボードが「全サービス healthy」と表示していたため、
**見ていないサービスが落ちても緑に見える**状態だった
（stg で実測: `vision` を停止しても修正前は `overall: healthy` のまま）。

現在は**ゲートウェイの全上流**（auth を除く 20 件 ＋ auth 自身 = 21 件）を網羅している。
網羅は `scripts/ci/check_health_coverage.py` が機械的に検査する
（`make repo-invariants` の `health-coverage`。上流を足して一覧へ入れ忘れると落ちる）。

```bash
$ curl -sS http://127.0.0.1:19500/api/v1/health/services
{"services": [ … 21 件 … ], "overall": "healthy", "checked_at": "…"}
```

**新しいサービスを足したら `docker-compose.yml` の `auth.HEALTH_SERVICE_URLS` にも足すこと。**
忘れても `health-coverage` が検出する。

## 変更履歴

- 2026-09-18: 19 サービス（auth 含む）の `/health` を DB 到達性チェックへ変更。
  auth の集約ヘルスを実 DB 判定・実レイテンシ計測へ変更。
  回帰テスト（DB 到達不能時に 503）を各サービスに追加。
- 2026-10-14: 集約ヘルスの対象を **3 件 → 20 件**（ゲートウェイの全上流）へ拡張。
  `scripts/ci/check_health_coverage.py` で網羅を検査するようにした。
