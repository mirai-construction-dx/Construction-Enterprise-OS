# Construction-Enterprise-OS 開発用 Makefile

.PHONY: help dev up down build test lint clean schema-bootstrap schema-generate schema-check session-check ddl-coverage ci-coverage repo-invariants

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
	@scripts/db/bootstrap_schema.sh "$${DATABASE_URL:?DATABASE_URL を設定してください}"
	cd services/auth && alembic upgrade head
	cd services/workflow && alembic upgrade head

db-rollback: ## マイグレーションを1つ戻す(auth のみ。他はサービス単位で実行する)
	cd services/auth && alembic downgrade -1

db-seed: ## 開発用シード投入(マイグレーション適用後に実行。冪等)
	scripts/db/seed_dev.sh "$${DATABASE_URL:?DATABASE_URL を設定してください}"

schema-bootstrap: ## 空DBへ全SQLマイグレーションを適用 (DATABASE_URL 必須)
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

repo-invariants: schema-check session-check ddl-coverage ci-coverage ## サービス横断の不変条件をまとめて検証(CI の matrix では検出できないもの)
	@echo "✅ リポジトリ不変条件 OK"

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
