"use client";

import { useState, useEffect, useCallback } from "react";
import { get, ApiError } from "@/lib/api-client";
import { Layers, Clock, CheckSquare } from "lucide-react";

type WorkType = {
  id: number;
  code: string;
  name: string;
  category: string;
  stdHours: number;
  safetyReq: boolean;
  qualReq: string | null;
  cert: string | null;
};

const CATEGORY_COLORS: Record<string, string> = {
  土工: "bg-yellow-100 text-yellow-800",
  基礎工: "bg-orange-100 text-orange-800",
  躯体工: "bg-blue-100 text-blue-800",
  仕上工: "bg-green-100 text-green-800",
  設備工: "bg-purple-100 text-purple-800",
  外構: "bg-teal-100 text-teal-800",
};

export default function WorkTypesPage() {
  const [workTypes, setWorkTypes] = useState<WorkType[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const json = await get<{
        data?: { items?: Record<string, unknown>[] };
        items?: Record<string, unknown>[];
      }>("/construction/work-types?per_page=50");
      const data = json?.data?.items ?? json?.items ?? json?.data ?? [];
      setWorkTypes(
        Array.isArray(data)
          ? data.map((item: Record<string, unknown>) => ({
              id: Number(item.id ?? 0),
              code: String(item.code ?? item.work_type_code ?? ""),
              name: String(item.name ?? ""),
              category: String(item.category ?? ""),
              stdHours: Number(item.standard_rate ?? item.std_hours ?? 0),
              safetyReq: Boolean(
                item.safety_required ?? item.safety_req ?? false,
              ),
              qualReq: item.qualification_required
                ? String(item.qualification_required)
                : item.qual_req
                  ? String(item.qual_req)
                  : null,
              cert: item.certification
                ? String(item.certification)
                : item.cert
                  ? String(item.cert)
                  : null,
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

  const totalTypes = workTypes.length;
  const categories = [...new Set(workTypes.map((w) => w.category))].length;
  const safetyRequired = workTypes.filter((w) => w.safetyReq).length;

  return (
    <div className="space-y-6 p-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">作業種別マスタ</h1>
          <p className="text-sm text-gray-500 mt-1">
            工事作業の種別・資格・安全要件管理
            {loading && (
              <span className="ml-2 text-blue-500 animate-pulse">
                読み込み中...
              </span>
            )}
          </p>
        </div>
        <button className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white text-sm rounded-lg hover:bg-blue-700">
          <Layers className="w-4 h-4" />
          種別追加
        </button>
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <div className="bg-white rounded-xl border border-gray-200 p-4 flex items-center gap-3">
          <div className="p-2 bg-blue-50 rounded-lg">
            <Layers className="w-5 h-5 text-blue-600" />
          </div>
          <div>
            <p className="text-xs text-gray-500">登録種別数</p>
            <p className="text-2xl font-bold text-gray-900">{totalTypes}</p>
          </div>
        </div>
        <div className="bg-white rounded-xl border border-gray-200 p-4 flex items-center gap-3">
          <div className="p-2 bg-green-50 rounded-lg">
            <Clock className="w-5 h-5 text-green-600" />
          </div>
          <div>
            <p className="text-xs text-gray-500">カテゴリ数</p>
            <p className="text-2xl font-bold text-gray-900">{categories}</p>
          </div>
        </div>
        <div className="bg-white rounded-xl border border-gray-200 p-4 flex items-center gap-3">
          <div className="p-2 bg-orange-50 rounded-lg">
            <CheckSquare className="w-5 h-5 text-orange-600" />
          </div>
          <div>
            <p className="text-xs text-gray-500">安全要件あり</p>
            <p className="text-2xl font-bold text-gray-900">{safetyRequired}</p>
          </div>
        </div>
      </div>

      {error && (
        <div role="alert" aria-live="assertive" className="rounded-xl border border-danger-500/30 bg-danger-50 px-4 py-3 text-sm text-danger-700">
          {error}
        </div>
      )}
      {!loading && !error && workTypes.length === 0 && (
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
                  種別コード
                </th>
                <th className="px-4 py-3 text-left font-semibold text-gray-600">
                  種別名
                </th>
                <th className="px-4 py-3 text-left font-semibold text-gray-600 whitespace-nowrap">
                  カテゴリ
                </th>
                <th className="px-4 py-3 text-right font-semibold text-gray-600 whitespace-nowrap">
                  標準工数(h)
                </th>
                <th className="px-4 py-3 text-center font-semibold text-gray-600 whitespace-nowrap">
                  安全要件
                </th>
                <th className="px-4 py-3 text-left font-semibold text-gray-600">
                  資格要件
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {workTypes.map((wt) => (
                <tr key={wt.id} className="hover:bg-gray-50">
                  <td className="px-4 py-3 text-gray-500 whitespace-nowrap text-xs font-mono">
                    {wt.code}
                  </td>
                  <td className="px-4 py-3 font-medium text-gray-900">
                    {wt.name}
                  </td>
                  <td className="px-4 py-3 whitespace-nowrap">
                    <span
                      className={`px-2 py-0.5 rounded-full text-xs font-medium ${CATEGORY_COLORS[wt.category] ?? "bg-gray-100 text-gray-700"}`}
                    >
                      {wt.category}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-gray-600 whitespace-nowrap text-right">
                    {wt.stdHours}h
                  </td>
                  <td className="px-4 py-3 text-center">
                    {wt.safetyReq ? (
                      <CheckSquare className="w-4 h-4 text-orange-500 mx-auto" />
                    ) : (
                      <span className="text-gray-300">—</span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-gray-600 text-xs">
                    {wt.qualReq ?? <span className="text-gray-400">不要</span>}
                    {wt.cert && (
                      <span className="ml-2 px-1.5 py-0.5 bg-gray-100 text-gray-600 rounded text-xs">
                        {wt.cert}
                      </span>
                    )}
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
