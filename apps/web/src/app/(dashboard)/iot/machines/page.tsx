"use client";

import { useState, useEffect, useCallback } from "react";
import { get, ApiError } from "@/lib/api-client";
import { Truck, Fuel, MapPin, Activity } from "lucide-react";

type MachineStatus = "running" | "idle" | "stopped" | "maintenance";

interface Machine {
  id: string;
  machineNumber: string;
  type: string;
  location: string;
  status: MachineStatus;
  engineHours: number;
  fuelLevel: number;
  gpsLat: string;
  gpsLng: string;
  lastComm: string;
}

const STATUS_CONFIG: Record<
  MachineStatus,
  { label: string; badge: string; dot: string; row: string }
> = {
  running: {
    label: "稼働中",
    badge: "bg-green-100 text-green-800",
    dot: "bg-green-500",
    row: "",
  },
  idle: {
    label: "アイドル",
    badge: "bg-yellow-100 text-yellow-800",
    dot: "bg-yellow-500",
    row: "",
  },
  stopped: {
    label: "停止中",
    badge: "bg-gray-100 text-gray-600",
    dot: "bg-gray-400",
    row: "opacity-70",
  },
  maintenance: {
    label: "整備中",
    badge: "bg-orange-100 text-orange-800",
    dot: "bg-orange-500",
    row: "",
  },
};

function FuelBar({ level }: { level: number }) {
  const color =
    level <= 25 ? "bg-red-500" : level <= 50 ? "bg-yellow-500" : "bg-green-500";
  return (
    <div className="flex items-center gap-2">
      <div className="w-20 h-2.5 bg-gray-200 rounded-full overflow-hidden">
        <div
          className={`h-full rounded-full ${color}`}
          style={{ width: `${level}%` }}
        />
      </div>
      <span
        className={`text-xs font-medium ${level <= 25 ? "text-red-600" : level <= 50 ? "text-yellow-600" : "text-gray-700"}`}
      >
        {level}%
      </span>
    </div>
  );
}

// Helper to normalize API status to MachineStatus
function normalizeMachineStatus(raw: string): MachineStatus {
  const map: Record<string, MachineStatus> = {
    running: "running",
    active: "running",
    idle: "idle",
    stopped: "stopped",
    inactive: "stopped",
    maintenance: "maintenance",
  };
  return map[raw?.toLowerCase()] ?? "stopped";
}

export default function MachinesPage() {
  const [machines, setMachines] = useState<Machine[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const json = await get<{
        data?: { items?: Record<string, unknown>[] };
        items?: Record<string, unknown>[];
      }>("/iot/machines?per_page=50");
      const data: Record<string, unknown>[] =
        json?.data?.items ?? json?.items ?? [];
      setMachines(
        Array.isArray(data)
          ? data.map((item) => ({
              id: String(item.id ?? ""),
              machineNumber: String(item.name ?? item.machine_number ?? ""),
              type: String(item.machine_type ?? item.type ?? ""),
              location: String(item.location ?? ""),
              status: normalizeMachineStatus(String(item.status ?? "")),
              engineHours: Number(item.engine_hours ?? 0),
              fuelLevel: Number(item.fuel_level ?? item.health_score ?? 0),
              gpsLat: String(item.gps_lat ?? ""),
              gpsLng: String(item.gps_lng ?? ""),
              lastComm: String(
                item.last_comm ?? item.last_maintenance_at ?? "",
              ),
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

  const stats = {
    running: machines.filter((m) => m.status === "running").length,
    idle: machines.filter((m) => m.status === "idle").length,
    maintenance: machines.filter((m) => m.status === "maintenance").length,
    stopped: machines.filter((m) => m.status === "stopped").length,
    fuelLow: machines.filter((m) => m.fuelLevel <= 30).length,
  };

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">重機稼働管理</h1>
          <p className="text-sm text-gray-500 mt-1">
            IoTセンサー — GPS位置・稼働状況・燃料監視
          </p>
        </div>
        <div className="flex items-center gap-3">
          {loading && (
            <span className="text-xs text-blue-500 animate-pulse">
              データ取得中...
            </span>
          )}
          <Truck className="w-8 h-8 text-blue-600" />
        </div>
      </div>

      {error && (
        <div role="alert" aria-live="assertive" className="rounded-xl border border-danger-500/30 bg-danger-50 px-4 py-3 text-sm text-danger-700">
          {error}
        </div>
      )}
      {!loading && !error && machines.length === 0 && (
        <div className="rounded-xl border border-gray-200 bg-white px-4 py-8 text-center text-sm text-gray-500">
          該当データがありません。
        </div>
      )}

      {/* 統計カード */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
        <div className="bg-white rounded-lg border p-4 flex items-center gap-3">
          <Activity className="w-7 h-7 text-green-500 shrink-0" />
          <div>
            <p className="text-xs text-gray-500">稼働中</p>
            <p className="text-2xl font-bold text-green-600">{stats.running}</p>
          </div>
        </div>
        <div className="bg-white rounded-lg border p-4 flex items-center gap-3">
          <Activity className="w-7 h-7 text-yellow-500 shrink-0" />
          <div>
            <p className="text-xs text-gray-500">アイドル</p>
            <p className="text-2xl font-bold text-yellow-600">{stats.idle}</p>
          </div>
        </div>
        <div className="bg-white rounded-lg border p-4 flex items-center gap-3">
          <Truck className="w-7 h-7 text-orange-500 shrink-0" />
          <div>
            <p className="text-xs text-gray-500">整備中</p>
            <p className="text-2xl font-bold text-orange-600">
              {stats.maintenance}
            </p>
          </div>
        </div>
        <div className="bg-white rounded-lg border p-4 flex items-center gap-3">
          <Activity className="w-7 h-7 text-gray-400 shrink-0" />
          <div>
            <p className="text-xs text-gray-500">停止中</p>
            <p className="text-2xl font-bold text-gray-500">{stats.stopped}</p>
          </div>
        </div>
        <div className="bg-white rounded-lg border p-4 flex items-center gap-3">
          <Fuel className="w-7 h-7 text-red-500 shrink-0" />
          <div>
            <p className="text-xs text-gray-500">燃料補給推奨</p>
            <p className="text-2xl font-bold text-red-600">{stats.fuelLow}</p>
          </div>
        </div>
      </div>

      {/* 重機テーブル */}
      <div className="bg-white rounded-lg border overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 border-b">
              <tr>
                <th className="px-4 py-3 text-left font-medium text-gray-600">
                  機番
                </th>
                <th className="px-4 py-3 text-left font-medium text-gray-600">
                  機種
                </th>
                <th className="px-4 py-3 text-left font-medium text-gray-600">
                  設置場所
                </th>
                <th className="px-4 py-3 text-left font-medium text-gray-600">
                  稼働状況
                </th>
                <th className="px-4 py-3 text-left font-medium text-gray-600">
                  エンジン時間
                </th>
                <th className="px-4 py-3 text-left font-medium text-gray-600">
                  燃料残量
                </th>
                <th className="px-4 py-3 text-left font-medium text-gray-600">
                  GPS座標
                </th>
                <th className="px-4 py-3 text-left font-medium text-gray-600">
                  最終通信
                </th>
              </tr>
            </thead>
            <tbody className="divide-y">
              {machines.map((m) => (
                <tr
                  key={m.id}
                  className={`hover:bg-gray-50 transition-colors ${STATUS_CONFIG[m.status].row}`}
                >
                  <td className="px-4 py-3 font-mono text-xs font-bold text-gray-700">
                    {m.machineNumber}
                  </td>
                  <td className="px-4 py-3 font-medium text-gray-900">
                    {m.type}
                  </td>
                  <td className="px-4 py-3 text-gray-600 text-xs">
                    {m.location}
                  </td>
                  <td className="px-4 py-3">
                    <span
                      className={`inline-flex items-center gap-1 px-2 py-1 rounded-full text-xs font-medium ${STATUS_CONFIG[m.status].badge}`}
                    >
                      <span
                        className={`w-1.5 h-1.5 rounded-full ${STATUS_CONFIG[m.status].dot}`}
                      />
                      {STATUS_CONFIG[m.status].label}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-gray-700 font-mono text-xs">
                    {m.engineHours.toLocaleString()} h
                  </td>
                  <td className="px-4 py-3">
                    <FuelBar level={m.fuelLevel} />
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-1 text-xs text-gray-500">
                      <MapPin className="w-3 h-3 shrink-0" />
                      <span className="font-mono">
                        {m.gpsLat}, {m.gpsLng}
                      </span>
                    </div>
                  </td>
                  <td className="px-4 py-3 text-gray-500 text-xs font-mono">
                    {m.lastComm}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="px-4 py-3 border-t bg-gray-50 text-xs text-gray-500">
          全 {machines.length} 台 — 燃料30%以下は補給推奨
        </div>
      </div>
    </div>
  );
}
