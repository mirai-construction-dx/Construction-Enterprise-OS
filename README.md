# 🏗️ Construction-Enterprise-OS

> **建設・土木業向け統合オペレーティングシステム** — 全業務・全データ・全プロセスを統合するデジタル基盤

[![CI](https://github.com/Kensan196948G/Construction-Enterprise-OS/actions/workflows/ci.yml/badge.svg)](https://github.com/Kensan196948G/Construction-Enterprise-OS/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/Python-3.12+-blue.svg)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-blue.svg)](https://fastapi.tiangolo.com)
[![Next.js](https://img.shields.io/badge/Next.js-14-black.svg)](https://nextjs.org)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-336791.svg)](https://postgresql.org)
[![Kubernetes](https://img.shields.io/badge/Kubernetes-1.28-326ce5.svg)](https://kubernetes.io)
[![License](https://img.shields.io/badge/License-Proprietary-red.svg)]()

---

## 📋 概要

建設・土木業における**全業務・全データ・全プロセスを統合**するデジタル基盤です。個別バラバラの業務アプリケーション群を **「OSレイヤ」** によって統合し、単一の真実 (Single Source of Truth) として機能させます。

### 🚀 MVP 稼働状況(2026-08-19)

| 環境 | URL | 内容 | 状態 |
|---|---|---|---|
| MVP プロトタイプ | https://construction-os-mvp.mirai-dx-platform.com | WebUI `webui/Construction-Enterprise-OS---CRUD.html`(正本スタイル+全ページCRUD) | ✅ 稼働・E2E は `e2e/*.spec.ts` 計28テスト(desktop/mobile の2プロジェクト) |
| 本番 | https://construction-os.mirai-dx-platform.com | 同上(同一コンテンツ) | ✅ 稼働 |
| DB | Neon `construction-enterprise-os` | auth スキーマ(Migration+Seed 適用) | ✅ 空DB再実行可能 |

- **WebUI(CRUD 統合版)**: **OpenDesign 正本バンドルのスタイルを一切変更せず**、そのバンドルにデータ層+CRUD を統合(`webui/Construction-Enterprise-OS---CRUD.html`)。
  **全ページ(13 カテゴリ・約 90 ルート)の右側コンテンツで「データ取得・新規作成・編集・削除・検索」が操作可能**。
  データは localStorage 永続化ストア(シード: 工事/ワークフロー/文書/センサー/原価/安全/協力会社/ユーザー/重機/作業員/契約/請求/GIS/AI/IoT 等 30 コレクション)。
  auth API(`/api/v1/health`・`/api/v1/auth/*`)は実接続。他サービス API 未稼働のため同一インターフェースのローカルストアで代替(将来差し替え可)。
- 設計正本: `webui/`(OpenDesign ハンドオフ、プロトタイプは `standalone-prototype.html` として保全)+ `docs/design/opendesign-spec.md`
- 検証: `e2e/mvp.spec.ts`(9)+ `e2e/crud.spec.ts`(11)+ `e2e/api.spec.ts`(8)= **28 テスト**(Playwright、desktop/mobile の2プロジェクトで実行)
- 運用: `docs/operations/deployment.md`・`docs/operations/neon-database.md`・`docs/operations/production-deploy-record.md`

```mermaid
graph TB
    subgraph "🏛️ Construction Enterprise OS"
        direction TB
        L4["🛡️ Layer 4: セキュリティ・統制<br/>SOC/SIEM | ゼロトラスト | EDR | 監査"]
        L3["📱 Layer 3: 業務アプリケーション<br/>ERP | 現場DX | 協力会社連携 | モバイル | BI"]
        L2["🧩 Layer 2: ドメイン基盤<br/>AI | IoT | GIS | BIM | 文書管理 | ワークフロー"]
        L1["⚙️ Layer 1: 共通基盤 (OSカーネル)<br/>認証 | データ | API GW | イベント | 通知 | ログ"]
        L0["🖥️ Layer 0: インフラ基盤<br/>K8s | PostgreSQL | Redis | Kafka | MinIO"]
        L4 --> L3 --> L2 --> L1 --> L0
    end

    U1["🏢 ゼネコン"]
    U2["👷 サブコン"]
    U3["📋 発注者"]
    U4["🏗️ 専門工事会社"]

    U1 & U2 & U3 & U4 --> L4

    style L4 fill:#dc2626,color:#fff
    style L3 fill:#1a56db,color:#fff
    style L2 fill:#7c3aed,color:#fff
    style L1 fill:#16a34a,color:#fff
    style L0 fill:#4b5563,color:#fff
```

### 🎯 対象ユーザー

| 🏢 事業者    | 👷 現場    | 📋 管理        |
| ------------ | ---------- | -------------- |
| ゼネコン     | 現場作業員 | 経営層         |
| サブコン     | 現場監督   | 管理部門       |
| 専門工事会社 | 協力会社   | 発注者・監理者 |

---

## 🏛️ システムアーキテクチャ

```mermaid
graph LR
    subgraph "🌐 クライアント層"
        WEB["🖥️ Web App<br/>Next.js 14"]
        MOBILE["📱 Mobile PWA<br/>React + PWA"]
        API_CLIENT["🔗 External API<br/>REST / Webhook"]
    end

    subgraph "🚪 API Gateway 層"
        GW["🌐 API Gateway<br/>FastAPI | レート制限 | 認証"]
    end

    subgraph "⚙️ マイクロサービス層"
        AUTH["🔐 認証<br/>JWT/MFA/RBAC"]
        DOC["📄 文書管理<br/>MinIO/S3"]
        WF["🔄 WFエンジン<br/>承認フロー"]
        GIS["🗺️ GIS<br/>PostGIS/GeoServer"]
        IOT["📡 IoT<br/>MQTT/時系列"]
        AI["🤖 AI基盤<br/>LLM/VectorDB"]
        ERP["💰 ERP<br/>原価/会計"]
        NOTIF["🔔 通知<br/>Push/Email"]
    end

    subgraph "💾 データ層"
        PG["🐘 PostgreSQL 16<br/>+ PostGIS + TimescaleDB"]
        REDIS["⚡ Redis 7<br/>Cache/Session"]
        KAFKA["📨 Kafka<br/>Event Bus"]
        ES["🔍 Elasticsearch 8<br/>全文検索"]
        MINIO["🪣 MinIO<br/>Object Storage"]
    end

    WEB & MOBILE & API_CLIENT --> GW
    GW --> AUTH & DOC & WF & GIS & IOT & AI & ERP & NOTIF
    AUTH & DOC & WF & GIS & IOT & AI & ERP & NOTIF --> PG & REDIS & KAFKA & ES & MINIO

    style GW fill:#1a56db,color:#fff
    style PG fill:#336791,color:#fff
    style REDIS fill:#dc382d,color:#fff
    style KAFKA fill:#231f20,color:#fff
```

---

## 🛠️ 技術スタック

| レイヤ                     | 🔧 技術                             | 📌 バージョン  |
| -------------------------- | ----------------------------------- | -------------- |
| **フロントエンド**         | React + Next.js (App Router)        | 18 / 14        |
| **UIコンポーネント**       | shadcn/ui + Radix UI + Tailwind CSS | latest         |
| **バックエンド**           | Python + FastAPI                    | 3.12 / 0.115   |
| **データベース**           | PostgreSQL + PostGIS + TimescaleDB  | 16 / 3.4 / 2.x |
| **キャッシュ**             | Redis                               | 7              |
| **メッセージキュー**       | RabbitMQ / Apache Kafka             | 3.13 / 3.7     |
| **検索エンジン**           | Elasticsearch + Kibana              | 8.14           |
| **オブジェクトストレージ** | MinIO (S3互換)                      | latest         |
| **AI/ML**                  | PyTorch + LangChain + LlamaIndex    | latest         |
| **コンテナ**               | Docker + Kubernetes                 | latest         |
| **CI/CD**                  | GitHub Actions                      | latest         |
| **モノレポ管理**           | pnpm workspaces + Turborepo         | 9 / 2.x        |

---

## 📁 プロジェクト構造

```text
construction-enterprise-os/
├── 📱 apps/                        🖥️ デプロイ可能アプリ
│   ├── web/                        Next.js フロントエンド
│   └── mobile/                     PWA / モバイル
├── ⚙️ services/                    バックエンド マイクロサービス (22)
│   ├── 🔐 auth/                    統合認証基盤
│   ├── 🌐 gateway/                 API Gateway
│   ├── 📄 document/                文書管理
│   ├── 🔄 workflow/                ワークフローエンジン
│   ├── 🗺️ gis/                     GIS統合基盤
│   ├── 📡 iot/                     IoT統合基盤
│   ├── 🤖 ai/                      AI共通基盤
│   ├── 👁️ vision/                  画像AI/OCR
│   ├── 💰 erp/                     ERP経営管理
│   ├── ⛑️ safety/                  安全管理
│   ├── 🏗️ field-dx/                現場DX
│   ├── 🤝 partner/                 協力会社連携
│   ├── 🔒 security/                セキュリティ
│   ├── 🔮 maintenance/             維持管理
│   ├── 📊 analytics/               データレイク/BI
│   ├── ⚡ automation/              自動化/RPA
│   ├── 🚢 advanced/                港湾/点検/設計照査
│   ├── 🧠 autonomous/              自律化エンジン
│   ├── 🏢 platform/                共通プラットフォーム
│   ├── 🔔 notification/            統合通知
│   ├── 🏗️ bim/                     BIM/CIM基盤
│   └── 🏗️ construction/            施工管理
├── 📦 packages/                    共有パッケージ (5)
│   ├── 🎨 ui/                      共通UIコンポーネント
│   ├── 🧬 core/                    共通型定義・定数
│   ├── 🔐 auth-core/               認証共通ロジック
│   ├── 📨 event-core/              イベント共通定義
│   └── 📊 logging/                 統合ログ基盤
├── ☸️ infra/                        IaC
│   ├── terraform/                  Terraform設定
│   ├── kubernetes/                 K8sマニフェスト
│   └── docker/                     Dockerfile群
├── 📚 docs/                        設計ドキュメント
│   └── architecture/               アーキテクチャ設計書
└── 🔧 scripts/                     ユーティリティ
    └── db/init/                    DB初期化スクリプト
```

---

## 📊 開発状況 — 全23サービス

```mermaid
pie title テスト構成（サービス別の目安）
    "Foundation 層" : 76
    "Data & AI 層" : 184
    "Platform 層" : 117
    "Business 層" : 57
    "Autonomous 層" : 17
```

| 🔢 レイヤ        | 🧩 コンポーネント   | 📁 サービス                  | 🧪 テスト | 📊 状態 |
| ---------------- | ------------------- | ---------------------------- | --------- | ------- |
| **① Foundation** | 🔐 認証基盤         | `services/auth/`             | 30        | ✅      |
|                  | 🌐 API Gateway      | `services/gateway/`          | 9         | ✅      |
|                  | 📨 イベント基盤     | `packages/event-core/`       | —         | ✅      |
|                  | 📊 共通ログ         | `packages/logging/`          | 24        | ✅      |
|                  | 🔔 共通通知         | `services/notification/`     | 13        | ✅      |
|                  | 🛡️ 権限管理 (RBAC)  | `services/auth/`             | —         | ✅      |
|                  | 📝 監査証跡         | `services/auth/`             | —         | ✅      |
|                  | 🎨 統合UI           | `packages/ui/` + `apps/web/` | —         | ✅      |
| **② Data & AI**  | 🗺️ GIS              | `services/gis/`              | 25        | ✅      |
|                  | 📄 文書管理         | `services/document/`         | 12        | ✅      |
|                  | 📡 IoT              | `services/iot/`              | 22        | ✅      |
|                  | 🤖 AI               | `services/ai/`               | 29        | ✅      |
|                  | 🏗️ BIM/CIM          | `services/bim/`              | 35        | ✅      |
|                  | 👁️ OCR/画像AI       | `services/vision/`           | 17        | ✅      |
|                  | 🧬 ベクトルDB       | `services/vision/`           | 17        | ✅      |
|                  | 🗄️ データレイク     | `services/analytics/`        | 27        | ✅      |
| **③ Platform**   | 🔄 ワークフロー     | `services/workflow/`         | 17        | ✅      |
|                  | 🔒 セキュリティ     | `services/security/`         | 23        | ✅      |
|                  | 🤝 協力会社連携     | `services/partner/`          | 21        | ✅      |
|                  | 📱 モバイル/PWA     | `apps/mobile/`               | —         | ✅      |
|                  | ⚡ 自動化/RPA       | `services/automation/`       | 12        | ✅      |
|                  | 🏢 共通PF           | `services/platform/`         | 22        | ✅      |
| **④ Business**   | 💰 ERP/経営         | `services/erp/`              | 27        | ✅      |
|                  | ⛑️ 安全管理         | `services/safety/`           | 14        | ✅      |
|                  | 🏗️ 現場DX           | `services/field-dx/`         | 20        | ✅      |
|                  | 🔮 維持管理         | `services/maintenance/`      | 18        | ✅      |
|                  | 🚢 港湾/点検        | `services/advanced/`         | 17        | ✅      |
| **⑤ Autonomous** | 🧠 AI Agent         | `services/autonomous/`       | 17        | ✅      |
|                  | 👥 デジタルツイン   | `services/autonomous/`       | 17        | ✅      |
|                  | 🎯 自動最適化       | `services/autonomous/`       | 17        | ✅      |
|                  | 🚜 自律施工         | 未着手                       | —         | ⚪      |
|                  | 🌊 海洋ロボティクス | 未着手                       | —         | ⚪      |
|                  | 🎮 自律制御         | 未着手                       | —         | ⚪      |

> **総計: 23サービス + 5パッケージ + 2アプリ | サービスPython 694 + Web 229 テスト（CI 実行）**

---

## 🚀 開発フェーズ ロードマップ

```mermaid
gantt
    title Construction-Enterprise-OS 開発ロードマップ
    dateFormat  YYYY-MM
    axisFormat  %Y-%m
    section 🏗️ Phase 0: 基盤構築
        認証基盤MVP          :done, p0a, 2026-05, 2026-06
        API Gateway          :done, p0b, 2026-05, 2026-06
        イベント/通知/ログ   :done, p0c, 2026-05, 2026-06
        UI Design System     :done, p0d, 2026-05, 2026-06
    section 🧩 Phase 1: 共通基盤
        権限管理 RBAC        :active, p1a, 2026-06, 2026-08
        監査証跡             :p1b, 2026-07, 2026-08
        マルチテナント       :p1c, 2026-08, 2026-09
    section 📡 Phase 2: ドメイン基盤
        文書管理             :p2a, 2026-07, 2026-10
        GIS 統合             :p2b, 2026-08, 2026-10
        IoT 統合             :p2c, 2026-09, 2026-12
        AI 基盤              :p2d, 2026-10, 2027-01
        BIM/CIM              :p2e, 2026-11, 2027-02
    section 📱 Phase 3: 業務アプリ
        ワークフロー         :p3a, 2026-08, 2026-11
        ERP/経営管理         :p3b, 2026-10, 2027-02
        現場DX               :p3c, 2026-11, 2027-03
        協力会社連携         :p3d, 2027-01, 2027-03
        モバイル/PWA         :p3e, 2027-02, 2027-04
    section 🛡️ Phase 4: 統制
        セキュリティ/SOC     :p4a, 2027-03, 2027-06
        ゼロトラスト         :p4b, 2027-04, 2027-06
    section 🧠 Phase 5: 自律化
        AI Agent             :p5a, 2027-01, 2027-06
        デジタルツイン       :p5b, 2027-03, 2027-07
        自律施工/制御        :p5c, 2027-06, 2027-10
    section 🚀 Phase 6: 本番
        安定化・リリース     :p6, 2027-07, 2027-11
```

---

## 🗂️ データフロー概要

```mermaid
sequenceDiagram
    actor User as 👤 ユーザー
    participant Web as 🖥️ Web/Mobile
    participant GW as 🌐 API Gateway
    participant Auth as 🔐 認証サービス
    participant Svc as ⚙️ 業務サービス
    participant Event as 📨 Kafka Event Bus
    participant DB as 💾 PostgreSQL
    participant Search as 🔍 Elasticsearch

    User->>Web: ログイン
    Web->>GW: POST /auth/login
    GW->>Auth: 認証リクエスト
    Auth->>DB: ユーザー検証
    DB-->>Auth: ユーザー情報
    Auth-->>GW: JWT トークン
    GW-->>Web: 認証成功 + Token

    User->>Web: 業務操作 (文書アップロード等)
    Web->>GW: REST API (Bearer Token)
    GW->>Auth: トークン検証
    Auth-->>GW: 検証OK
    GW->>Svc: サービス呼出
    Svc->>DB: データ永続化
    Svc->>Event: イベント発行
    Event->>Search: 検索インデックス更新
    Event->>Svc: 他サービス通知
    Svc-->>GW: レスポンス
    GW-->>Web: API レスポンス
    Web-->>User: 操作結果表示
```

---

## 🖥️ WebUI → Backend API 統合アーキテクチャ

```mermaid
graph LR
    subgraph "🖥️ Next.js App (:3100)"
        LP["🔑 /login\nuseAuthStore"]
        DB["📊 /dashboard"]
        DOCS["📄 /documents"]
        PROJ["🏗️ /projects"]
        WF["🔄 /workflows"]
        IOT["📡 /iot"]
        GIS["🗺️ /gis"]
        AC["🔗 api-client.ts\nBearer JWT"]
    end

    subgraph "🌐 API Gateway (:9000)"
        GW["FastAPI Gateway\nJWT 検証 + ルーティング"]
    end

    subgraph "⚙️ マイクロサービス"
        AUTH["🔐 Auth :8000"]
        DOC_SVC["📄 Document :8001"]
        WF_SVC["🔄 Workflow :8002"]
        GIS_SVC["🗺️ GIS :8003"]
        IOT_SVC["📡 IoT :8004"]
        CONST_SVC["🏗️ Construction :8016"]
    end

    LP & DB & DOCS & PROJ & WF & IOT & GIS --> AC
    AC -->|"/api/v1/* rewrites"| GW
    GW -->|"^/api/v1/auth"| AUTH
    GW -->|"^/api/v1/documents"| DOC_SVC
    GW -->|"^/api/v1/workflow"| WF_SVC
    GW -->|"^/api/v1/gis"| GIS_SVC
    GW -->|"^/api/v1/iot"| IOT_SVC
    GW -->|"^/api/v1/construction"| CONST_SVC

    style GW fill:#1a56db,color:#fff
    style AC fill:#16a34a,color:#fff
```

### 📋 ダッシュボードページ一覧

| 🖥️ ページ    | 📡 APIエンドポイント                 | 🔄 更新方式            | ⬛ フォールバック |
| ------------ | ------------------------------------ | ---------------------- | ----------------- |
| `/login`     | `POST /api/v1/auth/login`            | フォーム送信           | —                 |
| `/dashboard` | `/api/v1/construction/schedules`     | useEffect              | モックデータ      |
| `/documents` | `GET /api/v1/documents`              | useEffect              | モックデータ      |
| `/projects`  | `GET /api/v1/construction/schedules` | useEffect              | モックデータ      |
| `/workflows` | `GET /api/v1/workflow/instances`     | useEffect + アクション | モックデータ      |
| `/iot`       | `GET /api/v1/iot/devices`            | 30秒自動リフレッシュ   | モックデータ      |
| `/gis`       | `GET /api/v1/gis/sites`              | useEffect              | モックデータ      |

> 💡 **グレースフルフォールバック**: バックエンド未起動時はモックデータを表示するため、フロントエンド単体でも完全動作します。

---

## 🚀 クイックスタート

### 📦 前提条件

- **Node.js** >= 20 | **pnpm** >= 9
- **Python** >= 3.12
- **Docker** + Docker Compose

### ⚡ 開発環境起動

```bash
# 1. クローン
git clone https://github.com/Kensan196948G/Construction-Enterprise-OS.git
cd Construction-Enterprise-OS

# 2. インフラ起動 (PostgreSQL, Redis, Kafka, ES, MinIO)
make up
# または: docker compose up -d

# 3. Auth Service 起動
cd services/auth
cp .env.example .env
make auth-dev
# → http://localhost:8000/docs でSwagger UI表示

# 4. API Gateway 起動
cd services/gateway
uvicorn src.main:app --host 0.0.0.0 --port 9000 --reload
# → http://localhost:9000/docs

# 5. DBマイグレーション
make db-migrate

# 6. シードデータ投入
cd services/auth && python -m src.seed

# 7. Web フロントエンド起動
cd apps/web
pnpm install
pnpm dev
# → http://localhost:3100

# 8. テスト実行
make test
```

### 🔑 開発用ログイン情報

資格情報はコードに埋め込んでいません。環境変数で渡します。

| 変数 | 用途 |
| --- | --- |
| `ADMIN_EMAIL` / `ADMIN_PASSWORD` | `python -m src.seed` での管理ユーザ作成 |
| `E2E_ADMIN_EMAIL` / `E2E_ADMIN_PASSWORD` | Playwright E2E（`e2e/api.spec.ts`、CI では GitHub Secrets） |

---

## 📚 ドキュメント

| 📄 ドキュメント                                                       | 📝 内容                                       |
| --------------------------------------------------------------------- | --------------------------------------------- |
| [🏛️ 全体アーキテクチャ設計](docs/architecture/00-overview.md)         | 5レイヤ構造、開発計画、ADR                    |
| [🏛️ ADR-0001: CEOS の責任範囲](docs/architecture/ADR-0001-ceos-responsibility-boundary.md) | 工程・原価・契約の正本と MCIP/CDE/ArcSphere/MCAH の境界（V3.5準拠） |
| [🔌 ADR-0002: MCP 読み取り専用公開](docs/architecture/ADR-0002-ceos-mcp-readonly-publication.md) | 5ツール/hash-pinning/キルスイッチ、Core 契約整合 |
| [🔑 ADR-0003: MCP audience 分離とトークン交換](docs/architecture/ADR-0003-mcp-audience-token-exchange.md) | RFC 8693 交換・段階導入（Phase 0〜3）・fail-closed |
| [📜 Harness-Core 契約固定参照](contracts/vendor/harness-core/v0.6.0/VENDORED.md) | Core v0.6.0 固定（lock/sha256）と `contracts/mcp-tools/ceos.json` |
| [🔐 統合認証基盤 詳細設計](docs/architecture/01-auth-platform.md)     | データモデル/API/トークン/セキュリティ        |
| [🗄️ 統合データ基盤 詳細設計](docs/architecture/02-data-platform.md)   | PostgreSQL+PostGIS+TimescaleDB/マルチスキーマ |
| [🌐 API Gateway & イベント基盤](docs/architecture/03-api-gateway.md)  | Gateway+EventBus+Webhook設計                  |
| [🎨 共通UI・通知・ログ基盤](docs/architecture/04-common-platforms.md) | Design System/通知/ログ/検索                  |
| [🎨 OpenDesign 設計仕様](docs/design/opendesign-spec.md)               | 画面構成14カテゴリ/約90ルート/6ロール/ブランド |
| [📋 要件と MVP スコープ](docs/requirements/mvp-scope.md)               | OpenDesign との整合・未実装・残存リスク        |
| [🌐 API 概要・エンドポイント一覧](docs/api/overview.md)                | Gateway ルーティング/全サービスAPI            |
| [🗄️ Neon データベース運用](docs/operations/neon-database.md)           | 空検証DBへの Migration/Seed 再実行手順        |
| [🚀 デプロイ・ドメイン運用](docs/operations/deployment.md)             | Pages/Tunnel/DNS/ロールバック                 |
| [✅ 完了条件チェックリスト](docs/operations/completion-checklist.md)   | Goal 完了条件と証拠の一覧                     |

---

## 🛡️ セキュリティ

| 🔐 項目      | 🛠️ 方式              | 📋 詳細                |
| ------------ | -------------------- | ---------------------- |
| パスワード   | bcrypt               | cost >= 12             |
| JWT          | HS256 共有鍵          | 非開発環境で鍵未設定なら起動を拒否（fail-fast, #57）。本番前に RS256 化を検討 |
| MFA          | TOTP (RFC 6238)      | 有効化（/mfa/activate）・バックアップコードをハッシュ保存し単回消費 |
| ロックアウト | 5回連続失敗          | 15分ロック             |
| レート制限   | `/auth/login`        | 10回/分/IP             |
| 監査ログ     | 全認証イベント記録   | 改ざん検知             |
| API キー     | SHA-256 ハッシュ保存 | 作成時のみ平文返却     |

---

## 📜 ライセンス

**Proprietary** — All Rights Reserved

---

> 💚 **最終更新**: 2026-09-23 | 🟢 **ステータス**: STABLE | 🧪 **サービスPython 694 + Web 229 テスト CI 成功** | ⚙️ **23サービス** | 🏛️ **ADR-0001 で責任範囲を定義** | 🔌 **MCP: Harness-Core v0.6.0 契約整合（#93）** | 🔑 **ADR-0003 audience 分離・トークン交換（#95、Phase 0：既定無効／auth 103・MCP 81・gateway 27 passed）**
