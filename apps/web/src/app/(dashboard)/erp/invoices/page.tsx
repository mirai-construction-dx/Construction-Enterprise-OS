"use client";

import { useState, useEffect, useCallback } from "react";
import { FileText, CheckCircle, Clock, AlertCircle } from "lucide-react";
import { get, ApiError } from "@/lib/api-client";

type Invoice = {
  id: string;
  client: string;
  project: string;
  amount: number;
  issueDate: string;
  dueDate: string;
  status: "paid" | "pending" | "overdue";
};

const STATUS_CONFIG: Record<
  string,
  { label: string; cls: string; icon: React.ReactNode }
> = {
  paid: {
    label: "支払済",
    cls: "bg-green-100 text-green-800",
    icon: <CheckCircle className="w-3.5 h-3.5" />,
  },
  pending: {
    label: "未収",
    cls: "bg-yellow-100 text-yellow-800",
    icon: <Clock className="w-3.5 h-3.5" />,
  },
  overdue: {
    label: "延滞",
    cls: "bg-red-100 text-red-800",
    icon: <AlertCircle className="w-3.5 h-3.5" />,
  },
};

export default function InvoicesPage() {
  const [invoices, setInvoices] = useState<Invoice[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const json = await get<{
        data?: { items?: Record<string, unknown>[] };
        items?: Record<string, unknown>[];
      }>("/erp/invoices?per_page=50");
      const items: Record<string, unknown>[] =
        json?.data?.items ?? json?.items ?? [];
      setInvoices(
        Array.isArray(items)
          ? items.map(
              (item): Invoice => ({
                id: String(item.id ?? ""),
                client: String(item.client ?? item.client_name ?? ""),
                project: String(item.project ?? item.project_name ?? ""),
                amount: Number(item.amount ?? 0),
                issueDate: String(item.issueDate ?? item.issue_date ?? ""),
                dueDate: String(item.dueDate ?? item.due_date ?? ""),
                status: String(item.status ?? "pending") as Invoice["status"],
              }),
            )
          : [],
      );
      setError(null);
    } catch (err) {
      setError(
        err instanceof ApiError && err.status === 403
          ? "権限がありません。"
          : "データを取得できませんでした。",
      );
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const thisMonthCount = invoices.filter((inv) =>
    inv.issueDate.startsWith("2026-05"),
  ).length;
  const unpaidTotal = invoices
    .filter((inv) => inv.status === "pending" || inv.status === "overdue")
    .reduce((s, inv) => s + inv.amount, 0);
  const paidTotal = invoices
    .filter((inv) => inv.status === "paid")
    .reduce((s, inv) => s + inv.amount, 0);
  const overdueCount = invoices.filter(
    (inv) => inv.status === "overdue",
  ).length;

  return (
    <div className="max-w-7xl mx-auto px-4 py-8 space-y-8">
      {/* ページヘッダー */}
      <div>
        <h1 className="text-2xl font-bold text-gray-900">請求書管理</h1>
        <p className="text-sm text-gray-500 mt-1">
          発行済み請求書の一覧・入金状況・延滞管理を行います
        </p>
      </div>

      {/* 統計カード */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-5 flex items-start gap-4">
          <div className="p-3 rounded-lg bg-blue-50">
            <FileText className="w-5 h-5 text-blue-600" />
          </div>
          <div>
            <p className="text-xs text-gray-500 font-medium">今月発行数</p>
            <p className="text-xl font-bold text-gray-900 mt-0.5">
              {thisMonthCount}件
            </p>
          </div>
        </div>

        <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-5 flex items-start gap-4">
          <div className="p-3 rounded-lg bg-yellow-50">
            <Clock className="w-5 h-5 text-yellow-500" />
          </div>
          <div>
            <p className="text-xs text-gray-500 font-medium">未収合計</p>
            <p className="text-xl font-bold text-gray-900 mt-0.5">
              {unpaidTotal.toLocaleString()}円
            </p>
          </div>
        </div>

        <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-5 flex items-start gap-4">
          <div className="p-3 rounded-lg bg-green-50">
            <CheckCircle className="w-5 h-5 text-green-600" />
          </div>
          <div>
            <p className="text-xs text-gray-500 font-medium">支払済合計</p>
            <p className="text-xl font-bold text-gray-900 mt-0.5">
              {paidTotal.toLocaleString()}円
            </p>
          </div>
        </div>

        <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-5 flex items-start gap-4">
          <div className="p-3 rounded-lg bg-red-50">
            <AlertCircle className="w-5 h-5 text-red-500" />
          </div>
          <div>
            <p className="text-xs text-gray-500 font-medium">延滞件数</p>
            <p className="text-xl font-bold text-red-600 mt-0.5">
              {overdueCount}件
            </p>
          </div>
        </div>
      </div>

      {error && (
        <div role="alert" aria-live="assertive" className="rounded-xl border border-danger-500/30 bg-danger-50 px-4 py-3 text-sm text-danger-700">
          {error}
        </div>
      )}
      {!loading && !error && invoices.length === 0 && (
        <div className="rounded-xl border border-gray-200 bg-white px-4 py-8 text-center text-sm text-gray-500">
          該当データがありません。
        </div>
      )}

      {/* 請求書一覧テーブル */}
      <div className="bg-white rounded-xl shadow-sm border border-gray-100">
        <div className="px-6 py-4 border-b border-gray-100 flex items-center justify-between">
          <h2 className="text-base font-semibold text-gray-800">請求書一覧</h2>
          <span className="text-xs text-gray-400">全{invoices.length}件</span>
        </div>
        {loading ? (
          <div className="px-6 py-8 text-center text-sm text-gray-400">
            読み込み中...
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-gray-50 text-gray-500 text-xs uppercase tracking-wide">
                  <th className="px-6 py-3 text-left font-medium">請求番号</th>
                  <th className="px-6 py-3 text-left font-medium">取引先</th>
                  <th className="px-6 py-3 text-left font-medium">工事件名</th>
                  <th className="px-6 py-3 text-right font-medium">請求金額</th>
                  <th className="px-6 py-3 text-center font-medium">発行日</th>
                  <th className="px-6 py-3 text-center font-medium">
                    支払期日
                  </th>
                  <th className="px-6 py-3 text-center font-medium">
                    ステータス
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-50">
                {invoices.map((inv) => {
                  const cfg = STATUS_CONFIG[inv.status];
                  return (
                    <tr
                      key={inv.id}
                      className={`hover:bg-gray-50 transition-colors ${
                        inv.status === "overdue" ? "bg-red-50/40" : ""
                      }`}
                    >
                      <td className="px-6 py-4 font-mono text-xs font-medium text-gray-700">
                        {inv.id}
                      </td>
                      <td className="px-6 py-4 text-gray-900 font-medium whitespace-nowrap">
                        {inv.client}
                      </td>
                      <td className="px-6 py-4 text-gray-600 whitespace-nowrap">
                        {inv.project}
                      </td>
                      <td className="px-6 py-4 text-right font-semibold text-gray-900">
                        {inv.amount.toLocaleString()}円
                      </td>
                      <td className="px-6 py-4 text-center text-gray-600">
                        {inv.issueDate}
                      </td>
                      <td
                        className={`px-6 py-4 text-center font-medium ${
                          inv.status === "overdue"
                            ? "text-red-600"
                            : "text-gray-600"
                        }`}
                      >
                        {inv.dueDate}
                      </td>
                      <td className="px-6 py-4 text-center">
                        <span
                          className={`inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-medium ${cfg.cls}`}
                        >
                          {cfg.icon}
                          {cfg.label}
                        </span>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
