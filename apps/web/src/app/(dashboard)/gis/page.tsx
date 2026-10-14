"use client";

import { useState, useEffect } from "react";
import dynamic from "next/dynamic";
import { Map, MapPin, Layers, Navigation, AlertTriangle } from "lucide-react";
import { listSites, sitesFromGeoJSON } from "@/lib/api/gis";
import { ApiError } from "@/lib/api-client";
import type { MapSitePin } from "@/components/gis/LeafletMap";

// Leaflet requires DOM; load only on client side
const LeafletMap = dynamic(() => import("@/components/gis/LeafletMap"), {
  ssr: false,
  loading: () => (
    <div className="flex h-full items-center justify-center bg-gray-50 text-gray-400 text-sm">
      地図を読み込み中...
    </div>
  ),
});

const mapLayers = [
  { id: "sites", label: "工事現場", active: true, color: "primary" },
  { id: "safety", label: "安全区域", active: true, color: "safety" },
  { id: "underground", label: "地下埋設物", active: false, color: "danger" },
  { id: "transport", label: "搬入ルート", active: true, color: "approve" },
  { id: "equipment", label: "重機位置", active: true, color: "site" },
];

type SitePin = MapSitePin;

const nearbyAlerts = [
  {
    type: "weather",
    message: "強風警報 — 高所作業中止を推奨 (14:00〜18:00)",
    severity: "warning",
    site: "品川タワー",
  },
  {
    type: "equipment",
    message: "重機振動異常 — センサーS-010 閾値超過",
    severity: "alert",
    site: "川崎物流センター",
  },
  {
    type: "traffic",
    message: "搬入ルート渋滞 — 国道15号線 事故処理中",
    severity: "info",
    site: "横浜マンション",
  },
];

const equipment = [
  {
    id: "EQ-001",
    name: "タワークレーン TC-200",
    site: "品川タワー新築工事",
    status: "operating",
    operator: "木村 一郎",
  },
  {
    id: "EQ-002",
    name: "油圧ショベル ZX350",
    site: "川崎物流センター建設",
    status: "alert",
    operator: "加藤 二郎",
  },
  {
    id: "EQ-003",
    name: "コンクリートポンプ車",
    site: "横浜分譲マンション建設",
    status: "standby",
    operator: "松本 三郎",
  },
  {
    id: "EQ-004",
    name: "バックホウ PC200",
    site: "大田区道路改良工事",
    status: "operating",
    operator: "井上 四郎",
  },
];

const equipmentStatus = {
  operating: { label: "稼働中", className: "bg-approve-50 text-approve-700" },
  standby: { label: "待機中", className: "bg-concrete-50 text-concrete-600" },
  alert: { label: "要確認", className: "bg-danger-50 text-danger-700" },
};

export default function GISPage() {
  const [sitePins, setSitePins] = useState<SitePin[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listSites()
      .then((data) => {
        const sites = sitesFromGeoJSON(data);
        const mapped: SitePin[] = sites.map((s, i) => ({
          id: i + 1,
          name: s.name,
          lat: s.latitude,
          lng: s.longitude,
          status: s.status ?? "active",
          workers: 0,
          alerts: 0,
        }));
        setSitePins(mapped);
        setError(null);
      })
      .catch((err: unknown) => {
        setError(
          err instanceof ApiError && err.status === 403
            ? "権限がありません。"
            : "データを取得できませんでした。",
        );
      });
  }, []);

  return (
    <div className="p-6 lg:p-8 space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">GIS・現場マップ</h1>
          <p className="mt-1 text-gray-500 text-sm">
            工事現場・重機位置・安全区域のリアルタイム地図管理
          </p>
        </div>
        <div className="flex gap-2">
          <button className="inline-flex items-center gap-2 rounded-lg border border-gray-200 bg-white px-4 py-2.5 text-sm font-medium text-gray-700 hover:bg-gray-50 transition-colors">
            <Layers className="h-4 w-4" />
            レイヤー管理
          </button>
          <button className="inline-flex items-center gap-2 rounded-lg bg-primary-600 px-4 py-2.5 text-sm font-semibold text-white hover:bg-primary-700 transition-colors">
            <Navigation className="h-4 w-4" />
            現在地
          </button>
        </div>
      </div>

      {error && (
        <div role="alert" aria-live="assertive" className="rounded-xl border border-danger-500/30 bg-danger-50 px-4 py-3 text-sm text-danger-700">
          {error}
        </div>
      )}
      {!error && sitePins.length === 0 && (
        <div className="rounded-xl border border-gray-200 bg-white px-4 py-8 text-center text-sm text-gray-500">
          該当データがありません。
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Map Placeholder */}
        <div className="lg:col-span-2 space-y-4">
          {/* Real Leaflet Map */}
          <div
            className="relative rounded-xl border border-gray-200 bg-white overflow-hidden"
            style={{ height: "480px" }}
          >
            <LeafletMap sitePins={sitePins} height="480px" />
          </div>

          {/* Layer Controls */}
          <div className="rounded-xl border border-gray-200 bg-white p-4">
            <h3 className="text-sm font-semibold text-gray-700 mb-3">
              表示レイヤー
            </h3>
            <div className="flex flex-wrap gap-2">
              {mapLayers.map((layer) => (
                <label
                  key={layer.id}
                  className="flex items-center gap-2 cursor-pointer"
                >
                  <div
                    className={`relative inline-flex h-5 w-9 items-center rounded-full ${
                      layer.active ? `bg-${layer.color}-500` : "bg-gray-200"
                    } transition-colors`}
                  >
                    <span
                      className={`inline-block h-3.5 w-3.5 transform rounded-full bg-white shadow transition-transform ${
                        layer.active ? "translate-x-4.5" : "translate-x-0.5"
                      }`}
                    />
                  </div>
                  <span className="text-sm text-gray-700">{layer.label}</span>
                </label>
              ))}
            </div>
          </div>
        </div>

        {/* Right Panel */}
        <div className="space-y-4">
          {/* Alerts */}
          <div className="rounded-xl border border-gray-200 bg-white overflow-hidden">
            <div className="px-4 py-3 border-b border-gray-100">
              <h3 className="font-bold text-gray-900 text-sm">
                エリアアラート
              </h3>
            </div>
            <div className="divide-y divide-gray-100">
              {nearbyAlerts.map((alert, i) => (
                <div key={i} className="px-4 py-3">
                  <div className={`flex items-start gap-2`}>
                    <AlertTriangle
                      className={`h-4 w-4 mt-0.5 flex-shrink-0 ${
                        alert.severity === "alert"
                          ? "text-danger-500"
                          : alert.severity === "warning"
                            ? "text-safety-500"
                            : "text-primary-500"
                      }`}
                    />
                    <div>
                      <p className="text-xs font-semibold text-gray-800">
                        {alert.site}
                      </p>
                      <p className="text-xs text-gray-600 mt-0.5 leading-relaxed">
                        {alert.message}
                      </p>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Equipment List */}
          <div className="rounded-xl border border-gray-200 bg-white overflow-hidden">
            <div className="px-4 py-3 border-b border-gray-100">
              <h3 className="font-bold text-gray-900 text-sm">重機位置</h3>
            </div>
            <div className="divide-y divide-gray-100">
              {equipment.map((eq) => {
                const status =
                  equipmentStatus[eq.status as keyof typeof equipmentStatus];
                return (
                  <div
                    key={eq.id}
                    className="px-4 py-3 hover:bg-gray-50 transition-colors"
                  >
                    <div className="flex items-start justify-between gap-2">
                      <div>
                        <p className="text-xs font-semibold text-gray-900">
                          {eq.name}
                        </p>
                        <p className="text-xs text-gray-500 mt-0.5">
                          {eq.site}
                        </p>
                        <p className="text-xs text-gray-400">
                          操作: {eq.operator}
                        </p>
                      </div>
                      <span
                        className={`flex-shrink-0 rounded-full px-2 py-0.5 text-xs font-medium ${status.className}`}
                      >
                        {status.label}
                      </span>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          {/* Site List */}
          <div className="rounded-xl border border-gray-200 bg-white overflow-hidden">
            <div className="px-4 py-3 border-b border-gray-100">
              <h3 className="font-bold text-gray-900 text-sm">工事現場一覧</h3>
            </div>
            <div className="divide-y divide-gray-100">
              {sitePins.map((site) => (
                <div
                  key={site.id}
                  className="px-4 py-3 hover:bg-gray-50 transition-colors cursor-pointer"
                >
                  <div className="flex items-center gap-3">
                    <MapPin
                      className={`h-4 w-4 flex-shrink-0 ${
                        site.status === "alert"
                          ? "text-danger-500"
                          : site.status === "planning"
                            ? "text-gray-400"
                            : "text-primary-500"
                      }`}
                    />
                    <div>
                      <p className="text-xs font-semibold text-gray-900">
                        {site.name}
                      </p>
                      {site.workers > 0 && (
                        <p className="text-xs text-gray-500">
                          {site.workers}名 作業中
                        </p>
                      )}
                    </div>
                    {site.alerts > 0 && (
                      <span className="ml-auto text-xs bg-danger-500 text-white rounded-full px-1.5">
                        {site.alerts}
                      </span>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
