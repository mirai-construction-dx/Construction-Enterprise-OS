"use client";

import { useState, useEffect, useCallback } from "react";
import { get, ApiError } from "@/lib/api-client";
import {
  TrendingUp,
  BarChart3,
  ClipboardList,
  AlertTriangle,
  Plus,
  RefreshCw,
} from "lucide-react";

interface ZoneProgress {
  id: string;
  zone_name: string;
  plan_pct: number;
  actual_pct: number;
  diff: number;
  status: "on_track" | "delay" | "ahead" | "critical";
}

interface WorkReport {
  id: string;
  time: string;
  content: string;
  worker: string;
  zone: string;
  note: string | null;
}

const statusStyle: Record<string, { label: string; className: string }> = {
  on_track: { label: "順調", className: "bg-green-100 text-green-700" },
  ahead: { label: "前倒", className: "bg-blue-100 text-blue-700" },
  delay: { label: "遅延", className: "bg-orange-100 text-orange-700" },
  critical: { label: "要対応", className: "bg-red-100 text-red-700" },
};

function ProgressBar({ plan, actual }: { plan: number; actual: number }) {
  return (
    <div className="w-full min-w-[120px]">
      <div className="relative h-4 rounded-full bg-gray-100 overflow-hidden">
        {/* plan bar (light) */}
        <div
          className="absolute inset-y-0 left-0 rounded-full bg-gray-300"
          style={{ width: `${plan}%` }}
        />
        {/* actual bar */}
        <div
          className={`absolute inset-y-0 left-0 rounded-full transition-all ${
            actual >= plan
              ? "bg-blue-500"
              : actual >= plan - 5
                ? "bg-orange-400"
                : "bg-red-400"
          }`}
          style={{ width: `${actual}%` }}
        />
      </div>
      <div className="flex justify-between text-xs text-gray-400 mt-0.5">
        <span>計画 {plan}%</span>
        <span>実績 {actual}%</span>
      </div>
    </div>
  );
}

export default function FieldProgressPage() {
  const [zones, setZones] = useState<ZoneProgress[]>([]);
  const [reports, setReports] = useState<WorkReport[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const [zonesRes, reportsRes] = await Promise.allSettled([
        get<{ data?: ZoneProgress[] }>("/field/progress/zones"),
        get<{ data?: WorkReport[] }>("/field/progress/reports/today"),
      ]);
      if (zonesRes.status === "fulfilled") {
        setZones(
          Array.isArray(zonesRes.value?.data) ? zonesRes.value.data : [],
        );
      }
      if (reportsRes.status === "fulfilled") {
        setReports(
          Array.isArray(reportsRes.value?.data) ? reportsRes.value.data : [],
        );
      }
      const rejected = [zonesRes, reportsRes].filter(
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

  const totalPlan =
    zones.length > 0
      ? Math.round(zones.reduce((s, z) => s + z.plan_pct, 0) / zones.length)
      : 0;
  const totalActual =
    zones.length > 0
      ? Math.round(zones.reduce((s, z) => s + z.actual_pct, 0) / zones.length)
      : 0;
  const delayZones = zones.filter(
    (z) => z.status === "delay" || z.status === "critical",
  ).length;

  const statCards = [
    {
      label: "全体進捗率（実績）",
      value: `${totalActual}%`,
      sub: `計画 ${totalPlan}%`,
      icon: BarChart3,
      color:
        totalActual >= totalPlan
          ? "text-blue-500 bg-blue-50"
          : "text-orange-500 bg-orange-50",
    },
    {
      label: "今日の報告件数",
      value: reports.length,
      sub: "本日分",
      icon: ClipboardList,
      color: "text-green-500 bg-green-50",
    },
    {
      label: "遅延工区数",
      value: delayZones,
      sub: `全 ${zones.length} 工区中`,
      icon: AlertTriangle,
      color:
        delayZones > 0
          ? "text-red-500 bg-red-50"
          : "text-green-500 bg-green-50",
    },
    {
      label: "進捗差異（全体）",
      value: `${totalActual - totalPlan > 0 ? "+" : ""}${totalActual - totalPlan}%`,
      sub: "実績 − 計画",
      icon: TrendingUp,
      color:
        totalActual >= totalPlan
          ? "text-blue-500 bg-blue-50"
          : "text-orange-500 bg-orange-50",
    },
  ];

  return (
    <div className="p-6 lg:p-8 space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">工事進捗入力</h1>
          <p className="mt-1 text-sm text-gray-500">
            工区別進捗率と本日の作業報告を管理します
          </p>
        </div>
        <div className="flex gap-2">
          <button
            onClick={loadData}
            disabled={loading}
            className="inline-flex items-center gap-2 rounded-lg border border-gray-200 bg-white px-4 py-2.5 text-sm font-medium text-gray-700 hover:bg-gray-50 transition-colors disabled:opacity-50"
          >
            <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
            更新
          </button>
          <button className="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2.5 text-sm font-semibold text-white hover:bg-blue-700 transition-colors">
            <Plus className="h-4 w-4" />
            作業報告を追加
          </button>
        </div>
      </div>

      {error && (
        <div role="alert" aria-live="assertive" className="rounded-xl border border-danger-500/30 bg-danger-50 px-4 py-3 text-sm text-danger-700">
          {error}
        </div>
      )}
      {!loading && !error && zones.length === 0 && reports.length === 0 && (
        <div className="rounded-xl border border-gray-200 bg-white px-4 py-8 text-center text-sm text-gray-500">
          該当データがありません。
        </div>
      )}

      {/* KPI Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {statCards.map((card) => {
          const Icon = card.icon;
          const [iconColor, bgColor] = card.color.split(" ");
          return (
            <div
              key={card.label}
              className="rounded-xl border border-gray-200 bg-white p-5 hover:shadow-md transition-shadow"
            >
              <div className={`inline-flex rounded-lg p-2.5 ${bgColor}`}>
                <Icon className={`h-5 w-5 ${iconColor}`} />
              </div>
              <p className="mt-4 text-3xl font-bold text-gray-900">
                {card.value}
              </p>
              <p className="mt-1 text-sm font-medium text-gray-600">
                {card.label}
              </p>
              <p className="mt-2 text-xs text-gray-400">{card.sub}</p>
            </div>
          );
        })}
      </div>

      {/* Zone Progress Table */}
      <div className="rounded-xl border border-gray-200 bg-white overflow-hidden">
        <div className="flex items-center justify-between px-5 py-4 border-b border-gray-100">
          <h2 className="font-bold text-gray-900 flex items-center gap-2">
            <BarChart3 className="h-4 w-4 text-blue-500" />
            工区別進捗率
          </h2>
          <span className="text-xs text-gray-500">基準日: 2026/05/24</span>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-100 bg-gray-50/50">
                <th className="px-5 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wide">
                  工区名
                </th>
                <th className="px-5 py-3 text-center text-xs font-semibold text-gray-500 uppercase tracking-wide">
                  計画
                </th>
                <th className="px-5 py-3 text-center text-xs font-semibold text-gray-500 uppercase tracking-wide">
                  実績
                </th>
                <th className="px-5 py-3 text-center text-xs font-semibold text-gray-500 uppercase tracking-wide">
                  差異
                </th>
                <th className="px-5 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wide min-w-[200px]">
                  進捗バー
                </th>
                <th className="px-5 py-3 text-center text-xs font-semibold text-gray-500 uppercase tracking-wide">
                  ステータス
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {zones.map((zone) => {
                const st = statusStyle[zone.status];
                return (
                  <tr
                    key={zone.id}
                    className="hover:bg-gray-50 transition-colors"
                  >
                    <td className="px-5 py-4 font-medium text-gray-900">
                      {zone.zone_name}
                    </td>
                    <td className="px-5 py-4 text-center text-gray-700">
                      {zone.plan_pct}%
                    </td>
                    <td className="px-5 py-4 text-center font-semibold text-gray-900">
                      {zone.actual_pct}%
                    </td>
                    <td className="px-5 py-4 text-center">
                      <span
                        className={`font-semibold ${
                          zone.diff > 0
                            ? "text-blue-600"
                            : zone.diff < 0
                              ? zone.diff < -8
                                ? "text-red-600"
                                : "text-orange-500"
                              : "text-gray-500"
                        }`}
                      >
                        {zone.diff > 0 ? "+" : ""}
                        {zone.diff}%
                      </span>
                    </td>
                    <td className="px-5 py-4">
                      <ProgressBar
                        plan={zone.plan_pct}
                        actual={zone.actual_pct}
                      />
                    </td>
                    <td className="px-5 py-4 text-center">
                      <span
                        className={`rounded-full px-2.5 py-0.5 text-xs font-medium ${st.className}`}
                      >
                        {st.label}
                      </span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

      {/* Work Reports */}
      <div className="rounded-xl border border-gray-200 bg-white overflow-hidden">
        <div className="flex items-center justify-between px-5 py-4 border-b border-gray-100">
          <h2 className="font-bold text-gray-900 flex items-center gap-2">
            <ClipboardList className="h-4 w-4 text-green-500" />
            本日の作業報告
          </h2>
          <span className="text-xs text-gray-500">{reports.length} 件</span>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-100 bg-gray-50/50">
                <th className="px-5 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wide">
                  時刻
                </th>
                <th className="px-5 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wide">
                  作業内容
                </th>
                <th className="px-5 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wide">
                  担当者
                </th>
                <th className="px-5 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wide">
                  工区
                </th>
                <th className="px-5 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wide">
                  備考
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {reports.map((r) => (
                <tr key={r.id} className="hover:bg-gray-50 transition-colors">
                  <td className="px-5 py-3.5 text-gray-500 font-mono text-xs whitespace-nowrap">
                    {r.time}
                  </td>
                  <td className="px-5 py-3.5 text-gray-900">{r.content}</td>
                  <td className="px-5 py-3.5 text-gray-600 whitespace-nowrap">
                    {r.worker}
                  </td>
                  <td className="px-5 py-3.5">
                    <span className="rounded bg-gray-100 px-2 py-0.5 text-xs text-gray-600">
                      {r.zone}
                    </span>
                  </td>
                  <td className="px-5 py-3.5 text-xs text-gray-400">
                    {r.note ?? "—"}
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
