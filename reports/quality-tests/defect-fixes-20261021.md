# 第32バッチ — 開発ステップ 10 件の修正・実装（2026-10-21）

- 対象: Construction-Enterprise-OS（CEOS）
- 起点: `main` = `21e3a53`（第31バッチ後）／終点: `7635326`（統合 PR #221）
- 方針: オーナーの自動マージ委譲に従い、Required Checks 通過後に squash merge。`--admin` 迂回・force push なし。

## 1. 10 ステップの結果

| # | Issue | 内容 | PR | 結果 |
|---|---|---|---|---|
| 1 | #147 | 非文字列の org クレームを 500→403 ORG_INVALID に（18 サービス） | #212 | **merged** |
| 2 | #166 | auth の MFA 消費済みテストの flaky を修正 | #213 | **merged** |
| 3 | #116 | pytest 8.3.3 → 9.0.3 / pytest-asyncio 1.3.0 | #220 | **merged** |
| 4 | #133 | gis の `ST_DWithin` を geography でメートル評価、`location: null` は 422 | #221（#214） | **merged** |
| 5 | #134 | bim `/elements/search` の到達回帰テスト（本体は #159 で修正済み） | #221（#214） | **merged** |
| 6 | #135 | document の 500 から例外詳細を除去、不正 JSON は 400 | #221（#216） | **merged** |
| 7 | #136 | ai の他組織テンプレートを 404 に統一、DB 例外を握り潰さない | #221（#217） | **merged** |
| 8 | #138 | analytics の `connection_config` を write-only 化、作成にロール制限 | #221（#218） | **merged** |
| 9 | #118 | gateway の複数 `Set-Cookie` をすべて転送 | #221（#215） | **merged** |
| 10 | #125 | web API クライアント 9 件を実ルートに一致、allowlist を空に | #221（#219） | **merged** |

- 統合 PR #221 は 9 件の修正を cherry-pick で 1 本にまとめ、CI 54 checks を全 pass して squash merge。
- 個別 PR #214〜#219 は #221 のマージ後に **superseded としてクローズ**（二重マージなし）。

## 2. 検証（実測）

### 2.1 サービス単体

| サービス | 結果 | 備考 |
|---|---|---|
| gis | **151 passed**（+8） | 修正前に 4 件の赤を確認 |
| bim | **141 passed**（+2） | #134 は本体修正済みのため回帰ガードのみ |
| gateway | **92 passed** | 複数 Set-Cookie の赤→緑を確認。mypy success |
| document | **144 passed** | 新規 2 件は修正前 failed |
| ai | **112 passed** | 新規 5 件は修正前 failed |
| analytics | **103 passed** | 新規 5 件は修正前 failed |
| erp | **125 passed** | tenant.py の変更確認 |
| auth / notification / logging / event-core | **108 / 26 / 24 / 37 passed** | pytest 9.0.3 の隔離 venv |
| apps/web | **245 tests passed** / typecheck / lint / build | ルート照合 mismatches=0 / allowlisted=0 |

### 2.2 変異試験（歯の確認）

- tenant: 旧 `erp` 実装では `H-10:bad_org_int='EXC:AttributeError'` / `H-11:bad_org_list='EXC:AttributeError'` で **NG**。修正後は 18/18 **OK**。
- gis: 実 PostGIS（stg `ceos_stg`）で geography キャストを実行し、0.01°（緯度 35.6°）が **906.2 m** と返ることを確認（度なら 0.01 になるはず）。テーブル書込みなし。

### 2.3 stg への反映と再検証

- 変更 6 サービス（gateway / gis / document / ai / analytics / web）を main から再ビルド・再作成。
- `scripts/stg/status.sh` → **32 コンテナ / smoke 12 PASS 0 FAIL / 22 schemas 98 tables / pgBackRest ok**。
- `scripts/stg/e2e_stg.sh` → **16 passed**（gateway 経由の認証・認可・入力検証）。
- `env -u DATABASE_URL ENVIRONMENT=test make repo-invariants` → **exit 0**（13 ターゲット、tenant H-1〜H-11 を含む）。

## 3. 残課題・未確認（成功と書かない）

| 項目 | 状態 |
|---|---|
| CI の `scripts/tools` ジョブが `pytest==8.3.3` を直接固定 | **CVE が残存**。Issue #222 で追跡（`.github/workflows/**` は AI 書込不可） |
| analytics の保存時暗号化 | **未実装**（平文 JSONB）。コード・スキーマに明記済み |
| document / analytics の修正の stg E2E | 未実施（サービス単体テストと再デプロイのヘルスまで） |
| 実ブラウザでの複数 Set-Cookie 受信 | 未実施（フェイク上流＋TestClient で検証） |
| gis の距離の数値境界（実データ） | 合成座標 906.2m のみ。実データは使わない方針 |
| #134 の production 修正 | 既に #159 で修正済み。今回の追加は回帰テストのみ |

## 4. 参照

- 統合 PR: https://github.com/mirai-construction-dx/Construction-Enterprise-OS/pull/221
- tenant 修正: #212 / 認証 flaky: #213 / pytest: #220
- 残 CVE: #222
- 第31バッチ: `reports/staging/batch31-20261021.md`
