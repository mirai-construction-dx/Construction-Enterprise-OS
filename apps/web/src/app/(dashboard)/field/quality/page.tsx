"use client";

import { useState, useEffect, useCallback } from "react";
import { get, ApiError } from "@/lib/api-client";
import {
  CheckSquare,
  XSquare,
  ClipboardCheck,
  AlertTriangle,
  Clock,
  Plus,
  RefreshCw,
  ChevronDown,
  ChevronRight,
} from "lucide-react";

type Judgment = "pass" | "fail" | "pending";

interface CheckItem {
  id: string;
  name: string;
  judgment: Judgment;
  inspector: string | null;
  inspected_at: string | null;
  note: string | null;
}

interface CheckCategory {
  id: string;
  category: string;
  items: CheckItem[];
}

interface CorrectiveAction {
  id: string;
  item_name: string;
  category: string;
  issue: string;
  assignee: string;
  due_date: string;
  status: "open" | "in_progress" | "resolved";
}

const judgmentStyle: Record<
  Judgment,
  { label: string; className: string; icon: React.ElementType }
> = {
  pass: {
    label: "合格",
    className: "bg-green-50 text-green-700",
    icon: CheckSquare,
  },
  fail: { label: "不合格", className: "bg-red-50 text-red-700", icon: XSquare },
  pending: {
    label: "未検査",
    className: "bg-gray-100 text-gray-500",
    icon: Clock,
  },
};

const correctiveStatusStyle: Record<
  string,
  { label: string; className: string }
> = {
  open: { label: "未対応", className: "bg-red-100 text-red-700" },
  in_progress: { label: "対応中", className: "bg-orange-100 text-orange-700" },
  resolved: { label: "解決済", className: "bg-green-100 text-green-700" },
};

function CategorySection({ category }: { category: CheckCategory }) {
  const [expanded, setExpanded] = useState(true);
  const passCount = category.items.filter((i) => i.judgment === "pass").length;
  const failCount = category.items.filter((i) => i.judgment === "fail").length;
  const pendingCount = category.items.filter(
    (i) => i.judgment === "pending",
  ).length;

  return (
    <div className="rounded-xl border border-gray-200 bg-white overflow-hidden">
      <button
        onClick={() => setExpanded((v) => !v)}
        className="w-full flex items-center justify-between px-5 py-4 border-b border-gray-100 hover:bg-gray-50 transition-colors text-left"
      >
        <div className="flex items-center gap-3">
          {expanded ? (
            <ChevronDown className="h-4 w-4 text-gray-400" />
          ) : (
            <ChevronRight className="h-4 w-4 text-gray-400" />
          )}
          <h3 className="font-bold text-gray-900">{category.category}</h3>
        </div>
        <div className="flex items-center gap-3 text-xs">
          <span className="inline-flex items-center gap-1 text-green-600">
            <CheckSquare className="h-3.5 w-3.5" />
            合格 {passCount}
          </span>
          {failCount > 0 && (
            <span className="inline-flex items-center gap-1 text-red-600">
              <XSquare className="h-3.5 w-3.5" />
              不合格 {failCount}
            </span>
          )}
          {pendingCount > 0 && (
            <span className="inline-flex items-center gap-1 text-gray-400">
              <Clock className="h-3.5 w-3.5" />
              未検査 {pendingCount}
            </span>
          )}
        </div>
      </button>
      {expanded && (
        <div className="divide-y divide-gray-100">
          {category.items.map((item) => {
            const jd = judgmentStyle[item.judgment];
            const JIcon = jd.icon;
            return (
              <div
                key={item.id}
                className="px-5 py-3.5 hover:bg-gray-50 transition-colors"
              >
                <div className="flex items-start justify-between gap-4">
                  <div className="flex-1 min-w-0">
                    <p className="text-sm text-gray-900">{item.name}</p>
                    {item.note && (
                      <p className="mt-0.5 text-xs text-gray-400">
                        {item.note}
                      </p>
                    )}
                    {item.inspector && item.inspected_at && (
                      <p className="mt-0.5 text-xs text-gray-400">
                        検査: {item.inspector} / {item.inspected_at}
                      </p>
                    )}
                  </div>
                  <span
                    className={`flex-shrink-0 inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-medium ${jd.className}`}
                  >
                    <JIcon className="h-3 w-3" />
                    {jd.label}
                  </span>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

export default function FieldQualityPage() {
  const [categories, setCategories] = useState<CheckCategory[]>([]);
  const [corrective, setCorrective] = useState<CorrectiveAction[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const [catRes, caRes] = await Promise.allSettled([
        get<{ data?: CheckCategory[] }>("/field/quality/checks"),
        get<{ data?: CorrectiveAction[] }>("/field/quality/corrective"),
      ]);
      if (catRes.status === "fulfilled") {
        setCategories(
          Array.isArray(catRes.value?.data) ? catRes.value.data : [],
        );
      }
      if (caRes.status === "fulfilled") {
        setCorrective(Array.isArray(caRes.value?.data) ? caRes.value.data : []);
      }
      const rejected = [catRes, caRes].filter(
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

  const allItems = categories.flatMap((c) => c.items);
  const passCount = allItems.filter((i) => i.judgment === "pass").length;
  const failCount = allItems.filter((i) => i.judgment === "fail").length;
  const pendingCount = allItems.filter((i) => i.judgment === "pending").length;
  const passRate =
    allItems.length > 0
      ? Math.round((passCount / (allItems.length - pendingCount || 1)) * 100)
      : 0;

  const statCards = [
    {
      label: "合格率",
      value: `${passRate}%`,
      sub: `${passCount} / ${allItems.length - pendingCount} 項目`,
      icon: CheckSquare,
      color:
        passRate >= 90
          ? "text-green-500 bg-green-50"
          : "text-orange-500 bg-orange-50",
    },
    {
      label: "不合格件数",
      value: failCount,
      sub: "是正指示対象",
      icon: XSquare,
      color:
        failCount > 0 ? "text-red-500 bg-red-50" : "text-green-500 bg-green-50",
    },
    {
      label: "未検査数",
      value: pendingCount,
      sub: "検査待ち",
      icon: Clock,
      color: "text-gray-500 bg-gray-50",
    },
    {
      label: "是正指示（未解決）",
      value: corrective.filter((c) => c.status !== "resolved").length,
      sub: `全 ${corrective.length} 件中`,
      icon: AlertTriangle,
      color:
        corrective.filter((c) => c.status !== "resolved").length > 0
          ? "text-orange-500 bg-orange-50"
          : "text-green-500 bg-green-50",
    },
  ];

  return (
    <div className="p-6 lg:p-8 space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">品質チェック</h1>
          <p className="mt-1 text-sm text-gray-500">
            工種別の品質検査チェックリストと是正指示を管理します
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
            検査記録を追加
          </button>
        </div>
      </div>

      {error && (
        <div role="alert" aria-live="assertive" className="rounded-xl border border-danger-500/30 bg-danger-50 px-4 py-3 text-sm text-danger-700">
          {error}
        </div>
      )}
      {!loading && !error && categories.length === 0 && (
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

      {/* Checklist by Category */}
      <div className="space-y-4">
        <h2 className="font-bold text-gray-900 flex items-center gap-2">
          <ClipboardCheck className="h-4 w-4 text-blue-500" />
          品質検査チェックリスト
        </h2>
        {categories.map((cat) => (
          <CategorySection key={cat.id} category={cat} />
        ))}
      </div>

      {/* Corrective Actions */}
      <div className="rounded-xl border border-gray-200 bg-white overflow-hidden">
        <div className="flex items-center justify-between px-5 py-4 border-b border-gray-100">
          <h2 className="font-bold text-gray-900 flex items-center gap-2">
            <AlertTriangle className="h-4 w-4 text-orange-500" />
            不合格項目の是正指示
          </h2>
          <span className="text-xs text-gray-500">{corrective.length} 件</span>
        </div>
        <div className="divide-y divide-gray-100">
          {corrective.length === 0 ? (
            <div className="px-5 py-10 text-center text-sm text-gray-400">
              是正指示はありません
            </div>
          ) : (
            corrective.map((ca) => {
              const st = correctiveStatusStyle[ca.status];
              return (
                <div
                  key={ca.id}
                  className="px-5 py-4 hover:bg-gray-50 transition-colors"
                >
                  <div className="flex items-start justify-between gap-4">
                    <div className="flex-1 min-w-0 space-y-1">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="rounded bg-gray-100 px-2 py-0.5 text-xs text-gray-500">
                          {ca.category}
                        </span>
                        <p className="text-sm font-semibold text-gray-900">
                          {ca.item_name}
                        </p>
                      </div>
                      <p className="text-xs text-gray-600">{ca.issue}</p>
                      <div className="flex items-center gap-4 text-xs text-gray-400 flex-wrap">
                        <span>担当: {ca.assignee}</span>
                        <span>期限: {ca.due_date}</span>
                      </div>
                    </div>
                    <span
                      className={`flex-shrink-0 rounded-full px-2.5 py-0.5 text-xs font-medium ${st.className}`}
                    >
                      {st.label}
                    </span>
                  </div>
                </div>
              );
            })
          )}
        </div>
      </div>
    </div>
  );
}
