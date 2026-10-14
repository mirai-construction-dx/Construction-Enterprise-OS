"use client";

import { useState, useEffect, useCallback } from "react";
import {
  BarChart3,
  TrendingUp,
  TrendingDown,
  FileText,
  RefreshCw,
  DollarSign,
  Building2,
  Receipt,
  AlertCircle,
  CheckCircle2,
  Clock,
  ChevronRight,
} from "lucide-react";
import { get, ApiError } from "@/lib/api-client";

interface LedgerItem {
  id: string;
  project_code: string;
  project_name: string;
  project_type: string;
  client_name: string | null;
  contract_amount: number;
  budget_amount: number;
  actual_cost: number;
  estimated_profit: number | null;
  progress_rate: number;
  status: string;
  start_date: string | null;
  planned_end_date: string | null;
  location: string | null;
}

interface InvoiceItem {
  id: string;
  invoice_number: string;
  invoice_type: string;
  vendor_name: string;
  amount: number;
  tax_amount: number;
  total_amount: number;
  issue_date: string;
  due_date: string | null;
  status: string;
  paid_date: string | null;
  ledger_id: string | null;
}

interface LedgerListResponse {
  items: LedgerItem[];
  total: number;
  page: number;
  per_page: number;
}

interface InvoiceListResponse {
  items: InvoiceItem[];
  total: number;
  page: number;
  per_page: number;
}

function formatAmount(value: number): string {
  if (value >= 100000000) {
    return `¥${(value / 100000000).toFixed(1)}億`;
  }
  if (value >= 10000) {
    return `¥${(value / 10000).toFixed(0)}万`;
  }
  return `¥${value.toLocaleString()}`;
}

const ledgerStatusStyle: Record<
  string,
  { label: string; className: string; icon: React.ReactNode }
> = {
  planning: {
    label: "計画中",
    className: "bg-blue-100 text-blue-700 border-blue-200",
    icon: <Clock className="h-3.5 w-3.5" />,
  },
  in_progress: {
    label: "施工中",
    className: "bg-yellow-100 text-yellow-700 border-yellow-200",
    icon: <TrendingUp className="h-3.5 w-3.5" />,
  },
  completed: {
    label: "完了",
    className: "bg-green-100 text-green-700 border-green-200",
    icon: <CheckCircle2 className="h-3.5 w-3.5" />,
  },
  suspended: {
    label: "中断",
    className: "bg-red-100 text-red-700 border-red-200",
    icon: <AlertCircle className="h-3.5 w-3.5" />,
  },
};

const invoiceStatusStyle: Record<string, { label: string; className: string }> =
  {
    pending: {
      label: "未払い",
      className: "bg-yellow-100 text-yellow-700 border-yellow-200",
    },
    paid: {
      label: "支払済",
      className: "bg-green-100 text-green-700 border-green-200",
    },
    overdue: {
      label: "期限超過",
      className: "bg-red-100 text-red-700 border-red-200",
    },
    cancelled: {
      label: "キャンセル",
      className: "bg-gray-100 text-gray-600 border-gray-200",
    },
  };

const projectTypeLabel: Record<string, string> = {
  bridge: "橋梁",
  road: "道路",
  building: "建築",
  port: "港湾",
  tunnel: "トンネル",
  dam: "ダム",
  other: "その他",
};

export default function ERPPage() {
  const [ledgers, setLedgers] = useState<LedgerItem[]>([]);
  const [invoices, setInvoices] = useState<InvoiceItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [lastUpdated, setLastUpdated] = useState<Date>(new Date());
  const [error, setError] = useState<string | null>(null);

  const loadERPData = useCallback(async () => {
    setLoading(true);
    try {
      const [ledgerRes, invoiceRes] = await Promise.allSettled([
        get<LedgerListResponse>("/erp/ledger?per_page=20"),
        get<InvoiceListResponse>("/erp/invoices?per_page=10"),
      ]);

      if (ledgerRes.status === "fulfilled") {
        setLedgers(
          Array.isArray(ledgerRes.value?.items)
            ? (ledgerRes.value.items as unknown as LedgerItem[])
            : [],
        );
      }
      if (invoiceRes.status === "fulfilled") {
        setInvoices(
          Array.isArray(invoiceRes.value?.items)
            ? (invoiceRes.value.items as unknown as InvoiceItem[])
            : [],
        );
      }

      const rejected = [ledgerRes, invoiceRes].filter(
        (r): r is PromiseRejectedResult => r.status === "rejected",
      );
      setError(
        rejected.length === 0
          ? null
          : rejected.some(
                (r) => r.reason instanceof ApiError && r.reason.status === 403,
              )
            ? "権限がありません。"
            : "データを取得できませんでした。",
      );
      setLastUpdated(new Date());
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadERPData();
  }, [loadERPData]);

  const totalContract = ledgers.reduce((s, l) => s + l.contract_amount, 0);
  const totalActualCost = ledgers.reduce((s, l) => s + l.actual_cost, 0);
  const totalBudget = ledgers.reduce((s, l) => s + l.budget_amount, 0);
  const activeLedgers = ledgers.filter(
    (l) => l.status === "in_progress",
  ).length;
  const pendingInvoices = invoices.filter(
    (i) => i.status === "pending" || i.status === "overdue",
  ).length;
  const pendingAmount = invoices
    .filter((i) => i.status === "pending" || i.status === "overdue")
    .reduce((s, i) => s + i.total_amount, 0);
  const costRate = totalBudget > 0 ? (totalActualCost / totalBudget) * 100 : 0;

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">ERP・経営管理</h1>
          <p className="mt-1 text-sm text-gray-500">
            工事台帳・予算・原価・請求の統合管理
          </p>
        </div>
        <button
          onClick={loadERPData}
          disabled={loading}
          className="flex items-center gap-2 rounded-lg border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50"
        >
          <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
          更新
        </button>
      </div>

      {error && (
        <div role="alert" aria-live="assertive" className="rounded-xl border border-danger-500/30 bg-danger-50 px-4 py-3 text-sm text-danger-700">
          {error}
        </div>
      )}
      {!loading && !error && ledgers.length === 0 && (
        <div className="rounded-xl border border-gray-200 bg-white px-4 py-8 text-center text-sm text-gray-500">
          該当データがありません。
        </div>
      )}

      {/* KPI Cards */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <div className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm font-medium text-gray-500">施工中案件</p>
              <p className="mt-1 text-3xl font-bold text-gray-900">
                {activeLedgers}
                <span className="ml-1 text-lg font-medium text-gray-500">
                  件
                </span>
              </p>
            </div>
            <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-blue-50">
              <Building2 className="h-6 w-6 text-blue-600" />
            </div>
          </div>
          <p className="mt-2 text-xs text-gray-400">全{ledgers.length}案件中</p>
        </div>

        <div className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm font-medium text-gray-500">請負総額</p>
              <p className="mt-1 text-3xl font-bold text-gray-900">
                {formatAmount(totalContract)}
              </p>
            </div>
            <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-green-50">
              <DollarSign className="h-6 w-6 text-green-600" />
            </div>
          </div>
          <p className="mt-2 text-xs text-gray-400">
            予算総額 {formatAmount(totalBudget)}
          </p>
        </div>

        <div className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm font-medium text-gray-500">原価消化率</p>
              <p className="mt-1 text-3xl font-bold text-gray-900">
                {costRate.toFixed(1)}
                <span className="ml-1 text-lg font-medium text-gray-500">
                  %
                </span>
              </p>
            </div>
            <div
              className={`flex h-12 w-12 items-center justify-center rounded-xl ${costRate > 90 ? "bg-red-50" : costRate > 75 ? "bg-yellow-50" : "bg-green-50"}`}
            >
              {costRate > 90 ? (
                <TrendingDown className="h-6 w-6 text-red-600" />
              ) : (
                <BarChart3
                  className={`h-6 w-6 ${costRate > 75 ? "text-yellow-600" : "text-green-600"}`}
                />
              )}
            </div>
          </div>
          <p className="mt-2 text-xs text-gray-400">
            実績 {formatAmount(totalActualCost)}
          </p>
        </div>

        <div className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm font-medium text-gray-500">未払請求</p>
              <p className="mt-1 text-3xl font-bold text-gray-900">
                {pendingInvoices}
                <span className="ml-1 text-lg font-medium text-gray-500">
                  件
                </span>
              </p>
            </div>
            <div
              className={`flex h-12 w-12 items-center justify-center rounded-xl ${invoices.some((i) => i.status === "overdue") ? "bg-red-50" : "bg-orange-50"}`}
            >
              <Receipt
                className={`h-6 w-6 ${invoices.some((i) => i.status === "overdue") ? "text-red-600" : "text-orange-600"}`}
              />
            </div>
          </div>
          <p className="mt-2 text-xs text-gray-400">
            未払合計 {formatAmount(pendingAmount)}
          </p>
        </div>
      </div>

      {/* Ledger Table */}
      <div className="rounded-xl border border-gray-200 bg-white shadow-sm">
        <div className="flex items-center justify-between border-b border-gray-200 px-6 py-4">
          <div className="flex items-center gap-2">
            <FileText className="h-5 w-5 text-gray-500" />
            <h2 className="text-base font-semibold text-gray-900">
              工事台帳一覧
            </h2>
          </div>
          <span className="text-sm text-gray-500">全{ledgers.length}件</span>
        </div>
        <div className="overflow-x-auto">
          <table className="min-w-full divide-y divide-gray-200">
            <thead className="bg-gray-50">
              <tr>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">
                  工事コード / 工事名
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">
                  区分
                </th>
                <th className="px-4 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">
                  請負金額
                </th>
                <th className="px-4 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">
                  実績原価
                </th>
                <th className="px-4 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">
                  進捗率
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">
                  ステータス
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">
                  竣工予定
                </th>
                <th className="relative px-4 py-3">
                  <span className="sr-only">詳細</span>
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100 bg-white">
              {ledgers.map((ledger) => {
                const st =
                  ledgerStatusStyle[ledger.status] ??
                  ledgerStatusStyle["planning"];
                const costPct =
                  ledger.budget_amount > 0
                    ? (ledger.actual_cost / ledger.budget_amount) * 100
                    : 0;
                const isOverBudget = costPct > 100;
                return (
                  <tr key={ledger.id} className="hover:bg-gray-50">
                    <td className="px-4 py-3">
                      <p className="text-xs font-mono text-gray-400">
                        {ledger.project_code}
                      </p>
                      <p className="mt-0.5 text-sm font-medium text-gray-900">
                        {ledger.project_name}
                      </p>
                      {ledger.client_name && (
                        <p className="mt-0.5 text-xs text-gray-500">
                          {ledger.client_name}
                        </p>
                      )}
                    </td>
                    <td className="px-4 py-3 text-sm text-gray-600">
                      {projectTypeLabel[ledger.project_type] ??
                        ledger.project_type}
                    </td>
                    <td className="px-4 py-3 text-right">
                      <p className="text-sm font-semibold text-gray-900">
                        {formatAmount(ledger.contract_amount)}
                      </p>
                    </td>
                    <td className="px-4 py-3 text-right">
                      <p
                        className={`text-sm font-semibold ${isOverBudget ? "text-red-600" : "text-gray-900"}`}
                      >
                        {formatAmount(ledger.actual_cost)}
                      </p>
                      <p className="text-xs text-gray-400">
                        {costPct.toFixed(0)}%消化
                      </p>
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-2">
                        <div
                          className="flex-1 overflow-hidden rounded-full bg-gray-200"
                          style={{ minWidth: "60px" }}
                        >
                          <div
                            className={`h-1.5 rounded-full ${ledger.progress_rate >= 100 ? "bg-green-500" : ledger.progress_rate >= 75 ? "bg-blue-500" : "bg-yellow-500"}`}
                            style={{
                              width: `${Math.min(ledger.progress_rate, 100)}%`,
                            }}
                          />
                        </div>
                        <span className="text-xs font-medium text-gray-700 tabular-nums w-10 text-right">
                          {ledger.progress_rate.toFixed(0)}%
                        </span>
                      </div>
                    </td>
                    <td className="px-4 py-3">
                      <span
                        className={`inline-flex items-center gap-1 rounded-full border px-2.5 py-1 text-xs font-medium ${st.className}`}
                      >
                        {st.icon}
                        {st.label}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-sm text-gray-500">
                      {ledger.planned_end_date ?? "—"}
                    </td>
                    <td className="px-4 py-3 text-right">
                      <button className="text-gray-400 hover:text-primary-600">
                        <ChevronRight className="h-4 w-4" />
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          {ledgers.length === 0 && (
            <div className="flex flex-col items-center justify-center py-12 text-gray-400">
              <Building2 className="h-8 w-8 mb-2" />
              <p className="text-sm">工事台帳がありません</p>
            </div>
          )}
        </div>
      </div>

      {/* Invoice List */}
      <div className="rounded-xl border border-gray-200 bg-white shadow-sm">
        <div className="flex items-center justify-between border-b border-gray-200 px-6 py-4">
          <div className="flex items-center gap-2">
            <Receipt className="h-5 w-5 text-gray-500" />
            <h2 className="text-base font-semibold text-gray-900">請求一覧</h2>
          </div>
          <div className="flex items-center gap-3">
            {invoices.some((i) => i.status === "overdue") && (
              <span className="inline-flex items-center gap-1 rounded-full bg-red-50 px-2.5 py-1 text-xs font-medium text-red-700">
                <AlertCircle className="h-3.5 w-3.5" />
                期限超過あり
              </span>
            )}
            <span className="text-sm text-gray-500">
              直近{invoices.length}件
            </span>
          </div>
        </div>
        <div className="overflow-x-auto">
          <table className="min-w-full divide-y divide-gray-200">
            <thead className="bg-gray-50">
              <tr>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">
                  請求番号
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">
                  仕入先
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">
                  区分
                </th>
                <th className="px-4 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">
                  請求金額（税込）
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">
                  発行日
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">
                  支払期限
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">
                  ステータス
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100 bg-white">
              {invoices.map((inv) => {
                const st =
                  invoiceStatusStyle[inv.status] ??
                  invoiceStatusStyle["pending"];
                const invoiceTypeLabel: Record<string, string> = {
                  subcontract: "外注",
                  material: "材料",
                  equipment: "機械",
                  labor: "労務",
                  other: "その他",
                };
                return (
                  <tr key={inv.id} className="hover:bg-gray-50">
                    <td className="px-4 py-3">
                      <p className="text-sm font-mono text-gray-700">
                        {inv.invoice_number}
                      </p>
                    </td>
                    <td className="px-4 py-3 text-sm text-gray-900">
                      {inv.vendor_name}
                    </td>
                    <td className="px-4 py-3 text-sm text-gray-600">
                      {invoiceTypeLabel[inv.invoice_type] ?? inv.invoice_type}
                    </td>
                    <td className="px-4 py-3 text-right">
                      <p className="text-sm font-semibold text-gray-900">
                        {formatAmount(inv.total_amount)}
                      </p>
                      <p className="text-xs text-gray-400">
                        税抜 {formatAmount(inv.amount)}
                      </p>
                    </td>
                    <td className="px-4 py-3 text-sm text-gray-500">
                      {inv.issue_date}
                    </td>
                    <td className="px-4 py-3 text-sm">
                      <span
                        className={
                          inv.status === "overdue"
                            ? "font-medium text-red-600"
                            : "text-gray-500"
                        }
                      >
                        {inv.due_date ?? "—"}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      <span
                        className={`inline-flex items-center rounded-full border px-2.5 py-1 text-xs font-medium ${st.className}`}
                      >
                        {st.label}
                      </span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          {invoices.length === 0 && (
            <div className="flex flex-col items-center justify-center py-12 text-gray-400">
              <Receipt className="h-8 w-8 mb-2" />
              <p className="text-sm">請求データがありません</p>
            </div>
          )}
        </div>
      </div>

      <p className="text-right text-xs text-gray-400">
        最終更新: {lastUpdated.toLocaleTimeString("ja-JP")}
      </p>
    </div>
  );
}
