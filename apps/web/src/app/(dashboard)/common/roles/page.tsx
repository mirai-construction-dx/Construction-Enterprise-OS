"use client";

import { useState, useEffect, useCallback } from "react";
import { Shield, Lock, Users, CheckSquare } from "lucide-react";
import { get, ApiError } from "@/lib/api-client";

type Role = {
  id: number;
  name: string;
  description: string;
  users: number;
  moduleCount: number;
  updated: string;
};

const MODULES = [
  "ダッシュボード",
  "プロジェクト",
  "文書",
  "GIS",
  "IoT",
  "安全",
  "ERP",
  "ワークフロー",
  "設定",
];

const PERMISSIONS: Record<string, boolean[]> = {
  管理者: [true, true, true, true, true, true, true, true, true],
  プロジェクトマネージャー: [
    true,
    true,
    true,
    true,
    false,
    true,
    true,
    true,
    false,
  ],
  現場監督: [true, true, false, true, true, true, false, false, false],
  安全管理者: [true, false, false, false, true, true, false, false, false],
  閲覧のみ: [true, true, true, true, true, true, true, true, false],
};

export default function RolesPage() {
  const [roles, setRoles] = useState<Role[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const json = await get<{
        data?: { items?: Record<string, unknown>[] };
        items?: Record<string, unknown>[];
      }>("/roles?per_page=50");
      const data = json?.data?.items ?? json?.items ?? json?.data ?? [];
      setRoles(
        Array.isArray(data)
          ? data.map((item: Record<string, unknown>) => ({
              id: Number(item.id ?? 0),
              name: String(item.name ?? ""),
              description: String(item.description ?? ""),
              users: Number(item.users_count ?? item.users ?? 0),
              moduleCount: Number(
                item.permissions_count ?? item.module_count ?? 0,
              ),
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

  return (
    <div className="space-y-6 p-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">権限管理</h1>
          <p className="text-sm text-gray-500 mt-1">
            ロール定義と機能モジュールのアクセス権限
            {loading && (
              <span className="ml-2 text-blue-500 animate-pulse">
                読み込み中...
              </span>
            )}
          </p>
        </div>
        <button className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white text-sm rounded-lg hover:bg-blue-700">
          <Shield className="w-4 h-4" />
          ロール追加
        </button>
      </div>

      {error && (
        <div role="alert" aria-live="assertive" className="rounded-xl border border-danger-500/30 bg-danger-50 px-4 py-3 text-sm text-danger-700">
          {error}
        </div>
      )}
      {!loading && !error && roles.length === 0 && (
        <div className="rounded-xl border border-gray-200 bg-white px-4 py-8 text-center text-sm text-gray-500">
          該当データがありません。
        </div>
      )}

      {/* ロール一覧 */}
      <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
        <div className="px-5 py-4 border-b border-gray-200">
          <h2 className="text-base font-semibold text-gray-900">ロール一覧</h2>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-gray-50 border-b border-gray-200">
                <th className="px-4 py-3 text-left font-semibold text-gray-600">
                  ロール名
                </th>
                <th className="px-4 py-3 text-left font-semibold text-gray-600">
                  説明
                </th>
                <th className="px-4 py-3 text-right font-semibold text-gray-600 whitespace-nowrap">
                  ユーザー数
                </th>
                <th className="px-4 py-3 text-right font-semibold text-gray-600 whitespace-nowrap">
                  権限カテゴリ数
                </th>
                <th className="px-4 py-3 text-left font-semibold text-gray-600 whitespace-nowrap">
                  最終更新
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {roles.map((role) => (
                <tr key={role.id} className="hover:bg-gray-50">
                  <td className="px-4 py-3 font-medium text-gray-900 whitespace-nowrap">
                    <div className="flex items-center gap-2">
                      <Lock className="w-4 h-4 text-gray-400" />
                      {role.name}
                    </div>
                  </td>
                  <td className="px-4 py-3 text-gray-600">
                    {role.description}
                  </td>
                  <td className="px-4 py-3 text-gray-600 text-right whitespace-nowrap">
                    <div className="flex items-center justify-end gap-1">
                      <Users className="w-3.5 h-3.5 text-gray-400" />
                      {role.users}
                    </div>
                  </td>
                  <td className="px-4 py-3 text-gray-600 text-right whitespace-nowrap">
                    {role.moduleCount}
                  </td>
                  <td className="px-4 py-3 text-gray-500 whitespace-nowrap text-xs">
                    {role.updated}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* 権限マトリクス */}
      <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
        <div className="px-5 py-4 border-b border-gray-200">
          <h2 className="text-base font-semibold text-gray-900">
            権限マトリクス
          </h2>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-gray-50 border-b border-gray-200">
                <th className="px-4 py-3 text-left font-semibold text-gray-600 min-w-[180px]">
                  ロール
                </th>
                {MODULES.map((mod) => (
                  <th
                    key={mod}
                    className="px-3 py-3 text-center font-semibold text-gray-600 whitespace-nowrap text-xs"
                  >
                    {mod}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {roles.map((role) => (
                <tr key={role.id} className="hover:bg-gray-50">
                  <td className="px-4 py-2.5 font-medium text-gray-900 whitespace-nowrap">
                    {role.name}
                  </td>
                  {(PERMISSIONS[role.name] ?? MODULES.map(() => false)).map(
                    (allowed, idx) => (
                      <td key={idx} className="px-3 py-2.5 text-center">
                        {allowed ? (
                          <CheckSquare className="w-4 h-4 text-green-500 mx-auto" />
                        ) : (
                          <span className="text-gray-300 text-base leading-none">
                            ✕
                          </span>
                        )}
                      </td>
                    ),
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
