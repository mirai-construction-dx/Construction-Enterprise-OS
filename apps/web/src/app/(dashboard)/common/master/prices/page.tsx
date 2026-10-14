"use client";

import { useState, useEffect, useCallback } from "react";
import { DollarSign, RefreshCw, TrendingUp, FileText } from "lucide-react";
import { get, ApiError } from "@/lib/api-client";

type PriceItem = {
  id: number;
  name: string;
  unit: string;
  price: number;
  region: string;
  validFrom: string;
  validTo: string;
  note: string;
};

type HistoryItem = {
  date: string;
  name: string;
  before: number;
  after: number;
  rate: number;
};

const HISTORY: HistoryItem[] = [
  {
    date: "2024-10-01",
    name: "外壁タイル工",
    before: 8800,
    after: 9500,
    rate: 7.9,
  },
  {
    date: "2024-07-01",
    name: "左官工（モルタル塗）",
    before: 2600,
    after: 2800,
    rate: 7.7,
  },
  {
    date: "2024-04-01",
    name: "鉄筋組立工",
    before: 80000,
    after: 85000,
    rate: 6.3,
  },
  {
    date: "2024-04-01",
    name: "コンクリート打設工",
    before: 3000,
    after: 3200,
    rate: 6.7,
  },
];

export default function PricesPage() {
  const [prices, setPrices] = useState<PriceItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const json = await get<{
        data?: { items?: Record<string, unknown>[] };
        items?: Record<string, unknown>[];
      }>("/erp/costs?cost_type=unit_price&per_page=50");
      const data = json?.data?.items ?? json?.items ?? json?.data ?? [];
      setPrices(
        Array.isArray(data)
          ? data.map((item: Record<string, unknown>) => ({
              id: Number(item.id ?? 0),
              name: String(item.item_name ?? item.name ?? ""),
              unit: String(item.unit ?? ""),
              price: Number(item.unit_price ?? item.price ?? 0),
              region: String(item.region ?? "首都圏"),
              validFrom: String(item.effective_date ?? item.valid_from ?? ""),
              validTo: String(item.expiry_date ?? item.valid_to ?? ""),
              note: String(item.note ?? item.description ?? ""),
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

  const totalTypes = prices.length;
  const thisMonthRevised = HISTORY.filter((h) =>
    h.date.startsWith("2024-10"),
  ).length;

  return (
    <div className="space-y-6 p-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">単価マスタ</h1>
          <p className="text-sm text-gray-500 mt-1">
            工種別単価の管理・改定履歴
            {loading && (
              <span className="ml-2 text-blue-500 animate-pulse">
                読み込み中...
              </span>
            )}
          </p>
        </div>
        <button className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white text-sm rounded-lg hover:bg-blue-700">
          <DollarSign className="w-4 h-4" />
          単価追加
        </button>
      </div>

      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        <div className="bg-white rounded-xl border border-gray-200 p-4 flex items-center gap-3">
          <div className="p-2 bg-blue-50 rounded-lg">
            <FileText className="w-5 h-5 text-blue-600" />
          </div>
          <div>
            <p className="text-xs text-gray-500">登録工種数</p>
            <p className="text-2xl font-bold text-gray-900">{totalTypes}</p>
          </div>
        </div>
        <div className="bg-white rounded-xl border border-gray-200 p-4 flex items-center gap-3">
          <div className="p-2 bg-orange-50 rounded-lg">
            <RefreshCw className="w-5 h-5 text-orange-600" />
          </div>
          <div>
            <p className="text-xs text-gray-500">今月改定数</p>
            <p className="text-2xl font-bold text-gray-900">
              {thisMonthRevised}
            </p>
          </div>
        </div>
        <div className="bg-white rounded-xl border border-gray-200 p-4 flex items-center gap-3">
          <div className="p-2 bg-green-50 rounded-lg">
            <TrendingUp className="w-5 h-5 text-green-600" />
          </div>
          <div>
            <p className="text-xs text-gray-500">年間改定件数</p>
            <p className="text-2xl font-bold text-gray-900">{HISTORY.length}</p>
          </div>
        </div>
        <div className="bg-white rounded-xl border border-gray-200 p-4 flex items-center gap-3">
          <div className="p-2 bg-purple-50 rounded-lg">
            <DollarSign className="w-5 h-5 text-purple-600" />
          </div>
          <div>
            <p className="text-xs text-gray-500">適用地域</p>
            <p className="text-xl font-bold text-gray-900">首都圏</p>
          </div>
        </div>
      </div>

      {error && (
        <div role="alert" aria-live="assertive" className="rounded-xl border border-danger-500/30 bg-danger-50 px-4 py-3 text-sm text-danger-700">
          {error}
        </div>
      )}
      {!loading && !error && prices.length === 0 && (
        <div className="rounded-xl border border-gray-200 bg-white px-4 py-8 text-center text-sm text-gray-500">
          該当データがありません。
        </div>
      )}

      {/* 単価テーブル */}
      <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
        <div className="px-5 py-4 border-b border-gray-200">
          <h2 className="text-base font-semibold text-gray-900">
            工種別単価一覧
          </h2>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-gray-50 border-b border-gray-200">
                <th className="px-4 py-3 text-left font-semibold text-gray-600">
                  工種名
                </th>
                <th className="px-4 py-3 text-left font-semibold text-gray-600 whitespace-nowrap">
                  単位
                </th>
                <th className="px-4 py-3 text-right font-semibold text-gray-600 whitespace-nowrap">
                  単価
                </th>
                <th className="px-4 py-3 text-left font-semibold text-gray-600 whitespace-nowrap">
                  適用地域
                </th>
                <th className="px-4 py-3 text-left font-semibold text-gray-600 whitespace-nowrap">
                  有効期間
                </th>
                <th className="px-4 py-3 text-left font-semibold text-gray-600">
                  備考
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {prices.map((p) => (
                <tr key={p.id} className="hover:bg-gray-50">
                  <td className="px-4 py-3 font-medium text-gray-900">
                    {p.name}
                  </td>
                  <td className="px-4 py-3 text-gray-600 whitespace-nowrap">
                    {p.unit}
                  </td>
                  <td className="px-4 py-3 text-gray-900 font-medium whitespace-nowrap text-right">
                    ¥{p.price.toLocaleString()}
                  </td>
                  <td className="px-4 py-3 text-gray-600 whitespace-nowrap">
                    {p.region}
                  </td>
                  <td className="px-4 py-3 text-gray-600 whitespace-nowrap text-xs">
                    {p.validFrom} 〜 {p.validTo}
                  </td>
                  <td className="px-4 py-3 text-gray-500 text-xs">{p.note}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* 改定履歴 */}
      <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
        <div className="px-5 py-4 border-b border-gray-200">
          <h2 className="text-base font-semibold text-gray-900">改定履歴</h2>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-gray-50 border-b border-gray-200">
                <th className="px-4 py-3 text-left font-semibold text-gray-600 whitespace-nowrap">
                  改定日
                </th>
                <th className="px-4 py-3 text-left font-semibold text-gray-600">
                  工種名
                </th>
                <th className="px-4 py-3 text-right font-semibold text-gray-600 whitespace-nowrap">
                  変更前単価
                </th>
                <th className="px-4 py-3 text-right font-semibold text-gray-600 whitespace-nowrap">
                  変更後単価
                </th>
                <th className="px-4 py-3 text-right font-semibold text-gray-600 whitespace-nowrap">
                  変更率
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {HISTORY.map((h, i) => (
                <tr key={i} className="hover:bg-gray-50">
                  <td className="px-4 py-3 text-gray-600 whitespace-nowrap">
                    {h.date}
                  </td>
                  <td className="px-4 py-3 font-medium text-gray-900">
                    {h.name}
                  </td>
                  <td className="px-4 py-3 text-gray-500 whitespace-nowrap text-right">
                    ¥{h.before.toLocaleString()}
                  </td>
                  <td className="px-4 py-3 text-gray-900 font-medium whitespace-nowrap text-right">
                    ¥{h.after.toLocaleString()}
                  </td>
                  <td className="px-4 py-3 whitespace-nowrap text-right">
                    <span className="flex items-center justify-end gap-1 text-red-600 font-medium">
                      <TrendingUp className="w-3.5 h-3.5" />+{h.rate}%
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
