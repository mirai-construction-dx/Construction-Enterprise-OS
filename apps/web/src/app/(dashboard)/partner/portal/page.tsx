"use client";

import { useState, useEffect, useCallback } from "react";
import {
  Bell,
  FileDown,
  Newspaper,
  Download,
  AlertCircle,
  Info,
  CheckCircle,
  Building2,
} from "lucide-react";
import { get, ApiError } from "@/lib/api-client";

interface Notice {
  id: string;
  title: string;
  category: string;
  date: string;
  importance: "high" | "normal" | "low";
  isRead: boolean;
}

interface SharedDocument {
  id: string;
  name: string;
  type: string;
  updatedAt: string;
  fileSize: string;
}

interface Partner {
  id: string;
  name: string;
  partner_type: string;
  status: string;
  rating: number;
  email: string;
  phone: string;
  address: string;
}

const MOCK_NOTICES: Notice[] = [
  {
    id: "N-001",
    title: "2026年度安全管理基準の改定について",
    category: "安全管理",
    date: "2026-05-20",
    importance: "high",
    isRead: false,
  },
  {
    id: "N-002",
    title: "6月分請求書提出期限のご案内",
    category: "経理・請求",
    date: "2026-05-18",
    importance: "high",
    isRead: false,
  },
  {
    id: "N-003",
    title: "熱中症対策強化期間のお知らせ（6〜9月）",
    category: "安全管理",
    date: "2026-05-15",
    importance: "normal",
    isRead: true,
  },
  {
    id: "N-004",
    title: "施工体制台帳の電子化対応について",
    category: "書類手続き",
    date: "2026-05-10",
    importance: "normal",
    isRead: false,
  },
  {
    id: "N-005",
    title: "新規登録協力会社向け説明会の開催案内",
    category: "お知らせ",
    date: "2026-05-08",
    importance: "low",
    isRead: true,
  },
  {
    id: "N-006",
    title: "品川タワー現場入退場ルール変更のご案内",
    category: "現場管理",
    date: "2026-05-01",
    importance: "normal",
    isRead: true,
  },
];

const MOCK_DOCUMENTS: SharedDocument[] = [
  {
    id: "D-001",
    name: "2026年度 安全衛生管理規程",
    type: "規程・基準",
    updatedAt: "2026-05-01",
    fileSize: "2.4 MB",
  },
  {
    id: "D-002",
    name: "施工体制台帳（様式）",
    type: "書類様式",
    updatedAt: "2026-04-15",
    fileSize: "0.8 MB",
  },
  {
    id: "D-003",
    name: "作業員名簿（電子化対応版）",
    type: "書類様式",
    updatedAt: "2026-04-10",
    fileSize: "0.5 MB",
  },
  {
    id: "D-004",
    name: "品質管理検査チェックシート",
    type: "検査記録",
    updatedAt: "2026-03-28",
    fileSize: "1.2 MB",
  },
  {
    id: "D-005",
    name: "請求書・領収書テンプレート集",
    type: "書類様式",
    updatedAt: "2026-03-20",
    fileSize: "3.1 MB",
  },
  {
    id: "D-006",
    name: "工事写真管理マニュアル",
    type: "マニュアル",
    updatedAt: "2026-03-01",
    fileSize: "8.5 MB",
  },
  {
    id: "D-007",
    name: "環境保全対策基準書",
    type: "規程・基準",
    updatedAt: "2026-02-15",
    fileSize: "1.9 MB",
  },
  {
    id: "D-008",
    name: "緊急連絡先一覧（2026年度版）",
    type: "連絡先",
    updatedAt: "2026-01-10",
    fileSize: "0.3 MB",
  },
];

const IMPORTANCE_CONFIG = {
  high: { label: "重要", color: "bg-red-100 text-red-700", icon: AlertCircle },
  normal: { label: "通常", color: "bg-blue-100 text-blue-700", icon: Info },
  low: { label: "参考", color: "bg-gray-100 text-gray-600", icon: CheckCircle },
};

const DOC_TYPE_COLORS: Record<string, string> = {
  "規程・基準": "bg-purple-100 text-purple-700",
  書類様式: "bg-blue-100 text-blue-700",
  検査記録: "bg-green-100 text-green-700",
  マニュアル: "bg-yellow-100 text-yellow-700",
  連絡先: "bg-gray-100 text-gray-700",
};

export default function PartnerPortalPage() {
  const [partners, setPartners] = useState<Partner[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const json = await get<{
        data?: { items?: Record<string, unknown>[] };
        items?: Record<string, unknown>[];
      }>("/partner?status=active&per_page=50");
      const data: Record<string, unknown>[] =
        json?.data?.items ?? json?.items ?? [];
      setPartners(
        Array.isArray(data)
          ? data.map((item) => ({
              id: String(item.id ?? ""),
              name: String(item.name ?? ""),
              partner_type: String(item.partner_type ?? ""),
              status: String(item.status ?? ""),
              rating: Number(item.rating ?? 0),
              email: String(item.email ?? ""),
              phone: String(item.phone ?? ""),
              address: String(item.address ?? ""),
            }))
          : [],
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

  const unreadCount = MOCK_NOTICES.filter((n) => !n.isRead).length;
  const highCount = MOCK_NOTICES.filter(
    (n) => n.importance === "high" && !n.isRead,
  ).length;

  return (
    <div className="p-6 space-y-6">
      {/* ヘッダー */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">協力会社ポータル</h1>
          <p className="text-sm text-gray-500 mt-1">
            お知らせ・書類共有ポータル
          </p>
        </div>
        <div className="flex items-center gap-3">
          {loading && (
            <span className="text-xs text-blue-500 animate-pulse">
              データ取得中...
            </span>
          )}
        </div>
      </div>

      {error && (
        <div role="alert" aria-live="assertive" className="rounded-xl border border-danger-500/30 bg-danger-50 px-4 py-3 text-sm text-danger-700">
          {error}
        </div>
      )}
      {!loading && !error && partners.length === 0 && (
        <div className="rounded-xl border border-gray-200 bg-white px-4 py-8 text-center text-sm text-gray-500">
          該当データがありません。
        </div>
      )}

      {/* 統計カード */}
      <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
        <div className="bg-white rounded-xl p-4 shadow-sm border border-gray-100">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-red-50 rounded-lg">
              <Bell className="w-5 h-5 text-red-600" />
            </div>
            <div>
              <p className="text-xs text-gray-500">未読お知らせ</p>
              <p className="text-2xl font-bold text-gray-900">{unreadCount}</p>
              {highCount > 0 && (
                <p className="text-xs text-red-600">重要 {highCount}件</p>
              )}
            </div>
          </div>
        </div>
        <div className="bg-white rounded-xl p-4 shadow-sm border border-gray-100">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-blue-50 rounded-lg">
              <FileDown className="w-5 h-5 text-blue-600" />
            </div>
            <div>
              <p className="text-xs text-gray-500">共有書類数</p>
              <p className="text-2xl font-bold text-gray-900">
                {MOCK_DOCUMENTS.length}
              </p>
            </div>
          </div>
        </div>
        <div className="bg-white rounded-xl p-4 shadow-sm border border-gray-100">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-green-50 rounded-lg">
              <Newspaper className="w-5 h-5 text-green-600" />
            </div>
            <div>
              <p className="text-xs text-gray-500">今月ダウンロード</p>
              <p className="text-2xl font-bold text-gray-900">47</p>
            </div>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* お知らせリスト */}
        <div className="bg-white rounded-xl shadow-sm border border-gray-100 overflow-hidden">
          <div className="px-5 py-4 border-b border-gray-100 flex items-center justify-between">
            <h2 className="font-semibold text-gray-800 flex items-center gap-2">
              <Bell className="w-4 h-4 text-blue-600" />
              最新お知らせ
            </h2>
            <span className="text-xs text-gray-500">
              {MOCK_NOTICES.length}件
            </span>
          </div>
          <div className="divide-y divide-gray-50">
            {MOCK_NOTICES.map((notice) => {
              const cfg = IMPORTANCE_CONFIG[notice.importance];
              const Icon = cfg.icon;
              return (
                <div
                  key={notice.id}
                  className={`px-5 py-3 hover:bg-gray-50 transition-colors cursor-pointer ${!notice.isRead ? "bg-blue-50/40" : ""}`}
                >
                  <div className="flex items-start gap-3">
                    <div className="mt-0.5">
                      {!notice.isRead && (
                        <span className="inline-block w-2 h-2 rounded-full bg-blue-500 mt-1" />
                      )}
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 mb-1">
                        <span
                          className={`px-1.5 py-0.5 rounded text-xs font-medium ${cfg.color}`}
                        >
                          <span className="flex items-center gap-0.5">
                            <Icon className="w-3 h-3" />
                            {cfg.label}
                          </span>
                        </span>
                        <span className="bg-gray-100 text-gray-600 px-1.5 py-0.5 rounded text-xs">
                          {notice.category}
                        </span>
                      </div>
                      <p
                        className={`text-sm ${!notice.isRead ? "font-semibold text-gray-900" : "text-gray-700"} truncate`}
                      >
                        {notice.title}
                      </p>
                      <p className="text-xs text-gray-400 mt-0.5">
                        {notice.date}
                      </p>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
          <div className="px-5 py-3 border-t border-gray-100">
            <button className="text-sm text-blue-600 hover:underline">
              すべてのお知らせを見る →
            </button>
          </div>
        </div>

        {/* 共有書類リスト */}
        <div className="bg-white rounded-xl shadow-sm border border-gray-100 overflow-hidden">
          <div className="px-5 py-4 border-b border-gray-100 flex items-center justify-between">
            <h2 className="font-semibold text-gray-800 flex items-center gap-2">
              <FileDown className="w-4 h-4 text-green-600" />
              共有書類
            </h2>
            <span className="text-xs text-gray-500">
              {MOCK_DOCUMENTS.length}件
            </span>
          </div>
          <div className="divide-y divide-gray-50">
            {MOCK_DOCUMENTS.map((doc) => (
              <div
                key={doc.id}
                className="px-5 py-3 hover:bg-gray-50 transition-colors flex items-center justify-between gap-3"
              >
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium text-gray-900 truncate">
                    {doc.name}
                  </p>
                  <div className="flex items-center gap-2 mt-1">
                    <span
                      className={`px-1.5 py-0.5 rounded text-xs ${DOC_TYPE_COLORS[doc.type] ?? "bg-gray-100 text-gray-600"}`}
                    >
                      {doc.type}
                    </span>
                    <span className="text-xs text-gray-400">
                      {doc.updatedAt} 更新
                    </span>
                    <span className="text-xs text-gray-400">
                      {doc.fileSize}
                    </span>
                  </div>
                </div>
                <button className="flex items-center gap-1 text-xs text-blue-600 hover:text-blue-800 whitespace-nowrap border border-blue-200 rounded px-2 py-1 hover:bg-blue-50 transition-colors">
                  <Download className="w-3 h-3" />
                  DL
                </button>
              </div>
            ))}
          </div>
          <div className="px-5 py-3 border-t border-gray-100">
            <button className="text-sm text-blue-600 hover:underline">
              すべての書類を見る →
            </button>
          </div>
        </div>
      </div>

      {/* 協力会社一覧（APIから取得） */}
      {partners.length > 0 && (
        <div className="bg-white rounded-xl shadow-sm border border-gray-100 overflow-hidden">
          <div className="px-5 py-4 border-b border-gray-100 flex items-center justify-between">
            <h2 className="font-semibold text-gray-800 flex items-center gap-2">
              <Building2 className="w-4 h-4 text-purple-600" />
              登録協力会社
            </h2>
            <span className="text-xs text-gray-500">{partners.length}社</span>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-gray-50 border-b">
                <tr>
                  <th className="px-4 py-3 text-left font-medium text-gray-600">
                    会社名
                  </th>
                  <th className="px-4 py-3 text-left font-medium text-gray-600">
                    種別
                  </th>
                  <th className="px-4 py-3 text-left font-medium text-gray-600">
                    ステータス
                  </th>
                  <th className="px-4 py-3 text-left font-medium text-gray-600">
                    評価
                  </th>
                  <th className="px-4 py-3 text-left font-medium text-gray-600">
                    連絡先
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y">
                {partners.map((partner) => (
                  <tr
                    key={partner.id}
                    className="hover:bg-gray-50 transition-colors"
                  >
                    <td className="px-4 py-3 font-medium text-gray-900">
                      {partner.name}
                    </td>
                    <td className="px-4 py-3 text-gray-600 text-xs">
                      {partner.partner_type}
                    </td>
                    <td className="px-4 py-3">
                      <span className="inline-flex items-center gap-1 px-2 py-1 rounded-full text-xs font-medium bg-green-100 text-green-800">
                        {partner.status}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-gray-700">
                      {"★".repeat(Math.min(5, Math.round(partner.rating)))}
                      <span className="text-gray-400 text-xs ml-1">
                        ({partner.rating.toFixed(1)})
                      </span>
                    </td>
                    <td className="px-4 py-3 text-gray-600 text-xs">
                      {partner.email}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
