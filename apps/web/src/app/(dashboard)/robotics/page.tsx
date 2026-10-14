"use client";

import { useState, useCallback, useEffect } from "react";
import { get, ApiError } from "@/lib/api-client";
import {
  Plane,
  Bot,
  Cpu,
  Globe,
  ArrowRight,
  Activity,
  Clock,
} from "lucide-react";
import Link from "next/link";

interface RoboticsCard {
  id: string;
  title: string;
  description: string;
  href: string;
  icon: React.ReactNode;
  iconBg: string;
  stat: string;
  statLabel: string;
}

interface RecentActivity {
  id: string;
  timestamp: string;
  category: "drone" | "rpa" | "autonomous" | "twin";
  content: string;
  status: "success" | "warning" | "error" | "info";
}

type Activity = {
  id: string;
  time: string;
  type: string;
  message: string;
  severity?: string;
};

const ROBOTICS_CARDS: RoboticsCard[] = [
  {
    id: "drone",
    title: "ドローン測量",
    description:
      "UAVによる空撮・測量データ管理。飛行計画・点群データ・進捗状況をリアルタイムで確認できます。",
    href: "/robotics/drone",
    icon: <Plane className="h-6 w-6" />,
    iconBg: "bg-sky-500",
    stat: "3台",
    statLabel: "フライト中",
  },
  {
    id: "rpa",
    title: "RPA自動化",
    description:
      "業務プロセスの自動化タスク管理。請求書処理・日報集計・承認フローを自動実行します。",
    href: "/robotics/rpa",
    icon: <Bot className="h-6 w-6" />,
    iconBg: "bg-violet-500",
    stat: "8タスク",
    statLabel: "アクティブ",
  },
  {
    id: "autonomous",
    title: "自律施工",
    description:
      "自律施工機器の稼働状況・エラーログ管理。ブルドーザー・ショベル・転圧機の自律運転を監視します。",
    href: "/robotics/autonomous",
    icon: <Cpu className="h-6 w-6" />,
    iconBg: "bg-orange-500",
    stat: "3台",
    statLabel: "稼働中",
  },
  {
    id: "twin",
    title: "デジタルツイン",
    description:
      "建設現場のリアルタイム3Dデジタルツイン。センサーデータと連動して現場の状況を可視化します。",
    href: "/robotics/twin",
    icon: <Globe className="h-6 w-6" />,
    iconBg: "bg-teal-500",
    stat: "4件",
    statLabel: "同期中",
  },
];

const categoryIcon: Record<RecentActivity["category"], React.ReactNode> = {
  drone: <Plane className="h-4 w-4" />,
  rpa: <Bot className="h-4 w-4" />,
  autonomous: <Cpu className="h-4 w-4" />,
  twin: <Globe className="h-4 w-4" />,
};

const categoryBg: Record<RecentActivity["category"], string> = {
  drone: "bg-sky-100 text-sky-600",
  rpa: "bg-violet-100 text-violet-600",
  autonomous: "bg-orange-100 text-orange-600",
  twin: "bg-teal-100 text-teal-600",
};

const activityStatusDot: Record<RecentActivity["status"], string> = {
  success: "bg-green-400",
  warning: "bg-yellow-400",
  error: "bg-red-500",
  info: "bg-blue-400",
};

export default function RoboticsPage() {
  const [activities, setActivities] = useState<Activity[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const json = await get<{
        data?: { items?: Record<string, unknown>[] };
        items?: Record<string, unknown>[];
      }>("/autonomous/activities?per_page=20");
      const items = json?.data?.items ?? json?.items ?? json?.data ?? [];
      setActivities(
        Array.isArray(items)
          ? items.map((item: Record<string, unknown>) => ({
              id: String(item.id ?? ""),
              time: String(item.time ?? item.created_at ?? ""),
              type: String(item.type ?? ""),
              message: String(item.message ?? ""),
              severity: item.severity ? String(item.severity) : undefined,
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

  const getActivityCategory = (type: string): RecentActivity["category"] => {
    if (
      type === "drone" ||
      type === "rpa" ||
      type === "autonomous" ||
      type === "twin"
    ) {
      return type;
    }
    return "autonomous";
  };

  const getActivityStatus = (severity?: string): RecentActivity["status"] => {
    if (
      severity === "success" ||
      severity === "warning" ||
      severity === "error" ||
      severity === "info"
    ) {
      return severity;
    }
    return "info";
  };

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold text-gray-900">
          自動化・ロボティクス
        </h1>
        <p className="mt-1 text-sm text-gray-500">
          ドローン・RPA・自律施工・デジタルツインの統合管理ダッシュボード
        </p>
      </div>

      {error && (
        <div role="alert" aria-live="assertive" className="rounded-xl border border-danger-500/30 bg-danger-50 px-4 py-3 text-sm text-danger-700">
          {error}
        </div>
      )}
      {!loading && !error && activities.length === 0 && (
        <div className="rounded-xl border border-gray-200 bg-white px-4 py-8 text-center text-sm text-gray-500">
          該当データがありません。
        </div>
      )}

      {/* Summary Cards */}
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        <div className="rounded-xl border border-gray-200 bg-white p-4 shadow-sm text-center">
          <div className="mx-auto mb-2 flex h-10 w-10 items-center justify-center rounded-xl bg-sky-50">
            <Plane className="h-5 w-5 text-sky-600" />
          </div>
          <p className="text-2xl font-bold text-gray-900">3</p>
          <p className="text-xs text-gray-500 mt-0.5">フライト中ドローン</p>
        </div>
        <div className="rounded-xl border border-gray-200 bg-white p-4 shadow-sm text-center">
          <div className="mx-auto mb-2 flex h-10 w-10 items-center justify-center rounded-xl bg-violet-50">
            <Activity className="h-5 w-5 text-violet-600" />
          </div>
          <p className="text-2xl font-bold text-gray-900">8</p>
          <p className="text-xs text-gray-500 mt-0.5">アクティブRPAタスク</p>
        </div>
        <div className="rounded-xl border border-gray-200 bg-white p-4 shadow-sm text-center">
          <div className="mx-auto mb-2 flex h-10 w-10 items-center justify-center rounded-xl bg-orange-50">
            <Cpu className="h-5 w-5 text-orange-600" />
          </div>
          <p className="text-2xl font-bold text-gray-900">3</p>
          <p className="text-xs text-gray-500 mt-0.5">稼働中自律機器</p>
        </div>
        <div className="rounded-xl border border-gray-200 bg-white p-4 shadow-sm text-center">
          <div className="mx-auto mb-2 flex h-10 w-10 items-center justify-center rounded-xl bg-teal-50">
            <Globe className="h-5 w-5 text-teal-600" />
          </div>
          <p className="text-2xl font-bold text-gray-900">4</p>
          <p className="text-xs text-gray-500 mt-0.5">同期中ツイン</p>
        </div>
      </div>

      {/* Feature Cards */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        {ROBOTICS_CARDS.map((card) => (
          <Link
            key={card.id}
            href={card.href}
            className="group rounded-xl border border-gray-200 bg-white p-6 shadow-sm hover:shadow-md hover:border-gray-300 transition-all"
          >
            <div className="flex items-start justify-between">
              <div className="flex items-center gap-3">
                <div
                  className={`flex h-11 w-11 items-center justify-center rounded-xl text-white ${card.iconBg}`}
                >
                  {card.icon}
                </div>
                <div>
                  <h3 className="text-base font-semibold text-gray-900 group-hover:text-blue-600 transition-colors">
                    {card.title}
                  </h3>
                  <p className="text-sm font-medium text-gray-500">
                    {card.stat}
                    <span className="ml-1 text-gray-400">{card.statLabel}</span>
                  </p>
                </div>
              </div>
              <ArrowRight className="h-4 w-4 text-gray-400 group-hover:text-blue-500 transition-colors mt-1" />
            </div>
            <p className="mt-3 text-sm text-gray-600 leading-relaxed">
              {card.description}
            </p>
          </Link>
        ))}
      </div>

      {/* Recent Activity */}
      <div className="rounded-xl border border-gray-200 bg-white shadow-sm">
        <div className="flex items-center justify-between border-b border-gray-200 px-6 py-4">
          <div className="flex items-center gap-2">
            <Clock className="h-5 w-5 text-gray-500" />
            <h2 className="text-base font-semibold text-gray-900">
              最近のアクティビティ
            </h2>
          </div>
          <span className="text-sm text-gray-500">
            {loading ? "読み込み中..." : "本日"}
          </span>
        </div>
        <div className="divide-y divide-gray-100">
          {activities.map((activity) => {
            const category = getActivityCategory(activity.type);
            const status = getActivityStatus(activity.severity);
            return (
              <div
                key={activity.id}
                className="flex items-start gap-3 px-6 py-3 hover:bg-gray-50"
              >
                <span className="mt-1 text-xs text-gray-400 tabular-nums w-10 flex-shrink-0">
                  {activity.time}
                </span>
                <div
                  className={`flex h-6 w-6 flex-shrink-0 items-center justify-center rounded-full ${categoryBg[category]}`}
                >
                  {categoryIcon[category]}
                </div>
                <div className="flex-1 min-w-0">
                  <p className="text-sm text-gray-700 leading-relaxed">
                    {activity.message}
                  </p>
                </div>
                <span
                  className={`mt-1.5 h-2 w-2 flex-shrink-0 rounded-full ${activityStatusDot[status]}`}
                />
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
