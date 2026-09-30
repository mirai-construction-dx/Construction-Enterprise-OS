# API 概要(全サービス・エンドポイント一覧)

> 本プロジェクトの API は **API Gateway**(FastAPI、port 9000)を単一入口とし、
> パスプレフィックスで各サービスへルーティングします。
> WebUI は `/api/v1/*` を Next.js リライト/Pages Function プロキシ経由で Gateway へ接続します。

## 1. ゲートウェイルーティング表

| プレフィックス | 転送先サービス | ポート |
|---|---|---|
| `/api/v1/health` `/api/v1/auth` `/api/v1/users` `/api/v1/roles` `/api/v1/permissions` `/api/v1/api-clients` `/api/v1/audit-logs` | auth | 8000 |
| `/api/v1/documents` | document | 8001 |
| `/api/v1/workflow` `/api/v1/cases` | workflow | 8002 |
| `/api/v1/gis` | gis | 8003 |
| `/api/v1/iot` | iot | 8004 |
| `/api/v1/ai` | ai | 8005 |
| `/api/v1/field` | field-dx | 8007 |
| `/api/v1/bim` | bim | 8008 |
| `/api/v1/maintenance` | maintenance | 8009 |
| `/api/v1/autonomous` | autonomous | 8010 |
| `/api/v1/vision` `/api/v1/ocr` `/api/v1/vectors` | vision | 8011 |
| `/api/v1/integrations` `/api/v1/platform` | platform | 8012 |
| `/api/v1/advanced` | advanced | 8013 |
| `/api/v1/analytics` | analytics | 8014 |
| `/api/v1/automation` | automation | 8015 |
| `/api/v1/construction` | construction | 8016 |
| `/api/v1/notification` | notification | 8017 |
| `/api/v1/partner` | partner | 8018 |
| `/api/v1/safety` | safety | 8019 |
| `/api/v1/erp` | erp | 8020 |
| `/api/v1/security` | security | 8021 |

設定: `services/gateway/src/config.py` の `UPSTREAM_SERVICES`(環境変数で上書き可)

`/api/v1/cases` `/api/v1/ocr` `/api/v1/vectors` はパス境界付き(`(?:/|$)`)で登録しており、`/api/v1/casesX` のような近接パスは転送しない。

## 2. サービス別エンドポイント

### auth(認証・認可・監査)— Neon DB 接続・検証済み
- `POST /api/v1/auth/login` / `POST /api/v1/auth/refresh` / `POST /api/v1/auth/logout` / `POST /api/v1/auth/logout-all`
- `POST /api/v1/auth/token` — トークン交換（RFC 8693、form-encoded。既定無効 `TOKEN_EXCHANGE_ENABLED=false`、gateway は 404 で遮断（`INTERNAL_ONLY_PATHS`）・内部利用のみ。[ADR-0003](../architecture/ADR-0003-mcp-audience-token-exchange.md)）
- `POST /api/v1/auth/mfa/setup|verify|disable`
- `GET /api/v1/users` / `GET/POST /api/v1/users/{user_id}`
- `GET /api/v1/roles` / `POST /api/v1/roles` / `GET /api/v1/roles/{role_id}` / `POST /api/v1/roles/{role_id}/permissions`
- `GET /api/v1/organizations` / `GET /api/v1/auth/ad/groups` / `GET /api/v1/auth/entra/policies`
- `GET /api/v1/health/services`

### document(文書管理)
- `POST /api/v1/documents/upload` / `GET /api/v1/documents/{document_id}` / `GET /api/v1/documents/{document_id}/download`
- `GET /api/v1/documents/{document_id}/versions` / `GET /api/v1/documents/{document_id}/versions/{version_number}`

### workflow(ワークフロー)
- `GET /api/v1/workflow/definitions` / `GET /api/v1/workflow/instances` / `GET /api/v1/workflow/instances/pending`
- `POST /api/v1/workflow/instances/{instance_id}/submit|approve|reject|cancel` / `GET .../history`

### gis(GIS・地図)
- `GET /api/v1/gis/in-area` `/nearby` `/intersecting/{site_id}` `/near-site/{site_id}` / `GET /{site_id}` `/infra_id` `/zone_id`

### iot(IoT・リアルタイム監視)
- `GET /api/v1/iot/sensors` `/machines` `/alerts` `/alert-rules`
- `POST /api/v1/iot/alerts/{alert_id}/acknowledge|resolve` / `GET /{device_id}/sensors` / `POST /{device_id}/heartbeat`

### ai(AI・分析基盤)
- `POST /api/v1/ai/chat` `/chat/stream` `/complete` / `POST /api/v1/ai/rag/generate` `/rag/search`
- `GET /api/v1/ai/models` `/prompts` / `POST /api/v1/ai/embeddings` `/embeddings/search`

### field-dx(現場DX)
- `GET /api/v1/field/progress` `/progress/zones` `/progress/reports/today` / `GET/POST /api/v1/field/instructions` `/photos` `/quality` `/quality/checks` `/reports`

### erp(ERP・経営管理)
- `GET /api/v1/erp/ledger` `/ledger/summary` `/invoices` / `POST /api/v1/erp/invoices/{invoice_id}/pay` / `GET /api/v1/erp/budgets/{budget_id}` `/costs/{cost_id}` `/costs/{cost_id}/approve`

### construction(施工管理)
- `GET /api/v1/construction/wbs` `/wbs/tree` `/schedules` `/resources` `/methods`
- `POST /api/v1/construction/methods/{method_id}/submit|approve|reject` / `GET /projects/{project_id}/gantt` `/critical-path` `/resource-cost-summary`

### safety(安全管理)
- `GET /api/v1/safety/hazards` `/hazards/open` `/incidents` `/incidents/active` `/inspections` `/inspections/stats`
- `POST /api/v1/safety/inspections/{inspection_id}/complete`

### partner(協力会社連携)
- `GET /api/v1/partner/{partner_id}` `/contacts` `/contracts` `/evaluations` `/rating` / `POST /{contract_id}/sign`

### security(セキュリティ・監査)
- `GET /api/v1/security/dashboard` `/incidents` `/incidents/active` `/policies` `/vulnerabilities` `/vulnerabilities/open`

### automation / autonomous / bim / vision / analytics / advanced / maintenance / notification / platform
- 各サービスの CRUD + 特化エンドポイント(上記「エンドポイント収集」参照)
- bim: `/api/v1/bim/{model_id}/elements`・`/elements/search`・`/pointcloud`
- vision: `/api/v1/ocr/process`・`/api/v1/vision/analyze`・`/api/v1/vectors/search`
- analytics: `/api/v1/analytics/datasources`・`/pipelines`・`/reports`

## 3. 認証方式

- `POST /api/v1/auth/login` → `access_token`(JWT、HS256、60分)+ `refresh_token`(30日)
- 以降の API は `Authorization: Bearer <access_token>` で認可(auth ミドルウェア)
- 権限: ロール(admin/site_manager/site_supervisor/site_worker/inspector/accountant/readonly)と
  パーミッション(`users.read` 等)で制御(Neon `auth` スキーマ)

## 4. 実証済みパス(本番 HTTPS)

`https://construction-os.mirai-dx-platform.com/api/v1/*`(Pages Function プロキシ
→ Cloudflare Tunnel → auth:18002 → Neon)でログイン・JWT・users/roles の動作を実証済み
(docs/operations/api-auth-db-verification.md 参照)。
