"use client";

import { useState, useEffect, useCallback } from "react";
import { get, ApiError } from "@/lib/api-client";
import { BarChart3, TrendingUp, Banknote, FileText } from "lucide-react";

// Mock data — 建設業規模（億単位）

const CASHFLOW_MONTHS = [
  {
    month: "1月",
    operating: 185000000,
    investing: -42000000,
    financing: -30000000,
    balance: 820000000,
  },
  {
    month: "2月",
    operating: 220000000,
    investing: -18000000,
    financing: -30000000,
    balance: 992000000,
  },
  {
    month: "3月",
    operating: 310000000,
    investing: -95000000,
    financing: -30000000,
    balance: 1177000000,
  },
  {
    month: "4月",
    operating: 195000000,
    investing: -28000000,
    financing: -30000000,
    balance: 1314000000,
  },
  {
    month: "5月",
    operating: 248000000,
    investing: -35000000,
    financing: -30000000,
    balance: 1497000000,
  },
];

type PlItem = {
  label: string;
  amount: number;
  indent: boolean;
  bold: boolean;
};

type FinancialSummary = {
  total_revenue: number;
  total_cost: number;
  gross_profit: number;
  operating_profit: number;
  projects_count: number;
};

function cfColor(val: number): string {
  if (val > 0) return "text-green-600 font-medium";
  if (val < 0) return "text-red-600 font-medium";
  return "text-gray-700";
}

function fmtAmount(val: number): string {
  const abs = Math.abs(val);
  const sign = val < 0 ? "▲" : val > 0 ? "+" : "";
  if (abs >= 100000000) {
    return `${sign}${(abs / 100000000).toFixed(2)}億円`;
  }
  return `${sign}${abs.toLocaleString()}円`;
}

function buildPlItemsFromSummary(summary: FinancialSummary): PlItem[] {
  const sga = summary.total_revenue - summary.total_cost - summary.gross_profit;
  return [
    {
      label: "売上高",
      amount: Number(summary.total_revenue ?? 0),
      indent: false,
      bold: false,
    },
    {
      label: "売上原価",
      amount: Number(summary.total_cost ?? 0),
      indent: false,
      bold: false,
    },
    {
      label: "売上総利益（粗利）",
      amount: Number(summary.gross_profit ?? 0),
      indent: false,
      bold: true,
    },
    {
      label: "販売費及び一般管理費",
      amount: Math.max(0, sga),
      indent: true,
      bold: false,
    },
    {
      label: "営業利益",
      amount: Number(summary.operating_profit ?? 0),
      indent: false,
      bold: true,
    },
  ];
}

export default function FinancePage() {
  const [plItems, setPlItems] = useState<PlItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const json = await get<{
        data?: FinancialSummary;
        summary?: FinancialSummary;
      }>("/erp/ledger/summary");
      const summary = (json?.data ??
        json?.summary ??
        json ??
        {}) as FinancialSummary;
      if (
        summary.total_revenue !== undefined ||
        summary.operating_profit !== undefined
      ) {
        setPlItems(buildPlItemsFromSummary(summary));
      } else {
        setPlItems([]);
      }
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

  const revenue = plItems.find((i) => i.label === "売上高")?.amount ?? 0;
  const operatingProfit =
    plItems.find((i) => i.label === "営業利益")?.amount ?? 0;
  const operatingMargin =
    revenue > 0 ? ((operatingProfit / revenue) * 100).toFixed(1) : "0.0";
  const latestCF = CASHFLOW_MONTHS[CASHFLOW_MONTHS.length - 1];
  const ytdRevenue = revenue;

  return (
    <div className="max-w-7xl mx-auto px-4 py-8 space-y-8">
      {/* ページヘッダー */}
      <div>
        <h1 className="text-2xl font-bold text-gray-900">財務レポート</h1>
        <p className="text-sm text-gray-500 mt-1">
          損益計算書・キャッシュフローの月次サマリーを確認します（2026年度）
        </p>
      </div>

      {error && (
        <div role="alert" aria-live="assertive" className="rounded-xl border border-danger-500/30 bg-danger-50 px-4 py-3 text-sm text-danger-700">
          {error}
        </div>
      )}
      {!loading && !error && plItems.length === 0 && (
        <div className="rounded-xl border border-gray-200 bg-white px-4 py-8 text-center text-sm text-gray-500">
          該当データがありません。
        </div>
      )}

      {/* 統計カード */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-5 flex items-start gap-4">
          <div className="p-3 rounded-lg bg-blue-50">
            <BarChart3 className="w-5 h-5 text-blue-600" />
          </div>
          <div>
            <p className="text-xs text-gray-500 font-medium">売上高（年度）</p>
            <p className="text-xl font-bold text-gray-900 mt-0.5">
              {(revenue / 100000000).toFixed(2)}億円
            </p>
          </div>
        </div>

        <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-5 flex items-start gap-4">
          <div className="p-3 rounded-lg bg-green-50">
            <TrendingUp className="w-5 h-5 text-green-600" />
          </div>
          <div>
            <p className="text-xs text-gray-500 font-medium">営業利益率</p>
            <p className="text-xl font-bold text-green-600 mt-0.5">
              {operatingMargin}%
            </p>
          </div>
        </div>

        <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-5 flex items-start gap-4">
          <div className="p-3 rounded-lg bg-orange-50">
            <Banknote className="w-5 h-5 text-orange-500" />
          </div>
          <div>
            <p className="text-xs text-gray-500 font-medium">当月末CF残高</p>
            <p className="text-xl font-bold text-gray-900 mt-0.5">
              {(latestCF.balance / 100000000).toFixed(2)}億円
            </p>
          </div>
        </div>

        <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-5 flex items-start gap-4">
          <div className="p-3 rounded-lg bg-purple-50">
            <FileText className="w-5 h-5 text-purple-600" />
          </div>
          <div>
            <p className="text-xs text-gray-500 font-medium">年累計売上</p>
            <p className="text-xl font-bold text-gray-900 mt-0.5">
              {(ytdRevenue / 100000000).toFixed(2)}億円
            </p>
          </div>
        </div>
      </div>

      {/* 損益計算書サマリー */}
      <div className="bg-white rounded-xl shadow-sm border border-gray-100">
        <div className="px-6 py-4 border-b border-gray-100 flex items-center gap-3">
          <h2 className="text-base font-semibold text-gray-800">
            損益計算書サマリー（2026年度）
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
                <th className="px-6 py-3 text-left font-medium">科目</th>
                <th className="px-6 py-3 text-right font-medium">金額</th>
                <th className="px-6 py-3 text-right font-medium">売上比率</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50">
              {plItems.map((item) => {
                const ratio =
                  revenue > 0
                    ? ((item.amount / revenue) * 100).toFixed(1)
                    : "0.0";
                return (
                  <tr
                    key={item.label}
                    className={item.bold ? "bg-gray-50" : "hover:bg-gray-50"}
                  >
                    <td
                      className={`px-6 py-3 ${item.indent ? "pl-10 text-gray-600" : "font-semibold text-gray-900"}`}
                    >
                      {item.label}
                    </td>
                    <td
                      className={`px-6 py-3 text-right ${
                        item.bold ? "font-bold text-gray-900" : "text-gray-700"
                      } ${item.amount < 0 ? "text-red-600" : ""}`}
                    >
                      {fmtAmount(item.amount)}
                    </td>
                    <td className="px-6 py-3 text-right text-gray-500 text-xs">
                      {Number(ratio) < 0 ? "▲" : ""}
                      {Math.abs(Number(ratio)).toFixed(1)}%
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

      {/* 月次キャッシュフロー */}
      <div className="bg-white rounded-xl shadow-sm border border-gray-100">
        <div className="px-6 py-4 border-b border-gray-100">
          <h2 className="text-base font-semibold text-gray-800">
            月次キャッシュフロー計算書（2026年 1〜5月）
          </h2>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-gray-50 text-gray-500 text-xs uppercase tracking-wide">
                <th className="px-6 py-3 text-left font-medium">月</th>
                <th className="px-6 py-3 text-right font-medium">営業CF</th>
                <th className="px-6 py-3 text-right font-medium">投資CF</th>
                <th className="px-6 py-3 text-right font-medium">財務CF</th>
                <th className="px-6 py-3 text-right font-medium">期末残高</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50">
              {CASHFLOW_MONTHS.map((row) => (
                <tr
                  key={row.month}
                  className="hover:bg-gray-50 transition-colors"
                >
                  <td className="px-6 py-4 font-medium text-gray-900">
                    {row.month}
                  </td>
                  <td
                    className={`px-6 py-4 text-right ${cfColor(row.operating)}`}
                  >
                    {fmtAmount(row.operating)}
                  </td>
                  <td
                    className={`px-6 py-4 text-right ${cfColor(row.investing)}`}
                  >
                    {fmtAmount(row.investing)}
                  </td>
                  <td
                    className={`px-6 py-4 text-right ${cfColor(row.financing)}`}
                  >
                    {fmtAmount(row.financing)}
                  </td>
                  <td className="px-6 py-4 text-right font-semibold text-gray-900">
                    {(row.balance / 100000000).toFixed(2)}億円
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
