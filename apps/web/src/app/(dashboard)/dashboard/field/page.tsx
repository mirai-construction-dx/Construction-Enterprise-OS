"use client";

import { useState, useEffect, useCallback } from "react";
import { Users, HardHat, Sun, Calendar } from "lucide-react";
import { get, ApiError } from "@/lib/api-client";

interface FieldProgress {
  id: string;
  site_id: string;
  site_name: string;
  progress_rate: number;
  worker_count: number;
  status: string;
  reported_at: string;
}

interface ScheduleItem {
  id: string;
  time: string;
  task: string;
  workers: number;
  status: string;
}

const RECENT_ALERTS = {
  safety: [
    { id: 1, msg: "第2工区 安全帯未着用検知", time: "08:42", level: "warning" },
    { id: 2, msg: "重機接近警告 BH-003付近", time: "08:15", level: "critical" },
    { id: 3, msg: "ヘルメット未着用 1名", time: "07:58", level: "warning" },
  ],
  quality: [
    {
      id: 4,
      msg: "コンクリート強度試験 要確認",
      time: "09:00",
      level: "warning",
    },
    { id: 5, msg: "配筋検査 第3工区 合格", time: "08:30", level: "info" },
    { id: 6, msg: "型枠精度 許容値内", time: "07:45", level: "info" },
  ],
  schedule: [
    { id: 7, msg: "掘削工事 2日遅延見込み", time: "08:00", level: "warning" },
    {
      id: 8,
      msg: "コンクリート打設 本日予定通り",
      time: "07:30",
      level: "info",
    },
    { id: 9, msg: "鉄筋工 工程前倒し完了", time: "07:00", level: "info" },
  ],
  iot: [
    { id: 10, msg: "GAS-003 CO濃度上昇警報", time: "08:42", level: "critical" },
    { id: 11, msg: "TEMP-001 高温アラート", time: "09:15", level: "critical" },
    { id: 12, msg: "VIB-007 振動超過検知", time: "08:30", level: "warning" },
  ],
};

const LEVEL_COLORS: Record<string, string> = {
  critical: "border-l-red-500 bg-red-50",
  warning: "border-l-yellow-500 bg-yellow-50",
  info: "border-l-blue-400 bg-blue-50",
};

const SCHEDULE_STATUS: Record<string, string> = {
  完了: "bg-green-100 text-green-800",
  進行中: "bg-blue-100 text-blue-800",
  予定: "bg-gray-100 text-gray-600",
};

// Helper to normalize schedule status from API
function normalizeScheduleStatus(raw: string): string {
  const map: Record<string, string> = {
    completed: "完了",
    done: "完了",
    in_progress: "進行中",
    active: "進行中",
    planned: "予定",
    scheduled: "予定",
    pending: "予定",
  };
  return map[raw?.toLowerCase()] ?? raw ?? "予定";
}

export default function FieldDashboardPage() {
  const [fieldProgress, setFieldProgress] = useState<FieldProgress[]>([]);
  const [scheduleItems, setScheduleItems] = useState<ScheduleItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const [progressResult, scheduleResult] = await Promise.allSettled([
        get<{
          data?: { items?: Record<string, unknown>[] };
          items?: Record<string, unknown>[];
        }>("/field/progress?per_page=20"),
        get<{
          data?: { items?: Record<string, unknown>[] };
          items?: Record<string, unknown>[];
        }>("/construction/schedule?per_page=20"),
      ]);

      if (progressResult.status === "fulfilled") {
        const progressJson = progressResult.value;
        const progressData: Record<string, unknown>[] =
          progressJson?.data?.items ?? progressJson?.items ?? [];
        setFieldProgress(
          Array.isArray(progressData)
            ? progressData.map((item) => ({
                id: String(item.id ?? ""),
                site_id: String(item.site_id ?? ""),
                site_name: String(item.site_name ?? ""),
                progress_rate: Number(item.progress_rate ?? 0),
                worker_count: Number(item.worker_count ?? 0),
                status: String(item.status ?? ""),
                reported_at: String(item.reported_at ?? ""),
              }))
            : [],
        );
      }

      if (scheduleResult.status === "fulfilled") {
        const scheduleJson = scheduleResult.value;
        const scheduleData: Record<string, unknown>[] =
          scheduleJson?.data?.items ?? scheduleJson?.items ?? [];
        setScheduleItems(
          Array.isArray(scheduleData)
            ? scheduleData.map((item) => ({
                id: String(item.id ?? ""),
                time: String(item.start_time ?? item.time ?? ""),
                task: String(item.task ?? item.name ?? item.title ?? ""),
                workers: Number(item.workers ?? item.worker_count ?? 0),
                status: normalizeScheduleStatus(String(item.status ?? "")),
              }))
            : [],
        );
      }

      const rejected = [progressResult, scheduleResult].filter(
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

  // Derive stats from API data if available, otherwise use static values
  const totalWorkers =
    fieldProgress.length > 0
      ? fieldProgress.reduce((acc, fp) => acc + fp.worker_count, 0)
      : 0;

  const stats = [
    {
      label: "今日の作業員数",
      value: `${totalWorkers}名`,
      icon: Users,
      color: "text-blue-600",
      bg: "bg-blue-50",
    },
    {
      label: "稼働重機数",
      value: "6台",
      icon: HardHat,
      color: "text-orange-600",
      bg: "bg-orange-50",
    },
    {
      label: "作業指示数",
      value: `${scheduleItems.length}件`,
      icon: Calendar,
      color: "text-purple-600",
      bg: "bg-purple-50",
    },
  ];

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">
            現場ダッシュボード
          </h1>
          <p className="text-sm text-gray-500 mt-1">
            ダッシュボード — 本日の作業状況・アラート
          </p>
        </div>
        <div className="flex items-center gap-3">
          {loading && (
            <span className="text-xs text-blue-500 animate-pulse">
              データ取得中...
            </span>
          )}
          <HardHat className="w-8 h-8 text-orange-500" />
        </div>
      </div>

      {error && (
        <div role="alert" aria-live="assertive" className="rounded-xl border border-danger-500/30 bg-danger-50 px-4 py-3 text-sm text-danger-700">
          {error}
        </div>
      )}
      {!loading &&
        !error &&
        fieldProgress.length === 0 &&
        scheduleItems.length === 0 && (
          <div className="rounded-xl border border-gray-200 bg-white px-4 py-8 text-center text-sm text-gray-500">
            該当データがありません。
          </div>
        )}

      {/* サマリーカード */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {stats.map((s) => {
          const Icon = s.icon;
          return (
            <div
              key={s.label}
              className="bg-white rounded-lg border p-4 flex items-center gap-4"
            >
              <div
                className={`w-12 h-12 rounded-lg ${s.bg} flex items-center justify-center shrink-0`}
              >
                <Icon className={`w-6 h-6 ${s.color}`} />
              </div>
              <div>
                <p className="text-xs text-gray-500">{s.label}</p>
                <p className="text-2xl font-bold text-gray-900">{s.value}</p>
              </div>
            </div>
          );
        })}
      </div>

      {/* 現場進捗（APIから取得時のみ表示） */}
      {fieldProgress.length > 0 && (
        <div className="bg-white rounded-lg border overflow-hidden">
          <div className="px-4 py-3 border-b bg-gray-50">
            <h2 className="font-semibold text-gray-700">現場進捗状況</h2>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-gray-50 border-b">
                <tr>
                  <th className="px-4 py-3 text-left font-medium text-gray-600">
                    現場名
                  </th>
                  <th className="px-4 py-3 text-left font-medium text-gray-600">
                    進捗率
                  </th>
                  <th className="px-4 py-3 text-left font-medium text-gray-600">
                    作業員数
                  </th>
                  <th className="px-4 py-3 text-left font-medium text-gray-600">
                    ステータス
                  </th>
                  <th className="px-4 py-3 text-left font-medium text-gray-600">
                    報告日時
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y">
                {fieldProgress.map((fp) => (
                  <tr
                    key={fp.id}
                    className="hover:bg-gray-50 transition-colors"
                  >
                    <td className="px-4 py-3 font-medium text-gray-900">
                      {fp.site_name}
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-2">
                        <div className="w-24 h-2 bg-gray-200 rounded-full overflow-hidden">
                          <div
                            className="h-full bg-blue-500 rounded-full"
                            style={{
                              width: `${Math.min(100, fp.progress_rate)}%`,
                            }}
                          />
                        </div>
                        <span className="text-xs text-gray-700">
                          {fp.progress_rate}%
                        </span>
                      </div>
                    </td>
                    <td className="px-4 py-3 text-gray-700">
                      {fp.worker_count}名
                    </td>
                    <td className="px-4 py-3">
                      <span className="inline-flex items-center px-2 py-1 rounded-full text-xs font-medium bg-blue-100 text-blue-800">
                        {fp.status}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-gray-500 text-xs">
                      {fp.reported_at}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* 天気情報 */}
      <div className="bg-white rounded-lg border p-4">
        <h2 className="font-semibold text-gray-700 mb-3 flex items-center gap-2">
          <Sun className="w-4 h-4 text-yellow-500" />
          本日の気象情報
        </h2>
        <div className="grid grid-cols-2 md:grid-cols-5 gap-4 text-center">
          <div>
            <p className="text-3xl">☀️</p>
            <p className="text-xs text-gray-500 mt-1">天気</p>
            <p className="font-semibold text-gray-800">晴れ</p>
          </div>
          <div>
            <p className="text-2xl font-bold text-orange-500">28.4°C</p>
            <p className="text-xs text-gray-500 mt-1">気温</p>
          </div>
          <div>
            <p className="text-2xl font-bold text-blue-500">62%</p>
            <p className="text-xs text-gray-500 mt-1">湿度</p>
          </div>
          <div>
            <p className="text-2xl font-bold text-teal-500">3.2 m/s</p>
            <p className="text-xs text-gray-500 mt-1">風速</p>
          </div>
          <div>
            <span className="inline-block px-3 py-1 bg-green-100 text-green-800 text-sm font-semibold rounded-full mt-1">
              作業適 ✓
            </span>
            <p className="text-xs text-gray-500 mt-1">作業適性</p>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* 直近アラート */}
        <div className="space-y-4">
          <h2 className="font-semibold text-gray-700">直近アラート</h2>
          {(
            [
              { key: "safety", label: "安全" },
              { key: "quality", label: "品質" },
              { key: "schedule", label: "工程" },
              { key: "iot", label: "IoT" },
            ] as const
          ).map(({ key, label }) => (
            <div
              key={key}
              className="bg-white rounded-lg border overflow-hidden"
            >
              <div className="px-3 py-2 bg-gray-50 border-b">
                <span className="font-medium text-gray-700 text-sm">
                  {label}アラート
                </span>
              </div>
              <div className="divide-y">
                {RECENT_ALERTS[key].map((alert) => (
                  <div
                    key={alert.id}
                    className={`px-3 py-2 border-l-4 text-sm ${LEVEL_COLORS[alert.level]}`}
                  >
                    <div className="flex justify-between items-start gap-2">
                      <span className="text-gray-800">{alert.msg}</span>
                      <span className="text-xs text-gray-400 shrink-0">
                        {alert.time}
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>

        {/* 今日のスケジュール */}
        <div>
          <h2 className="font-semibold text-gray-700 mb-4">
            今日のスケジュール
          </h2>
          <div className="bg-white rounded-lg border overflow-hidden">
            <div className="divide-y">
              {scheduleItems.map((item) => (
                <div
                  key={item.id}
                  className="flex items-center gap-4 px-4 py-3"
                >
                  <span className="font-mono text-sm text-gray-500 w-12 shrink-0">
                    {item.time}
                  </span>
                  <div className="flex-1 min-w-0">
                    <p className="font-medium text-gray-900 text-sm truncate">
                      {item.task}
                    </p>
                    <p className="text-xs text-gray-400">{item.workers}名</p>
                  </div>
                  <span
                    className={`px-2 py-1 rounded-full text-xs font-medium shrink-0 ${SCHEDULE_STATUS[item.status] ?? "bg-gray-100 text-gray-600"}`}
                  >
                    {item.status}
                  </span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
