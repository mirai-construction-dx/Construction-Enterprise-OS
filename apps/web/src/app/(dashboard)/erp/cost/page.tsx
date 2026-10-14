"use client";

import { useState, useEffect, useCallback } from "react";
import { Calculator, TrendingDown, BarChart2 } from "lucide-react";
import { get, ApiError } from "@/lib/api-client";

// Mock data (fallback)

const MONTHLY_COSTS = [
  { month: "1月", cost: 58200000 },
  { month: "2月", cost: 72400000 },
  { month: "3月", cost: 94800000 },
  { month: "4月", cost: 86300000 },
  { month: "5月", cost: 105800000 },
];

type CostWorkType = {
  id: number;
  name: string;
  planned: number;
  actual: number;
};

function evalLabel(diff: number): { label: string; cls: string } {
  if (diff > 0)
    return { label: "有利差異", cls: "bg-green-100 text-green-800" };
  if (diff < 0) return { label: "不利差異", cls: "bg-red-100 text-red-800" };
  return { label: "差異なし", cls: "bg-gray-100 text-gray-700" };
}

function diffRateColor(rate: number): string {
  if (rate <= -5) return "text-red-600 font-semibold";
  if (rate < 0) return "text-orange-500 font-semibold";
  if (rate >= 5) return "text-green-600 font-semibold";
  return "text-gray-700";
}

export default function CostPage() {
  const [costWorkTypes, setCostWorkTypes] = useState<CostWorkType[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const json = await get<{
        data?: { items?: Record<string, unknown>[] };
        items?: Record<string, unknown>[];
      }>("/erp/costs?per_page=50");
      const items = json?.data?.items ?? json?.items ?? json?.data ?? [];
      setCostWorkTypes(
        Array.isArray(items)
          ? items.map((item) => ({
              id: Number(item.id ?? 0),
              name: String(
                item.cost_type ?? item.project_name ?? item.name ?? "",
              ),
              planned: Number(item.planned ?? item.budget_amount ?? 0),
              actual: Number(item.amount ?? item.actual_amount ?? 0),
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

  const totalPlanned = costWorkTypes.reduce((s, w) => s + w.planned, 0);
  const totalActual = costWorkTypes.reduce((s, w) => s + w.actual, 0);
  const totalDiff = totalPlanned - totalActual;
  const totalDiffRate =
    totalPlanned > 0 ? ((totalDiff / totalPlanned) * 100).toFixed(1) : "0.0";

  return (
    <div className="max-w-7xl mx-auto px-4 py-8 space-y-8">
      {/* ページヘッダー */}
      <div>
        <h1 className="text-2xl font-bold text-gray-900">原価管理</h1>
        <p className="text-sm text-gray-500 mt-1">
          工種別の計画原価と実際原価を比較し、差異を分析します
        </p>
      </div>

      {error && (
        <div role="alert" aria-live="assertive" className="rounded-xl border border-danger-500/30 bg-danger-50 px-4 py-3 text-sm text-danger-700">
          {error}
        </div>
      )}
      {!loading && !error && costWorkTypes.length === 0 && (
        <div className="rounded-xl border border-gray-200 bg-white px-4 py-8 text-center text-sm text-gray-500">
          該当データがありません。
        </div>
      )}

      {/* 統計カード */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-5 flex items-start gap-4">
          <div className="p-3 rounded-lg bg-blue-50">
            <Calculator className="w-5 h-5 text-blue-600" />
          </div>
          <div>
            <p className="text-xs text-gray-500 font-medium">総計画原価</p>
            <p className="text-xl font-bold text-gray-900 mt-0.5">
              {totalPlanned.toLocaleString()}円
            </p>
          </div>
        </div>

        <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-5 flex items-start gap-4">
          <div className="p-3 rounded-lg bg-orange-50">
            <BarChart2 className="w-5 h-5 text-orange-500" />
          </div>
          <div>
            <p className="text-xs text-gray-500 font-medium">総実際原価</p>
            <p className="text-xl font-bold text-gray-900 mt-0.5">
              {totalActual.toLocaleString()}円
            </p>
          </div>
        </div>

        <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-5 flex items-start gap-4">
          <div
            className={`p-3 rounded-lg ${totalDiff >= 0 ? "bg-green-50" : "bg-red-50"}`}
          >
            <TrendingDown
              className={`w-5 h-5 ${totalDiff >= 0 ? "text-green-600" : "text-red-600"}`}
            />
          </div>
          <div>
            <p className="text-xs text-gray-500 font-medium">総差異</p>
            <p
              className={`text-xl font-bold mt-0.5 ${
                totalDiff >= 0 ? "text-green-600" : "text-red-600"
              }`}
            >
              {totalDiff >= 0 ? "+" : ""}
              {totalDiff.toLocaleString()}円
            </p>
          </div>
        </div>

        <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-5 flex items-start gap-4">
          <div className="p-3 rounded-lg bg-purple-50">
            <Calculator className="w-5 h-5 text-purple-600" />
          </div>
          <div>
            <p className="text-xs text-gray-500 font-medium">原価差異率</p>
            <p
              className={`text-xl font-bold mt-0.5 ${
                Number(totalDiffRate) >= 0 ? "text-green-600" : "text-red-600"
              }`}
            >
              {Number(totalDiffRate) >= 0 ? "+" : ""}
              {totalDiffRate}%
            </p>
          </div>
        </div>
      </div>

      {/* 工種別原価テーブル */}
      <div className="bg-white rounded-xl shadow-sm border border-gray-100">
        <div className="px-6 py-4 border-b border-gray-100 flex items-center gap-3">
          <h2 className="text-base font-semibold text-gray-800">
            工種別 原価差異分析
          </h2>
          {loading && (
            <span className="text-xs text-gray-400 animate-pulse">
              読み込み中...
            </span>
          )}
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-gray-50 text-gray-500 text-xs uppercase tracking-wide">
                <th className="px-6 py-3 text-left font-medium">工種</th>
                <th className="px-6 py-3 text-right font-medium">計画原価</th>
                <th className="px-6 py-3 text-right font-medium">実際原価</th>
                <th className="px-6 py-3 text-right font-medium">差異額</th>
                <th className="px-6 py-3 text-right font-medium">差異率</th>
                <th className="px-6 py-3 text-center font-medium">評価</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50">
              {costWorkTypes.map((w) => {
                const diff = w.planned - w.actual;
                const diffRate = w.planned > 0 ? (diff / w.planned) * 100 : 0;
                const { label, cls } = evalLabel(diff);
                return (
                  <tr key={w.id} className="hover:bg-gray-50 transition-colors">
                    <td className="px-6 py-4 font-medium text-gray-900">
                      {w.name}
                    </td>
                    <td className="px-6 py-4 text-right text-gray-700">
                      {w.planned.toLocaleString()}円
                    </td>
                    <td className="px-6 py-4 text-right text-gray-700">
                      {w.actual.toLocaleString()}円
                    </td>
                    <td
                      className={`px-6 py-4 text-right font-medium ${
                        diff >= 0 ? "text-green-600" : "text-red-600"
                      }`}
                    >
                      {diff >= 0 ? "+" : ""}
                      {diff.toLocaleString()}円
                    </td>
                    <td
                      className={`px-6 py-4 text-right ${diffRateColor(diffRate)}`}
                    >
                      {diffRate >= 0 ? "+" : ""}
                      {diffRate.toFixed(1)}%
                    </td>
                    <td className="px-6 py-4 text-center">
                      <span
                        className={`inline-block px-2 py-0.5 rounded-full text-xs font-medium ${cls}`}
                      >
                        {label}
                      </span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

      {/* 月別原価推移テーブル */}
      <div className="bg-white rounded-xl shadow-sm border border-gray-100">
        <div className="px-6 py-4 border-b border-gray-100">
          <h2 className="text-base font-semibold text-gray-800">
            月別 原価推移（2026年）
          </h2>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-gray-50 text-gray-500 text-xs uppercase tracking-wide">
                <th className="px-6 py-3 text-left font-medium">月</th>
                <th className="px-6 py-3 text-right font-medium">実績原価</th>
                <th className="px-6 py-3 text-right font-medium">前月比</th>
                <th className="px-6 py-3 text-left font-medium">グラフ</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50">
              {MONTHLY_COSTS.map((m, i) => {
                const prev = i > 0 ? MONTHLY_COSTS[i - 1].cost : null;
                const change =
                  prev != null ? ((m.cost - prev) / prev) * 100 : null;
                const maxCost = Math.max(...MONTHLY_COSTS.map((x) => x.cost));
                const barWidth = (m.cost / maxCost) * 100;
                return (
                  <tr
                    key={m.month}
                    className="hover:bg-gray-50 transition-colors"
                  >
                    <td className="px-6 py-4 font-medium text-gray-900">
                      {m.month}
                    </td>
                    <td className="px-6 py-4 text-right text-gray-700">
                      {m.cost.toLocaleString()}円
                    </td>
                    <td className="px-6 py-4 text-right">
                      {change != null ? (
                        <span
                          className={`font-medium ${
                            change >= 0 ? "text-red-500" : "text-green-600"
                          }`}
                        >
                          {change >= 0 ? "▲" : "▼"}
                          {Math.abs(change).toFixed(1)}%
                        </span>
                      ) : (
                        <span className="text-gray-400">—</span>
                      )}
                    </td>
                    <td className="px-6 py-4 min-w-[180px]">
                      <div className="w-full bg-gray-100 rounded-full h-2">
                        <div
                          className="h-2 rounded-full bg-blue-500"
                          style={{ width: `${barWidth}%` }}
                        />
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
