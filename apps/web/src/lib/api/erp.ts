import { get, post, put } from "../api-client";

export interface BudgetItem {
  id: string;
  organization_id: string;
  project_id?: string;
  category: string;
  description?: string;
  planned_amount: number;
  actual_amount?: number;
  fiscal_year?: number;
  status: string;
  created_at?: string;
  updated_at?: string;
}

export interface CostItem {
  id: string;
  organization_id: string;
  project_id?: string;
  category: string;
  description?: string;
  amount: number;
  currency?: string;
  status: "pending" | "approved" | "rejected";
  incurred_at?: string;
  approved_by?: string;
  created_at?: string;
  updated_at?: string;
}

export interface Invoice {
  id: string;
  organization_id: string;
  vendor_id?: string;
  invoice_number: string;
  amount: number;
  currency?: string;
  status: "draft" | "sent" | "paid" | "overdue" | "cancelled";
  issued_at?: string;
  due_at?: string;
  paid_at?: string;
  created_at?: string;
  updated_at?: string;
}

export interface LedgerEntry {
  id: string;
  organization_id: string;
  account_code: string;
  description?: string;
  debit?: number;
  credit?: number;
  balance?: number;
  transaction_date?: string;
  created_at?: string;
}

export interface FinancialSummary {
  total_budget: number;
  total_actual: number;
  variance: number;
  variance_pct: number;
  by_category: Record<string, { planned: number; actual: number }>;
}

interface ListResponse<T> {
  items: T[];
  total: number;
}

export function listBudgetItems(
  ledgerId: string,
  params?: {
    organization_id?: string;
    project_id?: string;
    fiscal_year?: number;
  },
) {
  const q = new URLSearchParams();
  if (params?.organization_id) q.set("organization_id", params.organization_id);
  if (params?.project_id) q.set("project_id", params.project_id);
  if (params?.fiscal_year) q.set("fiscal_year", String(params.fiscal_year));
  return get<ListResponse<BudgetItem>>(
    `/erp/ledger/${ledgerId}/budgets${q.toString() ? `?${q}` : ""}`,
  );
}

export function createBudgetItem(
  ledgerId: string,
  body: Omit<BudgetItem, "id" | "created_at" | "updated_at">,
) {
  return post<BudgetItem>(`/erp/ledger/${ledgerId}/budgets`, body);
}

export function updateBudgetItem(id: string, body: Partial<BudgetItem>) {
  return put<BudgetItem>(`/erp/budgets/${id}`, body);
}

export function listCosts(
  ledgerId: string,
  params?: {
    organization_id?: string;
    project_id?: string;
    status?: string;
  },
) {
  const q = new URLSearchParams();
  if (params?.organization_id) q.set("organization_id", params.organization_id);
  if (params?.project_id) q.set("project_id", params.project_id);
  if (params?.status) q.set("status", params.status);
  return get<ListResponse<CostItem>>(
    `/erp/ledger/${ledgerId}/costs${q.toString() ? `?${q}` : ""}`,
  );
}

export function createCost(
  ledgerId: string,
  body: Omit<CostItem, "id" | "created_at" | "updated_at">,
) {
  return post<CostItem>(`/erp/ledger/${ledgerId}/costs`, body);
}

export function updateCost(id: string, body: Partial<CostItem>) {
  return put<CostItem>(`/erp/costs/${id}`, body);
}

export function approveCost(id: string) {
  return post<CostItem>(`/erp/costs/${id}/approve`, {});
}

export function listInvoices(params?: {
  organization_id?: string;
  status?: string;
}) {
  const q = new URLSearchParams();
  if (params?.organization_id) q.set("organization_id", params.organization_id);
  if (params?.status) q.set("status", params.status);
  return get<ListResponse<Invoice>>(
    `/erp/invoices${q.toString() ? `?${q}` : ""}`,
  );
}

export function getInvoice(id: string) {
  return get<Invoice>(`/erp/invoices/${id}`);
}

export function createInvoice(
  body: Omit<Invoice, "id" | "created_at" | "updated_at">,
) {
  return post<Invoice>("/erp/invoices", body);
}

export function updateInvoice(id: string, body: Partial<Invoice>) {
  return put<Invoice>(`/erp/invoices/${id}`, body);
}

export function payInvoice(id: string) {
  return post<Invoice>(`/erp/invoices/${id}/pay`, {});
}

export function listLedger(params?: {
  organization_id?: string;
  account_code?: string;
}) {
  const q = new URLSearchParams();
  if (params?.organization_id) q.set("organization_id", params.organization_id);
  if (params?.account_code) q.set("account_code", params.account_code);
  return get<ListResponse<LedgerEntry>>(
    `/erp/ledger${q.toString() ? `?${q}` : ""}`,
  );
}

export function createLedgerEntry(
  body: Omit<LedgerEntry, "id" | "created_at">,
) {
  return post<LedgerEntry>("/erp/ledger", body);
}

export function getLedgerSummary(id: string) {
  return get<FinancialSummary>(`/erp/ledger/${id}/summary`);
}
