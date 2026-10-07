"use client";

import { useState, useEffect, useCallback } from "react";
import { DollarSign, TrendingUp, BarChart3, PieChart } from "lucide-react";
import { get, ApiError } from "@/lib/api-client";

// Mock data (fallback)

const BUDGET_CATEGORIES = [
  { name: "人件費", budget: 282000000, actual: 210000000 },
  { name: "資材費", budget: 375000000, actual: 298000000 },
  { name: "外注費", budget: 158000000, actual: 121000000 },
  { name: "機械費", budget: 84000000, actual: 62000000 },
  { name: "諸経費", budget: 41000000, actual: 35700000 },
];

const STATUS_COLOR: Record<string, string> = {
  進行中: "bg-blue-100 text-blue-800",
  完了: "bg-green-100 text-green-800",
  計画中: "bg-gray-100 text-gray-700",
  超過: "bg-red-100 text-red-800",
};

type BudgetProject = {
  id: number;
  name: string;
  budget: number;
  actual: number;
  status: string;
};

function execRate(actual: number, budget: number): number {
  return budget > 0 ? (actual / budget) * 100 : 0;
}

function rateColorClass(rate: number): string {
  if (rate >= 100) return "text-red-600 font-semibold";
  if (rate >= 85) return "text-yellow-600 font-semibold";
  return "text-green-600 font-semibold";
}

export default function BudgetPage() {
  const [budgetProjects, setBudgetProjects] = useState<BudgetProject[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const json = await get<{
        data?: { items?: Record<string, unknown>[] };
        items?: Record<string, unknown>[];
      }>("/erp/budgets?per_page=50");
      const items = json?.data?.items ?? json?.items ?? json?.data ?? [];
      setBudgetProjects(
        Array.isArray(items)
          ? items.map((item) => ({
              id: Number(item.id ?? 0),
              name: String(item.project_name ?? item.name ?? ""),
              budget: Number(item.budget_amount ?? item.budget ?? 0),
              actual: Number(item.actual_amount ?? item.actual ?? 0),
              status: String(item.status ?? "進行中"),
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

  const totalBudget = budgetProjects.reduce((s, p) => s + p.budget, 0);
  const totalActual = budgetProjects.reduce((s, p) => s + p.actual, 0);
  const totalRate = execRate(totalActual, totalBudget).toFixed(1);
  const totalRemain = totalBudget - totalActual;

  return (
    <div className="max-w-7xl mx-auto px-4 py-8 space-y-8">
      {/* ページヘッダー */}
      <div>
        <h1 className="text-2xl font-bold text-gray-900">予算管理</h1>
        <p className="text-sm text-gray-500 mt-1">
          プロジェクト別・費目別の予算執行状況を管理します
        </p>
      </div>

      {error && (
        <div role="alert" aria-live="assertive" className="rounded-xl border border-danger-500/30 bg-danger-50 px-4 py-3 text-sm text-danger-700">
          {error}
        </div>
      )}
      {!loading && !error && budgetProjects.length === 0 && (
        <div className="rounded-xl border border-gray-200 bg-white px-4 py-8 text-center text-sm text-gray-500">
          該当データがありません。
        </div>
      )}

      {/* 統計カード */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-5 flex items-start gap-4">
          <div className="p-3 rounded-lg bg-blue-50">
            <DollarSign className="w-5 h-5 text-blue-600" />
          </div>
          <div>
            <p className="text-xs text-gray-500 font-medium">総予算額</p>
            <p className="text-xl font-bold text-gray-900 mt-0.5">
              {totalBudget.toLocaleString()}円
            </p>
          </div>
        </div>

        <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-5 flex items-start gap-4">
          <div className="p-3 rounded-lg bg-orange-50">
            <TrendingUp className="w-5 h-5 text-orange-500" />
          </div>
          <div>
            <p className="text-xs text-gray-500 font-medium">実績合計</p>
            <p className="text-xl font-bold text-gray-900 mt-0.5">
              {totalActual.toLocaleString()}円
            </p>
          </div>
        </div>

        <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-5 flex items-start gap-4">
          <div className="p-3 rounded-lg bg-purple-50">
            <BarChart3 className="w-5 h-5 text-purple-600" />
          </div>
          <div>
            <p className="text-xs text-gray-500 font-medium">執行率</p>
            <p className="text-xl font-bold text-gray-900 mt-0.5">
              {totalRate}%
            </p>
          </div>
        </div>

        <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-5 flex items-start gap-4">
          <div className="p-3 rounded-lg bg-green-50">
            <PieChart className="w-5 h-5 text-green-600" />
          </div>
          <div>
            <p className="text-xs text-gray-500 font-medium">残予算</p>
            <p className="text-xl font-bold text-gray-900 mt-0.5">
              {totalRemain.toLocaleString()}円
            </p>
          </div>
        </div>
      </div>

      {/* プロジェクト別予算テーブル */}
      <div className="bg-white rounded-xl shadow-sm border border-gray-100">
        <div className="px-6 py-4 border-b border-gray-100 flex items-center gap-3">
          <h2 className="text-base font-semibold text-gray-800">
            プロジェクト別 予算 vs 実績
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
                <th className="px-6 py-3 text-left font-medium">
                  プロジェクト名
                </th>
                <th className="px-6 py-3 text-right font-medium">予算額</th>
                <th className="px-6 py-3 text-right font-medium">実績額</th>
                <th className="px-6 py-3 text-right font-medium">執行率</th>
                <th className="px-6 py-3 text-right font-medium">残予算</th>
                <th className="px-6 py-3 text-center font-medium">
                  ステータス
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50">
              {budgetProjects.map((p) => {
                const rate = execRate(p.actual, p.budget);
                const remain = p.budget - p.actual;
                return (
                  <tr key={p.id} className="hover:bg-gray-50 transition-colors">
                    <td className="px-6 py-4 font-medium text-gray-900">
                      {p.name}
                    </td>
                    <td className="px-6 py-4 text-right text-gray-700">
                      {p.budget.toLocaleString()}円
                    </td>
                    <td className="px-6 py-4 text-right text-gray-700">
                      {p.actual.toLocaleString()}円
                    </td>
                    <td
                      className={`px-6 py-4 text-right ${rateColorClass(rate)}`}
                    >
                      {rate.toFixed(1)}%
                    </td>
                    <td className="px-6 py-4 text-right text-gray-700">
                      {remain >= 0
                        ? `${remain.toLocaleString()}円`
                        : `▲${Math.abs(remain).toLocaleString()}円`}
                    </td>
                    <td className="px-6 py-4 text-center">
                      <span
                        className={`inline-block px-2 py-0.5 rounded-full text-xs font-medium ${
                          STATUS_COLOR[p.status] ?? "bg-gray-100 text-gray-700"
                        }`}
                      >
                        {p.status}
                      </span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

      {/* 費目別予算テーブル */}
      <div className="bg-white rounded-xl shadow-sm border border-gray-100">
        <div className="px-6 py-4 border-b border-gray-100">
          <h2 className="text-base font-semibold text-gray-800">
            費目別 予算配分・執行状況
          </h2>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-gray-50 text-gray-500 text-xs uppercase tracking-wide">
                <th className="px-6 py-3 text-left font-medium">費目</th>
                <th className="px-6 py-3 text-right font-medium">予算額</th>
                <th className="px-6 py-3 text-right font-medium">実績額</th>
                <th className="px-6 py-3 text-right font-medium">残額</th>
                <th className="px-6 py-3 text-right font-medium">執行率</th>
                <th className="px-6 py-3 text-left font-medium w-40">
                  進捗バー
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50">
              {BUDGET_CATEGORIES.map((c) => {
                const rate = execRate(c.actual, c.budget);
                const remain = c.budget - c.actual;
                const barColor =
                  rate >= 100
                    ? "bg-red-500"
                    : rate >= 85
                      ? "bg-yellow-400"
                      : "bg-blue-500";
                return (
                  <tr
                    key={c.name}
                    className="hover:bg-gray-50 transition-colors"
                  >
                    <td className="px-6 py-4 font-medium text-gray-900">
                      {c.name}
                    </td>
                    <td className="px-6 py-4 text-right text-gray-700">
                      {c.budget.toLocaleString()}円
                    </td>
                    <td className="px-6 py-4 text-right text-gray-700">
                      {c.actual.toLocaleString()}円
                    </td>
                    <td className="px-6 py-4 text-right text-gray-700">
                      {remain.toLocaleString()}円
                    </td>
                    <td
                      className={`px-6 py-4 text-right ${rateColorClass(rate)}`}
                    >
                      {rate.toFixed(1)}%
                    </td>
                    <td className="px-6 py-4 w-40">
                      <div className="w-full bg-gray-100 rounded-full h-2">
                        <div
                          className={`h-2 rounded-full ${barColor}`}
                          style={{ width: `${Math.min(rate, 100)}%` }}
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
