"use client";

import { useState, useEffect, useCallback } from "react";
import { get, ApiError } from "@/lib/api-client";
import { Route, Truck, MapPin, AlertTriangle } from "lucide-react";

type RouteStatus = "通常" | "工事中" | "通行止め" | "迂回推奨";

interface TransportRoute {
  id: string;
  name: string;
  origin: string;
  destination: string;
  distance: string;
  duration: string;
  weightLimit: string;
  status: RouteStatus;
  tripsThisMonth: number;
}

const STATUS_CONFIG: Record<RouteStatus, { className: string; dot: string }> = {
  通常: { className: "bg-green-100 text-green-800", dot: "bg-green-500" },
  工事中: { className: "bg-yellow-100 text-yellow-800", dot: "bg-yellow-500" },
  通行止め: { className: "bg-red-100 text-red-800", dot: "bg-red-500" },
  迂回推奨: {
    className: "bg-orange-100 text-orange-800",
    dot: "bg-orange-500",
  },
};

// Helper to normalize API route status to RouteStatus
function normalizeRouteStatus(raw: string): RouteStatus {
  const map: Record<string, RouteStatus> = {
    normal: "通常",
    active: "通常",
    open: "通常",
    under_construction: "工事中",
    construction: "工事中",
    closed: "通行止め",
    blocked: "通行止め",
    detour: "迂回推奨",
    detour_recommended: "迂回推奨",
  };
  return map[raw?.toLowerCase()] ?? "通常";
}

export default function RoutesPage() {
  const [routes, setRoutes] = useState<TransportRoute[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const json = await get<{
        data?: { items?: Record<string, unknown>[] };
        items?: Record<string, unknown>[];
      }>("/gis/routes?per_page=50");
      const data: Record<string, unknown>[] =
        json?.data?.items ?? json?.items ?? [];
      setRoutes(
        Array.isArray(data)
          ? data.map((item) => {
              const distance = Number(item.distance ?? 0);
              const duration = Number(item.duration ?? 0);
              return {
                id: String(item.id ?? ""),
                name: String(item.name ?? ""),
                origin: String(item.origin ?? item.start_point ?? ""),
                destination: String(item.destination ?? item.end_point ?? ""),
                distance: distance > 0 ? `${distance.toFixed(1)} km` : "",
                duration: duration > 0 ? `${duration} 分` : "",
                weightLimit: String(item.weight_limit ?? ""),
                status: normalizeRouteStatus(String(item.status ?? "")),
                tripsThisMonth: Number(
                  item.trips_this_month ?? item.coordinates_count ?? 0,
                ),
              };
            })
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

  const stats = {
    total: routes.length,
    closed: routes.filter((r) => r.status === "通行止め").length,
    tripsTotal: routes.reduce((acc, r) => acc + r.tripsThisMonth, 0),
    trucks: 24,
  };

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">運搬ルート管理</h1>
          <p className="text-sm text-gray-500 mt-1">
            GIS/地図 — 資材運搬ルート・通行状況
          </p>
        </div>
        <div className="flex items-center gap-3">
          {loading && (
            <span className="text-xs text-blue-500 animate-pulse">
              データ取得中...
            </span>
          )}
          <Route className="w-8 h-8 text-blue-600" />
        </div>
      </div>

      {/* 統計カード */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <div className="bg-white rounded-lg border p-4 flex items-center gap-3">
          <Route className="w-8 h-8 text-blue-500 shrink-0" />
          <div>
            <p className="text-xs text-gray-500">登録ルート数</p>
            <p className="text-2xl font-bold text-gray-800">{stats.total}</p>
          </div>
        </div>
        <div className="bg-white rounded-lg border p-4 flex items-center gap-3">
          <AlertTriangle className="w-8 h-8 text-red-500 shrink-0" />
          <div>
            <p className="text-xs text-gray-500">通行止め数</p>
            <p className="text-2xl font-bold text-red-600">{stats.closed}</p>
          </div>
        </div>
        <div className="bg-white rounded-lg border p-4 flex items-center gap-3">
          <Truck className="w-8 h-8 text-green-500 shrink-0" />
          <div>
            <p className="text-xs text-gray-500">今月通行回数</p>
            <p className="text-2xl font-bold text-gray-800">
              {stats.tripsTotal}
            </p>
          </div>
        </div>
        <div className="bg-white rounded-lg border p-4 flex items-center gap-3">
          <Truck className="w-8 h-8 text-purple-500 shrink-0" />
          <div>
            <p className="text-xs text-gray-500">資材運搬台数</p>
            <p className="text-2xl font-bold text-gray-800">{stats.trucks}</p>
          </div>
        </div>
      </div>

      {error && (
        <div role="alert" aria-live="assertive" className="rounded-xl border border-danger-500/30 bg-danger-50 px-4 py-3 text-sm text-danger-700">
          {error}
        </div>
      )}
      {!loading && !error && routes.length === 0 && (
        <div className="rounded-xl border border-gray-200 bg-white px-4 py-8 text-center text-sm text-gray-500">
          該当データがありません。
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* ルートテーブル */}
        <div className="lg:col-span-2">
          <div className="bg-white rounded-lg border overflow-hidden">
            <div className="px-4 py-3 border-b bg-gray-50">
              <h2 className="font-semibold text-gray-700">ルート一覧</h2>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="bg-gray-50 border-b">
                  <tr>
                    <th className="px-4 py-3 text-left font-medium text-gray-600">
                      ルート名
                    </th>
                    <th className="px-4 py-3 text-left font-medium text-gray-600">
                      出発地
                    </th>
                    <th className="px-4 py-3 text-left font-medium text-gray-600">
                      目的地
                    </th>
                    <th className="px-4 py-3 text-left font-medium text-gray-600">
                      距離
                    </th>
                    <th className="px-4 py-3 text-left font-medium text-gray-600">
                      所要時間
                    </th>
                    <th className="px-4 py-3 text-left font-medium text-gray-600">
                      制限重量
                    </th>
                    <th className="px-4 py-3 text-left font-medium text-gray-600">
                      通行状況
                    </th>
                    <th className="px-4 py-3 text-left font-medium text-gray-600">
                      今月回数
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y">
                  {routes.map((route) => (
                    <tr
                      key={route.id}
                      className="hover:bg-gray-50 transition-colors"
                    >
                      <td className="px-4 py-3 font-medium text-gray-900">
                        {route.name}
                      </td>
                      <td className="px-4 py-3 text-gray-600 text-xs">
                        {route.origin}
                      </td>
                      <td className="px-4 py-3 text-gray-600 text-xs">
                        {route.destination}
                      </td>
                      <td className="px-4 py-3 text-gray-600">
                        {route.distance}
                      </td>
                      <td className="px-4 py-3 text-gray-600">
                        {route.duration}
                      </td>
                      <td className="px-4 py-3 text-gray-600">
                        {route.weightLimit}
                      </td>
                      <td className="px-4 py-3">
                        <span
                          className={`inline-flex items-center gap-1 px-2 py-1 rounded-full text-xs font-medium ${STATUS_CONFIG[route.status].className}`}
                        >
                          <span
                            className={`w-1.5 h-1.5 rounded-full ${STATUS_CONFIG[route.status].dot}`}
                          />
                          {route.status}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-gray-600 text-right">
                        {route.tripsThisMonth}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>

        {/* 地図プレースホルダー */}
        <div className="lg:col-span-1 space-y-4">
          <div className="bg-slate-800 rounded-lg overflow-hidden">
            <div className="h-72 flex flex-col items-center justify-center text-slate-400">
              <MapPin className="w-12 h-12 mb-3 text-slate-600" />
              <p className="text-base font-semibold text-slate-300">
                Route Map
              </p>
              <p className="text-xs mt-2 text-slate-500 text-center px-4">
                実装時は Mapbox / Leaflet を統合
              </p>
            </div>
          </div>

          {/* ステータス凡例 */}
          <div className="bg-white rounded-lg border p-4 space-y-2">
            <h3 className="font-semibold text-gray-700 text-sm">
              通行状況凡例
            </h3>
            {(Object.keys(STATUS_CONFIG) as RouteStatus[]).map((status) => (
              <div key={status} className="flex items-center gap-2 text-sm">
                <span
                  className={`w-2.5 h-2.5 rounded-full ${STATUS_CONFIG[status].dot}`}
                />
                <span className="text-gray-700">{status}</span>
                <span className="ml-auto text-gray-500 text-xs">
                  {routes.filter((r) => r.status === status).length} ルート
                </span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
