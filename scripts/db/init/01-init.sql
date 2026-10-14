-- Construction-Enterprise-OS データベース初期化（開発用 compose の postgres コンテナ）
-- docker-entrypoint-initdb.d として **DB 作成直後に 1 度だけ** 実行される。
--
-- ここでスキーマだけを作る理由（2026-10-14 実測の是正）:
--   旧版はこのファイルから auth.organizations / auth.permissions へ INSERT していたが、
--   それらの表はサービス側のマイグレーション（alembic）が作るため、初期化時点には存在しない。
--   docker-entrypoint は .sql を `psql -v ON_ERROR_STOP=1` で流すので、空の DB では
--     ERROR: リレーション"auth.organizations"は存在しません   （psql exit=3）
--   となり、**コンテナが起動しなかった**（実測）。
--   シードはマイグレーション適用後に流す必要があるため scripts/db/seed/ へ移した。
--   適用は `scripts/db/seed_dev.sh`（make db-seed）。
--
-- スキーマの正本は各サービスのマイグレーションである。ここに並ぶのは
-- 「マイグレーションが作るスキーマ」と一致していることを検査で担保するための控えであり、
-- ここにしか無いスキーマを足してはならない（scripts/db/check_service_ddl_coverage.py が検査する）。
--
-- 2026-10-14: master / project / quality / audit を削除した。
--   これらは本ファイルだけが作っており、サービス・マイグレーション・alembic の
--   いずれからもスキーマ修飾で参照されていなかった（参照 0 件を実測）。
--   staging には存在せず、dev と stg のスキーマ集合が食い違う原因になっていた。

-- ============================================================
-- スキーマ作成（マイグレーションと同じ集合）
-- ============================================================
CREATE SCHEMA IF NOT EXISTS auth;
CREATE SCHEMA IF NOT EXISTS workflow;
CREATE SCHEMA IF NOT EXISTS document;
CREATE SCHEMA IF NOT EXISTS erp;
CREATE SCHEMA IF NOT EXISTS safety;
CREATE SCHEMA IF NOT EXISTS partner;
CREATE SCHEMA IF NOT EXISTS iot;
