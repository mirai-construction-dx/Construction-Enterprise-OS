-- bim スキーマ 基盤 DDL (自動生成 / 冪等)
--
-- 生成元: services/bim/src/models (SQLAlchemy メタデータ)
-- 再生成: python3 scripts/db/generate_base_schema.py bim
--
-- このファイルは models の定義と一致します。既存オブジェクトがある場合は
-- 何もせず、既存データを変更しません。

CREATE EXTENSION IF NOT EXISTS postgis;

CREATE SCHEMA IF NOT EXISTS bim;

SET search_path TO bim, public;

CREATE TABLE IF NOT EXISTS bim.bim_models (
	id UUID NOT NULL, 
	organization_id UUID NOT NULL, 
	project_id UUID, 
	name VARCHAR(500) NOT NULL, 
	description TEXT, 
	model_type VARCHAR(50) NOT NULL, 
	file_format VARCHAR(50) NOT NULL, 
	file_size BIGINT, 
	file_key VARCHAR(1000), 
	version VARCHAR(50), 
	status VARCHAR(20) NOT NULL, 
	author VARCHAR(255), 
	software VARCHAR(255), 
	coordinate_system VARCHAR(100), 
	bounding_box JSONB, 
	discipline VARCHAR(100), 
	lod VARCHAR(20), 
	tags TEXT[], 
	metadata JSONB, 
	uploaded_by UUID, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id)
);

CREATE TABLE IF NOT EXISTS bim.point_clouds (
	id UUID NOT NULL, 
	organization_id UUID NOT NULL, 
	project_id UUID, 
	name VARCHAR(500) NOT NULL, 
	description TEXT, 
	capture_method VARCHAR(50), 
	capture_date DATE, 
	point_count BIGINT, 
	file_size BIGINT, 
	file_format VARCHAR(50), 
	file_key VARCHAR(1000), 
	coordinate_system VARCHAR(100), 
	bounding_box JSONB, 
	density FLOAT, 
	accuracy_mm FLOAT, 
	is_colorized BOOLEAN NOT NULL, 
	is_classified BOOLEAN NOT NULL, 
	version VARCHAR(50), 
	source_model_id UUID, 
	source_video_id VARCHAR(255), 
	location geometry(POLYGON,4326), 
	metadata JSONB, 
	uploaded_by UUID, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id)
);

CREATE TABLE IF NOT EXISTS bim.bim_elements (
	id UUID NOT NULL, 
	model_id UUID NOT NULL, 
	element_id VARCHAR(255), 
	name VARCHAR(500), 
	element_type VARCHAR(100), 
	category VARCHAR(100), 
	properties JSONB, 
	quantity FLOAT, 
	unit VARCHAR(50), 
	level_name VARCHAR(100), 
	building_name VARCHAR(255), 
	location geometry(POINTZ,4326), 
	bounding_box JSONB, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(model_id) REFERENCES bim.bim_models (id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS ix_bim_models_discipline ON bim.bim_models (discipline);

CREATE INDEX IF NOT EXISTS ix_bim_models_format ON bim.bim_models (file_format);

CREATE INDEX IF NOT EXISTS ix_bim_models_org ON bim.bim_models (organization_id);

CREATE INDEX IF NOT EXISTS ix_bim_models_project ON bim.bim_models (project_id);

CREATE INDEX IF NOT EXISTS ix_bim_models_status ON bim.bim_models (status);

CREATE INDEX IF NOT EXISTS ix_bim_models_type ON bim.bim_models (model_type);

CREATE INDEX IF NOT EXISTS ix_point_clouds_location ON bim.point_clouds USING gist (location);

CREATE INDEX IF NOT EXISTS ix_point_clouds_method ON bim.point_clouds (capture_method);

CREATE INDEX IF NOT EXISTS ix_point_clouds_org ON bim.point_clouds (organization_id);

CREATE INDEX IF NOT EXISTS ix_point_clouds_project ON bim.point_clouds (project_id);

CREATE INDEX IF NOT EXISTS ix_bim_elements_category ON bim.bim_elements (category);

CREATE INDEX IF NOT EXISTS ix_bim_elements_level ON bim.bim_elements (level_name);

CREATE INDEX IF NOT EXISTS ix_bim_elements_location ON bim.bim_elements USING gist (location);

CREATE INDEX IF NOT EXISTS ix_bim_elements_model ON bim.bim_elements (model_id);

CREATE INDEX IF NOT EXISTS ix_bim_elements_type ON bim.bim_elements (element_type);
