# ADR-0007: iot のデバイス個体認証（heartbeat / telemetry ingest）

- 状態: **proposed**（オーナー承認前。採択された決定ではない）
- 日付: 2026-10-21
- 決定者: 提案（本セッション）。採択はオーナー
- 上位規範: `Conforms-to: ADR-0004（テナント分離）`
- 関連: #154（本 ADR の起案 Issue）、#132（組織照合。PR #153 で実装済み）

## 背景

#132 により、heartbeat と telemetry ingest は **トークンの `org` とデバイスの `organization_id` を照合**し、
他組織のデバイス・未登録デバイスは 404 になった（`services/iot/src/api/telemetry.py:46-56`、
`services/iot/src/api/devices.py`、回帰テスト `tests/test_device_ingest_isolation.py` 22 passed）。

しかし、**デバイス個体を認証してはいない**。実測（2026-10-21）:

| 項目 | 実測 |
|---|---|
| 認証 | `get_current_client` は `token_data.type` が `client` または `user` なら受理する（`services/iot/src/middleware/auth.py:77-97`） |
| デバイスの同一性 | トークンに `device_id` は無い。リクエスト本文の `device_id` を組織で絞るだけ |
| センサーの所属 | `TelemetryPoint.sensor_id` は任意。**センサーがそのデバイスに属するか**は検証していない |
| M2M トークン | `services/auth/src/services/token_service.py:49` に `create_m2m_token` がある（device 束縛は未定義） |

したがって、**組織内の正規ユーザー（または漏えいした client 資格情報）** は、
同じ組織の任意のデバイスとして heartbeat / telemetry を送れる。組織境界は守られているが、
「どのデバイスになりすせるか」は制限されていない。

## 選択肢

| 観点 | A: per-device secret（HMAC/署名） | B: mTLS（クライアント証明書） | C: デバイス用の署名付きトークン（OAuth client credentials 相当） |
|---|---|---|---|
| 仕組み | デバイスごとの鍵でリクエストを署名 | デバイスごとの証明書で相互 TLS | デバイス資格情報で token endpoint から短命 JWT（`device_id` クレーム）を取得 |
| 実装コスト | 中（署名検証・鍵管理） | 高（CA・配布・失効・ゲートウェイ対応） | **中**（auth の既存 token 基盤を拡張） |
| ローテーション | 鍵の再発行が必要 | 証明書の再発行 | secret の再発行＋短命トークンで自然に更新 |
| 失効 | 鍵失効リスト | CRL/OCSP | DB のデバイス状態＋短命トークンで即時性が高い |
| リプレイ耐性 | nonce/時刻が必要 | TLS で担保 | 短命＋jti（必要なら） |
| 既存基盤との整合 | 新しい署名基盤 | ネットワーク構成の変更 | **auth / JWT / RBAC と整合** |

**推奨: C（デバイス用の署名付きトークン）を Phase 1 とし、B は将来の強化として残す。**

理由:

1. 既に auth が JWT 発行・検証を持ち、`get_current_client` も `client` トークンを受理する。
   `device_id` クレームを追加し、**ingest 時に本文の `device_id` と照合**するのが最小の変更で済む。
2. 短命トークンにより、失効は「デバイス状態を `disabled` にする」でほぼ即時になる。
3. mTLS は配布・失効・ゲートウェイ（Cloudflare Tunnel）の制約が大きく、Phase 1 では過剰。

## 決定（案）

1. **デバイス資格情報**を auth で発行する。デバイスごとに `client_id` と secret を持ち、
   `POST /api/v1/auth/token`（client credentials）で **短命 JWT**（例: 15 分）を取得する。
   トークンのクレームに `type: device`、`device_id`、`org`、`scopes: ["iot:ingest"]` を入れる。
2. **ingest / heartbeat は `type: device` を要求**する（ユーザートークンでの ingest は許可しない）。
   本文の `device_id` とトークンの `device_id` が一致しない場合は **403 DEVICE_MISMATCH**。
3. `sensor_id` が指定された場合、**その sensor がトークンの device に属する**ことを検証する。
   不一致は 404（存在を明かさない）。
4. **発行・ローテーション・失効**:
   - 発行は管理 API（admin）に限定。secret はハッシュで保存し、平文を返すのは発行時 1 回のみ。
   - ローテーションは「新 secret 発行 → デバイス切替 → 旧 secret 失効」。猶予期間を設ける。
   - 失効はデバイス状態 `disabled` と secret の `revoked_at` で行い、短命トークンの残寿命だけ遅延する。
   - 漏えい時は該当デバイスの secret を即時失効し、テレメトリの異常を監査ログで確認する。
5. `create_m2m_token` は **device 用に拡張しない**（汎用 M2M と混ぜない）。デバイス用は
   別の token grant として実装し、監査上区別する。
6. **移行**: 既存のユーザー/client トークンによる ingest は、移行期間中は設定で許可し、
   既定は device トークンのみとする（fail-closed）。移行期間の終了は別途判断する。

## 影響

- デバイス側の実装変更（トークン取得・更新）が必要。既存の ingest クライアントは移行まで動かない可能性。
- auth の token endpoint・クレーム・監査ログの変更。`type: device` の RBAC を追加する。
- Cloudflare Tunnel 経由の ingress は変更しない（Phase 1）。mTLS を採る場合は別 ADR。

## 実装 Issue への分割（提案）

1. デバイス資格情報のデータモデル（`client_id` / secret ハッシュ / `revoked_at` / 状態）
2. auth の device token grant と `device_id` クレーム、監査ログ
3. iot の `type: device` 強制・`device_id` 照合・`sensor_id` 所属検証
4. 管理 API（発行・ローテーション・失効）
5. 移行手順と設定フラグ、既存データの棚卸し
6. 回帰テスト（他デバイス・他組織・失効後・sensor 不一致）

## 未決

- **本 ADR は提案であり、採択されていない。** 認証方式の変更は Approval 対象（`GITHUB_POLICY.md` §8）。
- トークン寿命、ローテーション猶予、移行期間の長さは運用判断。
- mTLS を将来導入するか（デバイス網の構成次第）。
