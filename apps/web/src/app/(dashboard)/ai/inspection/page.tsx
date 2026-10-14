"use client";

import { useState, useEffect, useCallback } from "react";
import { Camera, Brain, AlertCircle, CheckCircle, Search } from "lucide-react";
import { get, ApiError } from "@/lib/api-client";

interface InspectionItem {
  id: string;
  fileName: string;
  location: string;
  status: "queued" | "analyzing" | "completed" | "error";
  anomalies: string[];
  confidence: number;
  capturedAt: string;
}

// API response shape from /api/v1/advanced/inspections-ai
interface InspectionResult {
  id: string | number;
  site_id?: string | number;
  site_name?: string;
  inspection_type?: string;
  ai_score?: number; // 0–100 confidence
  issues_found?: number | string[];
  status?: string;
  inspected_at?: string;
  // optional mapped fields
  file_name?: string;
  location?: string;
  anomalies?: string[];
  confidence?: number;
}

const STATUS_CONFIG = {
  queued: { label: "待機中", color: "bg-gray-100 text-gray-600" },
  analyzing: { label: "解析中", color: "bg-blue-100 text-blue-700" },
  completed: { label: "完了", color: "bg-green-100 text-green-700" },
  error: { label: "エラー", color: "bg-red-100 text-red-700" },
};

const ANOMALY_COLORS: Record<string, string> = {
  ひび割れ: "bg-orange-100 text-orange-700",
  錆び: "bg-red-100 text-red-700",
  剥離: "bg-yellow-100 text-yellow-700",
  その他: "bg-gray-100 text-gray-700",
};

/** Map InspectionResult status string to InspectionItem status */
function toItemStatus(s?: string): InspectionItem["status"] {
  if (!s) return "queued";
  const lower = s.toLowerCase();
  if (lower.includes("完了") || lower === "completed") return "completed";
  if (lower.includes("解析") || lower === "analyzing" || lower === "processing")
    return "analyzing";
  if (lower.includes("エラー") || lower === "error" || lower === "failed")
    return "error";
  return "queued";
}

/** Map InspectionResult → InspectionItem for display */
function toInspectionItem(r: InspectionResult, idx: number): InspectionItem {
  const anomalies = Array.isArray(r.anomalies)
    ? r.anomalies
    : Array.isArray(r.issues_found)
      ? (r.issues_found as string[])
      : [];

  return {
    id: String(r.id ?? `I-${String(idx + 1).padStart(3, "0")}`),
    fileName:
      r.file_name ??
      `inspection_${String(r.site_id ?? idx + 1)}_${r.inspection_type ?? "ai"}.jpg`,
    location: r.location ?? r.site_name ?? "—",
    status: toItemStatus(r.status),
    anomalies,
    confidence: r.confidence ?? r.ai_score ?? 0,
    capturedAt: r.inspected_at ?? "—",
  };
}

export default function AIInspectionPage() {
  const [items, setItems] = useState<InspectionItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const json = await get<
        InspectionResult[] | { items: InspectionResult[] }
      >("/advanced/inspections?per_page=20");
      const apiItems: InspectionResult[] = Array.isArray(json)
        ? json
        : (json?.items ?? []);
      setItems(apiItems.map((r, i) => toInspectionItem(r, i)));
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

  const completed = items.filter((i) => i.status === "completed").length;
  const withAnomalies = items.filter((i) => i.anomalies.length > 0).length;
  const needsReview = items.filter(
    (i) => i.anomalies.length > 0 && i.confidence < 90,
  ).length;
  const avgConfidence = Math.round(
    items
      .filter((i) => i.confidence > 0)
      .reduce((s, i) => s + i.confidence, 0) /
      (items.filter((i) => i.confidence > 0).length || 1),
  );

  const anomalyCounts = {
    ひび割れ: items.flatMap((i) => i.anomalies).filter((a) => a === "ひび割れ")
      .length,
    錆び: items.flatMap((i) => i.anomalies).filter((a) => a === "錆び").length,
    剥離: items.flatMap((i) => i.anomalies).filter((a) => a === "剥離").length,
    その他: items.flatMap((i) => i.anomalies).filter((a) => a === "その他")
      .length,
  };

  return (
    <div className="p-6 space-y-6">
      {/* ヘッダー */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">AI点検</h1>
          <p className="text-sm text-gray-500 mt-1">
            点検画像のAI自動解析・異常検出
          </p>
        </div>
        <div className="flex items-center gap-3">
          {loading && (
            <span className="text-xs text-blue-600 bg-blue-50 px-2 py-1 rounded-full animate-pulse">
              データ取得中...
            </span>
          )}
          <div className="flex items-center gap-2 text-xs text-gray-500 bg-blue-50 px-3 py-1.5 rounded-full">
            <Brain className="w-3.5 h-3.5 text-blue-600" />
            Vision AI powered
          </div>
        </div>
      </div>

      {error && (
        <div role="alert" aria-live="assertive" className="rounded-xl border border-danger-500/30 bg-danger-50 px-4 py-3 text-sm text-danger-700">
          {error}
        </div>
      )}
      {!loading && !error && items.length === 0 && (
        <div className="rounded-xl border border-gray-200 bg-white px-4 py-8 text-center text-sm text-gray-500">
          該当データがありません。
        </div>
      )}

      {/* 統計カード */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <div className="bg-white rounded-xl p-4 shadow-sm border border-gray-100">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-blue-50 rounded-lg">
              <Camera className="w-5 h-5 text-blue-600" />
            </div>
            <div>
              <p className="text-xs text-gray-500">解析済み数</p>
              <p className="text-2xl font-bold text-gray-900">{completed}</p>
            </div>
          </div>
        </div>
        <div className="bg-white rounded-xl p-4 shadow-sm border border-gray-100">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-red-50 rounded-lg">
              <AlertCircle className="w-5 h-5 text-red-600" />
            </div>
            <div>
              <p className="text-xs text-gray-500">異常検出数</p>
              <p className="text-2xl font-bold text-gray-900">
                {withAnomalies}
              </p>
            </div>
          </div>
        </div>
        <div className="bg-white rounded-xl p-4 shadow-sm border border-gray-100">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-yellow-50 rounded-lg">
              <Search className="w-5 h-5 text-yellow-600" />
            </div>
            <div>
              <p className="text-xs text-gray-500">要確認数</p>
              <p className="text-2xl font-bold text-gray-900">{needsReview}</p>
            </div>
          </div>
        </div>
        <div className="bg-white rounded-xl p-4 shadow-sm border border-gray-100">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-green-50 rounded-lg">
              <CheckCircle className="w-5 h-5 text-green-600" />
            </div>
            <div>
              <p className="text-xs text-gray-500">解析精度</p>
              <p className="text-2xl font-bold text-gray-900">
                {avgConfidence}%
              </p>
            </div>
          </div>
        </div>
      </div>

      {/* 異常検出サマリー */}
      <div className="bg-white rounded-xl p-5 shadow-sm border border-gray-100">
        <h2 className="text-sm font-semibold text-gray-700 mb-4 flex items-center gap-2">
          <AlertCircle className="w-4 h-4 text-orange-500" />
          異常検出カテゴリ別件数
        </h2>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          {Object.entries(anomalyCounts).map(([cat, count]) => (
            <div key={cat} className="text-center p-3 rounded-lg bg-gray-50">
              <span
                className={`inline-block px-2 py-0.5 rounded text-xs font-medium mb-2 ${ANOMALY_COLORS[cat]}`}
              >
                {cat}
              </span>
              <p className="text-2xl font-bold text-gray-900">{count}</p>
              <p className="text-xs text-gray-500">件</p>
            </div>
          ))}
        </div>
      </div>

      {/* 解析キューテーブル */}
      <div className="bg-white rounded-xl shadow-sm border border-gray-100 overflow-hidden">
        <div className="px-5 py-4 border-b border-gray-100">
          <h2 className="font-semibold text-gray-800">点検画像解析キュー</h2>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 border-b border-gray-200">
              <tr>
                <th className="text-left px-4 py-3 font-medium text-gray-600">
                  ファイル名
                </th>
                <th className="text-left px-4 py-3 font-medium text-gray-600">
                  撮影場所
                </th>
                <th className="text-left px-4 py-3 font-medium text-gray-600">
                  解析状況
                </th>
                <th className="text-left px-4 py-3 font-medium text-gray-600">
                  検出異常
                </th>
                <th className="text-left px-4 py-3 font-medium text-gray-600">
                  信頼度
                </th>
                <th className="text-left px-4 py-3 font-medium text-gray-600">
                  撮影日時
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {items.map((item) => (
                <tr
                  key={item.id}
                  className="hover:bg-gray-50 transition-colors"
                >
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-2">
                      <Camera className="w-4 h-4 text-gray-400" />
                      <span className="font-mono text-xs text-gray-700">
                        {item.fileName}
                      </span>
                    </div>
                  </td>
                  <td className="px-4 py-3 text-gray-700">{item.location}</td>
                  <td className="px-4 py-3">
                    <span
                      className={`px-2 py-0.5 rounded-full text-xs font-medium ${STATUS_CONFIG[item.status].color}`}
                    >
                      {STATUS_CONFIG[item.status].label}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    {item.anomalies.length === 0 ? (
                      item.status === "completed" ? (
                        <span className="flex items-center gap-1 text-green-600 text-xs">
                          <CheckCircle className="w-3 h-3" />
                          異常なし
                        </span>
                      ) : (
                        <span className="text-gray-400 text-xs">—</span>
                      )
                    ) : (
                      <div className="flex flex-wrap gap-1">
                        {item.anomalies.map((a) => (
                          <span
                            key={a}
                            className={`px-1.5 py-0.5 rounded text-xs ${ANOMALY_COLORS[a] ?? "bg-gray-100 text-gray-700"}`}
                          >
                            {a}
                          </span>
                        ))}
                      </div>
                    )}
                  </td>
                  <td className="px-4 py-3">
                    {item.confidence > 0 ? (
                      <div className="flex items-center gap-2">
                        <div className="w-12 h-1.5 bg-gray-100 rounded-full overflow-hidden">
                          <div
                            className={`h-full rounded-full ${item.confidence >= 90 ? "bg-green-500" : item.confidence >= 75 ? "bg-yellow-500" : "bg-red-500"}`}
                            style={{ width: `${item.confidence}%` }}
                          />
                        </div>
                        <span className="text-xs text-gray-600">
                          {item.confidence}%
                        </span>
                      </div>
                    ) : (
                      <span className="text-gray-400 text-xs">—</span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-gray-500 text-xs whitespace-nowrap">
                    {item.capturedAt}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="px-4 py-3 border-t border-gray-100 text-sm text-gray-500">
          {items.length}件
        </div>
      </div>
    </div>
  );
}
