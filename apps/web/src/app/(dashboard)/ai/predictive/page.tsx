"use client";

import { useState, useEffect, useCallback } from "react";
import { Activity, AlertTriangle, Wrench, Clock } from "lucide-react";
import { get, ApiError } from "@/lib/api-client";

interface Equipment {
  id: string;
  name: string;
  location: string;
  healthScore: number;
  remainingLifeDays: number;
  nextInspectionDate: string;
  status: "normal" | "warning" | "critical";
  lastMaintained: string;
}

// API response shape from /api/v1/advanced/predictive
interface PredictiveResult {
  id: string | number;
  asset_id?: string;
  asset_name?: string;
  failure_probability?: number; // 0–1 or 0–100
  risk_level?: "normal" | "warning" | "critical" | "low" | "medium" | "high";
  predicted_failure_at?: string;
  recommendation?: string;
  // optional extra fields
  health_score?: number;
  remaining_life_days?: number;
  next_inspection_date?: string;
  last_maintained?: string;
  location?: string;
}

const STATUS_CONFIG = {
  normal: {
    label: "正常",
    color: "bg-green-100 text-green-700",
    barColor: "bg-green-500",
  },
  warning: {
    label: "注意",
    color: "bg-yellow-100 text-yellow-700",
    barColor: "bg-yellow-500",
  },
  critical: {
    label: "要対応",
    color: "bg-red-100 text-red-700",
    barColor: "bg-red-500",
  },
};

/** Map API risk_level to Equipment status */
function toStatus(
  risk: PredictiveResult["risk_level"],
  prob?: number,
): Equipment["status"] {
  if (risk === "critical" || risk === "high") return "critical";
  if (risk === "warning" || risk === "medium") return "warning";
  if (risk === "normal" || risk === "low") return "normal";
  // fallback: use failure_probability (0–1 scale assumed)
  const p = (prob ?? 0) > 1 ? (prob ?? 0) / 100 : (prob ?? 0);
  if (p >= 0.7) return "critical";
  if (p >= 0.4) return "warning";
  return "normal";
}

/** Map PredictiveResult → Equipment for display */
function toEquipment(r: PredictiveResult, idx: number): Equipment {
  const prob = r.failure_probability ?? 0;
  const normProb = prob > 1 ? prob / 100 : prob;
  const healthScore =
    r.health_score != null ? r.health_score : Math.round((1 - normProb) * 100);
  return {
    id: String(r.id ?? `EQ-${idx + 1}`),
    name: r.asset_name ?? r.asset_id ?? `設備 ${idx + 1}`,
    location: r.location ?? "—",
    healthScore,
    remainingLifeDays: r.remaining_life_days ?? 0,
    nextInspectionDate: r.next_inspection_date ?? r.predicted_failure_at ?? "—",
    status: toStatus(r.risk_level, r.failure_probability),
    lastMaintained: r.last_maintained ?? "—",
  };
}

function HealthGauge({
  score,
  status,
}: {
  score: number;
  status: Equipment["status"];
}) {
  const barColor = STATUS_CONFIG[status].barColor;
  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between">
        <span
          className={`text-sm font-bold ${score >= 80 ? "text-green-600" : score >= 60 ? "text-yellow-600" : "text-red-600"}`}
        >
          {score}%
        </span>
      </div>
      <div className="w-24 h-2 bg-gray-100 rounded-full overflow-hidden">
        <div
          className={`h-full rounded-full ${barColor}`}
          style={{ width: `${score}%` }}
        />
      </div>
    </div>
  );
}

export default function AIPredictivePage() {
  const [equipment, setEquipment] = useState<Equipment[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const json = await get<
        PredictiveResult[] | { items: PredictiveResult[] }
      >("/advanced/predictive?per_page=20");
      const items: PredictiveResult[] = Array.isArray(json)
        ? json
        : (json?.items ?? []);
      setEquipment(items.map((r, i) => toEquipment(r, i)));
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

  const warningCount = equipment.filter((e) => e.status === "warning").length;
  const criticalCount = equipment.filter((e) => e.status === "critical").length;
  const alerts = equipment
    .filter((e) => e.status !== "normal")
    .sort((a, b) => a.healthScore - b.healthScore);

  return (
    <div className="p-6 space-y-6">
      {/* ヘッダー */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">予知保全</h1>
          <p className="text-sm text-gray-500 mt-1">
            AIによる機器健全度モニタリング・寿命予測
          </p>
        </div>
        <div className="flex items-center gap-3">
          {loading && (
            <span className="text-xs text-blue-600 bg-blue-50 px-2 py-1 rounded-full animate-pulse">
              データ取得中...
            </span>
          )}
          <div className="flex items-center gap-2 text-xs text-gray-500 bg-blue-50 px-3 py-1.5 rounded-full">
            <Activity className="w-3.5 h-3.5 text-blue-600" />
            Predictive AI
          </div>
        </div>
      </div>

      {error && (
        <div role="alert" aria-live="assertive" className="rounded-xl border border-danger-500/30 bg-danger-50 px-4 py-3 text-sm text-danger-700">
          {error}
        </div>
      )}
      {!loading && !error && equipment.length === 0 && (
        <div className="rounded-xl border border-gray-200 bg-white px-4 py-8 text-center text-sm text-gray-500">
          該当データがありません。
        </div>
      )}

      {/* 統計カード */}
      <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
        <div className="bg-white rounded-xl p-4 shadow-sm border border-gray-100">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-blue-50 rounded-lg">
              <Activity className="w-5 h-5 text-blue-600" />
            </div>
            <div>
              <p className="text-xs text-gray-500">監視機器数</p>
              <p className="text-2xl font-bold text-gray-900">
                {equipment.length}
              </p>
            </div>
          </div>
        </div>
        <div className="bg-white rounded-xl p-4 shadow-sm border border-gray-100">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-yellow-50 rounded-lg">
              <AlertTriangle className="w-5 h-5 text-yellow-600" />
            </div>
            <div>
              <p className="text-xs text-gray-500">警告数</p>
              <p className="text-2xl font-bold text-gray-900">{warningCount}</p>
            </div>
          </div>
        </div>
        <div className="bg-white rounded-xl p-4 shadow-sm border border-gray-100">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-red-50 rounded-lg">
              <Wrench className="w-5 h-5 text-red-600" />
            </div>
            <div>
              <p className="text-xs text-gray-500">緊急交換推奨</p>
              <p className="text-2xl font-bold text-gray-900">
                {criticalCount}
              </p>
            </div>
          </div>
        </div>
      </div>

      {/* アラートリスト */}
      {alerts.length > 0 && (
        <div className="bg-white rounded-xl p-5 shadow-sm border border-orange-200">
          <h2 className="text-sm font-semibold text-gray-700 mb-3 flex items-center gap-2">
            <AlertTriangle className="w-4 h-4 text-orange-500" />
            要注意機器アラート
          </h2>
          <div className="space-y-2">
            {alerts.map((eq) => (
              <div
                key={eq.id}
                className={`flex items-center justify-between p-3 rounded-lg ${eq.status === "critical" ? "bg-red-50 border border-red-100" : "bg-yellow-50 border border-yellow-100"}`}
              >
                <div className="flex items-center gap-3">
                  <span
                    className={`px-2 py-0.5 rounded text-xs font-medium ${STATUS_CONFIG[eq.status].color}`}
                  >
                    {STATUS_CONFIG[eq.status].label}
                  </span>
                  <span className="font-medium text-gray-900 text-sm">
                    {eq.name}
                  </span>
                  <span className="text-gray-500 text-xs">{eq.location}</span>
                </div>
                <div className="flex items-center gap-4 text-xs text-gray-600">
                  <span>
                    健全度{" "}
                    <strong className="text-red-600">{eq.healthScore}%</strong>
                  </span>
                  <span>
                    残存寿命 <strong>{eq.remainingLifeDays}日</strong>
                  </span>
                  <span>
                    次回点検 <strong>{eq.nextInspectionDate}</strong>
                  </span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* 機器一覧テーブル */}
      <div className="bg-white rounded-xl shadow-sm border border-gray-100 overflow-hidden">
        <div className="px-5 py-4 border-b border-gray-100">
          <h2 className="font-semibold text-gray-800">機器別健全度一覧</h2>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 border-b border-gray-200">
              <tr>
                <th className="text-left px-4 py-3 font-medium text-gray-600">
                  機器名
                </th>
                <th className="text-left px-4 py-3 font-medium text-gray-600">
                  設置場所
                </th>
                <th className="text-left px-4 py-3 font-medium text-gray-600">
                  健全度
                </th>
                <th className="text-left px-4 py-3 font-medium text-gray-600">
                  予測残存寿命
                </th>
                <th className="text-left px-4 py-3 font-medium text-gray-600">
                  次回点検推奨日
                </th>
                <th className="text-left px-4 py-3 font-medium text-gray-600">
                  最終整備日
                </th>
                <th className="text-left px-4 py-3 font-medium text-gray-600">
                  状態
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {equipment.map((eq) => (
                <tr key={eq.id} className="hover:bg-gray-50 transition-colors">
                  <td className="px-4 py-3 font-medium text-gray-900">
                    {eq.name}
                  </td>
                  <td className="px-4 py-3 text-gray-600">{eq.location}</td>
                  <td className="px-4 py-3">
                    <HealthGauge score={eq.healthScore} status={eq.status} />
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-1 text-sm">
                      <Clock className="w-3.5 h-3.5 text-gray-400" />
                      <span
                        className={
                          eq.remainingLifeDays <= 30
                            ? "text-red-600 font-semibold"
                            : eq.remainingLifeDays <= 60
                              ? "text-yellow-600 font-semibold"
                              : "text-gray-700"
                        }
                      >
                        {eq.remainingLifeDays}日
                      </span>
                    </div>
                  </td>
                  <td className="px-4 py-3 text-gray-600 text-xs whitespace-nowrap">
                    {eq.nextInspectionDate}
                  </td>
                  <td className="px-4 py-3 text-gray-500 text-xs">
                    {eq.lastMaintained}
                  </td>
                  <td className="px-4 py-3">
                    <span
                      className={`px-2 py-0.5 rounded-full text-xs font-medium ${STATUS_CONFIG[eq.status].color}`}
                    >
                      {STATUS_CONFIG[eq.status].label}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="px-4 py-3 border-t border-gray-100 text-sm text-gray-500">
          {equipment.length}台
        </div>
      </div>
    </div>
  );
}
