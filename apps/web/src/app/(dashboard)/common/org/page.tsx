"use client";

import { useState, useEffect, useCallback } from "react";
import { get, ApiError } from "@/lib/api-client";
import { Building, Users, Network, TreePine } from "lucide-react";

type Department = {
  id: number;
  code: string;
  name: string;
  manager: string;
  members: number;
  parent: string | null;
  work: string;
  level: number;
};

const INDENT_CLASSES: Record<number, string> = {
  0: "",
  1: "pl-6",
  2: "pl-12",
};

export default function OrgPage() {
  const [departments, setDepartments] = useState<Department[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const json = await get<{
        data?: { items?: Record<string, unknown>[] };
        items?: Record<string, unknown>[];
      }>("/users/organizations?per_page=20");
      const data = json?.data?.items ?? json?.items ?? json?.data ?? [];
      setDepartments(
        Array.isArray(data)
          ? data.map((item: Record<string, unknown>, idx: number) => ({
              id: Number(item.id ?? idx),
              code: String(item.code ?? `D${String(idx + 1).padStart(3, "0")}`),
              name: String(item.name ?? ""),
              manager: String(item.manager ?? item.manager_name ?? ""),
              members: Number(item.users_count ?? item.members ?? 0),
              parent: item.parent_name ? String(item.parent_name) : null,
              work: String(item.description ?? item.work ?? ""),
              level: Number(item.level ?? 0),
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

  const totalDept = departments.length;
  const totalMembers =
    departments
      .filter((d) => d.level === 1)
      .reduce((s, d) => s + d.members, 0) +
    (departments.find((d) => d.level === 0)?.members ?? 0);
  const executives = departments
    .filter((d) => d.level === 0)
    .reduce((s, d) => s + d.members, 0);
  const offices = departments.filter((d) => d.code.startsWith("D00")).length;

  return (
    <div className="space-y-6 p-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">組織管理</h1>
          <p className="text-sm text-gray-500 mt-1">
            部署・チームの組織ツリー管理
            {loading && (
              <span className="ml-2 text-blue-500 animate-pulse">
                読み込み中...
              </span>
            )}
          </p>
        </div>
        <button className="px-4 py-2 bg-blue-600 text-white text-sm rounded-lg hover:bg-blue-700">
          部署追加
        </button>
      </div>

      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        <div className="bg-white rounded-xl border border-gray-200 p-4 flex items-center gap-3">
          <div className="p-2 bg-blue-50 rounded-lg">
            <Building className="w-5 h-5 text-blue-600" />
          </div>
          <div>
            <p className="text-xs text-gray-500">総部署数</p>
            <p className="text-2xl font-bold text-gray-900">{totalDept}</p>
          </div>
        </div>
        <div className="bg-white rounded-xl border border-gray-200 p-4 flex items-center gap-3">
          <div className="p-2 bg-green-50 rounded-lg">
            <Users className="w-5 h-5 text-green-600" />
          </div>
          <div>
            <p className="text-xs text-gray-500">総人員数</p>
            <p className="text-2xl font-bold text-gray-900">{totalMembers}</p>
          </div>
        </div>
        <div className="bg-white rounded-xl border border-gray-200 p-4 flex items-center gap-3">
          <div className="p-2 bg-purple-50 rounded-lg">
            <Network className="w-5 h-5 text-purple-600" />
          </div>
          <div>
            <p className="text-xs text-gray-500">役員数</p>
            <p className="text-2xl font-bold text-gray-900">{executives}</p>
          </div>
        </div>
        <div className="bg-white rounded-xl border border-gray-200 p-4 flex items-center gap-3">
          <div className="p-2 bg-orange-50 rounded-lg">
            <TreePine className="w-5 h-5 text-orange-600" />
          </div>
          <div>
            <p className="text-xs text-gray-500">事業所数</p>
            <p className="text-2xl font-bold text-gray-900">{offices}</p>
          </div>
        </div>
      </div>

      {error && (
        <div role="alert" aria-live="assertive" className="rounded-xl border border-danger-500/30 bg-danger-50 px-4 py-3 text-sm text-danger-700">
          {error}
        </div>
      )}
      {!loading && !error && departments.length === 0 && (
        <div className="rounded-xl border border-gray-200 bg-white px-4 py-8 text-center text-sm text-gray-500">
          該当データがありません。
        </div>
      )}

      {/* 組織ツリーテーブル */}
      <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
        <div className="px-5 py-4 border-b border-gray-200">
          <h2 className="text-base font-semibold text-gray-900">組織ツリー</h2>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-gray-50 border-b border-gray-200">
                <th className="px-4 py-3 text-left font-semibold text-gray-600 whitespace-nowrap">
                  部署コード
                </th>
                <th className="px-4 py-3 text-left font-semibold text-gray-600">
                  部署名
                </th>
                <th className="px-4 py-3 text-left font-semibold text-gray-600 whitespace-nowrap">
                  責任者
                </th>
                <th className="px-4 py-3 text-right font-semibold text-gray-600 whitespace-nowrap">
                  人数
                </th>
                <th className="px-4 py-3 text-left font-semibold text-gray-600 whitespace-nowrap">
                  上位部署
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {departments.map((dept) => (
                <tr
                  key={dept.id}
                  className={`hover:bg-gray-50 ${dept.level === 0 ? "bg-gray-50 font-semibold" : ""}`}
                >
                  <td className="px-4 py-2.5 text-gray-500 whitespace-nowrap text-xs">
                    {dept.code}
                  </td>
                  <td
                    className={`px-4 py-2.5 text-gray-900 whitespace-nowrap ${INDENT_CLASSES[dept.level] ?? ""}`}
                  >
                    {dept.name}
                  </td>
                  <td className="px-4 py-2.5 text-gray-600 whitespace-nowrap">
                    {dept.manager}
                  </td>
                  <td className="px-4 py-2.5 text-gray-600 whitespace-nowrap text-right">
                    {dept.members}名
                  </td>
                  <td className="px-4 py-2.5 text-gray-500 whitespace-nowrap">
                    {dept.parent ?? "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* 部署カード */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        {departments
          .filter((d) => d.level <= 1)
          .map((dept) => (
            <div
              key={dept.id}
              className="bg-white rounded-xl border border-gray-200 p-4"
            >
              <div className="flex items-start justify-between">
                <div>
                  <h3 className="font-semibold text-gray-900">{dept.name}</h3>
                  <p className="text-xs text-gray-400 mt-0.5">{dept.code}</p>
                </div>
                <span className="text-xs bg-blue-100 text-blue-800 px-2 py-0.5 rounded-full font-medium">
                  {dept.members}名
                </span>
              </div>
              <div className="mt-3 space-y-1">
                <p className="text-sm text-gray-600">
                  <span className="text-gray-400">責任者:</span> {dept.manager}
                </p>
                <p className="text-sm text-gray-600">
                  <span className="text-gray-400">業務:</span> {dept.work}
                </p>
              </div>
            </div>
          ))}
      </div>
    </div>
  );
}
