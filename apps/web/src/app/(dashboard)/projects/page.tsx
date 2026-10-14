"use client";

import { useState, useEffect } from "react";
import {
  ClipboardList,
  MapPin,
  Calendar,
  Users,
  TrendingUp,
  AlertTriangle,
  CheckCircle,
  Clock,
  Plus,
  Search,
  Filter,
  MoreVertical,
} from "lucide-react";
import { get, ApiError } from "@/lib/api-client";

// Mock data (fallback)

interface Project {
  id: number;
  name: string;
  code: string;
  location: string;
  status: string;
  progress: number;
  startDate: string;
  endDate: string;
  manager: string;
  workers: number;
  budget: string;
  spent: string;
  alerts: number;
}

const statusConfig = {
  active: {
    label: "施工中",
    className: "bg-approve-50 text-approve-700",
    icon: CheckCircle,
  },
  planning: {
    label: "計画中",
    className: "bg-primary-50 text-primary-700",
    icon: Clock,
  },
  delayed: {
    label: "遅延",
    className: "bg-danger-50 text-danger-700",
    icon: AlertTriangle,
  },
  completed: {
    label: "完工",
    className: "bg-concrete-50 text-concrete-600",
    icon: CheckCircle,
  },
};

export default function ProjectsPage() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setIsLoading(true);
    get<{
      items?: {
        id: string;
        name: string;
        status?: string;
        progress?: number;
        start_date?: string;
        end_date?: string;
      }[];
    }>("/construction/schedules?per_page=20")
      .then((data) => {
        const items = data?.items;
        setProjects(
          Array.isArray(items)
            ? items.map((s, i) => ({
                id: i + 1,
                name: s.name,
                code: s.id.slice(0, 12).toUpperCase(),
                location: "—",
                status: s.status ?? "active",
                progress: s.progress ?? 0,
                startDate: s.start_date ?? "—",
                endDate: s.end_date ?? "—",
                manager: "—",
                workers: 0,
                budget: "—",
                spent: "—",
                alerts: 0,
              }))
            : [],
        );
        setError(null);
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

  const summaryStats = [
    {
      label: "総工事数",
      value: String(projects.length),
      icon: ClipboardList,
      color: "primary",
    },
    {
      label: "施工中",
      value: String(projects.filter((p) => p.status === "active").length),
      icon: TrendingUp,
      color: "approve",
    },
    {
      label: "遅延中",
      value: String(projects.filter((p) => p.status === "delayed").length),
      icon: AlertTriangle,
      color: "danger",
    },
    {
      label: "総作業員",
      value: String(projects.reduce((s, p) => s + p.workers, 0)),
      icon: Users,
      color: "safety",
    },
  ];

  return (
    <div className="p-6 lg:p-8 space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">工事管理</h1>
          <p className="mt-1 text-gray-500 text-sm">
            進行中・計画中の全工事案件を管理します
          </p>
        </div>
        <button className="inline-flex items-center gap-2 rounded-lg bg-primary-600 px-4 py-2.5 text-sm font-semibold text-white hover:bg-primary-700 transition-colors">
          <Plus className="h-4 w-4" />
          新規工事登録
        </button>
      </div>

      {/* Summary Stats */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        {summaryStats.map((stat) => {
          const Icon = stat.icon;
          return (
            <div
              key={stat.label}
              className="rounded-xl border border-gray-200 bg-white p-4"
            >
              <div className="flex items-center gap-3">
                <div className={`rounded-lg p-2 bg-${stat.color}-50`}>
                  <Icon className={`h-5 w-5 text-${stat.color}-600`} />
                </div>
                <div>
                  <p className="text-2xl font-bold text-gray-900">
                    {stat.value}
                  </p>
                  <p className="text-xs text-gray-500">{stat.label}</p>
                </div>
              </div>
            </div>
          );
        })}
      </div>

      {/* Search and Filter */}
      <div className="flex flex-col sm:flex-row gap-3">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-400" />
          <input
            type="text"
            placeholder="工事名・コード・場所で検索..."
            className="w-full rounded-lg border border-gray-200 bg-white pl-10 pr-4 py-2.5 text-sm focus:border-primary-500 focus:outline-none focus:ring-2 focus:ring-primary-500/20"
          />
        </div>
        <button className="inline-flex items-center gap-2 rounded-lg border border-gray-200 bg-white px-4 py-2.5 text-sm font-medium text-gray-700 hover:bg-gray-50 transition-colors">
          <Filter className="h-4 w-4" />
          フィルター
        </button>
      </div>

      {error && (
        <div role="alert" aria-live="assertive" className="rounded-xl border border-danger-500/30 bg-danger-50 px-4 py-3 text-sm text-danger-700">
          {error}
        </div>
      )}
      {!isLoading && !error && projects.length === 0 && (
        <div className="rounded-xl border border-gray-200 bg-white px-4 py-8 text-center text-sm text-gray-500">
          該当データがありません。
        </div>
      )}

      {/* Project Table */}
      <div className="overflow-hidden rounded-xl border border-gray-200 bg-white">
        <table className="min-w-full divide-y divide-gray-100">
          <thead>
            <tr className="bg-gray-50">
              <th className="px-5 py-3.5 text-left text-xs font-semibold text-gray-500 uppercase tracking-wide">
                工事名
              </th>
              <th className="hidden md:table-cell px-5 py-3.5 text-left text-xs font-semibold text-gray-500 uppercase tracking-wide">
                所在地
              </th>
              <th className="px-5 py-3.5 text-left text-xs font-semibold text-gray-500 uppercase tracking-wide">
                ステータス
              </th>
              <th className="hidden lg:table-cell px-5 py-3.5 text-left text-xs font-semibold text-gray-500 uppercase tracking-wide">
                進捗
              </th>
              <th className="hidden lg:table-cell px-5 py-3.5 text-left text-xs font-semibold text-gray-500 uppercase tracking-wide">
                担当
              </th>
              <th className="hidden xl:table-cell px-5 py-3.5 text-left text-xs font-semibold text-gray-500 uppercase tracking-wide">
                工期
              </th>
              <th className="px-5 py-3.5 text-left text-xs font-semibold text-gray-500 uppercase tracking-wide">
                予算
              </th>
              <th className="px-5 py-3.5"></th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {projects.map((project) => {
              const status =
                statusConfig[project.status as keyof typeof statusConfig];
              const StatusIcon = status.icon;
              return (
                <tr
                  key={project.id}
                  className="hover:bg-gray-50 transition-colors"
                >
                  <td className="px-5 py-4">
                    <div>
                      <p className="font-semibold text-gray-900 text-sm">
                        {project.name}
                      </p>
                      <p className="text-xs text-gray-400 mt-0.5">
                        {project.code}
                      </p>
                    </div>
                  </td>
                  <td className="hidden md:table-cell px-5 py-4">
                    <div className="flex items-center gap-1.5 text-sm text-gray-600">
                      <MapPin className="h-3.5 w-3.5 text-gray-400 flex-shrink-0" />
                      {project.location}
                    </div>
                  </td>
                  <td className="px-5 py-4">
                    <span
                      className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium ${status.className}`}
                    >
                      <StatusIcon className="h-3 w-3" />
                      {status.label}
                      {project.alerts > 0 && (
                        <span className="ml-1 rounded-full bg-danger-500 text-white text-[10px] px-1.5">
                          {project.alerts}
                        </span>
                      )}
                    </span>
                  </td>
                  <td className="hidden lg:table-cell px-5 py-4">
                    <div className="flex items-center gap-3">
                      <div className="flex-1 h-1.5 rounded-full bg-gray-100 min-w-[80px]">
                        <div
                          className={`h-full rounded-full ${
                            project.status === "delayed"
                              ? "bg-danger-500"
                              : project.status === "completed"
                                ? "bg-concrete-400"
                                : "bg-primary-500"
                          }`}
                          style={{ width: `${project.progress}%` }}
                        />
                      </div>
                      <span className="text-xs font-medium text-gray-600 w-8 text-right">
                        {project.progress}%
                      </span>
                    </div>
                  </td>
                  <td className="hidden lg:table-cell px-5 py-4">
                    <div className="flex items-center gap-1.5 text-sm text-gray-600">
                      <Users className="h-3.5 w-3.5 text-gray-400" />
                      <span>{project.manager}</span>
                    </div>
                  </td>
                  <td className="hidden xl:table-cell px-5 py-4">
                    <div className="flex items-center gap-1 text-xs text-gray-500">
                      <Calendar className="h-3.5 w-3.5 text-gray-400" />
                      <span>
                        {project.startDate}〜{project.endDate}
                      </span>
                    </div>
                  </td>
                  <td className="px-5 py-4">
                    <div>
                      <p className="text-sm font-semibold text-gray-900">
                        {project.spent}
                      </p>
                      <p className="text-xs text-gray-400">/{project.budget}</p>
                    </div>
                  </td>
                  <td className="px-5 py-4">
                    <button className="text-gray-400 hover:text-gray-600 transition-colors">
                      <MoreVertical className="h-4 w-4" />
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {/* Pagination */}
      <div className="flex items-center justify-between text-sm text-gray-500">
        <span>全 {projects.length} 件</span>
        <div className="flex gap-1">
          <button
            className="rounded-lg border border-gray-200 px-3 py-1.5 hover:bg-gray-50 transition-colors disabled:opacity-50"
            disabled
          >
            前へ
          </button>
          <button className="rounded-lg border border-primary-500 bg-primary-50 text-primary-700 px-3 py-1.5 font-medium">
            1
          </button>
          <button className="rounded-lg border border-gray-200 px-3 py-1.5 hover:bg-gray-50 transition-colors">
            次へ
          </button>
        </div>
      </div>
    </div>
  );
}
