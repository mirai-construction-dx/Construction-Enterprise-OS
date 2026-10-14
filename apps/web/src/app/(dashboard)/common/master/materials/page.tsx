"use client";

import { useState, useEffect, useCallback } from "react";
import { get, ApiError } from "@/lib/api-client";
import { Package, Boxes, DollarSign, RefreshCw } from "lucide-react";

type Material = {
  id: number;
  code: string;
  name: string;
  spec: string;
  unit: string;
  price: number;
  stock: number;
  category: string;
  updated: string;
};

const CATEGORY_COLORS: Record<string, string> = {
  鉄筋: "bg-red-100 text-red-800",
  コンクリート: "bg-gray-100 text-gray-700",
  木材: "bg-yellow-100 text-yellow-800",
  電材: "bg-blue-100 text-blue-800",
  管材: "bg-green-100 text-green-800",
  仮設: "bg-purple-100 text-purple-800",
};

export default function MaterialsPage() {
  const [materials, setMaterials] = useState<Material[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      let json:
        | {
            data?: { items?: Record<string, unknown>[] };
            items?: Record<string, unknown>[];
          }
        | undefined;
      try {
        json = await get<{
          data?: { items?: Record<string, unknown>[] };
          items?: Record<string, unknown>[];
        }>("/construction/materials?per_page=50");
      } catch {
        json = await get<{
          data?: { items?: Record<string, unknown>[] };
          items?: Record<string, unknown>[];
        }>("/erp/materials?per_page=50");
      }
      const data = json?.data?.items ?? json?.items ?? json?.data ?? [];
      setMaterials(
        Array.isArray(data)
          ? data.map((item: Record<string, unknown>) => ({
              id: Number(item.id ?? 0),
              code: String(item.code ?? item.material_code ?? ""),
              name: String(item.name ?? ""),
              spec: String(item.spec ?? item.specification ?? ""),
              unit: String(item.unit ?? ""),
              price: Number(item.unit_price ?? item.price ?? 0),
              stock: Number(item.stock_quantity ?? item.stock ?? 0),
              category: String(item.material_type ?? item.category ?? ""),
              updated: String(item.updated_at ?? item.created_at ?? ""),
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

  const totalItems = materials.length;
  const thisMonthUpdated = materials.filter((m) =>
    m.updated.startsWith("2024-11"),
  ).length;
  const lowStock = materials.filter((m) => m.stock < 10).length;
  const priceRevision = 3;

  return (
    <div className="space-y-6 p-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">資材マスタ</h1>
          <p className="text-sm text-gray-500 mt-1">
            建設資材・材料のマスタデータ管理
            {loading && (
              <span className="ml-2 text-blue-500 animate-pulse">
                読み込み中...
              </span>
            )}
          </p>
        </div>
        <button className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white text-sm rounded-lg hover:bg-blue-700">
          <Package className="w-4 h-4" />
          品目追加
        </button>
      </div>

      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        <div className="bg-white rounded-xl border border-gray-200 p-4 flex items-center gap-3">
          <div className="p-2 bg-blue-50 rounded-lg">
            <Package className="w-5 h-5 text-blue-600" />
          </div>
          <div>
            <p className="text-xs text-gray-500">総品目数</p>
            <p className="text-2xl font-bold text-gray-900">{totalItems}</p>
          </div>
        </div>
        <div className="bg-white rounded-xl border border-gray-200 p-4 flex items-center gap-3">
          <div className="p-2 bg-green-50 rounded-lg">
            <RefreshCw className="w-5 h-5 text-green-600" />
          </div>
          <div>
            <p className="text-xs text-gray-500">今月更新</p>
            <p className="text-2xl font-bold text-gray-900">
              {thisMonthUpdated}
            </p>
          </div>
        </div>
        <div className="bg-white rounded-xl border border-gray-200 p-4 flex items-center gap-3">
          <div className="p-2 bg-orange-50 rounded-lg">
            <Boxes className="w-5 h-5 text-orange-600" />
          </div>
          <div>
            <p className="text-xs text-gray-500">低在庫</p>
            <p className="text-2xl font-bold text-gray-900">{lowStock}</p>
          </div>
        </div>
        <div className="bg-white rounded-xl border border-gray-200 p-4 flex items-center gap-3">
          <div className="p-2 bg-purple-50 rounded-lg">
            <DollarSign className="w-5 h-5 text-purple-600" />
          </div>
          <div>
            <p className="text-xs text-gray-500">単価改定予定</p>
            <p className="text-2xl font-bold text-gray-900">{priceRevision}</p>
          </div>
        </div>
      </div>

      {error && (
        <div role="alert" aria-live="assertive" className="rounded-xl border border-danger-500/30 bg-danger-50 px-4 py-3 text-sm text-danger-700">
          {error}
        </div>
      )}
      {!loading && !error && materials.length === 0 && (
        <div className="rounded-xl border border-gray-200 bg-white px-4 py-8 text-center text-sm text-gray-500">
          該当データがありません。
        </div>
      )}

      <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-gray-50 border-b border-gray-200">
                <th className="px-4 py-3 text-left font-semibold text-gray-600 whitespace-nowrap">
                  品目コード
                </th>
                <th className="px-4 py-3 text-left font-semibold text-gray-600">
                  品名
                </th>
                <th className="px-4 py-3 text-left font-semibold text-gray-600">
                  規格
                </th>
                <th className="px-4 py-3 text-left font-semibold text-gray-600 whitespace-nowrap">
                  単位
                </th>
                <th className="px-4 py-3 text-right font-semibold text-gray-600 whitespace-nowrap">
                  標準単価
                </th>
                <th className="px-4 py-3 text-right font-semibold text-gray-600 whitespace-nowrap">
                  在庫数
                </th>
                <th className="px-4 py-3 text-left font-semibold text-gray-600 whitespace-nowrap">
                  カテゴリ
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {materials.map((mat) => (
                <tr
                  key={mat.id}
                  className={`hover:bg-gray-50 ${mat.stock < 10 ? "bg-red-50" : ""}`}
                >
                  <td className="px-4 py-3 text-gray-500 whitespace-nowrap text-xs font-mono">
                    {mat.code}
                  </td>
                  <td className="px-4 py-3 font-medium text-gray-900">
                    {mat.name}
                  </td>
                  <td className="px-4 py-3 text-gray-600 text-xs">
                    {mat.spec}
                  </td>
                  <td className="px-4 py-3 text-gray-600 whitespace-nowrap">
                    {mat.unit}
                  </td>
                  <td className="px-4 py-3 text-gray-900 whitespace-nowrap text-right font-medium">
                    ¥{mat.price.toLocaleString()}
                  </td>
                  <td
                    className={`px-4 py-3 whitespace-nowrap text-right font-medium ${mat.stock < 10 ? "text-red-600" : "text-gray-900"}`}
                  >
                    {mat.stock.toLocaleString()}
                  </td>
                  <td className="px-4 py-3 whitespace-nowrap">
                    <span
                      className={`px-2 py-0.5 rounded-full text-xs font-medium ${CATEGORY_COLORS[mat.category] ?? "bg-gray-100 text-gray-700"}`}
                    >
                      {mat.category}
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
