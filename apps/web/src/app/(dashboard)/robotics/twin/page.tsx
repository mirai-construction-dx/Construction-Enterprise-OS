"use client";

import { useState, useCallback, useEffect } from "react";
import { get, ApiError } from "@/lib/api-client";
import {
  Globe,
  Layers,
  Activity,
  Wifi,
  WifiOff,
  RefreshCw,
} from "lucide-react";

interface DigitalTwin {
  id: string;
  name: string;
  targetSite: string;
  modelAccuracy: number;
  lastSync: string;
  sensorCount: number;
  dataPoints: number;
  status: "active" | "syncing" | "offline";
}

interface TwinSensor {
  id: string;
  sensorName: string;
  type:
    | "temperature"
    | "humidity"
    | "vibration"
    | "displacement"
    | "load"
    | "wind"
    | "camera"
    | "lidar";
  updateFrequency: string;
  lastUpdated: string;
  syncStatus: "synced" | "delayed" | "error";
  twinId: string;
}

const twinStatusStyle: Record<
  DigitalTwin["status"],
  { label: string; dot: string; text: string }
> = {
  active: { label: "稼働中", dot: "bg-green-500", text: "text-green-700" },
  syncing: {
    label: "同期中",
    dot: "bg-blue-500 animate-pulse",
    text: "text-blue-700",
  },
  offline: { label: "オフライン", dot: "bg-gray-400", text: "text-gray-600" },
};

const syncStatusStyle: Record<
  TwinSensor["syncStatus"],
  { label: string; className: string }
> = {
  synced: { label: "同期済", className: "bg-green-100 text-green-700" },
  delayed: { label: "遅延", className: "bg-yellow-100 text-yellow-700" },
  error: { label: "エラー", className: "bg-red-100 text-red-700" },
};

const sensorTypeLabel: Record<TwinSensor["type"], string> = {
  temperature: "温度",
  humidity: "湿度",
  vibration: "振動",
  displacement: "変位",
  load: "荷重",
  wind: "風速",
  camera: "カメラ",
  lidar: "LiDAR",
};

const sensorTypeColor: Record<TwinSensor["type"], string> = {
  temperature: "bg-red-100 text-red-700",
  humidity: "bg-blue-100 text-blue-700",
  vibration: "bg-orange-100 text-orange-700",
  displacement: "bg-purple-100 text-purple-700",
  load: "bg-gray-100 text-gray-700",
  wind: "bg-cyan-100 text-cyan-700",
  camera: "bg-indigo-100 text-indigo-700",
  lidar: "bg-green-100 text-green-700",
};

export default function DigitalTwinPage() {
  const [twins, setTwins] = useState<DigitalTwin[]>([]);
  const [sensors, setSensors] = useState<TwinSensor[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const [twinsResult, sensorsResult] = await Promise.allSettled([
        get<{
          data?: { items?: Record<string, unknown>[] };
          items?: Record<string, unknown>[];
        }>("/autonomous/digital-twins?per_page=50"),
        get<{
          data?: { items?: Record<string, unknown>[] };
          items?: Record<string, unknown>[];
        }>("/autonomous/twin-sensors?per_page=50"),
      ]);

      if (twinsResult.status === "fulfilled") {
        const json = twinsResult.value;
        const items: Record<string, unknown>[] =
          json?.data?.items ?? json?.items ?? [];
        setTwins(
          Array.isArray(items)
            ? items.map(
                (item: Record<string, unknown>): DigitalTwin => ({
                  id: String(item.id ?? ""),
                  name: String(item.name ?? ""),
                  targetSite: String(item.targetSite ?? item.target_site ?? ""),
                  modelAccuracy: Number(
                    item.modelAccuracy ?? item.model_accuracy ?? 0,
                  ),
                  lastSync: String(item.lastSync ?? item.last_sync ?? ""),
                  sensorCount: Number(
                    item.sensorCount ?? item.sensor_count ?? 0,
                  ),
                  dataPoints: Number(item.dataPoints ?? item.data_points ?? 0),
                  status: String(
                    item.status ?? "offline",
                  ) as DigitalTwin["status"],
                }),
              )
            : [],
        );
      }

      if (sensorsResult.status === "fulfilled") {
        const json = sensorsResult.value;
        const items: Record<string, unknown>[] =
          json?.data?.items ?? json?.items ?? [];
        setSensors(
          Array.isArray(items)
            ? items.map(
                (item: Record<string, unknown>): TwinSensor => ({
                  id: String(item.id ?? ""),
                  sensorName: String(item.sensorName ?? item.sensor_name ?? ""),
                  type: String(
                    item.type ?? "temperature",
                  ) as TwinSensor["type"],
                  updateFrequency: String(
                    item.updateFrequency ?? item.update_frequency ?? "",
                  ),
                  lastUpdated: String(
                    item.lastUpdated ?? item.last_updated ?? "",
                  ),
                  syncStatus: String(
                    item.syncStatus ?? item.sync_status ?? "error",
                  ) as TwinSensor["syncStatus"],
                  twinId: String(item.twinId ?? item.twin_id ?? ""),
                }),
              )
            : [],
        );
      }

      const rejected = [twinsResult, sensorsResult].filter(
        (r): r is PromiseRejectedResult => r.status === "rejected",
      );
      setError(
        rejected.length === 0
          ? null
          : rejected.some(
                (r) => r.reason instanceof ApiError && r.reason.status === 403,
              )
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

  const activeTwins = twins.filter((t) => t.status !== "offline").length;
  const totalSensors = twins.reduce((s, t) => s + t.sensorCount, 0);
  const totalDataPoints = twins.reduce((s, t) => s + t.dataPoints, 0);
  const delayedOrError = sensors.filter(
    (s) => s.syncStatus !== "synced",
  ).length;

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">デジタルツイン</h1>
          <p className="mt-1 text-sm text-gray-500">
            建設現場のデジタルツイン管理・センサーデータのリアルタイム同期
          </p>
        </div>
      </div>

      {error && (
        <div role="alert" aria-live="assertive" className="rounded-xl border border-danger-500/30 bg-danger-50 px-4 py-3 text-sm text-danger-700">
          {error}
        </div>
      )}
      {!loading && !error && twins.length === 0 && sensors.length === 0 && (
        <div className="rounded-xl border border-gray-200 bg-white px-4 py-8 text-center text-sm text-gray-500">
          該当データがありません。
        </div>
      )}

      {/* Stats */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <div className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm font-medium text-gray-500">稼働ツイン数</p>
              <p className="mt-1 text-3xl font-bold text-gray-900">
                {loading ? "—" : activeTwins}
                <span className="ml-1 text-lg font-medium text-gray-500">
                  件
                </span>
              </p>
            </div>
            <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-blue-50">
              <Globe className="h-6 w-6 text-blue-600" />
            </div>
          </div>
          <p className="mt-2 text-xs text-gray-400">全{twins.length}ツイン中</p>
        </div>

        <div className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm font-medium text-gray-500">総センサー数</p>
              <p className="mt-1 text-3xl font-bold text-gray-900">
                {loading ? "—" : totalSensors}
                <span className="ml-1 text-lg font-medium text-gray-500">
                  基
                </span>
              </p>
            </div>
            <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-purple-50">
              <Layers className="h-6 w-6 text-purple-600" />
            </div>
          </div>
          <p className="mt-2 text-xs text-gray-400">全ツイン合計</p>
        </div>

        <div className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm font-medium text-gray-500">
                今日のデータポイント
              </p>
              <p className="mt-1 text-3xl font-bold text-gray-900">
                {loading ? "—" : (totalDataPoints / 10000).toFixed(0)}
                <span className="ml-1 text-lg font-medium text-gray-500">
                  万
                </span>
              </p>
            </div>
            <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-green-50">
              <Activity className="h-6 w-6 text-green-600" />
            </div>
          </div>
          <p className="mt-2 text-xs text-gray-400">
            累計{totalDataPoints.toLocaleString()}件
          </p>
        </div>

        <div className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm font-medium text-gray-500">同期遅延</p>
              <p className="mt-1 text-3xl font-bold text-gray-900">
                {loading ? "—" : delayedOrError}
                <span className="ml-1 text-lg font-medium text-gray-500">
                  件
                </span>
              </p>
            </div>
            <div
              className={`flex h-12 w-12 items-center justify-center rounded-xl ${delayedOrError > 0 ? "bg-yellow-50" : "bg-green-50"}`}
            >
              <Wifi
                className={`h-6 w-6 ${delayedOrError > 0 ? "text-yellow-600" : "text-green-600"}`}
              />
            </div>
          </div>
          <p className="mt-2 text-xs text-gray-400">遅延・エラーのセンサー</p>
        </div>
      </div>

      {/* Twin List */}
      <div className="rounded-xl border border-gray-200 bg-white shadow-sm">
        <div className="flex items-center justify-between border-b border-gray-200 px-6 py-4">
          <div className="flex items-center gap-2">
            <Globe className="h-5 w-5 text-gray-500" />
            <h2 className="text-base font-semibold text-gray-900">
              デジタルツイン一覧
            </h2>
          </div>
          <span className="text-sm text-gray-500">全{twins.length}件</span>
        </div>
        <div className="overflow-x-auto">
          <table className="min-w-full divide-y divide-gray-200">
            <thead className="bg-gray-50">
              <tr>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">
                  ツイン名
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">
                  対象物件
                </th>
                <th className="px-4 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">
                  モデル精度
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">
                  最終同期
                </th>
                <th className="px-4 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">
                  センサー数
                </th>
                <th className="px-4 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">
                  データポイント
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">
                  状態
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100 bg-white">
              {twins.map((twin) => {
                const statusInfo = twinStatusStyle[twin.status];
                return (
                  <tr key={twin.id} className="hover:bg-gray-50">
                    <td className="px-4 py-3">
                      <p className="text-sm font-medium text-gray-900">
                        {twin.name}
                      </p>
                      <p className="text-xs text-gray-400">{twin.id}</p>
                    </td>
                    <td className="px-4 py-3 text-sm text-gray-700">
                      {twin.targetSite}
                    </td>
                    <td className="px-4 py-3 text-right">
                      <div className="flex items-center justify-end gap-2">
                        <div className="w-16 overflow-hidden rounded-full bg-gray-200">
                          <div
                            className={`h-1.5 rounded-full ${twin.modelAccuracy >= 97 ? "bg-green-500" : twin.modelAccuracy >= 93 ? "bg-blue-500" : "bg-yellow-500"}`}
                            style={{ width: `${twin.modelAccuracy}%` }}
                          />
                        </div>
                        <span className="text-sm font-medium tabular-nums text-gray-700">
                          {twin.modelAccuracy}%
                        </span>
                      </div>
                    </td>
                    <td className="px-4 py-3 text-sm text-gray-500 whitespace-nowrap">
                      <div className="flex items-center gap-1.5">
                        <RefreshCw className="h-3.5 w-3.5 text-gray-400" />
                        {twin.lastSync}
                      </div>
                    </td>
                    <td className="px-4 py-3 text-right text-sm font-medium text-gray-900">
                      {twin.sensorCount}基
                    </td>
                    <td className="px-4 py-3 text-right text-sm text-gray-700">
                      {twin.dataPoints.toLocaleString()}
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-1.5">
                        <span
                          className={`h-2 w-2 rounded-full ${statusInfo.dot}`}
                        />
                        <span
                          className={`text-sm font-medium ${statusInfo.text}`}
                        >
                          {statusInfo.label}
                        </span>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

      {/* 3D Viewer Placeholder */}
      <div className="rounded-xl border border-gray-200 bg-white shadow-sm">
        <div className="flex items-center justify-between border-b border-gray-200 px-6 py-4">
          <div className="flex items-center gap-2">
            <Layers className="h-5 w-5 text-gray-500" />
            <h2 className="text-base font-semibold text-gray-900">
              3D ビューワー
            </h2>
          </div>
          <span className="text-xs text-gray-400">
            品川タワー BIMモデル — リアルタイム表示
          </span>
        </div>
        <div className="h-80 bg-slate-900 flex items-center justify-center rounded-b-xl">
          <div className="text-center">
            <Globe className="mx-auto h-12 w-12 text-slate-400" />
            <p className="mt-3 text-sm font-medium text-slate-300">
              Digital Twin Viewer
            </p>
            <p className="mt-1 text-xs text-slate-500">
              3Dモデルをここに表示します
            </p>
            <button className="mt-4 rounded-lg border border-slate-600 px-4 py-2 text-xs text-slate-300 hover:bg-slate-800 transition-colors">
              ビューワーを起動
            </button>
          </div>
        </div>
      </div>

      {/* Sensor Data Feed */}
      <div className="rounded-xl border border-gray-200 bg-white shadow-sm">
        <div className="flex items-center justify-between border-b border-gray-200 px-6 py-4">
          <div className="flex items-center gap-2">
            <Wifi className="h-5 w-5 text-gray-500" />
            <h2 className="text-base font-semibold text-gray-900">
              データフィード状況
            </h2>
          </div>
          <span className="text-sm text-gray-500">
            {sensors.length}センサー
          </span>
        </div>
        <div className="overflow-x-auto">
          <table className="min-w-full divide-y divide-gray-200">
            <thead className="bg-gray-50">
              <tr>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">
                  センサー名
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">
                  種別
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">
                  更新頻度
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">
                  最終更新
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">
                  同期状態
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100 bg-white">
              {sensors.map((sensor) => {
                const syncInfo = syncStatusStyle[sensor.syncStatus];
                return (
                  <tr key={sensor.id} className="hover:bg-gray-50">
                    <td className="px-4 py-3">
                      <p className="text-sm font-medium text-gray-900">
                        {sensor.sensorName}
                      </p>
                    </td>
                    <td className="px-4 py-3">
                      <span
                        className={`inline-flex items-center rounded-full px-2.5 py-1 text-xs font-medium ${sensorTypeColor[sensor.type]}`}
                      >
                        {sensorTypeLabel[sensor.type]}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-sm text-gray-700">
                      {sensor.updateFrequency}
                    </td>
                    <td className="px-4 py-3 text-sm text-gray-500 whitespace-nowrap">
                      {sensor.lastUpdated}
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-1.5">
                        {sensor.syncStatus === "synced" ? (
                          <Wifi className="h-3.5 w-3.5 text-green-500" />
                        ) : (
                          <WifiOff className="h-3.5 w-3.5 text-red-500" />
                        )}
                        <span
                          className={`inline-flex items-center rounded-full px-2.5 py-1 text-xs font-medium ${syncInfo.className}`}
                        >
                          {syncInfo.label}
                        </span>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
