"use client";

import { useState, useEffect, useCallback } from "react";
import {
  Cpu,
  Activity,
  Thermometer,
  Wind,
  Gauge,
  Zap,
  AlertTriangle,
  CheckCircle,
  WifiOff,
  RefreshCw,
  TrendingUp,
  TrendingDown,
} from "lucide-react";
import { get, ApiError } from "@/lib/api-client";

interface Sensor {
  id: string;
  name: string;
  type: string;
  value: string;
  threshold: string;
  status: "normal" | "warning" | "alert" | "offline";
  battery: number;
  lastUpdate: string;
}

interface SensorGroup {
  project: string;
  sensors: Sensor[];
}

const statusConfig = {
  normal: {
    label: "正常",
    className: "bg-approve-50 text-approve-700",
    dot: "bg-approve-500",
    icon: CheckCircle,
  },
  warning: {
    label: "警戒",
    className: "bg-safety-50 text-safety-700",
    dot: "bg-safety-500",
    icon: AlertTriangle,
  },
  alert: {
    label: "アラート",
    className: "bg-danger-50 text-danger-700",
    dot: "bg-danger-500",
    icon: AlertTriangle,
  },
  offline: {
    label: "オフライン",
    className: "bg-concrete-50 text-concrete-500",
    dot: "bg-concrete-400",
    icon: WifiOff,
  },
};

const typeIconMap: Record<string, React.ElementType> = {
  displacement: Activity,
  tilt: TrendingDown,
  temperature: Thermometer,
  noise: Wind,
  vibration: Gauge,
  dust: Wind,
  oxygen: Cpu,
  power: Zap,
  pile: TrendingUp,
  water: Activity,
};

export default function IoTPage() {
  const [sensorGroups, setSensorGroups] = useState<SensorGroup[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [lastUpdated, setLastUpdated] = useState<Date>(new Date());
  const [error, setError] = useState<string | null>(null);

  const loadData = useCallback(() => {
    setIsLoading(true);
    get<{
      success?: boolean;
      data?: {
        devices?: {
          id: string;
          name: string;
          device_type: string;
          status: "online" | "offline" | "warning" | "alert";
          location?: string;
          project_id?: string;
          battery_level?: number;
          last_seen_at?: string;
        }[];
      };
    }>("/iot/devices?per_page=50")
      .then((data) => {
        const devices = data?.data?.devices;
        if (data?.success && Array.isArray(devices)) {
          const grouped = devices.reduce<Record<string, Sensor[]>>((acc, d) => {
            const key = d.project_id ?? "その他";
            if (!acc[key]) acc[key] = [];
            acc[key].push({
              id: d.id,
              name: d.name,
              type: d.device_type,
              value: "—",
              threshold: "—",
              status:
                d.status === "online"
                  ? "normal"
                  : d.status === "offline"
                    ? "offline"
                    : d.status === "warning"
                      ? "warning"
                      : "alert",
              battery: d.battery_level ?? 0,
              lastUpdate: d.last_seen_at
                ? new Date(d.last_seen_at).toLocaleString("ja-JP")
                : "不明",
            });
            return acc;
          }, {});
          setSensorGroups(
            Object.entries(grouped).map(([project, sensors]) => ({
              project,
              sensors,
            })),
          );
        } else {
          setSensorGroups([]);
        }
        setError(null);
        setLastUpdated(new Date());
      })
      .catch((err: unknown) => {
        setError(
          err instanceof ApiError && err.status === 403
            ? "権限がありません。"
            : "データを取得できませんでした。",
        );
      })
      .finally(() => setIsLoading(false));
  }, []);

  useEffect(() => {
    loadData();
    const interval = setInterval(loadData, 30000);
    return () => clearInterval(interval);
  }, [loadData]);

  const totalSensors = sensorGroups.flatMap((g) => g.sensors);
  const normalCount = totalSensors.filter((s) => s.status === "normal").length;
  const warningCount = totalSensors.filter(
    (s) => s.status === "warning",
  ).length;
  const alertCount = totalSensors.filter((s) => s.status === "alert").length;
  const offlineCount = totalSensors.filter(
    (s) => s.status === "offline",
  ).length;

  return (
    <div className="p-6 lg:p-8 space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">IoT監視</h1>
          <p className="mt-1 text-gray-500 text-sm">
            現場センサー・重機のリアルタイム状態監視
          </p>
        </div>
        <button
          onClick={loadData}
          disabled={isLoading}
          className="inline-flex items-center gap-2 rounded-lg border border-gray-200 bg-white px-4 py-2.5 text-sm font-medium text-gray-700 hover:bg-gray-50 transition-colors disabled:opacity-50"
        >
          <RefreshCw className={`h-4 w-4 ${isLoading ? "animate-spin" : ""}`} />
          更新
        </button>
      </div>

      {error && (
        <div role="alert" aria-live="assertive" className="rounded-xl border border-danger-500/30 bg-danger-50 px-4 py-3 text-sm text-danger-700">
          {error}
        </div>
      )}
      {!isLoading && !error && sensorGroups.length === 0 && (
        <div className="rounded-xl border border-gray-200 bg-white px-4 py-8 text-center text-sm text-gray-500">
          該当データがありません。
        </div>
      )}

      {/* Summary */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <div className="rounded-xl border border-gray-200 bg-white p-4">
          <div className="flex items-center gap-3">
            <div className="h-3 w-3 rounded-full bg-approve-500" />
            <div>
              <p className="text-2xl font-bold text-gray-900">{normalCount}</p>
              <p className="text-xs text-gray-500">正常</p>
            </div>
          </div>
        </div>
        <div className="rounded-xl border border-gray-200 bg-white p-4">
          <div className="flex items-center gap-3">
            <div className="h-3 w-3 rounded-full bg-safety-500" />
            <div>
              <p className="text-2xl font-bold text-gray-900">{warningCount}</p>
              <p className="text-xs text-gray-500">警戒</p>
            </div>
          </div>
        </div>
        <div className="rounded-xl border border-danger-200 bg-danger-50 p-4">
          <div className="flex items-center gap-3">
            <div className="h-3 w-3 rounded-full bg-danger-500 animate-pulse" />
            <div>
              <p className="text-2xl font-bold text-danger-700">{alertCount}</p>
              <p className="text-xs text-danger-600">アラート</p>
            </div>
          </div>
        </div>
        <div className="rounded-xl border border-gray-200 bg-white p-4">
          <div className="flex items-center gap-3">
            <div className="h-3 w-3 rounded-full bg-concrete-400" />
            <div>
              <p className="text-2xl font-bold text-gray-900">{offlineCount}</p>
              <p className="text-xs text-gray-500">オフライン</p>
            </div>
          </div>
        </div>
      </div>

      {/* Alert Banner */}
      {alertCount > 0 && (
        <div className="rounded-xl border border-danger-200 bg-danger-50 p-4 flex items-start gap-3">
          <AlertTriangle className="h-5 w-5 text-danger-600 mt-0.5 flex-shrink-0" />
          <div>
            <p className="font-semibold text-danger-800 text-sm">
              アラート検知: 川崎物流センター 重機振動センサー
            </p>
            <p className="text-xs text-danger-600 mt-1">
              振動値が閾値を超過しています（4.8 gal / 閾値 3.0
              gal）。重機の点検・作業中断を検討してください。
            </p>
          </div>
          <button className="ml-auto flex-shrink-0 text-xs font-medium text-danger-700 border border-danger-300 rounded px-2.5 py-1 hover:bg-danger-100 transition-colors">
            対応する
          </button>
        </div>
      )}

      {/* Sensor Groups */}
      {sensorGroups.map((group) => (
        <div
          key={group.project}
          className="rounded-xl border border-gray-200 bg-white overflow-hidden"
        >
          <div className="px-5 py-4 border-b border-gray-100 bg-gray-50">
            <h2 className="font-bold text-gray-900 text-sm">{group.project}</h2>
            <p className="text-xs text-gray-500 mt-0.5">
              {group.sensors.length} センサー
            </p>
          </div>
          <div className="divide-y divide-gray-100">
            {group.sensors.map((sensor) => {
              const status =
                statusConfig[sensor.status as keyof typeof statusConfig];
              const StatusIcon = status.icon;
              const TypeIcon = typeIconMap[sensor.type] || Cpu;
              return (
                <div
                  key={sensor.id}
                  className="px-5 py-4 hover:bg-gray-50 transition-colors"
                >
                  <div className="flex items-center gap-4">
                    <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-gray-100 flex-shrink-0">
                      <TypeIcon className="h-5 w-5 text-gray-600" />
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <p className="text-sm font-semibold text-gray-900">
                          {sensor.name}
                        </p>
                        <span
                          className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium ${status.className}`}
                        >
                          <span
                            className={`h-1.5 w-1.5 rounded-full ${status.dot}`}
                          />
                          {status.label}
                        </span>
                      </div>
                      <p className="text-xs text-gray-500 mt-0.5">
                        ID: {sensor.id} • 最終更新: {sensor.lastUpdate}
                      </p>
                    </div>
                    <div className="text-right flex-shrink-0">
                      <p
                        className={`text-lg font-bold ${
                          sensor.status === "alert"
                            ? "text-danger-700"
                            : sensor.status === "warning"
                              ? "text-safety-700"
                              : sensor.status === "offline"
                                ? "text-concrete-500"
                                : "text-gray-900"
                        }`}
                      >
                        {sensor.value}
                      </p>
                      <p className="text-xs text-gray-400">
                        閾値: {sensor.threshold}
                      </p>
                    </div>
                    {sensor.status !== "offline" && (
                      <div className="flex-shrink-0 text-right ml-4">
                        <div className="flex items-center gap-1 justify-end">
                          <div className="h-1.5 w-16 rounded-full bg-gray-100">
                            <div
                              className={`h-full rounded-full ${
                                sensor.battery > 50
                                  ? "bg-approve-500"
                                  : sensor.battery > 20
                                    ? "bg-safety-500"
                                    : "bg-danger-500"
                              }`}
                              style={{ width: `${sensor.battery}%` }}
                            />
                          </div>
                          <span className="text-xs text-gray-500 w-8 text-right">
                            {sensor.battery}%
                          </span>
                        </div>
                        <p className="text-xs text-gray-400 mt-0.5">電池残量</p>
                      </div>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      ))}
    </div>
  );
}
