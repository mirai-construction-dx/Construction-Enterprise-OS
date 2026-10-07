"use client";

import { useState, useEffect, useCallback } from "react";
import {
  FileSearch,
  Scan,
  FileText,
  CheckCircle,
  Upload,
  Clock,
  Filter,
} from "lucide-react";
import { listOcrResults, type OcrResult } from "../../../../lib/api/vision";
import { ApiError } from "@/lib/api-client";

interface OcrItem {
  id: string;
  fileName: string;
  docType: string;
  uploadedAt: string;
  status: "queued" | "processing" | "completed" | "failed";
  charCount: number;
  processingTime: number | null;
}

const STATUS_CONFIG = {
  queued: { label: "待機中", color: "bg-gray-100 text-gray-600" },
  processing: { label: "処理中", color: "bg-blue-100 text-blue-700" },
  completed: { label: "完了", color: "bg-green-100 text-green-700" },
  failed: { label: "失敗", color: "bg-red-100 text-red-700" },
};

const DOC_TYPE_COLORS: Record<string, string> = {
  図面: "bg-purple-100 text-purple-700",
  仕様書: "bg-blue-100 text-blue-700",
  契約書: "bg-yellow-100 text-yellow-700",
  請求書: "bg-green-100 text-green-700",
  検査記録: "bg-orange-100 text-orange-700",
};

/** Map OcrResult.status → OcrItem.status ("pending" becomes "queued") */
function toOcrStatus(s: OcrResult["status"]): OcrItem["status"] {
  if (s === "completed") return "completed";
  if (s === "processing") return "processing";
  if (s === "failed") return "failed";
  return "queued"; // covers "pending"
}

/** Map OcrResult → OcrItem for display */
function toOcrItem(r: OcrResult, idx: number): OcrItem {
  const fileName = r.file_key?.split("/").pop() ?? `document_${idx + 1}.pdf`;
  const charCount = r.extracted_text?.length ?? 0;
  const processingTime =
    r.processing_time_ms != null
      ? Math.round(r.processing_time_ms / 1000)
      : null;

  return {
    id: r.id,
    fileName,
    docType: "その他",
    uploadedAt: r.created_at ?? "—",
    status: toOcrStatus(r.status),
    charCount,
    processingTime,
  };
}

export default function AIOcrPage() {
  const [ocrItems, setOcrItems] = useState<OcrItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [statusFilter, setStatusFilter] = useState<string>("all");
  const [docTypeFilter, setDocTypeFilter] = useState<string>("all");
  const [error, setError] = useState<string | null>(null);

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const results = await listOcrResults({ limit: 20 });
      setOcrItems(
        Array.isArray(results) ? results.map((r, i) => toOcrItem(r, i)) : [],
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

  const completed = ocrItems.filter((i) => i.status === "completed").length;
  const successRate = Math.round((completed / (ocrItems.length || 1)) * 100);
  const totalChars = ocrItems.reduce((s, i) => s + i.charCount, 0);
  const timeSamples = ocrItems.filter((i) => i.processingTime !== null);
  const avgTime =
    timeSamples.length > 0
      ? Math.round(
          timeSamples.reduce((s, i) => s + (i.processingTime ?? 0), 0) /
            timeSamples.length,
        )
      : 0;

  const filteredItems = ocrItems.filter((i) => {
    const matchStatus = statusFilter === "all" || i.status === statusFilter;
    const matchType = docTypeFilter === "all" || i.docType === docTypeFilter;
    return matchStatus && matchType;
  });

  const docTypes = Array.from(new Set(ocrItems.map((i) => i.docType)));

  return (
    <div className="p-6 space-y-6">
      {/* ヘッダー */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">OCR文書認識</h1>
          <p className="text-sm text-gray-500 mt-1">
            PDF・画像からのテキスト自動抽出
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
            ファイルアップロード
          </button>
        </div>
      </div>

      {error && (
        <div role="alert" aria-live="assertive" className="rounded-xl border border-danger-500/30 bg-danger-50 px-4 py-3 text-sm text-danger-700">
          {error}
        </div>
      )}
      {!loading && !error && ocrItems.length === 0 && (
        <div className="rounded-xl border border-gray-200 bg-white px-4 py-8 text-center text-sm text-gray-500">
          該当データがありません。
        </div>
      )}

      {/* 統計カード */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <div className="bg-white rounded-xl p-4 shadow-sm border border-gray-100">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-blue-50 rounded-lg">
              <Scan className="w-5 h-5 text-blue-600" />
            </div>
            <div>
              <p className="text-xs text-gray-500">今日処理数</p>
              <p className="text-2xl font-bold text-gray-900">
                {ocrItems.length}
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
              <p className="text-xs text-gray-500">成功率</p>
              <p className="text-2xl font-bold text-gray-900">{successRate}%</p>
            </div>
          </div>
        </div>
        <div className="bg-white rounded-xl p-4 shadow-sm border border-gray-100">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-purple-50 rounded-lg">
              <FileText className="w-5 h-5 text-purple-600" />
            </div>
            <div>
              <p className="text-xs text-gray-500">抽出文字数</p>
              <p className="text-xl font-bold text-gray-900">
                {totalChars.toLocaleString()}
              </p>
            </div>
          </div>
        </div>
        <div className="bg-white rounded-xl p-4 shadow-sm border border-gray-100">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-orange-50 rounded-lg">
              <Clock className="w-5 h-5 text-orange-600" />
            </div>
            <div>
              <p className="text-xs text-gray-500">平均処理時間</p>
              <p className="text-2xl font-bold text-gray-900">{avgTime}秒</p>
            </div>
          </div>
        </div>
      </div>

      {/* 書類種別内訳 */}
      <div className="bg-white rounded-xl p-5 shadow-sm border border-gray-100">
        <h2 className="text-sm font-semibold text-gray-700 mb-4 flex items-center gap-2">
          <FileSearch className="w-4 h-4 text-blue-500" />
          書類種別内訳
        </h2>
        <div className="flex flex-wrap gap-3">
          {Object.keys(DOC_TYPE_COLORS).map((type) => {
            const count = ocrItems.filter((i) => i.docType === type).length;
            if (count === 0) return null;
            return (
              <div
                key={type}
                className="flex items-center gap-2 bg-gray-50 rounded-lg px-3 py-2"
              >
                <span
                  className={`px-2 py-0.5 rounded text-xs font-medium ${DOC_TYPE_COLORS[type]}`}
                >
                  {type}
                </span>
                <span className="text-sm font-bold text-gray-900">
                  {count}件
                </span>
              </div>
            );
          })}
        </div>
      </div>

      {/* 処理キューテーブル */}
      <div className="bg-white rounded-xl shadow-sm border border-gray-100 overflow-hidden">
        <div className="px-5 py-4 border-b border-gray-100 flex items-center justify-between">
          <h2 className="font-semibold text-gray-800">処理キュー</h2>
          <div className="flex items-center gap-2">
            <Filter className="w-4 h-4 text-gray-400" />
            <select
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value)}
              className="text-xs border border-gray-200 rounded-lg px-2 py-1 text-gray-600 focus:outline-none focus:ring-1 focus:ring-blue-400"
            >
              <option value="all">全ステータス</option>
              <option value="queued">待機中</option>
              <option value="processing">処理中</option>
              <option value="completed">完了</option>
              <option value="failed">失敗</option>
            </select>
            <select
              value={docTypeFilter}
              onChange={(e) => setDocTypeFilter(e.target.value)}
              className="text-xs border border-gray-200 rounded-lg px-2 py-1 text-gray-600 focus:outline-none focus:ring-1 focus:ring-blue-400"
            >
              <option value="all">全書類種別</option>
              {docTypes.map((t) => (
                <option key={t} value={t}>
                  {t}
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
                  書類種別
                </th>
                <th className="text-left px-4 py-3 font-medium text-gray-600">
                  アップロード日時
                </th>
                <th className="text-left px-4 py-3 font-medium text-gray-600">
                  処理状況
                </th>
                <th className="text-left px-4 py-3 font-medium text-gray-600">
                  抽出テキスト量
                </th>
                <th className="text-left px-4 py-3 font-medium text-gray-600">
                  処理時間
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {filteredItems.map((item) => (
                <tr
                  key={item.id}
                  className="hover:bg-gray-50 transition-colors"
                >
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-2">
                      <FileText className="w-4 h-4 text-gray-400 flex-shrink-0" />
                      <span className="font-mono text-xs text-gray-700 truncate max-w-[200px]">
                        {item.fileName}
                      </span>
                    </div>
                  </td>
                  <td className="px-4 py-3">
                    <span
                      className={`px-2 py-0.5 rounded text-xs font-medium ${DOC_TYPE_COLORS[item.docType] ?? "bg-gray-100 text-gray-600"}`}
                    >
                      {item.docType}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-gray-500 text-xs whitespace-nowrap">
                    {item.uploadedAt}
                  </td>
                  <td className="px-4 py-3">
                    <span
                      className={`px-2 py-0.5 rounded-full text-xs font-medium ${STATUS_CONFIG[item.status].color}`}
                    >
                      {STATUS_CONFIG[item.status].label}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-gray-700 text-sm">
                    {item.charCount > 0
                      ? `${item.charCount.toLocaleString()} 文字`
                      : "—"}
                  </td>
                  <td className="px-4 py-3 text-gray-600 text-sm">
                    {item.processingTime !== null
                      ? `${item.processingTime}秒`
                      : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="px-4 py-3 border-t border-gray-100 text-sm text-gray-500">
          {filteredItems.length}件
          {filteredItems.length !== ocrItems.length && (
            <span className="ml-1 text-gray-400">
              （全{ocrItems.length}件中）
            </span>
          )}
        </div>
      </div>
    </div>
  );
}
