"use client";

import { useState, useEffect, useCallback } from "react";
import { get, ApiError } from "@/lib/api-client";
import { Webhook, Bell, CheckCircle, Activity } from "lucide-react";

type WebhookStatus = "active" | "inactive" | "error";

type WebhookItem = {
  id: string | number;
  name: string;
  url: string;
  shortUrl: string;
  events: string[];
  auth: string;
  lastFired: string;
  successRate: number;
  status: WebhookStatus;
};

const EVENT_COLORS: Record<string, string> = {
  "safety:incident": "bg-red-100 text-red-800",
  "safety:near-miss": "bg-orange-100 text-orange-800",
  "project:updated": "bg-blue-100 text-blue-800",
  "project:milestone": "bg-purple-100 text-purple-800",
  "workflow:approved": "bg-green-100 text-green-800",
  "workflow:rejected": "bg-red-100 text-red-800",
  "iot:alert": "bg-yellow-100 text-yellow-800",
  "iot:threshold": "bg-orange-100 text-orange-800",
  "document:approved": "bg-teal-100 text-teal-800",
};

export default function WebhooksPage() {
  const [webhooks, setWebhooks] = useState<WebhookItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const json = await get<{
        data?: { items?: Record<string, unknown>[] };
        items?: Record<string, unknown>[];
      }>("/notification/webhooks?per_page=50");
      const items = json?.data?.items ?? json?.items ?? json?.data ?? [];
      setWebhooks(
        Array.isArray(items)
          ? items.map(
              (item): WebhookItem => ({
                id: String(item.id ?? ""),
                name: String(item.name ?? ""),
                url: String(item.url ?? ""),
                shortUrl: String(
                  item.shortUrl ?? item.short_url ?? item.url ?? "",
                ),
                events: Array.isArray(item.events)
                  ? (item.events as string[]).map(String)
                  : [],
                auth: String(item.auth ?? ""),
                lastFired: String(item.lastFired ?? item.last_fired ?? ""),
                successRate: Number(item.successRate ?? item.success_rate ?? 0),
                status: String(item.status ?? "inactive") as WebhookStatus,
              }),
            )
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

  const total = webhooks.length;
  const active = webhooks.filter((w) => w.status === "active").length;
  const todayFired = 342;
  const activeWebhooks = webhooks.filter((w) => w.status === "active");
  const avgSuccessRate =
    activeWebhooks.length > 0
      ? Math.round(
          activeWebhooks.reduce((s, w) => s + w.successRate, 0) /
            activeWebhooks.length,
        )
      : 0;

  return (
    <div className="space-y-6 p-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Webhook設定</h1>
          <p className="text-sm text-gray-500 mt-1">
            外部システムへのイベント通知管理
          </p>
        </div>
        <button className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white text-sm rounded-lg hover:bg-blue-700">
          <Webhook className="w-4 h-4" />
          Webhook追加
        </button>
      </div>

      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        <div className="bg-white rounded-xl border border-gray-200 p-4 flex items-center gap-3">
          <div className="p-2 bg-blue-50 rounded-lg">
            <Webhook className="w-5 h-5 text-blue-600" />
          </div>
          <div>
            <p className="text-xs text-gray-500">登録数</p>
            <p className="text-2xl font-bold text-gray-900">{total}</p>
          </div>
        </div>
        <div className="bg-white rounded-xl border border-gray-200 p-4 flex items-center gap-3">
          <div className="p-2 bg-green-50 rounded-lg">
            <CheckCircle className="w-5 h-5 text-green-600" />
          </div>
          <div>
            <p className="text-xs text-gray-500">アクティブ</p>
            <p className="text-2xl font-bold text-gray-900">{active}</p>
          </div>
        </div>
        <div className="bg-white rounded-xl border border-gray-200 p-4 flex items-center gap-3">
          <div className="p-2 bg-purple-50 rounded-lg">
            <Bell className="w-5 h-5 text-purple-600" />
          </div>
          <div>
            <p className="text-xs text-gray-500">今日の発火数</p>
            <p className="text-2xl font-bold text-gray-900">{todayFired}</p>
          </div>
        </div>
        <div className="bg-white rounded-xl border border-gray-200 p-4 flex items-center gap-3">
          <div className="p-2 bg-orange-50 rounded-lg">
            <Activity className="w-5 h-5 text-orange-600" />
          </div>
          <div>
            <p className="text-xs text-gray-500">平均成功率</p>
            <p className="text-2xl font-bold text-gray-900">
              {avgSuccessRate}%
            </p>
          </div>
        </div>
      </div>

      {error && (
        <div role="alert" aria-live="assertive" className="rounded-xl border border-danger-500/30 bg-danger-50 px-4 py-3 text-sm text-danger-700">
          {error}
        </div>
      )}
      {!loading && !error && webhooks.length === 0 && (
        <div className="rounded-xl border border-gray-200 bg-white px-4 py-8 text-center text-sm text-gray-500">
          該当データがありません。
        </div>
      )}

      <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
        {loading ? (
          <div className="px-6 py-8 text-center text-sm text-gray-400">
            読み込み中...
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-gray-50 border-b border-gray-200">
                  <th className="px-4 py-3 text-left font-semibold text-gray-600">
                    Webhook名
                  </th>
                  <th className="px-4 py-3 text-left font-semibold text-gray-600 whitespace-nowrap">
                    URL
                  </th>
                  <th className="px-4 py-3 text-left font-semibold text-gray-600 whitespace-nowrap">
                    イベント種別
                  </th>
                  <th className="px-4 py-3 text-left font-semibold text-gray-600 whitespace-nowrap">
                    認証方式
                  </th>
                  <th className="px-4 py-3 text-left font-semibold text-gray-600 whitespace-nowrap">
                    最終発火
                  </th>
                  <th className="px-4 py-3 text-right font-semibold text-gray-600 whitespace-nowrap">
                    成功率
                  </th>
                  <th className="px-4 py-3 text-left font-semibold text-gray-600 whitespace-nowrap">
                    状態
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {webhooks.map((wh) => (
                  <tr key={wh.id} className="hover:bg-gray-50">
                    <td className="px-4 py-3 font-medium text-gray-900 whitespace-nowrap">
                      {wh.name}
                    </td>
                    <td className="px-4 py-3 whitespace-nowrap">
                      <span className="font-mono text-xs text-gray-600 bg-gray-100 px-2 py-0.5 rounded truncate max-w-[200px] block">
                        {wh.shortUrl}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex flex-wrap gap-1">
                        {wh.events.map((ev) => (
                          <span
                            key={ev}
                            className={`px-1.5 py-0.5 rounded text-xs font-medium ${EVENT_COLORS[ev] ?? "bg-gray-100 text-gray-700"}`}
                          >
                            {ev}
                          </span>
                        ))}
                      </div>
                    </td>
                    <td className="px-4 py-3 text-gray-600 whitespace-nowrap text-xs">
                      {wh.auth}
                    </td>
                    <td className="px-4 py-3 text-gray-500 whitespace-nowrap text-xs">
                      {wh.lastFired}
                    </td>
                    <td className="px-4 py-3 whitespace-nowrap text-right">
                      <span
                        className={`font-medium ${wh.successRate >= 98 ? "text-green-600" : wh.successRate >= 90 ? "text-orange-600" : "text-red-600"}`}
                      >
                        {wh.successRate}%
                      </span>
                    </td>
                    <td className="px-4 py-3 whitespace-nowrap">
                      {wh.status === "active" ? (
                        <span className="flex items-center gap-1 text-green-700 text-xs font-medium">
                          <span className="w-2 h-2 bg-green-500 rounded-full" />{" "}
                          有効
                        </span>
                      ) : (
                        <span className="flex items-center gap-1 text-gray-400 text-xs font-medium">
                          <span className="w-2 h-2 bg-gray-400 rounded-full" />{" "}
                          無効
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
