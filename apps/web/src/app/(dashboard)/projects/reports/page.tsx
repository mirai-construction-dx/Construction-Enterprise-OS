"use client";

import { useState, useEffect, useCallback } from "react";
import { FileText, BarChart3, Send, Eye } from "lucide-react";
import { get, ApiError } from "@/lib/api-client";

type Report = {
  id: number;
  name: string;
  type: string;
  project: string;
  created: string;
  author: string;
  status: string;
};

const STATUS_STYLES: Record<string, string> = {
  approved: "bg-green-100 text-green-800",
  sent: "bg-blue-100 text-blue-800",
  draft: "bg-gray-100 text-gray-700",
};

const STATUS_LABELS: Record<string, string> = {
  approved: "承認済み",
  sent: "配信済み",
  draft: "下書き",
};

const TYPE_STYLES: Record<string, string> = {
  月次報告: "bg-purple-100 text-purple-800",
  週次報告: "bg-blue-100 text-blue-800",
  完工報告: "bg-green-100 text-green-800",
  中間報告: "bg-orange-100 text-orange-800",
  竣工写真集: "bg-pink-100 text-pink-800",
};

export default function ReportsPage() {
  const [reports, setReports] = useState<Report[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const json = await get<{
        data?: { items?: Record<string, unknown>[] };
        items?: Record<string, unknown>[];
      }>("/analytics/reports?per_page=20");
      const data = json?.data?.items ?? json?.items ?? json?.data ?? [];
      setReports(
        Array.isArray(data)
          ? data.map((item: Record<string, unknown>) => ({
              id: Number(item.id ?? 0),
              name: String(item.title ?? item.name ?? ""),
              type: String(item.report_type ?? item.type ?? ""),
              project: String(item.project_name ?? item.project ?? ""),
              created: String(item.created_at ?? "").slice(0, 10),
              author: String(item.created_by ?? item.author ?? ""),
              status: String(item.status ?? "draft"),
            }))
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

  const thisMonth = reports.filter((r) =>
    r.created.startsWith("2024-11"),
  ).length;
  const approved = reports.filter((r) => r.status === "approved").length;
  const draft = reports.filter((r) => r.status === "draft").length;
  const sent = reports.filter((r) => r.status === "sent").length;

  return (
    <div className="space-y-6 p-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">
            プロジェクトレポート
          </h1>
          <p className="text-sm text-gray-500 mt-1">
            工事報告書・週次月次レポートの管理
            {loading && (
              <span className="ml-2 text-blue-500 animate-pulse">
                読み込み中...
              </span>
            )}
          </p>
        </div>
        <button className="px-4 py-2 bg-blue-600 text-white text-sm rounded-lg hover:bg-blue-700">
          レポート作成
        </button>
      </div>

      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        <div className="bg-white rounded-xl border border-gray-200 p-4 flex items-center gap-3">
          <div className="p-2 bg-blue-50 rounded-lg">
            <FileText className="w-5 h-5 text-blue-600" />
          </div>
          <div>
            <p className="text-xs text-gray-500">今月作成数</p>
            <p className="text-2xl font-bold text-gray-900">{thisMonth}</p>
          </div>
        </div>
        <div className="bg-white rounded-xl border border-gray-200 p-4 flex items-center gap-3">
          <div className="p-2 bg-green-50 rounded-lg">
            <BarChart3 className="w-5 h-5 text-green-600" />
          </div>
          <div>
            <p className="text-xs text-gray-500">承認済み</p>
            <p className="text-2xl font-bold text-gray-900">{approved}</p>
          </div>
        </div>
        <div className="bg-white rounded-xl border border-gray-200 p-4 flex items-center gap-3">
          <div className="p-2 bg-gray-50 rounded-lg">
            <Eye className="w-5 h-5 text-gray-600" />
          </div>
          <div>
            <p className="text-xs text-gray-500">下書き</p>
            <p className="text-2xl font-bold text-gray-900">{draft}</p>
          </div>
        </div>
        <div className="bg-white rounded-xl border border-gray-200 p-4 flex items-center gap-3">
          <div className="p-2 bg-purple-50 rounded-lg">
            <Send className="w-5 h-5 text-purple-600" />
          </div>
          <div>
            <p className="text-xs text-gray-500">配信済み</p>
            <p className="text-2xl font-bold text-gray-900">{sent}</p>
          </div>
        </div>
      </div>

      {error && (
        <div role="alert" aria-live="assertive" className="rounded-xl border border-danger-500/30 bg-danger-50 px-4 py-3 text-sm text-danger-700">
          {error}
        </div>
      )}
      {!loading && !error && reports.length === 0 && (
        <div className="rounded-xl border border-gray-200 bg-white px-4 py-8 text-center text-sm text-gray-500">
          該当データがありません。
        </div>
      )}

      <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-gray-50 border-b border-gray-200">
                <th className="px-4 py-3 text-left font-semibold text-gray-600">
                  レポート名
                </th>
                <th className="px-4 py-3 text-left font-semibold text-gray-600 whitespace-nowrap">
                  種別
                </th>
                <th className="px-4 py-3 text-left font-semibold text-gray-600 whitespace-nowrap">
                  対象プロジェクト
                </th>
                <th className="px-4 py-3 text-left font-semibold text-gray-600 whitespace-nowrap">
                  作成日
                </th>
                <th className="px-4 py-3 text-left font-semibold text-gray-600 whitespace-nowrap">
                  作成者
                </th>
                <th className="px-4 py-3 text-left font-semibold text-gray-600 whitespace-nowrap">
                  ステータス
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {reports.map((report) => (
                <tr key={report.id} className="hover:bg-gray-50">
                  <td className="px-4 py-3 font-medium text-blue-700 hover:underline cursor-pointer">
                    {report.name}
                  </td>
                  <td className="px-4 py-3 whitespace-nowrap">
                    <span
                      className={`px-2 py-0.5 rounded-full text-xs font-medium ${TYPE_STYLES[report.type] ?? "bg-gray-100 text-gray-700"}`}
                    >
                      {report.type}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-gray-600 whitespace-nowrap">
                    {report.project}
                  </td>
                  <td className="px-4 py-3 text-gray-600 whitespace-nowrap">
                    {report.created}
                  </td>
                  <td className="px-4 py-3 text-gray-600 whitespace-nowrap">
                    {report.author}
                  </td>
                  <td className="px-4 py-3 whitespace-nowrap">
                    <span
                      className={`px-2 py-0.5 rounded-full text-xs font-medium ${STATUS_STYLES[report.status]}`}
                    >
                      {STATUS_LABELS[report.status]}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
