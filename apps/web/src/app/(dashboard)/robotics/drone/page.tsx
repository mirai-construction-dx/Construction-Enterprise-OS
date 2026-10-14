"use client";

import { useState, useCallback, useEffect } from "react";
import { get, ApiError } from "@/lib/api-client";
import { Plane, Camera, Map, Wind, Clock, Plus } from "lucide-react";

interface FlightRecord {
  id: string;
  flightId: string;
  date: string;
  pilot: string;
  area: string;
  altitude: number;
  flightTimeMin: number;
  photoCount: number;
  status: "completed" | "in_flight" | "scheduled" | "cancelled";
  coverage: number;
}

const STATUS_CONFIG = {
  completed: { label: "完了", color: "bg-green-100 text-green-700" },
  in_flight: { label: "飛行中", color: "bg-blue-100 text-blue-700" },
  scheduled: { label: "予定", color: "bg-gray-100 text-gray-600" },
  cancelled: { label: "中止", color: "bg-red-100 text-red-700" },
};

export default function DronePage() {
  const [flights, setFlights] = useState<FlightRecord[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const json = await get<{
        data?: { items?: Record<string, unknown>[] };
        items?: Record<string, unknown>[];
      }>("/autonomous/drone-flights?per_page=50");
      const items: Record<string, unknown>[] =
        json?.data?.items ?? json?.items ?? [];
      setFlights(
        Array.isArray(items)
          ? items.map((item: Record<string, unknown>) => ({
              id: String(item.id ?? ""),
              flightId: String(item.flightId ?? item.flight_id ?? ""),
              date: String(item.date ?? ""),
              pilot: String(item.pilot ?? item.pilot_name ?? ""),
              area: String(item.area ?? ""),
              altitude: Number(item.altitude ?? 0),
              flightTimeMin: Number(
                item.flightTimeMin ?? item.flight_time_min ?? 0,
              ),
              photoCount: Number(item.photoCount ?? item.photo_count ?? 0),
              status: String(
                item.status ?? "scheduled",
              ) as FlightRecord["status"],
              coverage: Number(item.coverage ?? 0),
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

  const thisMonthFlights = flights.filter((f) =>
    f.date.startsWith("2026-05"),
  ).length;
  const totalFlightTime = flights
    .filter((f) => f.status === "completed")
    .reduce((s, f) => s + f.flightTimeMin, 0);
  const totalPhotos = flights
    .filter((f) => f.status === "completed")
    .reduce((s, f) => s + f.photoCount, 0);
  const inFlight = flights.find((f) => f.status === "in_flight");

  return (
    <div className="p-6 space-y-6">
      {/* ヘッダー */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">ドローン測量</h1>
          <p className="text-sm text-gray-500 mt-1">
            ドローンフライト管理・空撮測量データ
          </p>
        </div>
        <button className="flex items-center gap-2 bg-blue-600 text-white px-4 py-2 rounded-lg hover:bg-blue-700 transition-colors text-sm">
          <Plus className="w-4 h-4" />
          フライト計画
        </button>
      </div>

      {error && (
        <div role="alert" aria-live="assertive" className="rounded-xl border border-danger-500/30 bg-danger-50 px-4 py-3 text-sm text-danger-700">
          {error}
        </div>
      )}
      {!loading && !error && flights.length === 0 && (
        <div className="rounded-xl border border-gray-200 bg-white px-4 py-8 text-center text-sm text-gray-500">
          該当データがありません。
        </div>
      )}

      {/* 統計カード */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <div className="bg-white rounded-xl p-4 shadow-sm border border-gray-100">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-blue-50 rounded-lg">
              <Plane className="w-5 h-5 text-blue-600" />
            </div>
            <div>
              <p className="text-xs text-gray-500">今月フライト数</p>
              <p className="text-2xl font-bold text-gray-900">
                {loading ? "—" : thisMonthFlights}
              </p>
            </div>
          </div>
        </div>
        <div className="bg-white rounded-xl p-4 shadow-sm border border-gray-100">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-green-50 rounded-lg">
              <Clock className="w-5 h-5 text-green-600" />
            </div>
            <div>
              <p className="text-xs text-gray-500">総飛行時間</p>
              <p className="text-2xl font-bold text-gray-900">
                {loading
                  ? "—"
                  : `${Math.floor(totalFlightTime / 60)}h${totalFlightTime % 60}m`}
              </p>
            </div>
          </div>
        </div>
        <div className="bg-white rounded-xl p-4 shadow-sm border border-gray-100">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-purple-50 rounded-lg">
              <Camera className="w-5 h-5 text-purple-600" />
            </div>
            <div>
              <p className="text-xs text-gray-500">撮影枚数</p>
              <p className="text-2xl font-bold text-gray-900">
                {loading ? "—" : totalPhotos.toLocaleString()}
              </p>
            </div>
          </div>
        </div>
        <div className="bg-white rounded-xl p-4 shadow-sm border border-gray-100">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-orange-50 rounded-lg">
              <Map className="w-5 h-5 text-orange-600" />
            </div>
            <div>
              <p className="text-xs text-gray-500">面積カバレッジ</p>
              <p className="text-2xl font-bold text-gray-900">94%</p>
            </div>
          </div>
        </div>
      </div>

      {/* 飛行中フライト */}
      {inFlight && (
        <div className="bg-white rounded-xl p-5 shadow-sm border border-blue-200">
          <div className="flex items-center gap-2 mb-4">
            <div className="w-2 h-2 rounded-full bg-blue-500 animate-pulse" />
            <h2 className="font-semibold text-gray-800">現在飛行中</h2>
            <span className="ml-auto text-xs text-blue-600 bg-blue-50 px-2 py-0.5 rounded-full">
              {inFlight.flightId}
            </span>
          </div>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-4">
            <div>
              <p className="text-xs text-gray-500">エリア</p>
              <p className="text-sm font-medium text-gray-900">
                {inFlight.area}
              </p>
            </div>
            <div>
              <p className="text-xs text-gray-500">パイロット</p>
              <p className="text-sm font-medium text-gray-900">
                {inFlight.pilot}
              </p>
            </div>
            <div>
              <p className="text-xs text-gray-500">高度</p>
              <p className="text-sm font-medium text-gray-900">
                {inFlight.altitude}m
              </p>
            </div>
            <div>
              <p className="text-xs text-gray-500">撮影済み</p>
              <p className="text-sm font-medium text-gray-900">
                {inFlight.photoCount}枚 (推定)
              </p>
            </div>
          </div>
          <div>
            <div className="flex items-center justify-between mb-1">
              <span className="text-xs text-gray-600">進捗</span>
              <span className="text-xs font-medium text-blue-600">
                {inFlight.coverage}%
              </span>
            </div>
            <div className="h-3 bg-gray-100 rounded-full overflow-hidden">
              <div
                className="h-full bg-blue-500 rounded-full transition-all"
                style={{ width: `${inFlight.coverage}%` }}
              />
            </div>
          </div>
        </div>
      )}

      {/* フライト一覧テーブル */}
      <div className="bg-white rounded-xl shadow-sm border border-gray-100 overflow-hidden">
        <div className="px-5 py-4 border-b border-gray-100">
          <h2 className="font-semibold text-gray-800">フライト一覧</h2>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 border-b border-gray-200">
              <tr>
                <th className="text-left px-4 py-3 font-medium text-gray-600">
                  フライトID
                </th>
                <th className="text-left px-4 py-3 font-medium text-gray-600">
                  日付
                </th>
                <th className="text-left px-4 py-3 font-medium text-gray-600">
                  パイロット
                </th>
                <th className="text-left px-4 py-3 font-medium text-gray-600">
                  エリア
                </th>
                <th className="text-left px-4 py-3 font-medium text-gray-600">
                  高度
                </th>
                <th className="text-left px-4 py-3 font-medium text-gray-600">
                  飛行時間
                </th>
                <th className="text-left px-4 py-3 font-medium text-gray-600">
                  撮影枚数
                </th>
                <th className="text-left px-4 py-3 font-medium text-gray-600">
                  ステータス
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {flights.map((flight) => (
                <tr
                  key={flight.id}
                  className="hover:bg-gray-50 transition-colors"
                >
                  <td className="px-4 py-3 font-mono text-xs text-gray-600">
                    {flight.flightId}
                  </td>
                  <td className="px-4 py-3 text-gray-700">{flight.date}</td>
                  <td className="px-4 py-3 text-gray-700">{flight.pilot}</td>
                  <td className="px-4 py-3 font-medium text-gray-900">
                    {flight.area}
                  </td>
                  <td className="px-4 py-3 text-gray-600">
                    <div className="flex items-center gap-1">
                      <Wind className="w-3 h-3 text-gray-400" />
                      {flight.altitude}m
                    </div>
                  </td>
                  <td className="px-4 py-3 text-gray-700">
                    {flight.flightTimeMin > 0
                      ? `${flight.flightTimeMin}分`
                      : "—"}
                  </td>
                  <td className="px-4 py-3 text-gray-700">
                    {flight.photoCount > 0 ? (
                      <div className="flex items-center gap-1">
                        <Camera className="w-3 h-3 text-gray-400" />
                        {flight.photoCount}枚
                      </div>
                    ) : (
                      "—"
                    )}
                  </td>
                  <td className="px-4 py-3">
                    <span
                      className={`px-2 py-0.5 rounded-full text-xs font-medium ${STATUS_CONFIG[flight.status].color}`}
                    >
                      {STATUS_CONFIG[flight.status].label}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="px-4 py-3 border-t border-gray-100 text-sm text-gray-500">
          {flights.length}件
        </div>
      </div>
    </div>
  );
}
