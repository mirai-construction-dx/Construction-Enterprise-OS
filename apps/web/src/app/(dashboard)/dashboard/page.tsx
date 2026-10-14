"use client";

import { useState, useEffect } from "react";
import {
  ClipboardList,
  CheckSquare,
  AlertTriangle,
  FileText,
  ArrowUpRight,
  Plus,
  Search,
  Settings,
  Users,
} from "lucide-react";
import { get, ApiError } from "@/lib/api-client";

interface DashboardStats {
  activeProjects: number;
  pendingApprovals: number;
  iotAlerts: number;
  newDocuments: number;
}

const activities = [
  {
    action: "安全パトロール報告書が提出されました",
    project: "品川タワー新築工事",
    time: "10分前",
  },
  {
    action: "工程会議議事録の承認依頼",
    project: "横浜分譲マンション",
    time: "32分前",
  },
  {
    action: "コンクリート強度試験結果がアップロードされました",
    project: "大田区土木工事",
    time: "1時間前",
  },
  {
    action: "週間安全サイクルが完了しました",
    project: "新宿再開発ビル",
    time: "2時間前",
  },
  {
    action: "重機稼働データの異常を検知",
    project: "川崎物流センター",
    time: "3時間前",
  },
];

const quickActions = [
  { icon: Plus, label: "新規工事登録" },
  { icon: Search, label: "図面検索" },
  { icon: Users, label: "作業員管理" },
  { icon: Settings, label: "システム設定" },
];

const colorMap: Record<string, { bg: string; text: string; icon: string }> = {
  primary: {
    bg: "bg-primary-50",
    text: "text-primary-600",
    icon: "text-primary-500",
  },
  safety: {
    bg: "bg-safety-50",
    text: "text-safety-700",
    icon: "text-safety-500",
  },
  danger: {
    bg: "bg-danger-50",
    text: "text-danger-700",
    icon: "text-danger-500",
  },
  approve: {
    bg: "bg-approve-50",
    text: "text-approve-700",
    icon: "text-approve-500",
  },
};

export default function DashboardPage() {
  const [dashStats, setDashStats] = useState<DashboardStats>({
    activeProjects: 0,
    pendingApprovals: 0,
    iotAlerts: 0,
    newDocuments: 0,
  });
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.allSettled([
      get<{ total?: number }>("/construction/schedules?per_page=1"),
      get<{ data?: unknown[] }>("/workflow/instances/pending"),
      get<{ data?: { total?: number } }>("/iot/alerts?per_page=1"),
      get<{ data?: { pagination?: { total?: number } } }>(
        "/documents?per_page=1",
      ),
    ]).then(([schedules, workflows, alerts, documents]) => {
      setDashStats({
        activeProjects:
          schedules.status === "fulfilled" && schedules.value?.total != null
            ? schedules.value.total
            : 0,
        pendingApprovals:
          workflows.status === "fulfilled" &&
          Array.isArray(workflows.value?.data)
            ? workflows.value.data.length
            : 0,
        iotAlerts:
          alerts.status === "fulfilled" && alerts.value?.data?.total != null
            ? alerts.value.data.total
            : 0,
        newDocuments:
          documents.status === "fulfilled" &&
          documents.value?.data?.pagination?.total != null
            ? documents.value.data.pagination.total
            : 0,
      });
      const rejected = [schedules, workflows, alerts, documents].filter(
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
    });
  }, []);

  const stats = [
    {
      label: "進行中工事",
      value: String(dashStats.activeProjects),
      icon: ClipboardList,
      trend: "+2 今月",
      trendUp: true,
      color: "primary",
    },
    {
      label: "要承認",
      value: String(dashStats.pendingApprovals),
      icon: CheckSquare,
      trend: "3件 期限切迫",
      trendUp: true,
      color: "safety",
    },
    {
      label: "IoTアラート",
      value: String(dashStats.iotAlerts),
      icon: AlertTriangle,
      trend: "要対応",
      trendUp: false,
      color: "danger",
    },
    {
      label: "新着文書",
      value: String(dashStats.newDocuments),
      icon: FileText,
      trend: "+8 今週",
      trendUp: true,
      color: "approve",
    },
  ];

  return (
    <div className="p-6 lg:p-8 space-y-8">
      {/* Welcome */}
      <div>
        <h1 className="text-2xl font-bold text-gray-900">
          おかえりなさい、田中さん
        </h1>
        <p className="mt-1 text-gray-500">
          本日も安全第一で。現場の状況を確認しましょう。
        </p>
      </div>

      {error && (
        <div role="alert" aria-live="assertive" className="rounded-xl border border-danger-500/30 bg-danger-50 px-4 py-3 text-sm text-danger-700">
          {error}
        </div>
      )}

      {/* Stat Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {stats.map((stat) => {
          const Icon = stat.icon;
          const colors = colorMap[stat.color];
          return (
            <div
              key={stat.label}
              className="rounded-xl border border-gray-200 bg-white p-5 hover:shadow-md transition-shadow"
            >
              <div className="flex items-start justify-between">
                <div className={`rounded-lg p-2.5 ${colors.bg}`}>
                  <Icon className={`h-5 w-5 ${colors.icon}`} />
                </div>
                <ArrowUpRight className="h-4 w-4 text-gray-400" />
              </div>
              <p className="mt-4 text-3xl font-bold text-gray-900">
                {stat.value}
              </p>
              <p className="mt-1 text-sm font-medium text-gray-600">
                {stat.label}
              </p>
              <p
                className={`mt-2 text-xs ${
                  stat.trendUp ? "text-approve-600" : "text-danger-600"
                }`}
              >
                {stat.trend}
              </p>
            </div>
          );
        })}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Activity Feed */}
        <div className="lg:col-span-2 rounded-xl border border-gray-200 bg-white">
          <div className="flex items-center justify-between border-b border-gray-100 px-5 py-4">
            <h2 className="font-bold text-gray-900">最近のアクティビティ</h2>
            <button className="text-sm text-primary-600 hover:text-primary-700 font-medium">
              すべて表示
            </button>
          </div>
          <div className="divide-y divide-gray-100">
            {activities.map((item, i) => (
              <div
                key={i}
                className="px-5 py-4 hover:bg-gray-50 transition-colors"
              >
                <p className="text-sm font-medium text-gray-900">
                  {item.action}
                </p>
                <div className="mt-1 flex items-center gap-2 text-xs text-gray-500">
                  <span>{item.project}</span>
                  <span>•</span>
                  <span>{item.time}</span>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Quick Actions */}
        <div className="rounded-xl border border-gray-200 bg-white p-5">
          <h2 className="font-bold text-gray-900 mb-4">クイックアクション</h2>
          <div className="grid grid-cols-2 gap-3">
            {quickActions.map((action) => {
              const Icon = action.icon;
              return (
                <button
                  key={action.label}
                  className="flex flex-col items-center gap-2 rounded-lg border border-gray-200 p-4 hover:border-primary-300 hover:bg-primary-50/50 transition-colors text-center"
                >
                  <Icon className="h-5 w-5 text-primary-600" />
                  <span className="text-xs font-medium text-gray-700">
                    {action.label}
                  </span>
                </button>
              );
            })}
          </div>

          {/* Safety widget */}
          <div className="mt-5 rounded-lg bg-safety-50 p-4">
            <div className="flex items-center gap-2">
              <AlertTriangle className="h-4 w-4 text-safety-600" />
              <span className="text-sm font-bold text-safety-700">
                熱中症警戒
              </span>
            </div>
            <p className="mt-1 text-xs text-safety-600">
              本日のWBGT予測値: 28°C (厳重警戒)
              <br />
              こまめな水分補給を徹底してください。
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
