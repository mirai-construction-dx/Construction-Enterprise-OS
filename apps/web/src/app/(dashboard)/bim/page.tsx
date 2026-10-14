"use client";

import { useState, useEffect, useCallback } from "react";
import {
  Box,
  Layers,
  FileBox,
  CheckCircle,
  Clock,
  AlertCircle,
  Upload,
  Filter,
} from "lucide-react";
import { listBimModels, type BimModel } from "../../../lib/api/bim";
import { ApiError } from "@/lib/api-client";

const STATUS_CONFIG: Record<
  string,
  { label: string; color: string; icon: React.ElementType }
> = {
  active: {
    label: "有効",
    color: "bg-green-100 text-green-700",
    icon: CheckCircle,
  },
  processing: {
    label: "処理中",
    color: "bg-blue-100 text-blue-700",
    icon: Clock,
  },
  error: {
    label: "エラー",
    color: "bg-red-100 text-red-700",
    icon: AlertCircle,
  },
};

const FORMAT_COLORS: Record<string, string> = {
  IFC: "bg-indigo-100 text-indigo-700",
  RVT: "bg-purple-100 text-purple-700",
  OBJ: "bg-orange-100 text-orange-700",
  FBX: "bg-pink-100 text-pink-700",
};

function formatFileSize(bytes?: number): string {
  if (!bytes) return "—";
  if (bytes >= 1073741824) return `${(bytes / 1073741824).toFixed(1)} GB`;
  if (bytes >= 1048576) return `${(bytes / 1048576).toFixed(1)} MB`;
  return `${(bytes / 1024).toFixed(0)} KB`;
}

function formatDate(iso?: string): string {
  if (!iso) return "—";
  return iso.slice(0, 10).replace(/-/g, "/");
}

export default function BimPage() {
  const [models, setModels] = useState<BimModel[]>([]);
  const [loading, setLoading] = useState(false);
  const [statusFilter, setStatusFilter] = useState<string>("all");
  const [error, setError] = useState<string | null>(null);

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const res = await listBimModels();
      setModels(Array.isArray(res.items) ? res.items : []);
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
    statusFilter === "all"
      ? models
      : models.filter((m) => m.status === statusFilter);

  const activeCount = models.filter((m) => m.status === "active").length;
  const processingCount = models.filter(
    (m) => m.status === "processing",
  ).length;
  const errorCount = models.filter((m) => m.status === "error").length;
  const totalElements = models.reduce((s, m) => s + (m.element_count ?? 0), 0);

  return (
    <div className="p-6 space-y-6">
      {/* ヘッダー */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">BIMモデル管理</h1>
          <p className="text-sm text-gray-500 mt-1">
            建設3Dモデルの統合管理・閲覧
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
            モデルアップロード
          </button>
        </div>
      </div>

      {error && (
        <div role="alert" aria-live="assertive" className="rounded-xl border border-danger-500/30 bg-danger-50 px-4 py-3 text-sm text-danger-700">
          {error}
        </div>
      )}
      {!loading && !error && models.length === 0 && (
        <div className="rounded-xl border border-gray-200 bg-white px-4 py-8 text-center text-sm text-gray-500">
          該当データがありません。
        </div>
      )}

      {/* 統計カード */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <div className="bg-white rounded-xl p-4 shadow-sm border border-gray-100">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-blue-50 rounded-lg">
              <Box className="w-5 h-5 text-blue-600" />
            </div>
            <div>
              <p className="text-xs text-gray-500">総モデル数</p>
              <p className="text-2xl font-bold text-gray-900">
                {models.length}
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
              <p className="text-xs text-gray-500">有効</p>
              <p className="text-2xl font-bold text-gray-900">{activeCount}</p>
            </div>
          </div>
        </div>
        <div className="bg-white rounded-xl p-4 shadow-sm border border-gray-100">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-purple-50 rounded-lg">
              <Layers className="w-5 h-5 text-purple-600" />
            </div>
            <div>
              <p className="text-xs text-gray-500">総要素数</p>
              <p className="text-xl font-bold text-gray-900">
                {totalElements.toLocaleString()}
              </p>
            </div>
          </div>
        </div>
        <div className="bg-white rounded-xl p-4 shadow-sm border border-gray-100">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-orange-50 rounded-lg">
              <AlertCircle className="w-5 h-5 text-orange-600" />
            </div>
            <div>
              <p className="text-xs text-gray-500">処理中 / エラー</p>
              <p className="text-2xl font-bold text-gray-900">
                {processingCount + errorCount}
              </p>
            </div>
          </div>
        </div>
      </div>

      {/* フィルター + モデルテーブル */}
      <div className="bg-white rounded-xl shadow-sm border border-gray-100 overflow-hidden">
        <div className="px-5 py-4 border-b border-gray-100 flex items-center justify-between">
          <h2 className="font-semibold text-gray-800 flex items-center gap-2">
            <FileBox className="w-4 h-4 text-blue-500" />
            モデル一覧
          </h2>
          <div className="flex items-center gap-2">
            <Filter className="w-4 h-4 text-gray-400" />
            <select
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value)}
              className="text-sm border border-gray-200 rounded-lg px-2 py-1 focus:outline-none focus:ring-2 focus:ring-blue-300"
            >
              <option value="all">すべて</option>
              <option value="active">有効</option>
              <option value="processing">処理中</option>
              <option value="error">エラー</option>
            </select>
          </div>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 border-b border-gray-200">
              <tr>
                <th className="text-left px-4 py-3 font-medium text-gray-600">
                  モデル名
                </th>
                <th className="text-left px-4 py-3 font-medium text-gray-600">
                  フォーマット
                </th>
                <th className="text-left px-4 py-3 font-medium text-gray-600">
                  ステータス
                </th>
                <th className="text-right px-4 py-3 font-medium text-gray-600">
                  要素数
                </th>
                <th className="text-right px-4 py-3 font-medium text-gray-600">
                  ファイルサイズ
                </th>
                <th className="text-left px-4 py-3 font-medium text-gray-600">
                  作成日
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {filtered.map((model) => {
                const sc = STATUS_CONFIG[model.status] ?? STATUS_CONFIG.error;
                const StatusIcon = sc.icon;
                return (
                  <tr
                    key={model.id}
                    className="hover:bg-gray-50 transition-colors"
                  >
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-2">
                        <Box className="w-4 h-4 text-gray-400 flex-shrink-0" />
                        <span className="font-medium text-gray-800 truncate max-w-[220px]">
                          {model.name}
                        </span>
                      </div>
                    </td>
                    <td className="px-4 py-3">
                      <span
                        className={`px-2 py-0.5 rounded text-xs font-medium ${FORMAT_COLORS[model.format ?? ""] ?? "bg-gray-100 text-gray-600"}`}
                      >
                        {model.format ?? "—"}
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
                    <td className="px-4 py-3 text-right text-gray-700">
                      {(model.element_count ?? 0) > 0
                        ? (model.element_count ?? 0).toLocaleString()
                        : "—"}
                    </td>
                    <td className="px-4 py-3 text-right text-gray-500">
                      {formatFileSize(model.file_size)}
                    </td>
                    <td className="px-4 py-3 text-gray-500 text-xs whitespace-nowrap">
                      {formatDate(model.created_at)}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <div className="px-4 py-3 border-t border-gray-100 text-sm text-gray-500">
          {filtered.length}件{statusFilter !== "all" ? `（絞り込み中）` : ""}
        </div>
      </div>
    </div>
  );
}
