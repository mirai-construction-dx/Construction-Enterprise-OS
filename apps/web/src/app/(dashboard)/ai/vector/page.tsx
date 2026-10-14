"use client";

import { useState, useEffect, useCallback } from "react";
import {
  Database,
  Search,
  Layers,
  CheckCircle,
  XCircle,
  FileText,
  Cpu,
  Hash,
} from "lucide-react";
import {
  listVectorIndices,
  vectorSearch,
  type VectorIndex,
  type VectorSearchResult,
} from "../../../../lib/api/vision";
import { ApiError } from "@/lib/api-client";

const INDEX_TYPE_COLOR: Record<string, string> = {
  HNSW: "bg-blue-100 text-blue-700",
  IVF: "bg-purple-100 text-purple-700",
  FLAT: "bg-gray-100 text-gray-600",
};

const METRIC_COLOR: Record<string, string> = {
  cosine: "bg-green-100 text-green-700",
  euclidean: "bg-orange-100 text-orange-700",
  dot_product: "bg-indigo-100 text-indigo-700",
};

const SOURCE_TYPE_LABEL: Record<string, string> = {
  inspection_report: "検査レポート",
  construction_spec: "施工仕様書",
  safety_manual: "安全マニュアル",
  bim_metadata: "BIMメタデータ",
  drawing: "図面",
};

function formatDate(iso?: string): string {
  if (!iso) return "—";
  return iso.slice(0, 10).replace(/-/g, "/");
}

function formatSimilarity(s: number): string {
  return `${Math.round(s * 100)}%`;
}

export default function VectorDBPage() {
  const [indices, setIndices] = useState<VectorIndex[]>([]);
  const [loading, setLoading] = useState(false);
  const [selectedIndexId, setSelectedIndexId] = useState<string>("");
  const [queryText, setQueryText] = useState("");
  const [topK, setTopK] = useState(5);
  const [searching, setSearching] = useState(false);
  const [results, setResults] = useState<VectorSearchResult[]>([]);
  const [searched, setSearched] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const data = await listVectorIndices({ limit: 20 });
      setIndices(Array.isArray(data) ? data : []);
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

  const activeIndices = indices.filter((i) => i.is_active);
  const totalVectors = indices.reduce((s, i) => s + (i.total_vectors ?? 0), 0);
  const totalDocuments = indices.reduce(
    (s, i) => s + (i.document_count ?? 0),
    0,
  );

  const handleSearch = async () => {
    if (!queryText.trim()) return;
    setSearching(true);
    setSearched(true);
    try {
      const indexId = selectedIndexId || indices[0]?.id || "";
      const data = await vectorSearch({
        index_id: indexId,
        query_text: queryText.trim(),
        top_k: topK,
      });
      setResults(Array.isArray(data) ? data : []);
      setError(null);
    } catch (err) {
      setResults([]);
      setError(
        err instanceof ApiError && err.status === 403
          ? "権限がありません。"
          : "データを取得できませんでした。",
      );
    } finally {
      setSearching(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter") handleSearch();
  };

  return (
    <div className="p-6 space-y-6">
      {/* ヘッダー */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">ベクターDB検索</h1>
          <p className="text-sm text-gray-500 mt-1">
            施工文書・検査レポートのセマンティック検索
          </p>
        </div>
        {loading && (
          <span className="text-xs text-blue-600 bg-blue-50 px-2 py-1 rounded-full animate-pulse">
            データ取得中...
          </span>
        )}
      </div>

      {error && (
        <div role="alert" aria-live="assertive" className="rounded-xl border border-danger-500/30 bg-danger-50 px-4 py-3 text-sm text-danger-700">
          {error}
        </div>
      )}
      {!loading && !error && indices.length === 0 && (
        <div className="rounded-xl border border-gray-200 bg-white px-4 py-8 text-center text-sm text-gray-500">
          該当データがありません。
        </div>
      )}

      {/* 統計カード */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <div className="bg-white rounded-xl p-4 shadow-sm border border-gray-100">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-blue-50 rounded-lg">
              <Database className="w-5 h-5 text-blue-600" />
            </div>
            <div>
              <p className="text-xs text-gray-500">インデックス数</p>
              <p className="text-2xl font-bold text-gray-900">
                {indices.length}
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
              <p className="text-xs text-gray-500">有効インデックス</p>
              <p className="text-2xl font-bold text-gray-900">
                {activeIndices.length}
              </p>
            </div>
          </div>
        </div>
        <div className="bg-white rounded-xl p-4 shadow-sm border border-gray-100">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-purple-50 rounded-lg">
              <Layers className="w-5 h-5 text-purple-600" />
            </div>
            <div>
              <p className="text-xs text-gray-500">総ベクター数</p>
              <p className="text-xl font-bold text-gray-900">
                {totalVectors.toLocaleString()}
              </p>
            </div>
          </div>
        </div>
        <div className="bg-white rounded-xl p-4 shadow-sm border border-gray-100">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-orange-50 rounded-lg">
              <FileText className="w-5 h-5 text-orange-600" />
            </div>
            <div>
              <p className="text-xs text-gray-500">総ドキュメント数</p>
              <p className="text-xl font-bold text-gray-900">
                {totalDocuments.toLocaleString()}
              </p>
            </div>
          </div>
        </div>
      </div>

      {/* セマンティック検索パネル */}
      <div className="bg-white rounded-xl p-5 shadow-sm border border-gray-100">
        <h2 className="text-sm font-semibold text-gray-700 mb-4 flex items-center gap-2">
          <Search className="w-4 h-4 text-blue-500" />
          セマンティック検索
        </h2>
        <div className="flex flex-col sm:flex-row gap-3">
          <select
            value={selectedIndexId}
            onChange={(e) => setSelectedIndexId(e.target.value)}
            className="text-sm border border-gray-200 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-300 sm:w-56"
          >
            <option value="">インデックスを選択</option>
            {activeIndices.map((idx) => (
              <option key={idx.id} value={idx.id}>
                {idx.collection_name}
              </option>
            ))}
          </select>
          <input
            type="text"
            value={queryText}
            onChange={(e) => setQueryText(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="検索クエリを入力（例: 外壁クラック検査基準）"
            className="flex-1 text-sm border border-gray-200 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-300"
          />
          <select
            value={topK}
            onChange={(e) => setTopK(Number(e.target.value))}
            className="text-sm border border-gray-200 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-300"
          >
            <option value={3}>Top 3</option>
            <option value={5}>Top 5</option>
            <option value={10}>Top 10</option>
          </select>
          <button
            onClick={handleSearch}
            disabled={searching || !queryText.trim()}
            className="flex items-center gap-2 bg-blue-600 text-white px-4 py-2 rounded-lg hover:bg-blue-700 transition-colors text-sm disabled:opacity-50 disabled:cursor-not-allowed"
          >
            <Search className="w-4 h-4" />
            {searching ? "検索中..." : "検索"}
          </button>
        </div>

        {/* 検索結果 */}
        {searched && (
          <div className="mt-5 space-y-3">
            <p className="text-xs text-gray-500">
              {results.length}件の類似ドキュメントが見つかりました
            </p>
            {results.map((r, idx) => (
              <div
                key={`${r.source_id}-${r.chunk_index}`}
                className="border border-gray-100 rounded-lg p-4 hover:border-blue-200 transition-colors"
              >
                <div className="flex items-start justify-between gap-3 mb-2">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="text-xs font-medium text-gray-500">
                      #{idx + 1}
                    </span>
                    <span className="px-2 py-0.5 rounded text-xs font-medium bg-blue-50 text-blue-700">
                      {SOURCE_TYPE_LABEL[r.source_type] ?? r.source_type}
                    </span>
                    <span className="text-xs text-gray-400 font-mono">
                      {r.source_id} · chunk {r.chunk_index}
                    </span>
                  </div>
                  <span
                    className={`text-sm font-bold flex-shrink-0 ${
                      r.similarity >= 0.9
                        ? "text-green-700"
                        : r.similarity >= 0.7
                          ? "text-yellow-700"
                          : "text-red-700"
                    }`}
                  >
                    {formatSimilarity(r.similarity)}
                  </span>
                </div>
                <p className="text-sm text-gray-800 leading-relaxed">
                  {r.content}
                </p>
                {Object.keys(r.metadata).length > 0 && (
                  <div className="mt-2 flex flex-wrap gap-2">
                    {Object.entries(r.metadata).map(([k, v]) => (
                      <span
                        key={k}
                        className="text-xs text-gray-500 bg-gray-50 px-2 py-0.5 rounded"
                      >
                        {k}: {String(v)}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>

      {/* インデックス一覧テーブル */}
      <div className="bg-white rounded-xl shadow-sm border border-gray-100 overflow-hidden">
        <div className="px-5 py-4 border-b border-gray-100">
          <h2 className="font-semibold text-gray-800 flex items-center gap-2">
            <Database className="w-4 h-4 text-blue-500" />
            インデックス一覧
          </h2>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 border-b border-gray-200">
              <tr>
                <th className="text-left px-4 py-3 font-medium text-gray-600">
                  コレクション名
                </th>
                <th className="text-left px-4 py-3 font-medium text-gray-600">
                  タイプ
                </th>
                <th className="text-left px-4 py-3 font-medium text-gray-600">
                  メトリクス
                </th>
                <th className="text-right px-4 py-3 font-medium text-gray-600">
                  次元数
                </th>
                <th className="text-right px-4 py-3 font-medium text-gray-600">
                  ベクター数
                </th>
                <th className="text-right px-4 py-3 font-medium text-gray-600">
                  ドキュメント数
                </th>
                <th className="text-left px-4 py-3 font-medium text-gray-600">
                  状態
                </th>
                <th className="text-left px-4 py-3 font-medium text-gray-600">
                  作成日
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {indices.map((idx) => (
                <tr key={idx.id} className="hover:bg-gray-50 transition-colors">
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-2">
                      <Cpu className="w-4 h-4 text-gray-400 flex-shrink-0" />
                      <span className="font-mono text-xs text-gray-800 truncate max-w-[200px]">
                        {idx.collection_name}
                      </span>
                    </div>
                  </td>
                  <td className="px-4 py-3">
                    <span
                      className={`px-2 py-0.5 rounded text-xs font-medium ${INDEX_TYPE_COLOR[idx.index_type] ?? "bg-gray-100 text-gray-600"}`}
                    >
                      {idx.index_type}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    <span
                      className={`px-2 py-0.5 rounded text-xs font-medium ${METRIC_COLOR[idx.metric] ?? "bg-gray-100 text-gray-600"}`}
                    >
                      {idx.metric}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-right">
                    <span className="flex items-center justify-end gap-1 text-gray-700">
                      <Hash className="w-3 h-3 text-gray-400" />
                      {idx.dimension}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-right text-gray-700">
                    {idx.total_vectors.toLocaleString()}
                  </td>
                  <td className="px-4 py-3 text-right text-gray-700">
                    {idx.document_count.toLocaleString()}
                  </td>
                  <td className="px-4 py-3">
                    {idx.is_active ? (
                      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-green-100 text-green-700">
                        <CheckCircle className="w-3 h-3" />
                        有効
                      </span>
                    ) : (
                      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-gray-100 text-gray-600">
                        <XCircle className="w-3 h-3" />
                        無効
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-gray-500 text-xs whitespace-nowrap">
                    {formatDate(idx.created_at)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="px-4 py-3 border-t border-gray-100 text-sm text-gray-500">
          {indices.length}件
        </div>
      </div>
    </div>
  );
}
