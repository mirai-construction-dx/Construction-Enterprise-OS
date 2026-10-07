"use client";

import { useState, useCallback, useEffect } from "react";
import { get, ApiError } from "@/lib/api-client";
import {
  Bot,
  Cpu,
  MapPin,
  Activity,
  AlertTriangle,
  CheckCircle,
  Clock,
} from "lucide-react";

interface AutonomousMachine {
  id: string;
  machineNo: string;
  type: "bulldozer" | "excavator" | "compactor";
  area: string;
  autonomousMode: "full" | "semi" | "standby";
  completionRate: number;
  operatingHours: number;
  status: "active" | "idle" | "error" | "charging";
}

interface ErrorLog {
  id: string;
  occurredAt: string;
  machineNo: string;
  errorType: string;
  description: string;
  resolution: "resolved" | "investigating" | "pending";
}

const machineTypeLabel: Record<AutonomousMachine["type"], string> = {
  bulldozer: "自律ブルドーザー",
  excavator: "自律ショベル",
  compactor: "自律転圧",
};

const machineTypeColor: Record<AutonomousMachine["type"], string> = {
  bulldozer: "bg-orange-100 text-orange-700",
  excavator: "bg-blue-100 text-blue-700",
  compactor: "bg-purple-100 text-purple-700",
};

const autonomousModeLabel: Record<AutonomousMachine["autonomousMode"], string> =
  {
    full: "完全自律",
    semi: "半自律",
    standby: "待機",
  };

const autonomousModeStyle: Record<AutonomousMachine["autonomousMode"], string> =
  {
    full: "bg-green-100 text-green-700 border-green-200",
    semi: "bg-blue-100 text-blue-700 border-blue-200",
    standby: "bg-gray-100 text-gray-600 border-gray-200",
  };

const machineStatusStyle: Record<
  AutonomousMachine["status"],
  { label: string; dot: string }
> = {
  active: { label: "稼働中", dot: "bg-green-500" },
  idle: { label: "待機中", dot: "bg-yellow-400" },
  error: { label: "エラー", dot: "bg-red-500" },
  charging: { label: "充電中", dot: "bg-blue-400" },
};

const resolutionStyle: Record<
  ErrorLog["resolution"],
  { label: string; className: string }
> = {
  resolved: { label: "対処済", className: "bg-green-100 text-green-700" },
  investigating: {
    label: "調査中",
    className: "bg-yellow-100 text-yellow-700",
  },
  pending: { label: "未対処", className: "bg-red-100 text-red-700" },
};

export default function AutonomousPage() {
  const [machines, setMachines] = useState<AutonomousMachine[]>([]);
  const [errorLogs, setErrorLogs] = useState<ErrorLog[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const [machinesResult, errorLogsResult] = await Promise.allSettled([
        get<{
          data?: { items?: Record<string, unknown>[] };
          items?: Record<string, unknown>[];
        }>("/autonomous/machines?per_page=50"),
        get<{
          data?: { items?: Record<string, unknown>[] };
          items?: Record<string, unknown>[];
        }>("/autonomous/error-logs?per_page=50"),
      ]);

      if (machinesResult.status === "fulfilled") {
        const json = machinesResult.value;
        const items: Record<string, unknown>[] =
          json?.data?.items ?? json?.items ?? [];
        setMachines(
          Array.isArray(items)
            ? items.map(
                (item: Record<string, unknown>): AutonomousMachine => ({
                  id: String(item.id ?? ""),
                  machineNo: String(item.machineNo ?? item.machine_no ?? ""),
                  type: String(
                    item.type ?? "bulldozer",
                  ) as AutonomousMachine["type"],
                  area: String(item.area ?? ""),
                  autonomousMode: String(
                    item.autonomousMode ?? item.autonomous_mode ?? "standby",
                  ) as AutonomousMachine["autonomousMode"],
                  completionRate: Number(
                    item.completionRate ?? item.completion_rate ?? 0,
                  ),
                  operatingHours: Number(
                    item.operatingHours ?? item.operating_hours ?? 0,
                  ),
                  status: String(
                    item.status ?? "idle",
                  ) as AutonomousMachine["status"],
                }),
              )
            : [],
        );
      }

      if (errorLogsResult.status === "fulfilled") {
        const json = errorLogsResult.value;
        const items: Record<string, unknown>[] =
          json?.data?.items ?? json?.items ?? [];
        setErrorLogs(
          Array.isArray(items)
            ? items.map(
                (item: Record<string, unknown>): ErrorLog => ({
                  id: String(item.id ?? ""),
                  occurredAt: String(item.occurredAt ?? item.occurred_at ?? ""),
                  machineNo: String(item.machineNo ?? item.machine_no ?? ""),
                  errorType: String(item.errorType ?? item.error_type ?? ""),
                  description: String(item.description ?? ""),
                  resolution: String(
                    item.resolution ?? "pending",
                  ) as ErrorLog["resolution"],
                }),
              )
            : [],
        );
      }

      const rejected = [machinesResult, errorLogsResult].filter(
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

  const activeMachines = machines.filter((m) => m.status === "active").length;
  const totalArea = 18420;
  const totalOperatingHours = machines.reduce(
    (s, m) => s + m.operatingHours,
    0,
  );
  const unresolvedErrors = errorLogs.filter(
    (e) => e.resolution !== "resolved",
  ).length;

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">自律施工</h1>
          <p className="mt-1 text-sm text-gray-500">
            自律施工機器の稼働状況・エラーログを管理します
          </p>
        </div>
      </div>

      {error && (
        <div role="alert" aria-live="assertive" className="rounded-xl border border-danger-500/30 bg-danger-50 px-4 py-3 text-sm text-danger-700">
          {error}
        </div>
      )}
      {!loading &&
        !error &&
        machines.length === 0 &&
        errorLogs.length === 0 && (
          <div className="rounded-xl border border-gray-200 bg-white px-4 py-8 text-center text-sm text-gray-500">
            該当データがありません。
          </div>
        )}

      {/* Stats */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <div className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm font-medium text-gray-500">稼働中台数</p>
              <p className="mt-1 text-3xl font-bold text-gray-900">
                {loading ? "—" : activeMachines}
                <span className="ml-1 text-lg font-medium text-gray-500">
                  台
                </span>
              </p>
            </div>
            <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-green-50">
              <Bot className="h-6 w-6 text-green-600" />
            </div>
          </div>
          <p className="mt-2 text-xs text-gray-400">全{machines.length}台中</p>
        </div>

        <div className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm font-medium text-gray-500">自律完了面積</p>
              <p className="mt-1 text-3xl font-bold text-gray-900">
                {totalArea.toLocaleString()}
                <span className="ml-1 text-lg font-medium text-gray-500">
                  m²
                </span>
              </p>
            </div>
            <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-blue-50">
              <MapPin className="h-6 w-6 text-blue-600" />
            </div>
          </div>
          <p className="mt-2 text-xs text-gray-400">本日累計</p>
        </div>

        <div className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm font-medium text-gray-500">
                今日の稼働時間
              </p>
              <p className="mt-1 text-3xl font-bold text-gray-900">
                {loading ? "—" : totalOperatingHours.toFixed(1)}
                <span className="ml-1 text-lg font-medium text-gray-500">
                  h
                </span>
              </p>
            </div>
            <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-purple-50">
              <Clock className="h-6 w-6 text-purple-600" />
            </div>
          </div>
          <p className="mt-2 text-xs text-gray-400">全機器合計</p>
        </div>

        <div className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm font-medium text-gray-500">エラー件数</p>
              <p className="mt-1 text-3xl font-bold text-gray-900">
                {loading ? "—" : unresolvedErrors}
                <span className="ml-1 text-lg font-medium text-gray-500">
                  件
                </span>
              </p>
            </div>
            <div
              className={`flex h-12 w-12 items-center justify-center rounded-xl ${unresolvedErrors > 0 ? "bg-red-50" : "bg-green-50"}`}
            >
              <Activity
                className={`h-6 w-6 ${unresolvedErrors > 0 ? "text-red-600" : "text-green-600"}`}
              />
            </div>
          </div>
          <p className="mt-2 text-xs text-gray-400">未対処エラー</p>
        </div>
      </div>

      {/* Machine Table */}
      <div className="rounded-xl border border-gray-200 bg-white shadow-sm">
        <div className="flex items-center justify-between border-b border-gray-200 px-6 py-4">
          <div className="flex items-center gap-2">
            <Cpu className="h-5 w-5 text-gray-500" />
            <h2 className="text-base font-semibold text-gray-900">
              自律施工機器一覧
            </h2>
          </div>
          <span className="text-sm text-gray-500">全{machines.length}台</span>
        </div>
        <div className="overflow-x-auto">
          <table className="min-w-full divide-y divide-gray-200">
            <thead className="bg-gray-50">
              <tr>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">
                  機番
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">
                  機種
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">
                  稼働エリア
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">
                  自律モード
                </th>
                <th className="px-4 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">
                  完了率
                </th>
                <th className="px-4 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">
                  稼働時間
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">
                  状態
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100 bg-white">
              {machines.map((machine) => {
                const statusInfo = machineStatusStyle[machine.status];
                return (
                  <tr key={machine.id} className="hover:bg-gray-50">
                    <td className="px-4 py-3">
                      <p className="text-sm font-mono font-medium text-gray-900">
                        {machine.machineNo}
                      </p>
                    </td>
                    <td className="px-4 py-3">
                      <span
                        className={`inline-flex items-center rounded-full px-2.5 py-1 text-xs font-medium ${machineTypeColor[machine.type]}`}
                      >
                        {machineTypeLabel[machine.type]}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-1.5">
                        <MapPin className="h-3.5 w-3.5 text-gray-400 flex-shrink-0" />
                        <span className="text-sm text-gray-700">
                          {machine.area}
                        </span>
                      </div>
                    </td>
                    <td className="px-4 py-3">
                      <span
                        className={`inline-flex items-center rounded-full border px-2.5 py-1 text-xs font-medium ${autonomousModeStyle[machine.autonomousMode]}`}
                      >
                        {autonomousModeLabel[machine.autonomousMode]}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex items-center justify-end gap-2">
                        <div className="w-20 overflow-hidden rounded-full bg-gray-200">
                          <div
                            className={`h-1.5 rounded-full ${machine.completionRate >= 80 ? "bg-green-500" : machine.completionRate >= 50 ? "bg-blue-500" : "bg-yellow-500"}`}
                            style={{ width: `${machine.completionRate}%` }}
                          />
                        </div>
                        <span className="w-10 text-right text-sm font-medium tabular-nums text-gray-700">
                          {machine.completionRate}%
                        </span>
                      </div>
                    </td>
                    <td className="px-4 py-3 text-right">
                      <span className="text-sm font-medium text-gray-700 tabular-nums">
                        {machine.operatingHours.toFixed(1)}h
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-1.5">
                        <span
                          className={`h-2 w-2 rounded-full ${statusInfo.dot}`}
                        />
                        <span className="text-sm text-gray-700">
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

      {/* Error Log */}
      <div className="rounded-xl border border-gray-200 bg-white shadow-sm">
        <div className="flex items-center justify-between border-b border-gray-200 px-6 py-4">
          <div className="flex items-center gap-2">
            <AlertTriangle className="h-5 w-5 text-gray-500" />
            <h2 className="text-base font-semibold text-gray-900">
              エラーログ
            </h2>
          </div>
          <span className="text-sm text-gray-500">
            直近{errorLogs.length}件
          </span>
        </div>
        <div className="overflow-x-auto">
          <table className="min-w-full divide-y divide-gray-200">
            <thead className="bg-gray-50">
              <tr>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">
                  発生日時
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">
                  機番
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">
                  エラー種別
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">
                  内容
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">
                  対処状況
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100 bg-white">
              {errorLogs.map((log) => {
                const res = resolutionStyle[log.resolution];
                return (
                  <tr key={log.id} className="hover:bg-gray-50">
                    <td className="px-4 py-3 text-sm text-gray-500 whitespace-nowrap">
                      {log.occurredAt}
                    </td>
                    <td className="px-4 py-3 text-sm font-mono font-medium text-gray-900">
                      {log.machineNo}
                    </td>
                    <td className="px-4 py-3">
                      <span className="text-sm font-medium text-gray-800">
                        {log.errorType}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-sm text-gray-600">
                      {log.description}
                    </td>
                    <td className="px-4 py-3">
                      <span
                        className={`inline-flex items-center rounded-full px-2.5 py-1 text-xs font-medium ${res.className}`}
                      >
                        {log.resolution === "resolved" && (
                          <CheckCircle className="mr-1 h-3.5 w-3.5" />
                        )}
                        {log.resolution === "pending" && (
                          <AlertTriangle className="mr-1 h-3.5 w-3.5" />
                        )}
                        {res.label}
                      </span>
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
