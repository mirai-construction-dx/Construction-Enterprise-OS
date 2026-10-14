"use client";

import { useState, useEffect, useCallback } from "react";
import { Target, TrendingUp, BarChart3, CheckCircle } from "lucide-react";
import { get, ApiError } from "@/lib/api-client";

type KpiCategory = "安全" | "品質" | "工程" | "コスト" | "環境";
type KpiTrend = "up" | "down" | "flat";

interface KpiItem {
  id: number;
  name: string;
  category: KpiCategory;
  target: number;
  actual: number;
  unit: string;
  trend: KpiTrend;
  prevPeriodChange: number; // % vs previous period
  lowerIsBetter?: boolean; // for KPIs where lower actual = better
}

const KPI_DATA: KpiItem[] = [
  // 安全
  {
    id: 1,
    name: "労働災害件数",
    category: "安全",
    target: 0,
    actual: 0,
    unit: "件",
    trend: "flat",
    prevPeriodChange: 0,
    lowerIsBetter: true,
  },
  {
    id: 2,
    name: "安全パトロール実施率",
    category: "安全",
    target: 100,
    actual: 98,
    unit: "%",
    trend: "up",
    prevPeriodChange: 3,
  },
  {
    id: 3,
    name: "ヒヤリハット報告件数",
    category: "安全",
    target: 20,
    actual: 24,
    unit: "件",
    trend: "up",
    prevPeriodChange: 20,
  },
  // 品質
  {
    id: 4,
    name: "検査合格率",
    category: "品質",
    target: 100,
    actual: 97.2,
    unit: "%",
    trend: "down",
    prevPeriodChange: -1.1,
  },
  {
    id: 5,
    name: "手直し工事率",
    category: "品質",
    target: 2,
    actual: 1.8,
    unit: "%",
    trend: "up",
    prevPeriodChange: -10,
    lowerIsBetter: true,
  },
  {
    id: 6,
    name: "品質不適合件数",
    category: "品質",
    target: 3,
    actual: 5,
    unit: "件",
    trend: "down",
    prevPeriodChange: 66.7,
    lowerIsBetter: true,
  },
  // 工程
  {
    id: 7,
    name: "工程遵守率",
    category: "工程",
    target: 95,
    actual: 91,
    unit: "%",
    trend: "down",
    prevPeriodChange: -3,
  },
  {
    id: 8,
    name: "完工件数（月）",
    category: "工程",
    target: 3,
    actual: 3,
    unit: "件",
    trend: "flat",
    prevPeriodChange: 0,
  },
  {
    id: 9,
    name: "工事進捗率（平均）",
    category: "工程",
    target: 65,
    actual: 62.8,
    unit: "%",
    trend: "up",
    prevPeriodChange: 5.2,
  },
  // コスト
  {
    id: 10,
    name: "原価率",
    category: "コスト",
    target: 85,
    actual: 84.2,
    unit: "%",
    trend: "up",
    prevPeriodChange: -0.8,
    lowerIsBetter: true,
  },
  {
    id: 11,
    name: "営業利益率",
    category: "コスト",
    target: 8,
    actual: 8.4,
    unit: "%",
    trend: "up",
    prevPeriodChange: 0.4,
  },
  {
    id: 12,
    name: "資材コスト削減率",
    category: "コスト",
    target: 5,
    actual: 3.8,
    unit: "%",
    trend: "down",
    prevPeriodChange: -1.2,
  },
  // 環境
  {
    id: 13,
    name: "CO₂排出量（月）",
    category: "環境",
    target: 450,
    actual: 423,
    unit: "t",
    trend: "up",
    prevPeriodChange: -6,
    lowerIsBetter: true,
  },
  {
    id: 14,
    name: "産廃リサイクル率",
    category: "環境",
    target: 85,
    actual: 88.5,
    unit: "%",
    trend: "up",
    prevPeriodChange: 3.5,
  },
  {
    id: 15,
    name: "騒音基準超過件数",
    category: "環境",
    target: 0,
    actual: 1,
    unit: "件",
    trend: "down",
    prevPeriodChange: 100,
    lowerIsBetter: true,
  },
];

interface SafetyStats {
  total: number;
  passed: number;
  failed: number;
  pass_rate: number;
  pending: number;
}

interface SafetyHazard {
  id: number;
  [key: string]: unknown;
}

const CATEGORY_COLORS: Record<KpiCategory, string> = {
  安全: "bg-red-100 text-red-800",
  品質: "bg-blue-100 text-blue-800",
  工程: "bg-purple-100 text-purple-800",
  コスト: "bg-green-100 text-green-800",
  環境: "bg-teal-100 text-teal-800",
};

// Compute achievement rate (0–100+). Handles "lower is better" KPIs.
function getAchievementRate(item: KpiItem): number {
  if (item.lowerIsBetter) {
    if (item.target === 0) return item.actual === 0 ? 100 : 0;
    if (item.actual <= item.target) return 100;
    return Math.round((item.target / item.actual) * 100);
  }
  if (item.target === 0) return item.actual === 0 ? 100 : 100;
  return Math.min(120, Math.round((item.actual / item.target) * 100));
}

function AchievementBar({ rate }: { rate: number }) {
  const color =
    rate >= 100 ? "bg-green-500" : rate >= 80 ? "bg-yellow-500" : "bg-red-500";
  const displayWidth = Math.min(100, rate);
  return (
    <div className="flex items-center gap-2">
      <div className="w-24 h-2.5 bg-gray-200 rounded-full overflow-hidden">
        <div
          className={`h-full rounded-full ${color}`}
          style={{ width: `${displayWidth}%` }}
        />
      </div>
      <span
        className={`text-xs font-semibold ${rate >= 100 ? "text-green-700" : rate >= 80 ? "text-yellow-700" : "text-red-700"}`}
      >
        {rate}%
      </span>
    </div>
  );
}

function TrendBadge({ trend, change }: { trend: KpiTrend; change: number }) {
  if (trend === "flat")
    return <span className="text-gray-400 font-bold text-base">→</span>;
  if (trend === "up")
    return (
      <span className="text-green-600 font-bold text-base">
        ↑{" "}
        <span className="text-xs font-normal text-green-600">
          {change > 0 ? "+" : ""}
          {change}%
        </span>
      </span>
    );
  return (
    <span className="text-red-600 font-bold text-base">
      ↓{" "}
      <span className="text-xs font-normal text-red-600">
        {change > 0 ? "+" : ""}
        {change}%
      </span>
    </span>
  );
}

export default function KpiDashboardPage() {
  const [kpiData, setKpiData] = useState<KpiItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const [statsRes, hazardsRes] = await Promise.allSettled([
        get<SafetyStats>("/safety/inspections/stats"),
        get<SafetyHazard[] | { items: SafetyHazard[] }>("/safety/hazards/open"),
      ]);

      let passRate: number | null = null;
      let openHazardCount: number | null = null;

      if (statsRes.status === "fulfilled") {
        const json = statsRes.value;
        passRate = json?.pass_rate ?? null;
      }

      if (hazardsRes.status === "fulfilled") {
        const json = hazardsRes.value;
        const items = Array.isArray(json) ? json : (json?.items ?? []);
        openHazardCount = items.length;
      }

      setKpiData(
        KPI_DATA.map((k) => {
          if (k.id === 2 && passRate !== null) {
            // 安全パトロール実施率
            const rounded = Math.round(passRate * 10) / 10;
            return {
              ...k,
              actual: rounded,
              trend: rounded >= k.actual ? "up" : "down",
              prevPeriodChange: Math.round((rounded - k.actual) * 10) / 10,
            };
          }
          if (k.id === 3 && openHazardCount !== null) {
            // ヒヤリハット報告件数
            return {
              ...k,
              actual: openHazardCount,
              trend:
                openHazardCount > k.actual
                  ? "up"
                  : openHazardCount < k.actual
                    ? "down"
                    : "flat",
              prevPeriodChange:
                k.actual > 0
                  ? Math.round(
                      ((openHazardCount - k.actual) / k.actual) * 1000,
                    ) / 10
                  : 0,
            };
          }
          return k;
        }),
      );

      const rejected = [statsRes, hazardsRes].filter(
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

  const rates = kpiData.map((k) => getAchievementRate(k));
  const achieved = rates.filter((r) => r >= 100).length;
  const improving = kpiData.filter((k) => k.trend === "up").length;
  const declining = kpiData.filter((k) => k.trend === "down").length;
  const overallRate =
    kpiData.length > 0 ? Math.round((achieved / kpiData.length) * 100) : 0;

  const stats = [
    {
      label: "全KPI達成率",
      value: `${overallRate}%`,
      sub: `${achieved} / ${kpiData.length} 件達成`,
      icon: CheckCircle,
      color: "text-green-600",
      bg: "bg-green-50",
    },
    {
      label: "改善中",
      value: `${improving}件`,
      sub: "前期比プラス",
      icon: TrendingUp,
      color: "text-blue-600",
      bg: "bg-blue-50",
    },
    {
      label: "悪化中",
      value: `${declining}件`,
      sub: "要注意KPI",
      icon: BarChart3,
      color: "text-red-600",
      bg: "bg-red-50",
    },
    {
      label: "モニタリング対象",
      value: `${kpiData.length}件`,
      sub: "5カテゴリ",
      icon: Target,
      color: "text-purple-600",
      bg: "bg-purple-50",
    },
  ];

  const categories: KpiCategory[] = ["安全", "品質", "工程", "コスト", "環境"];

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">
            KPIダッシュボード
          </h1>
          <p className="text-sm text-gray-500 mt-1">
            ダッシュボード — 全社KPI達成状況・トレンド分析
          </p>
        </div>
        <div className="flex items-center gap-3">
          {loading && (
            <span className="text-xs text-blue-600 bg-blue-50 px-2 py-1 rounded-full animate-pulse">
              データ取得中...
            </span>
          )}
          <Target className="w-8 h-8 text-purple-600" />
        </div>
      </div>

      {error && (
        <div role="alert" aria-live="assertive" className="rounded-xl border border-danger-500/30 bg-danger-50 px-4 py-3 text-sm text-danger-700">
          {error}
        </div>
      )}
      {!loading && !error && kpiData.length === 0 && (
        <div className="rounded-xl border border-gray-200 bg-white px-4 py-8 text-center text-sm text-gray-500">
          該当データがありません。
        </div>
      )}

      {/* 統計カード */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        {stats.map((s) => {
          const Icon = s.icon;
          return (
            <div key={s.label} className="bg-white rounded-lg border p-4">
              <div
                className={`w-10 h-10 rounded-lg ${s.bg} flex items-center justify-center mb-3`}
              >
                <Icon className={`w-5 h-5 ${s.color}`} />
              </div>
              <p className="text-xs text-gray-500">{s.label}</p>
              <p className="text-xl font-bold text-gray-900 mt-0.5">
                {s.value}
              </p>
              <p className="text-xs text-gray-400 mt-1">{s.sub}</p>
            </div>
          );
        })}
      </div>

      {/* カテゴリ別KPIテーブル */}
      {categories.map((cat) => {
        const items = kpiData.filter((k) => k.category === cat);
        return (
          <div key={cat} className="bg-white rounded-lg border overflow-hidden">
            <div className="px-4 py-3 border-b bg-gray-50 flex items-center gap-2">
              <span
                className={`px-2 py-0.5 rounded-full text-xs font-semibold ${CATEGORY_COLORS[cat]}`}
              >
                {cat}
              </span>
              <h2 className="font-semibold text-gray-700">
                {cat}カテゴリ KPI ({items.length}件)
              </h2>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="bg-gray-50 border-b">
                  <tr>
                    <th className="px-4 py-3 text-left font-medium text-gray-600">
                      KPI名
                    </th>
                    <th className="px-4 py-3 text-right font-medium text-gray-600">
                      目標値
                    </th>
                    <th className="px-4 py-3 text-right font-medium text-gray-600">
                      実績値
                    </th>
                    <th className="px-4 py-3 text-left font-medium text-gray-600 w-44">
                      達成率
                    </th>
                    <th className="px-4 py-3 text-left font-medium text-gray-600">
                      トレンド
                    </th>
                    <th className="px-4 py-3 text-right font-medium text-gray-600">
                      前期比
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y">
                  {items.map((kpi) => {
                    const rate = getAchievementRate(kpi);
                    return (
                      <tr key={kpi.id} className="hover:bg-gray-50">
                        <td className="px-4 py-3 font-medium text-gray-900">
                          {kpi.name}
                        </td>
                        <td className="px-4 py-3 text-right text-gray-600">
                          {kpi.target}
                          <span className="text-xs text-gray-400 ml-1">
                            {kpi.unit}
                          </span>
                        </td>
                        <td className="px-4 py-3 text-right font-semibold text-gray-900">
                          {kpi.actual}
                          <span className="text-xs text-gray-400 ml-1">
                            {kpi.unit}
                          </span>
                        </td>
                        <td className="px-4 py-3">
                          <AchievementBar rate={rate} />
                        </td>
                        <td className="px-4 py-3">
                          <TrendBadge
                            trend={kpi.trend}
                            change={kpi.prevPeriodChange}
                          />
                        </td>
                        <td className="px-4 py-3 text-right text-xs">
                          <span
                            className={
                              kpi.prevPeriodChange > 0
                                ? "text-green-600 font-medium"
                                : kpi.prevPeriodChange < 0
                                  ? "text-red-600 font-medium"
                                  : "text-gray-400"
                            }
                          >
                            {kpi.prevPeriodChange > 0 ? "+" : ""}
                            {kpi.prevPeriodChange}%
                          </span>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
        );
      })}
    </div>
  );
}
