"use client";

import { useState, useEffect, useCallback } from "react";
import {
  GitBranch,
  CheckCircle,
  Clock,
  XCircle,
  AlertCircle,
  Plus,
  Search,
  Filter,
  ChevronRight,
  User,
  Calendar,
  FileText,
} from "lucide-react";
import { get, post, ApiError } from "@/lib/api-client";

// Mock data (fallback)

interface WorkflowStep {
  label: string;
  status: string;
  assignee: string | null;
  completedAt: string | null;
}

interface Workflow {
  id: string;
  title: string;
  type: string;
  status: string;
  priority: string;
  createdAt: string;
  dueDate: string;
  requester: string;
  project: string;
  currentStep: number;
  steps: WorkflowStep[];
}

const workflowTypeConfig: Record<string, { label: string; className: string }> =
  {
    document_approval: {
      label: "書類承認",
      className: "bg-primary-50 text-primary-700",
    },
    inspection: { label: "検査申請", className: "bg-site-50 text-site-700" },
    safety: { label: "安全管理", className: "bg-safety-50 text-safety-700" },
    purchase: {
      label: "購買申請",
      className: "bg-approve-50 text-approve-700",
    },
  };

const statusConfig: Record<
  string,
  { label: string; className: string; icon: React.ElementType }
> = {
  draft: {
    label: "下書き",
    className: "bg-concrete-50 text-concrete-600",
    icon: FileText,
  },
  in_progress: {
    label: "承認中",
    className: "bg-primary-50 text-primary-700",
    icon: Clock,
  },
  pending_approval: {
    label: "承認待ち",
    className: "bg-safety-50 text-safety-700",
    icon: AlertCircle,
  },
  approved: {
    label: "承認済",
    className: "bg-approve-50 text-approve-700",
    icon: CheckCircle,
  },
  rejected: {
    label: "差戻し",
    className: "bg-danger-50 text-danger-700",
    icon: XCircle,
  },
};

const priorityConfig: Record<string, { label: string; className: string }> = {
  critical: { label: "緊急", className: "bg-danger-500 text-white" },
  high: { label: "高", className: "bg-safety-100 text-safety-700" },
  medium: { label: "中", className: "bg-concrete-100 text-concrete-600" },
  low: { label: "低", className: "bg-gray-100 text-gray-500" },
};

const stepStatusConfig: Record<string, string> = {
  done: "bg-approve-500 text-white border-approve-500",
  active: "bg-primary-600 text-white border-primary-600 animate-pulse",
  pending: "bg-white text-gray-400 border-gray-200",
  rejected: "bg-danger-500 text-white border-danger-500",
};

export default function WorkflowsPage() {
  const [workflows, setWorkflows] = useState<Workflow[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [actionLoading, setActionLoading] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const loadWorkflows = useCallback(() => {
    setIsLoading(true);
    get<{
      success?: boolean;
      data?: {
        id: string;
        title?: string;
        workflow_type?: string;
        status: string;
        priority?: string;
        created_at: string;
        due_date?: string | null;
        requester_id?: string;
        project_id?: string;
        current_step?: number;
        steps?: WorkflowStep[];
      }[];
    }>("/workflow/instances?per_page=20")
      .then((data) => {
        setWorkflows(
          data?.success && Array.isArray(data?.data)
            ? data.data.map((w) => ({
                id: w.id,
                title: w.title ?? w.id,
                type: w.workflow_type ?? "document_approval",
                status: w.status,
                priority: w.priority ?? "medium",
                createdAt: w.created_at.slice(0, 10),
                dueDate: w.due_date?.slice(0, 10) ?? "—",
                requester: w.requester_id ?? "—",
                project: w.project_id ?? "—",
                currentStep: w.current_step ?? 0,
                steps: w.steps ?? [],
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

  useEffect(() => {
    loadWorkflows();
  }, [loadWorkflows]);

  const handleApprove = async (id: string) => {
    setActionLoading(id);
    try {
      await post<unknown>(`/workflow/instances/${id}/approve`, {});
    } catch (err) {
      setError(
        err instanceof ApiError && err.status === 403
          ? "権限がありません。"
          : "操作に失敗しました。",
      );
    }
    loadWorkflows();
    setActionLoading(null);
  };

  const handleReject = async (id: string) => {
    setActionLoading(id);
    try {
      await post<unknown>(`/workflow/instances/${id}/reject`, {});
    } catch (err) {
      setError(
        err instanceof ApiError && err.status === 403
          ? "権限がありません。"
          : "操作に失敗しました。",
      );
    }
    loadWorkflows();
    setActionLoading(null);
  };

  const summaryStats = [
    {
      label: "承認待ち",
      value: workflows.filter((w) => w.status === "pending_approval").length,
      color: "safety",
    },
    {
      label: "進行中",
      value: workflows.filter((w) => w.status === "in_progress").length,
      color: "primary",
    },
    {
      label: "本日承認済",
      value: workflows.filter((w) => w.status === "approved").length,
      color: "approve",
    },
    {
      label: "差戻し",
      value: workflows.filter((w) => w.status === "rejected").length,
      color: "danger",
    },
  ];

  return (
    <div className="p-6 lg:p-8 space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">ワークフロー</h1>
          <p className="mt-1 text-gray-500 text-sm">
            書類承認・検査申請・安全管理の承認フロー管理
          </p>
        </div>
        <button className="inline-flex items-center gap-2 rounded-lg bg-primary-600 px-4 py-2.5 text-sm font-semibold text-white hover:bg-primary-700 transition-colors">
          <Plus className="h-4 w-4" />
          新規申請
        </button>
      </div>

      {error && (
        <div role="alert" aria-live="assertive" className="rounded-xl border border-danger-500/30 bg-danger-50 px-4 py-3 text-sm text-danger-700">
          {error}
        </div>
      )}
      {!isLoading && !error && workflows.length === 0 && (
        <div className="rounded-xl border border-gray-200 bg-white px-4 py-8 text-center text-sm text-gray-500">
          該当データがありません。
        </div>
      )}

      {/* Summary Stats */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        {summaryStats.map((stat) => (
          <div
            key={stat.label}
            className={`rounded-xl border p-4 ${
              stat.color === "danger"
                ? "border-danger-200 bg-danger-50"
                : stat.color === "safety"
                  ? "border-safety-200 bg-safety-50"
                  : "border-gray-200 bg-white"
            }`}
          >
            <p
              className={`text-3xl font-bold ${
                stat.color === "danger"
                  ? "text-danger-700"
                  : stat.color === "safety"
                    ? "text-safety-700"
                    : stat.color === "primary"
                      ? "text-primary-700"
                      : "text-approve-700"
              }`}
            >
              {stat.value}
            </p>
            <p className="text-xs text-gray-500 mt-1">{stat.label}</p>
          </div>
        ))}
      </div>

      {/* Search and Filter */}
      <div className="flex flex-col sm:flex-row gap-3">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-400" />
          <input
            type="text"
            placeholder="ワークフロー番号・タイトル・申請者で検索..."
            className="w-full rounded-lg border border-gray-200 bg-white pl-10 pr-4 py-2.5 text-sm focus:border-primary-500 focus:outline-none focus:ring-2 focus:ring-primary-500/20"
          />
        </div>
        <button className="inline-flex items-center gap-2 rounded-lg border border-gray-200 bg-white px-4 py-2.5 text-sm font-medium text-gray-700 hover:bg-gray-50 transition-colors">
          <Filter className="h-4 w-4" />
          フィルター
        </button>
      </div>

      {/* Workflow List */}
      <div className="space-y-4">
        {workflows.map((wf) => {
          const status = statusConfig[wf.status];
          const StatusIcon = status.icon;
          const type =
            workflowTypeConfig[wf.type] || workflowTypeConfig.document_approval;
          const priority = priorityConfig[wf.priority];

          return (
            <div
              key={wf.id}
              className="rounded-xl border border-gray-200 bg-white overflow-hidden hover:shadow-sm transition-shadow"
            >
              {/* Header Row */}
              <div className="flex items-start gap-4 p-5 border-b border-gray-100">
                <div className="flex-1 min-w-0">
                  <div className="flex flex-wrap items-center gap-2 mb-1.5">
                    <span className="text-xs font-mono text-gray-400">
                      {wf.id}
                    </span>
                    <span
                      className={`rounded-full px-2 py-0.5 text-xs font-medium ${type.className}`}
                    >
                      {type.label}
                    </span>
                    <span
                      className={`rounded-full px-2 py-0.5 text-xs font-medium ${priority.className}`}
                    >
                      {priority.label}
                    </span>
                  </div>
                  <h3 className="font-semibold text-gray-900 text-sm truncate">
                    {wf.title}
                  </h3>
                  <div className="flex flex-wrap items-center gap-4 mt-1.5 text-xs text-gray-500">
                    <span className="flex items-center gap-1">
                      <User className="h-3 w-3" />
                      {wf.requester}
                    </span>
                    <span className="flex items-center gap-1">
                      <GitBranch className="h-3 w-3" />
                      {wf.project}
                    </span>
                    <span className="flex items-center gap-1">
                      <Calendar className="h-3 w-3" />
                      期限: {wf.dueDate}
                    </span>
                  </div>
                </div>
                <div className="flex items-center gap-2 flex-shrink-0">
                  {(wf.status === "pending_approval" ||
                    wf.status === "in_progress") && (
                    <>
                      <button
                        onClick={() => handleApprove(wf.id)}
                        disabled={actionLoading === wf.id || isLoading}
                        className="inline-flex items-center gap-1 rounded-lg bg-approve-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-approve-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                      >
                        <CheckCircle className="h-3.5 w-3.5" />
                        承認
                      </button>
                      <button
                        onClick={() => handleReject(wf.id)}
                        disabled={actionLoading === wf.id || isLoading}
                        className="inline-flex items-center gap-1 rounded-lg border border-danger-300 px-3 py-1.5 text-xs font-semibold text-danger-700 hover:bg-danger-50 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                      >
                        <XCircle className="h-3.5 w-3.5" />
                        差戻し
                      </button>
                    </>
                  )}
                  <span
                    className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium ${status.className}`}
                  >
                    <StatusIcon className="h-3 w-3" />
                    {status.label}
                  </span>
                  <button className="text-gray-400 hover:text-gray-600 transition-colors">
                    <ChevronRight className="h-4 w-4" />
                  </button>
                </div>
              </div>

              {/* Steps */}
              <div className="px-5 py-4 bg-gray-50">
                <div className="flex items-center gap-0">
                  {wf.steps.map((step, idx) => (
                    <div key={idx} className="flex items-center flex-1 min-w-0">
                      <div className="flex flex-col items-center gap-1">
                        <div
                          className={`flex h-7 w-7 flex-shrink-0 items-center justify-center rounded-full border-2 text-xs font-bold ${stepStatusConfig[step.status]}`}
                        >
                          {step.status === "done" ? (
                            <CheckCircle className="h-4 w-4" />
                          ) : step.status === "rejected" ? (
                            <XCircle className="h-4 w-4" />
                          ) : (
                            idx + 1
                          )}
                        </div>
                        <p className="text-[10px] text-gray-500 whitespace-nowrap">
                          {step.label}
                        </p>
                        {step.assignee && (
                          <p className="text-[10px] text-gray-400 whitespace-nowrap hidden sm:block">
                            {step.assignee}
                          </p>
                        )}
                      </div>
                      {idx < wf.steps.length - 1 && (
                        <div
                          className={`flex-1 h-0.5 mx-1 mb-5 ${
                            wf.steps[idx + 1].status !== "pending"
                              ? "bg-approve-300"
                              : "bg-gray-200"
                          }`}
                        />
                      )}
                    </div>
                  ))}
                </div>
              </div>
            </div>
          );
        })}
      </div>

      {/* Pagination */}
      <div className="flex items-center justify-between text-sm text-gray-500">
        <span>全 {workflows.length} 件</span>
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
