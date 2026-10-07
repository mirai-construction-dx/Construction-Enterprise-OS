-- erp スキーマ 基盤 DDL (自動生成 / 冪等)
--
-- 生成元: services/erp/src/models (SQLAlchemy メタデータ)
-- 再生成: python3 scripts/db/generate_base_schema.py erp
--
-- このファイルは models の定義と一致します。既存オブジェクトがある場合は
-- 何もせず、既存データを変更しません。

CREATE SCHEMA IF NOT EXISTS erp;

SET search_path TO erp, public;

CREATE TABLE IF NOT EXISTS erp.project_ledger (
	id UUID NOT NULL, 
	organization_id UUID NOT NULL, 
	project_id UUID NOT NULL, 
	project_code VARCHAR(50) NOT NULL, 
	project_name VARCHAR(500) NOT NULL, 
	project_type VARCHAR(50) NOT NULL, 
	client_name VARCHAR(255), 
	contract_amount NUMERIC(15, 2) NOT NULL, 
	budget_amount NUMERIC(15, 2) NOT NULL, 
	actual_cost NUMERIC(15, 2) NOT NULL, 
	estimated_profit NUMERIC(15, 2), 
	progress_rate NUMERIC(5, 2) NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	start_date DATE, 
	planned_end_date DATE, 
	actual_end_date DATE, 
	location VARCHAR(500), 
	manager_id UUID, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id)
);

CREATE TABLE IF NOT EXISTS erp.budgets (
	id UUID NOT NULL, 
	organization_id UUID NOT NULL, 
	ledger_id UUID, 
	category VARCHAR(100) NOT NULL, 
	planned_amount NUMERIC(15, 2) NOT NULL, 
	actual_amount NUMERIC(15, 2) NOT NULL, 
	note TEXT, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(ledger_id) REFERENCES erp.project_ledger (id)
);

CREATE TABLE IF NOT EXISTS erp.invoices (
	id UUID NOT NULL, 
	organization_id UUID NOT NULL, 
	ledger_id UUID, 
	invoice_number VARCHAR(100) NOT NULL, 
	invoice_type VARCHAR(20) NOT NULL, 
	vendor_name VARCHAR(255) NOT NULL, 
	amount NUMERIC(15, 2) NOT NULL, 
	tax_amount NUMERIC(15, 2) NOT NULL, 
	total_amount NUMERIC(15, 2) NOT NULL, 
	issue_date DATE NOT NULL, 
	due_date DATE, 
	status VARCHAR(20) NOT NULL, 
	paid_date DATE, 
	payment_method VARCHAR(50), 
	notes TEXT, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(ledger_id) REFERENCES erp.project_ledger (id), 
	UNIQUE (invoice_number)
);

CREATE TABLE IF NOT EXISTS erp.labor_costs (
	id UUID NOT NULL, 
	organization_id UUID NOT NULL, 
	ledger_id UUID, 
	user_id UUID, 
	worker_name VARCHAR(255) NOT NULL, 
	work_date DATE NOT NULL, 
	work_hours NUMERIC(5, 2) NOT NULL, 
	hourly_rate NUMERIC(10, 2) NOT NULL, 
	total_cost NUMERIC(15, 2) NOT NULL, 
	work_type VARCHAR(100), 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(ledger_id) REFERENCES erp.project_ledger (id)
);

CREATE TABLE IF NOT EXISTS erp.cost_items (
	id UUID NOT NULL, 
	organization_id UUID NOT NULL, 
	ledger_id UUID, 
	budget_id UUID, 
	category VARCHAR(100) NOT NULL, 
	description TEXT NOT NULL, 
	amount NUMERIC(15, 2) NOT NULL, 
	cost_date DATE NOT NULL, 
	vendor_name VARCHAR(255), 
	invoice_number VARCHAR(100), 
	status VARCHAR(20) NOT NULL, 
	approved_by UUID, 
	approved_at TIMESTAMP WITH TIME ZONE, 
	receipt_file_key VARCHAR(1000), 
	created_by UUID, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(ledger_id) REFERENCES erp.project_ledger (id), 
	FOREIGN KEY(budget_id) REFERENCES erp.budgets (id)
);

CREATE INDEX IF NOT EXISTS ix_project_ledger_organization_id ON erp.project_ledger (organization_id);

CREATE INDEX IF NOT EXISTS ix_project_ledger_project_id ON erp.project_ledger (project_id);

CREATE INDEX IF NOT EXISTS ix_project_ledger_status ON erp.project_ledger (status);

CREATE INDEX IF NOT EXISTS ix_budgets_ledger_id ON erp.budgets (ledger_id);

CREATE INDEX IF NOT EXISTS ix_budgets_organization_id ON erp.budgets (organization_id);

CREATE INDEX IF NOT EXISTS ix_invoices_ledger_id ON erp.invoices (ledger_id);

CREATE INDEX IF NOT EXISTS ix_invoices_organization_id ON erp.invoices (organization_id);

CREATE INDEX IF NOT EXISTS ix_invoices_status ON erp.invoices (status);

CREATE INDEX IF NOT EXISTS ix_labor_costs_ledger_id ON erp.labor_costs (ledger_id);

CREATE INDEX IF NOT EXISTS ix_labor_costs_organization_id ON erp.labor_costs (organization_id);

CREATE INDEX IF NOT EXISTS ix_cost_items_budget_id ON erp.cost_items (budget_id);

CREATE INDEX IF NOT EXISTS ix_cost_items_ledger_id ON erp.cost_items (ledger_id);

CREATE INDEX IF NOT EXISTS ix_cost_items_organization_id ON erp.cost_items (organization_id);

CREATE INDEX IF NOT EXISTS ix_cost_items_status ON erp.cost_items (status);
