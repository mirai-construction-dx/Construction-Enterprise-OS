-- partner スキーマ 基盤 DDL (自動生成 / 冪等)
--
-- 生成元: services/partner/src/models (SQLAlchemy メタデータ)
-- 再生成: python3 scripts/db/generate_base_schema.py partner
--
-- このファイルは models の定義と一致します。既存オブジェクトがある場合は
-- 何もせず、既存データを変更しません。

CREATE SCHEMA IF NOT EXISTS partner;

SET search_path TO partner, public;

CREATE TABLE IF NOT EXISTS partner.partners (
	id UUID NOT NULL, 
	organization_id UUID NOT NULL, 
	name VARCHAR(255) NOT NULL, 
	name_kana VARCHAR(255), 
	company_type VARCHAR(50) NOT NULL, 
	tax_id VARCHAR(50), 
	address VARCHAR(500), 
	phone VARCHAR(20), 
	email VARCHAR(255), 
	website VARCHAR(500), 
	representative_name VARCHAR(255), 
	employee_count INTEGER, 
	established_year INTEGER, 
	specializations TEXT[], 
	license_info JSONB, 
	insurance_info JSONB, 
	status VARCHAR(20) NOT NULL, 
	rating FLOAT, 
	registered_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id)
);

CREATE TABLE IF NOT EXISTS partner.contracts (
	id UUID NOT NULL, 
	organization_id UUID NOT NULL, 
	partner_id UUID, 
	project_id UUID, 
	contract_number VARCHAR(100), 
	title VARCHAR(500) NOT NULL, 
	contract_type VARCHAR(50) NOT NULL, 
	amount NUMERIC(15, 2) NOT NULL, 
	currency VARCHAR(3) NOT NULL, 
	start_date DATE NOT NULL, 
	end_date DATE, 
	status VARCHAR(20) NOT NULL, 
	terms TEXT, 
	signed_by_our UUID, 
	signed_by_partner VARCHAR(255), 
	signed_at TIMESTAMP WITH TIME ZONE, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(partner_id) REFERENCES partner.partners (id)
);

CREATE TABLE IF NOT EXISTS partner.evaluations (
	id UUID NOT NULL, 
	organization_id UUID NOT NULL, 
	partner_id UUID, 
	project_id UUID, 
	evaluator_id UUID NOT NULL, 
	overall_score NUMERIC(3, 1) NOT NULL, 
	quality_score NUMERIC(3, 1), 
	safety_score NUMERIC(3, 1), 
	schedule_score NUMERIC(3, 1), 
	cost_score NUMERIC(3, 1), 
	communication_score NUMERIC(3, 1), 
	comment TEXT, 
	evaluation_period_start DATE, 
	evaluation_period_end DATE, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_evaluations_partner_project_evaluator UNIQUE (partner_id, project_id, evaluator_id), 
	FOREIGN KEY(partner_id) REFERENCES partner.partners (id)
);

CREATE TABLE IF NOT EXISTS partner.partner_contacts (
	id UUID NOT NULL, 
	partner_id UUID NOT NULL, 
	name VARCHAR(255) NOT NULL, 
	title VARCHAR(255), 
	department VARCHAR(255), 
	email VARCHAR(255) NOT NULL, 
	phone VARCHAR(20), 
	is_primary BOOLEAN NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(partner_id) REFERENCES partner.partners (id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS partner.project_assignments (
	id UUID NOT NULL, 
	organization_id UUID NOT NULL, 
	partner_id UUID, 
	project_id UUID NOT NULL, 
	contract_id UUID, 
	role VARCHAR(100) NOT NULL, 
	scope_of_work TEXT, 
	start_date DATE, 
	end_date DATE, 
	status VARCHAR(20) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(partner_id) REFERENCES partner.partners (id), 
	FOREIGN KEY(contract_id) REFERENCES partner.contracts (id)
);

CREATE INDEX IF NOT EXISTS ix_partners_company_type ON partner.partners (company_type);

CREATE INDEX IF NOT EXISTS ix_partners_name ON partner.partners (name);

CREATE INDEX IF NOT EXISTS ix_partners_organization_id ON partner.partners (organization_id);

CREATE INDEX IF NOT EXISTS ix_partners_status ON partner.partners (status);

CREATE INDEX IF NOT EXISTS ix_contracts_organization_id ON partner.contracts (organization_id);

CREATE INDEX IF NOT EXISTS ix_contracts_partner_id ON partner.contracts (partner_id);

CREATE INDEX IF NOT EXISTS ix_contracts_project_id ON partner.contracts (project_id);

CREATE INDEX IF NOT EXISTS ix_contracts_status ON partner.contracts (status);

CREATE INDEX IF NOT EXISTS ix_evaluations_evaluator_id ON partner.evaluations (evaluator_id);

CREATE INDEX IF NOT EXISTS ix_evaluations_partner_id ON partner.evaluations (partner_id);

CREATE INDEX IF NOT EXISTS ix_evaluations_project_id ON partner.evaluations (project_id);

CREATE INDEX IF NOT EXISTS ix_partner_contacts_partner_id ON partner.partner_contacts (partner_id);

CREATE INDEX IF NOT EXISTS ix_project_assignments_contract_id ON partner.project_assignments (contract_id);

CREATE INDEX IF NOT EXISTS ix_project_assignments_partner_id ON partner.project_assignments (partner_id);

CREATE INDEX IF NOT EXISTS ix_project_assignments_project_id ON partner.project_assignments (project_id);
