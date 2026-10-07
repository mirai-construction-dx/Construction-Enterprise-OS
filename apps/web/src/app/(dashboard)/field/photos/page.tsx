"use client";

import { useState, useEffect, useCallback } from "react";
import { get, ApiError } from "@/lib/api-client";
import {
  Camera,
  Image as ImageIcon,
  Tag,
  Upload,
  RefreshCw,
  AlertCircle,
} from "lucide-react";

interface SitePhoto {
  id: string;
  filename: string;
  taken_at: string;
  zone: string;
  tags: string[];
  uploader: string;
  needs_review: boolean;
  description: string;
}

const TAG_COLORS: Record<string, string> = {
  安全: "bg-green-100 text-green-700",
  進捗: "bg-blue-100 text-blue-700",
  完了: "bg-purple-100 text-purple-700",
  問題: "bg-red-100 text-red-700",
};

const ALL_ZONES = ["全工区", "A工区", "B工区", "C工区", "D工区"];
const ALL_TAGS = ["安全", "進捗", "完了", "問題"];

function PhotoCard({ photo }: { photo: SitePhoto }) {
  return (
    <div className="rounded-xl border border-gray-200 bg-white overflow-hidden hover:shadow-md transition-shadow">
      {/* Placeholder image area */}
      <div className="relative aspect-video bg-gray-200 flex items-center justify-center">
        <ImageIcon className="h-10 w-10 text-gray-400" aria-hidden="true" />
        {photo.needs_review && (
          <span className="absolute top-2 right-2 inline-flex items-center gap-1 rounded-full bg-red-500 px-2 py-0.5 text-xs font-semibold text-white shadow">
            <AlertCircle className="h-3 w-3" />
            要確認
          </span>
        )}
        <span className="absolute bottom-2 left-2 rounded bg-black/50 px-2 py-0.5 text-xs text-white">
          {photo.zone}
        </span>
      </div>

      {/* Card body */}
      <div className="p-3 space-y-2">
        <p className="text-xs font-medium text-gray-800 line-clamp-2 leading-snug">
          {photo.description}
        </p>
        <div className="flex flex-wrap gap-1">
          {photo.tags.map((tag) => (
            <span
              key={tag}
              className={`inline-flex items-center gap-0.5 rounded-full px-2 py-0.5 text-xs font-medium ${TAG_COLORS[tag] ?? "bg-gray-100 text-gray-600"}`}
            >
              <Tag className="h-2.5 w-2.5" />
              {tag}
            </span>
          ))}
        </div>
        <div className="flex items-center justify-between text-xs text-gray-400">
          <span>{photo.taken_at}</span>
          <span>{photo.uploader}</span>
        </div>
      </div>
    </div>
  );
}

export default function FieldPhotosPage() {
  const [photos, setPhotos] = useState<SitePhoto[]>([]);
  const [filterZone, setFilterZone] = useState<string>("all");
  const [filterTag, setFilterTag] = useState<string>("all");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const json = await get<{ data?: SitePhoto[] }>("/field/photos");
      setPhotos(Array.isArray(json?.data) ? json.data : []);
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

  const filtered = photos.filter((p) => {
    const zoneOk = filterZone === "all" || p.zone === filterZone;
    const tagOk = filterTag === "all" || p.tags.includes(filterTag);
    return zoneOk && tagOk;
  });

  const thisWeek = photos.filter((p) => p.taken_at >= "2026-05-18").length;
  const total = photos.length;
  const needsReview = photos.filter((p) => p.needs_review).length;

  const statCards = [
    {
      label: "今週アップロード",
      value: thisWeek,
      sub: "5/18〜5/24",
      icon: Upload,
      color: "text-blue-500 bg-blue-50",
    },
    {
      label: "総写真数",
      value: total,
      sub: "全期間",
      icon: Camera,
      color: "text-purple-500 bg-purple-50",
    },
    {
      label: "要確認",
      value: needsReview,
      sub: "レビュー待ち",
      icon: AlertCircle,
      color:
        needsReview > 0
          ? "text-red-500 bg-red-50"
          : "text-green-500 bg-green-50",
    },
  ];

  return (
    <div className="p-6 lg:p-8 space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">現場写真管理</h1>
          <p className="mt-1 text-sm text-gray-500">
            工区別の現場写真をアップロード・閲覧・管理します
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
            <Upload className="h-4 w-4" />
            写真をアップロード
          </button>
        </div>
      </div>

      {error && (
        <div role="alert" aria-live="assertive" className="rounded-xl border border-danger-500/30 bg-danger-50 px-4 py-3 text-sm text-danger-700">
          {error}
        </div>
      )}
      {!loading && !error && photos.length === 0 && (
        <div className="rounded-xl border border-gray-200 bg-white px-4 py-8 text-center text-sm text-gray-500">
          該当データがありません。
        </div>
      )}

      {/* KPI Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
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

      {/* Filters */}
      <div className="flex flex-wrap gap-4 items-center">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-xs font-medium text-gray-500">工区:</span>
          <button
            onClick={() => setFilterZone("all")}
            className={`rounded-full px-3 py-1 text-xs font-medium transition-colors ${filterZone === "all" ? "bg-blue-600 text-white" : "bg-gray-100 text-gray-600 hover:bg-gray-200"}`}
          >
            すべて
          </button>
          {ALL_ZONES.map((z) => (
            <button
              key={z}
              onClick={() => setFilterZone(z)}
              className={`rounded-full px-3 py-1 text-xs font-medium transition-colors ${filterZone === z ? "bg-blue-600 text-white" : "bg-gray-100 text-gray-600 hover:bg-gray-200"}`}
            >
              {z}
            </button>
          ))}
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-xs font-medium text-gray-500 flex items-center gap-1">
            <Tag className="h-3 w-3" />
            タグ:
          </span>
          <button
            onClick={() => setFilterTag("all")}
            className={`rounded-full px-3 py-1 text-xs font-medium transition-colors ${filterTag === "all" ? "bg-blue-600 text-white" : "bg-gray-100 text-gray-600 hover:bg-gray-200"}`}
          >
            すべて
          </button>
          {ALL_TAGS.map((t) => (
            <button
              key={t}
              onClick={() => setFilterTag(t)}
              className={`rounded-full px-3 py-1 text-xs font-medium transition-colors ${filterTag === t ? "bg-blue-600 text-white" : `${TAG_COLORS[t] ?? "bg-gray-100 text-gray-600"} hover:opacity-80`}`}
            >
              {t}
            </button>
          ))}
        </div>
      </div>

      {/* Photo Grid */}
      <div>
        <div className="flex items-center justify-between mb-3">
          <h2 className="font-bold text-gray-900 flex items-center gap-2">
            <Camera className="h-4 w-4 text-purple-500" />
            写真一覧
          </h2>
          <span className="text-xs text-gray-500">
            {filtered.length} 件表示
          </span>
        </div>
        {filtered.length === 0 ? (
          <div className="rounded-xl border border-gray-200 bg-white py-16 text-center text-sm text-gray-400">
            該当する写真はありません
          </div>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
            {filtered.map((photo) => (
              <PhotoCard key={photo.id} photo={photo} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
