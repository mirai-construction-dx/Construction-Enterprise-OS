# Construction-Enterprise-OS 開発用 Makefile

.PHONY: help dev up down build test lint clean schema-bootstrap schema-generate schema-check session-check ddl-coverage ci-coverage docs-links stg-pages-upstream tenant-conformance org-query-scoping health-coverage infra-consumers resource-limits secrets-hygiene static-guard-tests repo-invariants repo-invariants-ci

help: ## ヘルプ表示
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

# ============================================
# Docker 開発環境
# ============================================
up: ## 開発インフラ起動 (PostgreSQL, Redis, Kafka 他)
	docker compose up -d

down: ## 開発インフラ停止
	docker compose down

logs: ## コンテナログ表示
	docker compose logs -f

reset: ## 開発データ完全リセット
	docker compose down -v
	docker compose up -d

# ============================================
# バックエンド (Python/FastAPI)
# ============================================
auth-dev: ## Auth Service開発サーバー起動
	cd services/auth && uvicorn src.main:app --reload --host 0.0.0.0 --port 8000

auth-test: ## Auth Serviceテスト実行
	cd services/auth && python -m pytest tests/ -v -p no:flask

auth-lint: ## Auth Service lint実行
	cd services/auth && ruff check src/

auth-typecheck: ## Auth Service型チェック
	cd services/auth && mypy src/

# ============================================
# フロントエンド (Next.js)
# ============================================
web-dev: ## Webアプリ開発サーバー起動
	@echo "🌐 Starting on http://0.0.0.0:3100"
	@echo "📋 Network: http://$$(hostname -I | awk '{print $$1}'):3100"
	cd apps/web && pnpm dev

# ============================================
# データベース
# ============================================
db-migrate: ## マイグレーション実行(全サービスの SQL + auth/workflow の alembic)
	@# 2026-10-14: 旧実装は auth の alembic しか実行しておらず、README の手順どおりに
	@# 進めても workflow と他 20 サービスの表が作られなかった。
	@# 2026-10-14: DATABASE_URL は環境から無条件に来るため、他システムの DB を
	@# 掴んでいないかを先に検査する（本作業環境はハーネスが自分の DB を注入する）。
	@python3 scripts/db/check_target_db.py "$${DATABASE_URL:?DATABASE_URL を設定してください}"
	@scripts/db/bootstrap_schema.sh "$${DATABASE_URL:?DATABASE_URL を設定してください}"
	cd services/auth && alembic upgrade head
	cd services/workflow && alembic upgrade head

db-rollback: ## マイグレーションを1つ戻す(auth のみ。他はサービス単位で実行する)
	@python3 scripts/db/check_target_db.py "$${DATABASE_URL:?DATABASE_URL を設定してください}"
	cd services/auth && alembic downgrade -1

db-seed: ## 開発用シード投入(マイグレーション適用後に実行。冪等)
	@python3 scripts/db/check_target_db.py "$${DATABASE_URL:?DATABASE_URL を設定してください}"
	scripts/db/seed_dev.sh "$${DATABASE_URL:?DATABASE_URL を設定してください}"

schema-bootstrap: ## 空DBへ全SQLマイグレーションを適用 (DATABASE_URL 必須)
	@python3 scripts/db/check_target_db.py "$${DATABASE_URL:?DATABASE_URL を設定してください}"
	@scripts/db/bootstrap_schema.sh "$${DATABASE_URL:?DATABASE_URL を設定してください}"

schema-generate: ## ORMモデルから各サービスの基盤DDL(000_base_schema.sql)を再生成
	python3 scripts/db/generate_base_schema.py

schema-check: ## 基盤DDLがORMモデルと一致するか検証(乖離があれば失敗)
	python3 scripts/db/generate_base_schema.py --check

session-check: ## get_db が正常終了時に commit するか検証(暗黙ロールバックによる書込み消失の防止)
	python3 scripts/db/check_session_lifecycle.py

ddl-coverage: ## モデルを持つサービスが DDL の出所(migrations/ か alembic/)も持つか検証
	python3 scripts/db/check_service_ddl_coverage.py

ci-coverage: ## 各サービス/パッケージが CI のどこかで検査されているか検証
	python3 scripts/ci/check_coverage.py

docs-links: ## 追跡下の Markdown のローカルリンクが解決するか検証
	python3 scripts/docs/check_links.py

stg-pages-upstream: ## stg の Pages デプロイが本番 API を向いていないか検証(越境の防止)
	python3 scripts/stg/check_pages_upstream.py

tenant-conformance: ## 18 サービスの tenant ヘルパが同じ分離の振る舞いをするか検証
	python3 scripts/security/check_tenant_helper_conformance.py

org-query-scoping: ## クエリの organization_id が必ずテナントヘルパを通っているか検証(AST)
	python3 scripts/security/check_org_query_scoping.py

health-coverage: ## 集約ヘルスがゲートウェイの全上流を見ているか検証
	python3 scripts/ci/check_health_coverage.py

infra-consumers: ## 6基盤(redis/rabbitmq/kafka/elasticsearch/kibana/minio)の使われ方が実測どおりか検証
	python3 scripts/ci/check_infra_consumers.py

resource-limits: ## 全サービスに実行時へ反映される資源上限があるか検証
	python3 scripts/ci/check_memory_limits.py

secrets-hygiene: ## 秘密配置の限定ヒューリスティック検査（安全性証明ではない）
	python3 scripts/ci/check_secrets_hygiene.py

static-guard-tests: ## 静的ガードのオフライン回帰テスト
	python3 -B -m unittest discover -s scripts/ci -p 'test_*.py' -v

repo-invariants: secrets-hygiene static-guard-tests schema-check session-check ddl-coverage ci-coverage docs-links stg-pages-upstream tenant-conformance org-query-scoping health-coverage infra-consumers resource-limits ## リポジトリ横断の不変条件をまとめて検証(CI の matrix では検出できないもの)
	@echo "✅ リポジトリ不変条件 OK"

# CI 用（依存の軽い検査だけを回す）。
# schema-check は各サービスのモデルを import するため sqlalchemy と各サービスの
# 依存が要る（scripts/db/generate_base_schema.py の emit_metadata が
# `sys.executable -c EMITTER` をサービス単位で起動する）。素のランナーでは失敗するので
# CI では python-checks マトリクスがサービス単位で担当する（ci.yml の
# "Base schema DDL is in sync with models"）。
# マトリクスへの登録漏れは ci-coverage が検出するため、全サービスの被覆は保たれる。
# tenant-conformance は各サービスの src.middleware.tenant を import するため
# fastapi / PyJWT / pydantic-settings が要る（docs/operations/repo-invariants.workflow.yml）。
# org-query-scoping は標準ライブラリ（ast）だけで動く。health-coverage は PyYAML を使う。
# infra-consumers（ast + PyYAML）と resource-limits（PyYAML）も依存が軽いので CI で回す。
repo-invariants-ci: secrets-hygiene static-guard-tests session-check ddl-coverage ci-coverage docs-links stg-pages-upstream tenant-conformance org-query-scoping health-coverage infra-consumers resource-limits ## CI で回す不変条件(軽量な依存のみ)
	@echo "✅ CI 用のリポジトリ不変条件 OK（schema-check は python-checks が担当）"

# ============================================
# コード品質
# ============================================
test: auth-test ## 全テスト実行

lint: auth-lint ## 全lint実行

format: ## コードフォーマット
	cd services/auth && ruff format src/
	prettier --write "**/*.{ts,tsx,json,md,yaml,yml}"

# ============================================
# Git
# ============================================
git-status: ## Git状態確認
	git status

git-log: ## Gitログ表示
	git log --oneline -20
