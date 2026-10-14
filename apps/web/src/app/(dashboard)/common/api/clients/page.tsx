"use client";

import { useState, useEffect, useCallback } from "react";
import { get, ApiError } from "@/lib/api-client";
import { Key, Webhook, Activity, Shield } from "lucide-react";

type ApiClient = {
  id: number;
  name: string;
  type: string;
  apiKey: string;
  scopes: string[];
  lastUsed: string;
  status: string;
};

const STATUS_STYLES: Record<string, string> = {
  active: "bg-green-100 text-green-800",
  inactive: "bg-gray-100 text-gray-700",
};

const STATUS_LABELS: Record<string, string> = {
  active: "アクティブ",
  inactive: "非アクティブ",
};

export default function ApiClientsPage() {
  const [apiClients, setApiClients] = useState<ApiClient[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const json = await get<{
        data?: { items?: Record<string, unknown>[] };
        items?: Record<string, unknown>[];
      }>("/api-clients?per_page=50");
      const data = json?.data?.items ?? json?.items ?? json?.data ?? [];
      setApiClients(
        Array.isArray(data)
          ? data.map((item: Record<string, unknown>) => ({
              id: Number(item.id ?? 0),
              name: String(item.name ?? ""),
              type: String(item.client_type ?? item.type ?? ""),
              apiKey: String(item.client_id ?? item.api_key ?? ""),
              scopes: Array.isArray(item.permissions)
                ? (item.permissions as unknown[]).map((s) => String(s))
                : Array.isArray(item.scopes)
                  ? (item.scopes as unknown[]).map((s) => String(s))
                  : [],
              lastUsed: String(item.last_used_at ?? item.last_used ?? ""),
              status: String(item.status ?? "active"),
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

  const total = apiClients.length;
  const active = apiClients.filter((c) => c.status === "active").length;
  const todayCalls = 12847;

  return (
    <div className="space-y-6 p-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">
            APIクライアント管理
          </h1>
          <p className="text-sm text-gray-500 mt-1">
            外部システム連携APIキーの発行・管理
            {loading && (
              <span className="ml-2 text-blue-500 animate-pulse">
                読み込み中...
              </span>
            )}
          </p>
        </div>
        <button className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white text-sm rounded-lg hover:bg-blue-700">
          <Key className="w-4 h-4" />
          新規クライアント登録
        </button>
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <div className="bg-white rounded-xl border border-gray-200 p-4 flex items-center gap-3">
          <div className="p-2 bg-blue-50 rounded-lg">
            <Webhook className="w-5 h-5 text-blue-600" />
          </div>
          <div>
            <p className="text-xs text-gray-500">総クライアント数</p>
            <p className="text-2xl font-bold text-gray-900">{total}</p>
          </div>
        </div>
        <div className="bg-white rounded-xl border border-gray-200 p-4 flex items-center gap-3">
          <div className="p-2 bg-green-50 rounded-lg">
            <Shield className="w-5 h-5 text-green-600" />
          </div>
          <div>
            <p className="text-xs text-gray-500">アクティブ</p>
            <p className="text-2xl font-bold text-gray-900">{active}</p>
          </div>
        </div>
        <div className="bg-white rounded-xl border border-gray-200 p-4 flex items-center gap-3">
          <div className="p-2 bg-purple-50 rounded-lg">
            <Activity className="w-5 h-5 text-purple-600" />
          </div>
          <div>
            <p className="text-xs text-gray-500">今日のAPIコール</p>
            <p className="text-2xl font-bold text-gray-900">
              {todayCalls.toLocaleString()}
            </p>
          </div>
        </div>
      </div>

      {error && (
        <div role="alert" aria-live="assertive" className="rounded-xl border border-danger-500/30 bg-danger-50 px-4 py-3 text-sm text-danger-700">
          {error}
        </div>
      )}
      {!loading && !error && apiClients.length === 0 && (
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
                  クライアント名
                </th>
                <th className="px-4 py-3 text-left font-semibold text-gray-600 whitespace-nowrap">
                  システム種別
                </th>
                <th className="px-4 py-3 text-left font-semibold text-gray-600 whitespace-nowrap">
                  APIキー
                </th>
                <th className="px-4 py-3 text-left font-semibold text-gray-600 whitespace-nowrap">
                  権限スコープ
                </th>
                <th className="px-4 py-3 text-left font-semibold text-gray-600 whitespace-nowrap">
                  最終利用
                </th>
                <th className="px-4 py-3 text-left font-semibold text-gray-600 whitespace-nowrap">
                  ステータス
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {apiClients.map((client) => (
                <tr key={client.id} className="hover:bg-gray-50">
                  <td className="px-4 py-3 font-medium text-gray-900">
                    {client.name}
                  </td>
                  <td className="px-4 py-3 text-gray-600 whitespace-nowrap">
                    {client.type}
                  </td>
                  <td className="px-4 py-3 whitespace-nowrap">
                    <span className="font-mono text-xs text-gray-600 bg-gray-100 px-2 py-0.5 rounded">
                      {client.apiKey}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex flex-wrap gap-1">
                      {client.scopes.map((scope) => (
                        <span
                          key={scope}
                          className="px-1.5 py-0.5 bg-blue-50 text-blue-700 rounded text-xs font-mono"
                        >
                          {scope}
                        </span>
                      ))}
                    </div>
                  </td>
                  <td className="px-4 py-3 text-gray-500 whitespace-nowrap text-xs">
                    {client.lastUsed}
                  </td>
                  <td className="px-4 py-3 whitespace-nowrap">
                    <span
                      className={`px-2 py-0.5 rounded-full text-xs font-medium ${STATUS_STYLES[client.status]}`}
                    >
                      {STATUS_LABELS[client.status]}
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
