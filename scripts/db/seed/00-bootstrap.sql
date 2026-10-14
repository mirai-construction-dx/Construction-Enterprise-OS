-- Construction-Enterprise-OS 開発用シード（組織・権限）
--
-- **マイグレーション適用後に** 実行する。表はサービス側のマイグレーションが作るため、
-- DB 初期化直後（docker-entrypoint-initdb.d）には流せない。
--   scripts/db/seed_dev.sh        （または make db-seed）
--
-- 冪等: どちらの INSERT も WHERE NOT EXISTS で既存行を飛ばす。
-- 合成データのみ。本番・顧客・現場の実データを入れない（AGENTS.md §4.4）。

-- ============================================================
-- 組織シード（複数企業・現場）
-- ============================================================
INSERT INTO auth.organizations (id, parent_id, name, name_kana, type, status, metadata, created_at, updated_at)
-- 2026-10-14: type / status は ENUM（auth.org_type / auth.org_status）であり、
-- VALUES 由来の text は暗黙キャストされない。旧版の `SELECT *` は
--   列"type"は型auth.org_typeですが、式は型textでした
-- で必ず失敗していた（マイグレーション後でも dev のシードは動いていなかった）。
SELECT t.id, t.parent_id, t.name, t.name_kana,
       t.type::auth.org_type, t.status::auth.org_status,
       t.metadata, t.created_at, t.updated_at
FROM (VALUES
    -- 本社
    ('00000000-0000-0000-0000-000000000001'::uuid, NULL,
     'Construction-Enterprise-OS 本社', 'シーイーオーオーエスホンシャ', 'company', 'active',
     '{"address":"東京都千代田区丸の内1-1-1","established":"2024-04-01","tax_id":"T010000000001"}'::jsonb,
     now(), now()),
    -- 建設事業部
    ('10000000-0000-0000-0000-000000000001'::uuid, '00000000-0000-0000-0000-000000000001'::uuid,
     '建設事業部', 'ケンセツジギョウブ', 'department', 'active',
     '{"address":"東京都中央区日本橋2-2-2"}'::jsonb,
     now(), now()),
    -- 土木事業部
    ('10000000-0000-0000-0000-000000000002'::uuid, '00000000-0000-0000-0000-000000000001'::uuid,
     '土木事業部', 'ドボクジギョウブ', 'department', 'active',
     '{"address":"東京都新宿区西新宿3-3-3"}'::jsonb,
     now(), now()),
    -- 東京北 現場
    ('20000000-0000-0000-0000-000000000001'::uuid, '10000000-0000-0000-0000-000000000001'::uuid,
     '東京北プロジェクト現場', 'トウキョウキタプロジェクトゲンバ', 'site', 'active',
     '{"address":"埼玉県さいたま市浦和区4-4-4","project_code":"TKN-2026-001"}'::jsonb,
     now(), now()),
    -- 東京南 現場
    ('20000000-0000-0000-0000-000000000002'::uuid, '10000000-0000-0000-0000-000000000001'::uuid,
     '東京南プロジェクト現場', 'トウキョウミナミプロジェクトゲンバ', 'site', 'active',
     '{"address":"神奈川県横浜市西区5-5-5","project_code":"TKN-2026-002"}'::jsonb,
     now(), now()),
    -- 大阪 現場
    ('20000000-0000-0000-0000-000000000003'::uuid, '10000000-0000-0000-0000-000000000001'::uuid,
     '大阪梅田プロジェクト現場', 'オオサカウメダプロジェクトゲンバ', 'site', 'active',
     '{"address":"大阪府大阪市北区梅田6-6-6","project_code":"OSK-2026-001"}'::jsonb,
     now(), now()),
    -- 仙台 現場
    ('20000000-0000-0000-0000-000000000004'::uuid, '10000000-0000-0000-0000-000000000002'::uuid,
     '仙台東道路現場', 'センダイヒガシドウロゲンバ', 'site', 'active',
     '{"address":"宮城県仙台市若林区7-7-7","project_code":"SDI-2026-001"}'::jsonb,
     now(), now()),
    -- 協力会社
    ('30000000-0000-0000-0000-000000000001'::uuid, NULL,
     '株式会社 山田組', 'カブシキガイシャヤマダグミ', 'partner', 'active',
     '{"address":"東京都江東区豊洲8-8-8","contract_date":"2024-04-01","rating":"A"}'::jsonb,
     now(), now()),
    ('30000000-0000-0000-0000-000000000002'::uuid, NULL,
     '佐藤建設工業 株式会社', 'サトウケンセツコウギョウカブシキガイシャ', 'partner', 'active',
     '{"address":"千葉県千葉市美浜区9-9-9","contract_date":"2024-07-01","rating":"B+"}'::jsonb,
     now(), now()),
    ('30000000-0000-0000-0000-000000000003'::uuid, NULL,
     '鈴木土木 株式会社', 'スズキドボクカブシキガイシャ', 'partner', 'active',
     '{"address":"愛知県名古屋市中区10-10-10","contract_date":"2025-01-15","rating":"A-"}'::jsonb,
     now(), now())
) AS t(id, parent_id, name, name_kana, type, status, metadata, created_at, updated_at)
WHERE NOT EXISTS (SELECT 1 FROM auth.organizations WHERE id = t.id);

-- ============================================================
-- 権限シード
-- ============================================================
INSERT INTO auth.permissions (id, resource, action, description)
SELECT *
FROM (VALUES
    -- ユーザー管理
    (gen_random_uuid(), 'users',         'read',    'ユーザー情報の閲覧'),
    (gen_random_uuid(), 'users',         'create',  'ユーザーの作成'),
    (gen_random_uuid(), 'users',         'update',  'ユーザー情報の更新'),
    (gen_random_uuid(), 'users',         'delete',  'ユーザーの削除'),
    -- ロール管理
    (gen_random_uuid(), 'roles',          'read',    'ロール情報の閲覧'),
    (gen_random_uuid(), 'roles',          'create',  'ロールの作成'),
    (gen_random_uuid(), 'roles',          'update',  'ロール情報の更新'),
    (gen_random_uuid(), 'roles',          'delete',  'ロールの削除'),
    -- 権限参照
    (gen_random_uuid(), 'permissions',    'read',    '権限一覧の閲覧'),
    -- 組織管理
    (gen_random_uuid(), 'organizations',  'read',    '組織情報の閲覧'),
    (gen_random_uuid(), 'organizations',  'create',  '組織の作成'),
    (gen_random_uuid(), 'organizations',  'update',  '組織情報の更新'),
    (gen_random_uuid(), 'organizations',  'delete',  '組織の削除'),
    -- 文書管理
    (gen_random_uuid(), 'documents',      'read',    '文書の閲覧'),
    (gen_random_uuid(), 'documents',      'create',  '文書の作成'),
    (gen_random_uuid(), 'documents',      'update',  '文書の更新'),
    (gen_random_uuid(), 'documents',      'approve', '文書の承認'),
    (gen_random_uuid(), 'documents',      'delete',  '文書の削除'),
    -- 工事管理
    (gen_random_uuid(), 'projects',       'read',    '工事情報の閲覧'),
    (gen_random_uuid(), 'projects',       'create',  '工事の作成'),
    (gen_random_uuid(), 'projects',       'update',  '工事情報の更新'),
    (gen_random_uuid(), 'projects',       'delete',  '工事の削除'),
    -- ワークフロー
    (gen_random_uuid(), 'workflow',       'read',    'ワークフローの閲覧'),
    (gen_random_uuid(), 'workflow',       'approve', 'ワークフローの承認'),
    -- IoT
    (gen_random_uuid(), 'iot',            'read',    'IoTデータの閲覧'),
    (gen_random_uuid(), 'iot',            'ingest',  'IoTデータの送信'),
    -- GIS/BIM
    (gen_random_uuid(), 'gis',            'read',    'GISデータの閲覧'),
    (gen_random_uuid(), 'bim',            'read',    'BIMデータの閲覧'),
    -- 安全管理
    (gen_random_uuid(), 'safety',         'read',    '安全管理データの閲覧'),
    (gen_random_uuid(), 'safety',         'report',  '安全報告の作成'),
    (gen_random_uuid(), 'safety',         'manage',  '安全管理の統括'),
    -- 品質管理
    (gen_random_uuid(), 'quality',        'read',    '品質管理データの閲覧'),
    (gen_random_uuid(), 'quality',        'report',  '品質報告の作成'),
    (gen_random_uuid(), 'quality',        'manage',  '品質管理の統括'),
    -- 経営管理
    (gen_random_uuid(), 'erp',            'read',    '経営データの閲覧'),
    (gen_random_uuid(), 'erp',            'create',  '経営データの作成'),
    (gen_random_uuid(), 'erp',            'update',  '経営データの更新'),
    -- 協力会社
    (gen_random_uuid(), 'partner',        'read',    '協力会社情報の閲覧'),
    (gen_random_uuid(), 'partner',        'manage',  '協力会社の管理'),
    -- 監査
    (gen_random_uuid(), 'audit',          'read',    '監査ログの閲覧'),
    -- API クライアント
    (gen_random_uuid(), 'api_clients',    'read',    'APIクライアント情報の閲覧'),
    (gen_random_uuid(), 'api_clients',    'create',  'APIクライアントの作成'),
    (gen_random_uuid(), 'api_clients',    'revoke',  'APIクライアントの無効化')
) AS t(id, resource, action, description)
WHERE NOT EXISTS (
    SELECT 1 FROM auth.permissions p
    WHERE p.resource = t.resource AND p.action = t.action
);
