#!/usr/bin/env bash
# stg の `ceos_stg` で、アプリロールへ各スキーマの権限を与える。
#
# なぜ必要か:
#   `bootstrap_stg_db.sh` は public スキーマにしか DEFAULT PRIVILEGES を設定しない。
#   各サービスは自分のスキーマ（auth / document / notification / ...）を
#   マイグレーションで作り、その中に表を作る。したがって
#   「表が作られた後に、スキーマごとの権限を与える」処理が別に要る。
#   これが無いと notification のように起動時に書き込むサービスが
#   permission denied で起動に失敗する（2026-10-14 実測）。
#
# 冪等。マイグレーション適用のたびに実行してよい（migrate_stg.sh から呼ばれる）。
#
# 使い方:
#   scripts/stg/grant_stg_privileges.sh
set -euo pipefail

PORT="${STG_PG_PORT:-55438}"
DB_NAME="${STG_DB_NAME:-ceos_stg}"
APP_ROLE="${STG_DB_APP_ROLE:-ceos_stg_app}"
MIGRATOR_ROLE="${STG_DB_MIGRATOR_ROLE:-ceos_stg_migrator}"
AUDIT_ROLE="${STG_DB_AUDIT_ROLE:-ceos_stg_audit_reader}"

echo "== スキーマ権限の付与（$DB_NAME） =="
sudo -n -u postgres psql -p "$PORT" -d "$DB_NAME" -v ON_ERROR_STOP=1 -q <<SQL
DO \$\$
DECLARE
  s text;
BEGIN
  FOR s IN
    SELECT nspname FROM pg_namespace
     WHERE nspname NOT IN ('pg_catalog', 'information_schema', 'pg_toast')
       AND nspname NOT LIKE 'pg\_%'
  LOOP
    -- 参照とDML
    EXECUTE format('GRANT USAGE ON SCHEMA %I TO %I, %I', s, '${APP_ROLE}', '${AUDIT_ROLE}');
    EXECUTE format('GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA %I TO %I', s, '${APP_ROLE}');
    EXECUTE format('GRANT SELECT ON ALL TABLES IN SCHEMA %I TO %I', s, '${AUDIT_ROLE}');
    EXECUTE format('GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA %I TO %I', s, '${APP_ROLE}');
    -- 今後 migrator が作る表・シーケンスにも同じ権限を自動で付ける
    EXECUTE format(
      'ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA %I GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO %I',
      '${MIGRATOR_ROLE}', s, '${APP_ROLE}');
    EXECUTE format(
      'ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA %I GRANT SELECT ON TABLES TO %I',
      '${MIGRATOR_ROLE}', s, '${AUDIT_ROLE}');
    EXECUTE format(
      'ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA %I GRANT USAGE, SELECT ON SEQUENCES TO %I',
      '${MIGRATOR_ROLE}', s, '${APP_ROLE}');
  END LOOP;
END
\$\$;
SQL

echo "== 実測（アプリロールで書き込めるか） =="
sudo -n -u postgres psql -p "$PORT" -d "$DB_NAME" -tAc "
  SELECT string_agg(nspname, ' ' ORDER BY nspname)
    FROM pg_namespace n
   WHERE nspname NOT IN ('pg_catalog','information_schema','pg_toast')
     AND nspname NOT LIKE 'pg\_%'
     AND has_schema_privilege('${APP_ROLE}', nspname, 'USAGE')"
echo
echo "完了: アプリロール ${APP_ROLE} が全文スキーマを USAGE できる。"
