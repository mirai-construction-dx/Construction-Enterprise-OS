"use client";

import { useState, useEffect, useCallback } from "react";
import { ListTree, Clock, CheckSquare, BarChart2 } from "lucide-react";
import { get, ApiError } from "@/lib/api-client";

interface WbsItem {
  id: string;
  level: number;
  wbsNo: string;
  name: string;
  assignee: string;
  plannedHours: number;
  actualHours: number;
  start: string;
  end: string;
  progress: number;
}

// API response shape from /api/v1/construction/wbs
interface WbsApiItem {
  id: string | number;
  project_id?: string | number;
  project_name?: string;
  task_name?: string;
  name?: string;
  level?: number;
  status?: string;
  start_date?: string;
  end_date?: string;
  progress_rate?: number;
  progress?: number;
  assigned_to?: string;
  assignee?: string;
  planned_hours?: number;
  actual_hours?: number;
  wbs_no?: string;
}

const WBS_ITEMS: WbsItem[] = [
  {
    id: "1",
    level: 0,
    wbsNo: "1",
    name: "基礎工事",
    assignee: "田中 健一",
    plannedHours: 480,
    actualHours: 480,
    start: "2024-04-01",
    end: "2024-05-25",
    progress: 100,
  },
  {
    id: "1.1",
    level: 1,
    wbsNo: "1.1",
    name: "掘削工事",
    assignee: "田中 健一",
    plannedHours: 120,
    actualHours: 115,
    start: "2024-04-01",
    end: "2024-04-20",
    progress: 100,
  },
  {
    id: "1.2",
    level: 1,
    wbsNo: "1.2",
    name: "捨てコン打設",
    assignee: "鈴木 次郎",
    plannedHours: 40,
    actualHours: 38,
    start: "2024-04-21",
    end: "2024-04-25",
    progress: 100,
  },
  {
    id: "1.3",
    level: 1,
    wbsNo: "1.3",
    name: "配筋・型枠",
    assignee: "佐藤 三郎",
    plannedHours: 200,
    actualHours: 210,
    start: "2024-04-26",
    end: "2024-05-15",
    progress: 100,
  },
  {
    id: "1.3.1",
    level: 2,
    wbsNo: "1.3.1",
    name: "基礎配筋",
    assignee: "佐藤 三郎",
    plannedHours: 120,
    actualHours: 125,
    start: "2024-04-26",
    end: "2024-05-08",
    progress: 100,
  },
  {
    id: "1.3.2",
    level: 2,
    wbsNo: "1.3.2",
    name: "型枠組立",
    assignee: "木村 七海",
    plannedHours: 80,
    actualHours: 85,
    start: "2024-05-09",
    end: "2024-05-15",
    progress: 100,
  },
  {
    id: "2",
    level: 0,
    wbsNo: "2",
    name: "躯体工事",
    assignee: "山田 五郎",
    plannedHours: 960,
    actualHours: 620,
    start: "2024-06-01",
    end: "2024-10-15",
    progress: 62,
  },
  {
    id: "2.1",
    level: 1,
    wbsNo: "2.1",
    name: "1F躯体",
    assignee: "山田 五郎",
    plannedHours: 320,
    actualHours: 320,
    start: "2024-06-01",
    end: "2024-07-15",
    progress: 100,
  },
  {
    id: "2.2",
    level: 1,
    wbsNo: "2.2",
    name: "2F躯体",
    assignee: "山田 五郎",
    plannedHours: 320,
    actualHours: 180,
    start: "2024-07-16",
    end: "2024-08-31",
    progress: 55,
  },
  {
    id: "2.2.1",
    level: 2,
    wbsNo: "2.2.1",
    name: "2F配筋",
    assignee: "山田 五郎",
    plannedHours: 160,
    actualHours: 120,
    start: "2024-07-16",
    end: "2024-08-10",
    progress: 75,
  },
  {
    id: "2.2.2",
    level: 2,
    wbsNo: "2.2.2",
    name: "2Fコンクリ打設",
    assignee: "中村 八郎",
    plannedHours: 160,
    actualHours: 60,
    start: "2024-08-11",
    end: "2024-08-31",
    progress: 35,
  },
  {
    id: "2.3",
    level: 1,
    wbsNo: "2.3",
    name: "3F躯体",
    assignee: "山田 五郎",
    plannedHours: 320,
    actualHours: 120,
    start: "2024-09-01",
    end: "2024-10-15",
    progress: 0,
  },
  {
    id: "3",
    level: 0,
    wbsNo: "3",
    name: "仕上工事",
    assignee: "小林 九子",
    plannedHours: 600,
    actualHours: 0,
    start: "2024-10-16",
    end: "2025-02-28",
    progress: 0,
  },
  {
    id: "3.1",
    level: 1,
    wbsNo: "3.1",
    name: "外壁工事",
    assignee: "中村 八郎",
    plannedHours: 200,
    actualHours: 0,
    start: "2024-10-20",
    end: "2024-12-15",
    progress: 0,
  },
  {
    id: "3.2",
    level: 1,
    wbsNo: "3.2",
    name: "内装工事",
    assignee: "小林 九子",
    plannedHours: 400,
    actualHours: 0,
    start: "2024-11-01",
    end: "2025-02-28",
    progress: 0,
  },
];

const INDENT_CLASSES = ["", "pl-6", "pl-12"];

/** Map WbsApiItem → WbsItem for display */
function toWbsItem(w: WbsApiItem, idx: number): WbsItem {
  const progress =
    w.progress_rate != null ? Math.round(w.progress_rate) : (w.progress ?? 0);

  return {
    id: String(w.id ?? idx + 1),
    level: w.level ?? 0,
    wbsNo: w.wbs_no ?? String(w.id ?? idx + 1),
    name: w.task_name ?? w.name ?? `タスク ${idx + 1}`,
    assignee: w.assigned_to ?? w.assignee ?? "—",
    plannedHours: w.planned_hours ?? 0,
    actualHours: w.actual_hours ?? 0,
    start: w.start_date ?? "—",
    end: w.end_date ?? "—",
    progress,
  };
}

export default function WbsPage() {
  const [wbsItems, setWbsItems] = useState<WbsItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const json = await get<WbsApiItem[] | { items: WbsApiItem[] }>(
        "/construction/wbs?per_page=50",
      );
      const items: WbsApiItem[] = Array.isArray(json)
        ? json
        : (json?.items ?? []);
      setWbsItems(items.map((w, i) => toWbsItem(w, i)));
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

  const totalItems = wbsItems.length;
  const completedItems = wbsItems.filter((i) => i.progress === 100).length;
  const completionRate = Math.round((completedItems / (totalItems || 1)) * 100);
  const totalPlanned = wbsItems
    .filter((i) => i.level === 0)
    .reduce((s, i) => s + i.plannedHours, 0);
  const totalActual = wbsItems
    .filter((i) => i.level === 0)
    .reduce((s, i) => s + i.actualHours, 0);

  return (
    <div className="space-y-6 p-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">WBS管理</h1>
          <p className="text-sm text-gray-500 mt-1">
            品川タワー新築工事 — 作業分解構造
          </p>
        </div>
        <div className="flex items-center gap-3">
          {loading && (
            <span className="text-xs text-blue-600 bg-blue-50 px-2 py-1 rounded-full animate-pulse">
              データ取得中...
            </span>
          )}
          <button className="px-4 py-2 bg-blue-600 text-white text-sm rounded-lg hover:bg-blue-700">
            WBS更新
          </button>
        </div>
      </div>

      {error && (
        <div role="alert" aria-live="assertive" className="rounded-xl border border-danger-500/30 bg-danger-50 px-4 py-3 text-sm text-danger-700">
          {error}
        </div>
      )}
      {!loading && !error && wbsItems.length === 0 && (
        <div className="rounded-xl border border-gray-200 bg-white px-4 py-8 text-center text-sm text-gray-500">
          該当データがありません。
        </div>
      )}

      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        <div className="bg-white rounded-xl border border-gray-200 p-4 flex items-center gap-3">
          <div className="p-2 bg-blue-50 rounded-lg">
            <ListTree className="w-5 h-5 text-blue-600" />
          </div>
          <div>
            <p className="text-xs text-gray-500">総WBS項目数</p>
            <p className="text-2xl font-bold text-gray-900">{totalItems}</p>
          </div>
        </div>
        <div className="bg-white rounded-xl border border-gray-200 p-4 flex items-center gap-3">
          <div className="p-2 bg-green-50 rounded-lg">
            <CheckSquare className="w-5 h-5 text-green-600" />
          </div>
          <div>
            <p className="text-xs text-gray-500">完了率</p>
            <p className="text-2xl font-bold text-gray-900">
              {completionRate}%
            </p>
          </div>
        </div>
        <div className="bg-white rounded-xl border border-gray-200 p-4 flex items-center gap-3">
          <div className="p-2 bg-purple-50 rounded-lg">
            <Clock className="w-5 h-5 text-purple-600" />
          </div>
          <div>
            <p className="text-xs text-gray-500">計画工数合計</p>
            <p className="text-2xl font-bold text-gray-900">
              {totalPlanned.toLocaleString()}h
            </p>
          </div>
        </div>
        <div className="bg-white rounded-xl border border-gray-200 p-4 flex items-center gap-3">
          <div className="p-2 bg-orange-50 rounded-lg">
            <BarChart2 className="w-5 h-5 text-orange-600" />
          </div>
          <div>
            <p className="text-xs text-gray-500">実績工数合計</p>
            <p className="text-2xl font-bold text-gray-900">
              {totalActual.toLocaleString()}h
            </p>
          </div>
        </div>
      </div>

      <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-gray-50 border-b border-gray-200">
                <th className="px-4 py-3 text-left font-semibold text-gray-600 whitespace-nowrap">
                  WBS番号
                </th>
                <th className="px-4 py-3 text-left font-semibold text-gray-600 whitespace-nowrap">
                  作業名
                </th>
                <th className="px-4 py-3 text-left font-semibold text-gray-600 whitespace-nowrap">
                  担当者
                </th>
                <th className="px-4 py-3 text-right font-semibold text-gray-600 whitespace-nowrap">
                  計画工数(h)
                </th>
                <th className="px-4 py-3 text-right font-semibold text-gray-600 whitespace-nowrap">
                  実績工数(h)
                </th>
                <th className="px-4 py-3 text-left font-semibold text-gray-600 whitespace-nowrap">
                  開始日
                </th>
                <th className="px-4 py-3 text-left font-semibold text-gray-600 whitespace-nowrap">
                  終了日
                </th>
                <th className="px-4 py-3 text-left font-semibold text-gray-600 whitespace-nowrap w-36">
                  進捗
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {wbsItems.map((item) => (
                <tr
                  key={item.id}
                  className={`hover:bg-gray-50 ${item.level === 0 ? "bg-gray-50 font-semibold" : ""}`}
                >
                  <td className="px-4 py-2.5 text-gray-500 whitespace-nowrap text-xs">
                    {item.wbsNo}
                  </td>
                  <td
                    className={`px-4 py-2.5 text-gray-900 whitespace-nowrap ${INDENT_CLASSES[Math.min(item.level, INDENT_CLASSES.length - 1)]}`}
                  >
                    {item.name}
                  </td>
                  <td className="px-4 py-2.5 text-gray-600 whitespace-nowrap">
                    {item.assignee}
                  </td>
                  <td className="px-4 py-2.5 text-gray-600 whitespace-nowrap text-right">
                    {item.plannedHours}
                  </td>
                  <td className="px-4 py-2.5 text-gray-600 whitespace-nowrap text-right">
                    {item.actualHours}
                  </td>
                  <td className="px-4 py-2.5 text-gray-600 whitespace-nowrap">
                    {item.start}
                  </td>
                  <td className="px-4 py-2.5 text-gray-600 whitespace-nowrap">
                    {item.end}
                  </td>
                  <td className="px-4 py-2.5 whitespace-nowrap">
                    <div className="flex items-center gap-2">
                      <div className="flex-1 bg-gray-200 rounded-full h-2 min-w-[60px]">
                        <div
                          className={`h-2 rounded-full ${item.progress === 100 ? "bg-green-500" : "bg-blue-500"}`}
                          style={{ width: `${item.progress}%` }}
                        />
                      </div>
                      <span className="text-xs text-gray-600 w-8 text-right">
                        {item.progress}%
                      </span>
                    </div>
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
