"use client";

import { useState, useEffect, useCallback } from "react";
import { get, ApiError } from "@/lib/api-client";
import { Thermometer, Droplets, Wind, Activity } from "lucide-react";

type SensorState = "normal" | "warning" | "critical" | "offline";

interface EnvSensor {
  id: string;
  name: string;
  location: string;
  currentValue: number;
  unit: string;
  normalMin: number;
  normalMax: number;
  state: SensorState;
  lastUpdated: string;
  history: number[]; // 過去6時間 (1時間おき, index 0 = 6時間前)
}

const STATE_CONFIG: Record<
  SensorState,
  { label: string; dot: string; badge: string }
> = {
  normal: {
    label: "正常",
    dot: "bg-green-500",
    badge: "bg-green-100 text-green-800",
  },
  warning: {
    label: "警告",
    dot: "bg-yellow-500",
    badge: "bg-yellow-100 text-yellow-800",
  },
  critical: {
    label: "異常",
    dot: "bg-red-500",
    badge: "bg-red-100 text-red-800",
  },
  offline: {
    label: "オフライン",
    dot: "bg-gray-400",
    badge: "bg-gray-100 text-gray-600",
  },
};

const HOURS = ["3h前", "2h前", "1h前", "30m前", "15m前", "現在"];

function ValueBar({
  value,
  min,
  max,
  state,
}: {
  value: number;
  min: number;
  max: number;
  state: SensorState;
}) {
  if (state === "offline")
    return <div className="h-2 bg-gray-200 rounded-full" />;
  const pct = Math.min(100, Math.max(0, ((value - min) / (max - min)) * 100));
  const color =
    state === "normal"
      ? "bg-green-500"
      : state === "warning"
        ? "bg-yellow-500"
        : "bg-red-500";
  return (
    <div className="h-2 bg-gray-200 rounded-full overflow-hidden">
      <div
        className={`h-full rounded-full transition-all ${color}`}
        style={{ width: `${pct}%` }}
      />
    </div>
  );
}

// Helper to normalize API sensor status to SensorState
function normalizeSensorState(raw: string): SensorState {
  const map: Record<string, SensorState> = {
    normal: "normal",
    active: "normal",
    warning: "warning",
    alert: "warning",
    critical: "critical",
    error: "critical",
    offline: "offline",
    inactive: "offline",
  };
  return map[raw?.toLowerCase()] ?? "offline";
}

export default function EnvironmentPage() {
  const [sensors, setSensors] = useState<EnvSensor[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const json = await get<{
        data?: { items?: Record<string, unknown>[] };
        items?: Record<string, unknown>[];
      }>("/iot/sensors?per_page=50");
      const data: Record<string, unknown>[] =
        json?.data?.items ?? json?.items ?? [];
      setSensors(
        Array.isArray(data)
          ? data.map((item) => ({
              id: String(item.id ?? ""),
              name: String(item.name ?? ""),
              location: String(item.location ?? ""),
              currentValue: Number(item.value ?? 0),
              unit: String(item.unit ?? ""),
              normalMin: 0,
              normalMax: 100,
              state: normalizeSensorState(String(item.status ?? "")),
              lastUpdated: String(item.last_reading_at ?? ""),
              history: [],
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

  const online = sensors.filter((s) => s.state !== "offline").length;
  const alerting = sensors.filter(
    (s) => s.state === "warning" || s.state === "critical",
  ).length;
  const tempSensors = sensors.filter(
    (s) => s.unit === "°C" && s.state !== "offline",
  );
  const avgTemp =
    tempSensors.length > 0
      ? (
          tempSensors.reduce((acc, s) => acc + s.currentValue, 0) /
          tempSensors.length
        ).toFixed(1)
      : "—";
  const humSensors = sensors.filter(
    (s) => s.unit === "%" && s.state !== "offline",
  );
  const avgHum =
    humSensors.length > 0
      ? (
          humSensors.reduce((acc, s) => acc + s.currentValue, 0) /
          humSensors.length
        ).toFixed(0)
      : "—";

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">環境センサー監視</h1>
          <p className="text-sm text-gray-500 mt-1">
            IoTセンサー — 温湿度・CO₂・騒音・PM2.5・照度
          </p>
        </div>
        <div className="flex items-center gap-3">
          {loading && (
            <span className="text-xs text-blue-500 animate-pulse">
              データ取得中...
            </span>
          )}
          <Activity className="w-8 h-8 text-teal-600" />
        </div>
      </div>

      {error && (
        <div role="alert" aria-live="assertive" className="rounded-xl border border-danger-500/30 bg-danger-50 px-4 py-3 text-sm text-danger-700">
          {error}
        </div>
      )}
      {!loading && !error && sensors.length === 0 && (
        <div className="rounded-xl border border-gray-200 bg-white px-4 py-8 text-center text-sm text-gray-500">
          該当データがありません。
        </div>
      )}

      {/* 統計カード */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <div className="bg-white rounded-lg border p-4 flex items-center gap-3">
          <Activity className="w-8 h-8 text-green-500 shrink-0" />
          <div>
            <p className="text-xs text-gray-500">オンライン</p>
            <p className="text-2xl font-bold text-green-600">
              {online} / {sensors.length}
            </p>
          </div>
        </div>
        <div className="bg-white rounded-lg border p-4 flex items-center gap-3">
          <Wind className="w-8 h-8 text-yellow-500 shrink-0" />
          <div>
            <p className="text-xs text-gray-500">アラート中</p>
            <p className="text-2xl font-bold text-yellow-600">{alerting}</p>
          </div>
        </div>
        <div className="bg-white rounded-lg border p-4 flex items-center gap-3">
          <Thermometer className="w-8 h-8 text-orange-500 shrink-0" />
          <div>
            <p className="text-xs text-gray-500">平均気温</p>
            <p className="text-2xl font-bold text-gray-800">{avgTemp}°C</p>
          </div>
        </div>
        <div className="bg-white rounded-lg border p-4 flex items-center gap-3">
          <Droplets className="w-8 h-8 text-blue-500 shrink-0" />
          <div>
            <p className="text-xs text-gray-500">平均湿度</p>
            <p className="text-2xl font-bold text-gray-800">{avgHum}%</p>
          </div>
        </div>
      </div>

      {/* センサー一覧 */}
      <div className="bg-white rounded-lg border overflow-hidden">
        <div className="px-4 py-3 border-b bg-gray-50">
          <h2 className="font-semibold text-gray-700">センサー一覧</h2>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 border-b">
              <tr>
                <th className="px-4 py-3 text-left font-medium text-gray-600">
                  センサー名
                </th>
                <th className="px-4 py-3 text-left font-medium text-gray-600">
                  設置場所
                </th>
                <th className="px-4 py-3 text-left font-medium text-gray-600">
                  現在値
                </th>
                <th className="px-4 py-3 text-left font-medium text-gray-600">
                  正常範囲
                </th>
                <th className="px-4 py-3 text-left font-medium text-gray-600 w-32">
                  レベル
                </th>
                <th className="px-4 py-3 text-left font-medium text-gray-600">
                  状態
                </th>
                <th className="px-4 py-3 text-left font-medium text-gray-600">
                  最終更新
                </th>
              </tr>
            </thead>
            <tbody className="divide-y">
              {sensors.map((sensor) => (
                <tr
                  key={sensor.id}
                  className="hover:bg-gray-50 transition-colors"
                >
                  <td className="px-4 py-3 font-medium text-gray-900">
                    {sensor.name}
                  </td>
                  <td className="px-4 py-3 text-gray-600 text-xs">
                    {sensor.location}
                  </td>
                  <td className="px-4 py-3 font-semibold text-gray-900">
                    {sensor.state === "offline"
                      ? "—"
                      : `${sensor.currentValue} ${sensor.unit}`}
                  </td>
                  <td className="px-4 py-3 text-gray-500 text-xs">
                    {sensor.normalMin} ~ {sensor.normalMax} {sensor.unit}
                  </td>
                  <td className="px-4 py-3 w-32">
                    <ValueBar
                      value={sensor.currentValue}
                      min={sensor.normalMin}
                      max={sensor.normalMax}
                      state={sensor.state}
                    />
                  </td>
                  <td className="px-4 py-3">
                    <span
                      className={`inline-flex items-center gap-1 px-2 py-1 rounded-full text-xs font-medium ${STATE_CONFIG[sensor.state].badge}`}
                    >
                      <span
                        className={`w-1.5 h-1.5 rounded-full ${STATE_CONFIG[sensor.state].dot}`}
                      />
                      {STATE_CONFIG[sensor.state].label}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-gray-500 text-xs">
                    {sensor.lastUpdated}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* 時系列サンプリングデータ */}
      <div className="bg-white rounded-lg border overflow-hidden">
        <div className="px-4 py-3 border-b bg-gray-50">
          <h2 className="font-semibold text-gray-700">
            過去6時間 サンプリングデータ
          </h2>
          <p className="text-xs text-gray-400 mt-0.5">
            1時間おきのサンプリング値
          </p>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 border-b">
              <tr>
                <th className="px-4 py-3 text-left font-medium text-gray-600">
                  センサー名
                </th>
                {HOURS.map((h) => (
                  <th
                    key={h}
                    className="px-4 py-3 text-center font-medium text-gray-600"
                  >
                    {h}
                  </th>
                ))}
                <th className="px-4 py-3 text-left font-medium text-gray-600">
                  単位
                </th>
              </tr>
            </thead>
            <tbody className="divide-y">
              {sensors.map((sensor) => (
                <tr key={sensor.id} className="hover:bg-gray-50">
                  <td className="px-4 py-2.5 text-gray-700 text-xs font-medium">
                    {sensor.name}
                  </td>
                  {sensor.history.length > 0
                    ? sensor.history.map((v, i) => (
                        <td
                          key={i}
                          className="px-4 py-2.5 text-center text-xs text-gray-600"
                        >
                          {v === 0 ? (
                            <span className="text-gray-300">—</span>
                          ) : (
                            v
                          )}
                        </td>
                      ))
                    : HOURS.map((h) => (
                        <td
                          key={h}
                          className="px-4 py-2.5 text-center text-xs text-gray-300"
                        >
                          —
                        </td>
                      ))}
                  <td className="px-4 py-2.5 text-xs text-gray-400">
                    {sensor.unit}
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
