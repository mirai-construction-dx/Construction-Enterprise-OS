# 統合データ基盤 (Data Platform) 詳細設計

## 1. 責務

Construction-Enterprise-OSの全データを統合管理する「OSのファイルシステム」。
複数の専門DBを論理的に統合し、単一のデータアクセスレイヤを提供する。

## 2. データストア構成

### 2.1 物理ストア

| ストア | 技術 | 用途 |
|---|---|---|
| RDB (OLTP) | PostgreSQL 16 | トランザクション処理全般 |
| GIS拡張 | PostGIS 3.4 | 空間データ管理 |
| 時系列拡張 | TimescaleDB 2.x | IoTセンサーデータ、メトリクス |
| キャッシュ | Redis 7 | セッション、頻出データ |
| 全文検索 | Elasticsearch 8 | 文書検索、ログ検索、分析 |
| オブジェクト | MinIO (S3互換) | PDF/CAD/BIM/画像/動画 |
| メッセージ | RabbitMQ / Kafka | 非同期処理、イベント |
| グラフDB | Neo4j AuraDB (評価中) | 依存関係、BOM、組織構造 |
| ベクトルDB | pgvector / Qdrant | AI埋め込み、RAG |

### 2.2 データカテゴリ分類

```
Construction-Enterprise-OS データ
├── マスターデータ        → PostgreSQL (一元管理)
│   ├── 組織・ユーザー
│   ├── 工事マスター
│   ├── 資材マスター
│   ├── 単価マスター
│   └── コードマスター
│
├── トランザクションデータ  → PostgreSQL (サービス別スキーマ)
│   ├── 稟議・承認
│   ├── 契約・発注
│   ├── 作業日報
│   └── 品質記録
│
├── 時系列データ          → TimescaleDB
│   ├── センサーデータ
│   ├── 気象データ
│   ├── 機械稼働ログ
│   └── 位置トラッキング
│
├── 空間データ            → PostGIS
│   ├── 現場位置
│   ├── 工事範囲ポリゴン
│   ├── インフラ位置
│   └── 測量データ
│
├── 文書・メディア        → MinIO + Elasticsearch(メタデータ)
│   ├── PDF図面
│   ├── CADファイル
│   ├── BIMモデル
│   ├── 現場写真/動画
│   └── 電子納品成果
│
├── 監査ログ              → PostgreSQL（パーティション）
│   ├── 認証ログ
│   ├── 操作ログ
│   ├── データ変更履歴
│   └── APIアクセスログ
│
└── AIデータ              → pgvector + MinIO
    ├── 埋め込みベクトル
    ├── 学習データセット
    ├── アノテーション
    └── モデルメタデータ
```

## 3. PostgreSQL スキーマ設計方針

### 3.1 マルチスキーマ構成

```sql
-- スキーマ分割（スキーマ = ドメイン境界）
CREATE SCHEMA auth;          -- 認証・認可
CREATE SCHEMA master;        -- マスターデータ
CREATE SCHEMA project;       -- 工事管理
CREATE SCHEMA workflow;      -- 承認ワークフロー
CREATE SCHEMA document;      -- 文書管理メタデータ
CREATE SCHEMA erp;           -- 経営管理
CREATE SCHEMA safety;        -- 安全管理
CREATE SCHEMA quality;       -- 品質管理
CREATE SCHEMA partner;       -- 協力会社
CREATE SCHEMA audit;         -- 監査ログ
CREATE SCHEMA iot;           -- IoTメタデータ
```

### 3.2 監査証跡（全テーブル共通）

```sql
-- 全テーブルの基底カラム
id          UUID PRIMARY KEY DEFAULT gen_random_uuid()
created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
created_by  UUID REFERENCES auth.users(id)
updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
updated_by  UUID REFERENCES auth.users(id)
deleted_at  TIMESTAMPTZ          -- 論理削除
version     INTEGER DEFAULT 1     -- 楽観ロック
```

## 4. データアクセスレイヤ

### 4.1 データフェデレーション

```
┌─────────────────────────────────────────────┐
│         Data Federation Layer (GraphQL)       │
│  ┌──────────┬──────────┬──────────────────┐ │
│  │  Query   │ Mutation │   Subscription    │ │
│  └──────────┴──────────┴──────────────────┘ │
├─────────────────────────────────────────────┤
│          Data Access Service (FastAPI)        │
│  ┌──────────┬──────────┬──────────────────┐ │
│  │ REST API │  View    │  Materialized V.  │ │
│  └──────────┴──────────┴──────────────────┘ │
├─────────────────────────────────────────────┤
│              Storage Layer                    │
│  ┌────┬────┬──────┬──────┬────┬───────────┐ │
│  │ PG │TSDB│Redis │ ES   │ S3 │ pgvector  │ │
│  └────┴────┴──────┴──────┴────┴───────────┘ │
└─────────────────────────────────────────────┘
```

### 4.2 ポリシー

1. **マスターデータ**: 全サービス参照は Data Access Service 経由（キャッシュ: Redis）
2. **トランザクションデータ**: サービス自身が所有（他サービスはAPI経由で取得）
3. **時系列データ**: 書き込みは高速パス（MQTT→直接TimescaleDB）、読み取りはAPI経由
4. **文書・メディア**: MinIOに保存、メタデータはPostgreSQL、全文検索はElasticsearch
5. **監査ログ**: 全サービスがイベントバスにPublish、ログサービスが集約書き込み

## 5. データガバナンス

### 5.1 データ分類
| 分類 | 説明 | 暗号化 | 保存期間 |
|---|---|---|---|
| 機密 | 個人情報、財務、入札 | AES-256 暗号化 | 10年 |
| 内部限定 | 工事データ、契約 | 転送時TLS | 10年 |
| 関係者限り | 協力会社共有データ | 転送時TLS | 工事完了後5年 |
| 公開 | 公開情報 | - | 任意 |

### 5.2 データライフサイクル
```
作成 → 利用 → アーカイブ（5年後） → 削除（10年後）
                    ↓
              コールドストレージ (MinIO)
```

## 6. 開発環境構成

```yaml
# docker-compose.yml (開発用)
services:
  postgres:
    image: postgis/postgis:16-3.4
    environment:
      POSTGRES_USER: construction-os
      POSTGRES_PASSWORD: construction-os_dev
      POSTGRES_DB: construction-os
    ports: ["5432:5432"]
    volumes: [pgdata:/var/lib/postgresql/data]

  timescaledb:
    image: timescale/timescaledb:2.16.1-pg16
    environment:
      POSTGRES_USER: construction-os
      POSTGRES_PASSWORD: construction-os_dev
      POSTGRES_DB: construction-os_ts
    ports: ["5433:5432"]

  redis:
    image: redis:7-alpine
    ports: ["6379:6379"]

  elasticsearch:
    image: elasticsearch:8.14.0
    environment:
      discovery.type: single-node
      xpack.security.enabled: false
    ports: ["9200:9200"]

  minio:
    image: minio/minio:RELEASE.2025-09-07T16-13-09Z
    command: server /data --console-address ":9001"
    environment:
      MINIO_ROOT_USER: minioadmin
      MINIO_ROOT_PASSWORD: minioadmin
    ports: ["9000:9000", "9001:9001"]

  rabbitmq:
    image: rabbitmq:3-management-alpine
    ports: ["5672:5672", "15672:15672"]
```
