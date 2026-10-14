"use client";

import { useState, useEffect, useCallback } from "react";
import {
  Eye,
  ScanLine,
  AlertTriangle,
  CheckCircle,
  Clock,
  Upload,
  Filter,
  BarChart3,
} from "lucide-react";
import {
  listImageAnalyses,
  type ImageAnalysis,
} from "../../../../lib/api/vision";
import { ApiError } from "@/lib/api-client";

const ANALYSIS_TYPE_CONFIG: Record<string, { label: string; color: string }> = {
  defect_detection: {
    label: "欠陥検出",
    color: "bg-red-100 text-red-700",
  },
  crack_detection: {
    label: "クラック検出",
    color: "bg-orange-100 text-orange-700",
  },
  progress_tracking: {
    label: "進捗追跡",
    color: "bg-blue-100 text-blue-700",
  },
  material_recognition: {
    label: "材料認識",
    color: "bg-purple-100 text-purple-700",
  },
};

const STATUS_CONFIG: Record<
  string,
  { label: string; color: string; icon: React.ElementType }
> = {
  completed: {
    label: "完了",
    color: "bg-green-100 text-green-700",
    icon: CheckCircle,
  },
  processing: {
    label: "処理中",
    color: "bg-blue-100 text-blue-700",
    icon: Clock,
  },
  pending: {
    label: "待機中",
    color: "bg-gray-100 text-gray-600",
    icon: Clock,
  },
  failed: {
    label: "失敗",
    color: "bg-red-100 text-red-700",
    icon: AlertTriangle,
  },
};

function formatDate(iso?: string): string {
  if (!iso) return "—";
  return iso.slice(0, 16).replace("T", " ");
}

function formatTime(ms?: number | null): string {
  if (ms == null) return "—";
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${ms}ms`;
}

function formatConfidence(c?: number | null): string {
  if (c == null) return "—";
  return `${Math.round(c * 100)}%`;
}

export default function AIVisionPage() {
  const [analyses, setAnalyses] = useState<ImageAnalysis[]>([]);
  const [loading, setLoading] = useState(false);
  const [typeFilter, setTypeFilter] = useState<string>("all");
  const [error, setError] = useState<string | null>(null);

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const results = await listImageAnalyses({ limit: 20 });
      setAnalyses(Array.isArray(results) ? results : []);
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

  const filtered =
    typeFilter === "all"
      ? analyses
      : analyses.filter((a) => a.analysis_type === typeFilter);

  const completed = analyses.filter((a) => a.status === "completed");
  const defectCount = analyses.filter(
    (a) =>
      (a.analysis_type === "defect_detection" ||
        a.analysis_type === "crack_detection") &&
      a.status === "completed",
  ).length;
  const avgConfidence =
    completed.length > 0
      ? Math.round(
          (completed.reduce((s, a) => s + (a.confidence ?? 0), 0) /
            completed.length) *
            100,
        )
      : 0;

  return (
    <div className="p-6 space-y-6">
      {/* ヘッダー */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">AI画像解析</h1>
          <p className="text-sm text-gray-500 mt-1">
            現場画像の欠陥・クラック・進捗を自動検出
          </p>
        </div>
        <div className="flex items-center gap-3">
          {loading && (
            <span className="text-xs text-blue-600 bg-blue-50 px-2 py-1 rounded-full animate-pulse">
              データ取得中...
            </span>
          )}
          <button className="flex items-center gap-2 bg-blue-600 text-white px-4 py-2 rounded-lg hover:bg-blue-700 transition-colors text-sm">
            <Upload className="w-4 h-4" />
            画像アップロード
          </button>
        </div>
      </div>

      {error && (
        <div role="alert" aria-live="assertive" className="rounded-xl border border-danger-500/30 bg-danger-50 px-4 py-3 text-sm text-danger-700">
          {error}
        </div>
      )}
      {!loading && !error && analyses.length === 0 && (
        <div className="rounded-xl border border-gray-200 bg-white px-4 py-8 text-center text-sm text-gray-500">
          該当データがありません。
        </div>
      )}

      {/* 統計カード */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <div className="bg-white rounded-xl p-4 shadow-sm border border-gray-100">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-blue-50 rounded-lg">
              <ScanLine className="w-5 h-5 text-blue-600" />
            </div>
            <div>
              <p className="text-xs text-gray-500">今日の解析数</p>
              <p className="text-2xl font-bold text-gray-900">
                {analyses.length}
              </p>
            </div>
          </div>
        </div>
        <div className="bg-white rounded-xl p-4 shadow-sm border border-gray-100">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-green-50 rounded-lg">
              <CheckCircle className="w-5 h-5 text-green-600" />
            </div>
            <div>
              <p className="text-xs text-gray-500">完了</p>
              <p className="text-2xl font-bold text-gray-900">
                {completed.length}
              </p>
            </div>
          </div>
        </div>
        <div className="bg-white rounded-xl p-4 shadow-sm border border-gray-100">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-red-50 rounded-lg">
              <AlertTriangle className="w-5 h-5 text-red-600" />
            </div>
            <div>
              <p className="text-xs text-gray-500">欠陥 / クラック検出</p>
              <p className="text-2xl font-bold text-gray-900">{defectCount}</p>
            </div>
          </div>
        </div>
        <div className="bg-white rounded-xl p-4 shadow-sm border border-gray-100">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-purple-50 rounded-lg">
              <BarChart3 className="w-5 h-5 text-purple-600" />
            </div>
            <div>
              <p className="text-xs text-gray-500">平均信頼スコア</p>
              <p className="text-2xl font-bold text-gray-900">
                {avgConfidence}%
              </p>
            </div>
          </div>
        </div>
      </div>

      {/* 解析タイプ内訳 */}
      <div className="bg-white rounded-xl p-5 shadow-sm border border-gray-100">
        <h2 className="text-sm font-semibold text-gray-700 mb-4 flex items-center gap-2">
          <Eye className="w-4 h-4 text-blue-500" />
          解析タイプ内訳
        </h2>
        <div className="flex flex-wrap gap-3">
          {Object.entries(ANALYSIS_TYPE_CONFIG).map(([type, cfg]) => {
            const count = analyses.filter(
              (a) => a.analysis_type === type,
            ).length;
            if (count === 0) return null;
            return (
              <div
                key={type}
                className="flex items-center gap-2 bg-gray-50 rounded-lg px-3 py-2"
              >
                <span
                  className={`px-2 py-0.5 rounded text-xs font-medium ${cfg.color}`}
                >
                  {cfg.label}
                </span>
                <span className="text-sm font-bold text-gray-900">
                  {count}件
                </span>
              </div>
            );
          })}
        </div>
      </div>

      {/* 解析一覧テーブル */}
      <div className="bg-white rounded-xl shadow-sm border border-gray-100 overflow-hidden">
        <div className="px-5 py-4 border-b border-gray-100 flex items-center justify-between">
          <h2 className="font-semibold text-gray-800 flex items-center gap-2">
            <ScanLine className="w-4 h-4 text-blue-500" />
            解析キュー
          </h2>
          <div className="flex items-center gap-2">
            <Filter className="w-4 h-4 text-gray-400" />
            <select
              value={typeFilter}
              onChange={(e) => setTypeFilter(e.target.value)}
              className="text-sm border border-gray-200 rounded-lg px-2 py-1 focus:outline-none focus:ring-2 focus:ring-blue-300"
            >
              <option value="all">すべて</option>
              {Object.entries(ANALYSIS_TYPE_CONFIG).map(([type, cfg]) => (
                <option key={type} value={type}>
                  {cfg.label}
                </option>
              ))}
            </select>
          </div>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 border-b border-gray-200">
              <tr>
                <th className="text-left px-4 py-3 font-medium text-gray-600">
                  ファイル名
                </th>
                <th className="text-left px-4 py-3 font-medium text-gray-600">
                  解析タイプ
                </th>
                <th className="text-left px-4 py-3 font-medium text-gray-600">
                  ステータス
                </th>
                <th className="text-right px-4 py-3 font-medium text-gray-600">
                  信頼スコア
                </th>
                <th className="text-right px-4 py-3 font-medium text-gray-600">
                  処理時間
                </th>
                <th className="text-left px-4 py-3 font-medium text-gray-600">
                  日時
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {filtered.map((item) => {
                const sc = STATUS_CONFIG[item.status] ?? STATUS_CONFIG.pending;
                const tc = ANALYSIS_TYPE_CONFIG[item.analysis_type] ?? {
                  label: item.analysis_type,
                  color: "bg-gray-100 text-gray-600",
                };
                const StatusIcon = sc.icon;
                const fileName =
                  item.file_key?.split("/").pop() ?? item.file_key ?? "—";
                return (
                  <tr
                    key={item.id}
                    className="hover:bg-gray-50 transition-colors"
                  >
                    <td className="px-4 py-3">
                      <span className="font-mono text-xs text-gray-700 truncate max-w-[220px] block">
                        {fileName}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      <span
                        className={`px-2 py-0.5 rounded text-xs font-medium ${tc.color}`}
                      >
                        {tc.label}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      <span
                        className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium ${sc.color}`}
                      >
                        <StatusIcon className="w-3 h-3" />
                        {sc.label}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-right">
                      {item.confidence != null ? (
                        <span
                          className={`font-medium ${item.confidence >= 0.9 ? "text-green-700" : item.confidence >= 0.7 ? "text-yellow-700" : "text-red-700"}`}
                        >
                          {formatConfidence(item.confidence)}
                        </span>
                      ) : (
                        <span className="text-gray-400">—</span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-right text-gray-500 text-xs">
                      {formatTime(item.processing_time_ms)}
                    </td>
                    <td className="px-4 py-3 text-gray-500 text-xs whitespace-nowrap">
                      {formatDate(item.created_at)}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <div className="px-4 py-3 border-t border-gray-100 text-sm text-gray-500">
          {filtered.length}件{typeFilter !== "all" ? "（絞り込み中）" : ""}
        </div>
      </div>
    </div>
  );
}
