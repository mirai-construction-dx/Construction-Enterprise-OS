"use client";

import { useState, useCallback, useEffect } from "react";
import { get, ApiError } from "@/lib/api-client";
import { Shield, Cloud, Users, CheckCircle, RefreshCw } from "lucide-react";

const ENTRA_CONFIG = {
  tenantId: "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  clientId: "b2c3d4e5-f6a7-8901-bcde-f12345678901",
  scopes: ["openid", "profile", "email", "User.Read", "Group.Read.All"],
  status: "connected",
  lastSync: "2024-11-30 07:30",
  syncedUsers: 42,
  syncedGroups: 6,
};

type ConditionalPolicy = {
  id: number;
  name: string;
  target: string;
  condition: string;
  action: string;
  status: string;
};

export default function EntraPage() {
  const [policies, setPolicies] = useState<ConditionalPolicy[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const json = await get<{
        items?: Record<string, unknown>[];
        data?: Record<string, unknown>[];
      }>("/auth/entra/policies");
      const items: Record<string, unknown>[] = json?.items ?? json?.data ?? [];
      setPolicies(
        Array.isArray(items)
          ? items.map((item: Record<string, unknown>, idx: number) => ({
              id: Number(item.id ?? idx + 1),
              name: String(item.name ?? ""),
              target: String(item.target ?? ""),
              condition: String(item.condition ?? ""),
              action: String(item.action ?? ""),
              status: String(item.status ?? "disabled"),
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
          <h1 className="text-2xl font-bold text-gray-900">
            Microsoft Entra ID
          </h1>
          <p className="text-sm text-gray-500 mt-1">
            Entra ID (旧Azure AD) 連携設定
          </p>
        </div>
        <button className="flex items-center gap-2 px-4 py-2 border border-gray-300 rounded-lg text-sm text-gray-700 hover:bg-gray-50">
          <RefreshCw className="w-4 h-4" />
          今すぐ同期
        </button>
      </div>

      {/* 統計 */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <div className="bg-white rounded-xl border border-gray-200 p-4 flex items-center gap-3">
          <div className="p-2 bg-blue-50 rounded-lg">
            <Users className="w-5 h-5 text-blue-600" />
          </div>
          <div>
            <p className="text-xs text-gray-500">ユーザー同期数</p>
            <p className="text-2xl font-bold text-gray-900">
              {ENTRA_CONFIG.syncedUsers}名
            </p>
          </div>
        </div>
        <div className="bg-white rounded-xl border border-gray-200 p-4 flex items-center gap-3">
          <div className="p-2 bg-purple-50 rounded-lg">
            <Cloud className="w-5 h-5 text-purple-600" />
          </div>
          <div>
            <p className="text-xs text-gray-500">グループ同期数</p>
            <p className="text-2xl font-bold text-gray-900">
              {ENTRA_CONFIG.syncedGroups}件
            </p>
          </div>
        </div>
        <div className="bg-white rounded-xl border border-gray-200 p-4 flex items-center gap-3">
          <div className="p-2 bg-green-50 rounded-lg">
            <CheckCircle className="w-5 h-5 text-green-600" />
          </div>
          <div>
            <p className="text-xs text-gray-500">最終同期</p>
            <p className="text-sm font-bold text-gray-900">
              {ENTRA_CONFIG.lastSync}
            </p>
          </div>
        </div>
      </div>

      {/* 接続設定 */}
      <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
        <div className="px-5 py-4 border-b border-gray-200 flex items-center justify-between">
          <h2 className="text-base font-semibold text-gray-900">
            Entra ID接続設定
          </h2>
          <span className="flex items-center gap-1.5 text-green-700 text-xs font-medium bg-green-50 px-3 py-1 rounded-full">
            <span className="w-2 h-2 bg-green-500 rounded-full" />
            接続済み
          </span>
        </div>
        <div className="p-5 space-y-4">
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <div>
              <p className="text-xs text-gray-400 mb-1">テナント ID</p>
              <p className="text-sm font-mono text-gray-900 bg-gray-50 px-3 py-2 rounded-lg">
                {ENTRA_CONFIG.tenantId}
              </p>
            </div>
            <div>
              <p className="text-xs text-gray-400 mb-1">クライアント ID</p>
              <p className="text-sm font-mono text-gray-900 bg-gray-50 px-3 py-2 rounded-lg">
                {ENTRA_CONFIG.clientId}
              </p>
            </div>
          </div>
          <div>
            <p className="text-xs text-gray-400 mb-1">スコープ</p>
            <div className="flex flex-wrap gap-2">
              {ENTRA_CONFIG.scopes.map((scope) => (
                <span
                  key={scope}
                  className="px-2 py-0.5 bg-blue-50 text-blue-800 rounded-full text-xs font-mono"
                >
                  {scope}
                </span>
              ))}
            </div>
          </div>
        </div>
      </div>

      {error && (
        <div role="alert" aria-live="assertive" className="rounded-xl border border-danger-500/30 bg-danger-50 px-4 py-3 text-sm text-danger-700">
          {error}
        </div>
      )}
      {!loading && !error && policies.length === 0 && (
        <div className="rounded-xl border border-gray-200 bg-white px-4 py-8 text-center text-sm text-gray-500">
          該当データがありません。
        </div>
      )}

      {/* 条件付きアクセスポリシー */}
      <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
        <div className="px-5 py-4 border-b border-gray-200">
          <h2 className="text-base font-semibold text-gray-900">
            条件付きアクセスポリシー
            {loading && (
              <span className="ml-2 text-xs text-gray-400 font-normal">
                読み込み中...
              </span>
            )}
          </h2>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-gray-50 border-b border-gray-200">
                <th className="px-4 py-3 text-left font-semibold text-gray-600">
                  ポリシー名
                </th>
                <th className="px-4 py-3 text-left font-semibold text-gray-600 whitespace-nowrap">
                  対象
                </th>
                <th className="px-4 py-3 text-left font-semibold text-gray-600 whitespace-nowrap">
                  条件
                </th>
                <th className="px-4 py-3 text-left font-semibold text-gray-600 whitespace-nowrap">
                  アクション
                </th>
                <th className="px-4 py-3 text-left font-semibold text-gray-600 whitespace-nowrap">
                  状態
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {policies.map((policy) => (
                <tr key={policy.id} className="hover:bg-gray-50">
                  <td className="px-4 py-3 font-medium text-gray-900 whitespace-nowrap">
                    {policy.name}
                  </td>
                  <td className="px-4 py-3 text-gray-600 whitespace-nowrap">
                    {policy.target}
                  </td>
                  <td className="px-4 py-3 text-gray-600">
                    {policy.condition}
                  </td>
                  <td className="px-4 py-3 whitespace-nowrap">
                    <span
                      className={`px-2 py-0.5 rounded-full text-xs font-medium ${
                        policy.action === "ブロック"
                          ? "bg-red-100 text-red-800"
                          : policy.action === "MFA要求"
                            ? "bg-orange-100 text-orange-800"
                            : "bg-blue-100 text-blue-800"
                      }`}
                    >
                      {policy.action}
                    </span>
                  </td>
                  <td className="px-4 py-3 whitespace-nowrap">
                    {policy.status === "enabled" ? (
                      <span className="flex items-center gap-1 text-green-700 text-xs font-medium">
                        <CheckCircle className="w-3.5 h-3.5" /> 有効
                      </span>
                    ) : (
                      <span className="text-gray-400 text-xs">無効</span>
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
