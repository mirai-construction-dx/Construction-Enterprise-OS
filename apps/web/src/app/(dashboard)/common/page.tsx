"use client";

import { useState, useCallback, useEffect } from "react";
import Link from "next/link";
import {
  Settings,
  Users,
  Building,
  Key,
  Database,
  Webhook,
  CheckCircle,
  AlertTriangle,
} from "lucide-react";
import { get, ApiError } from "@/lib/api-client";

const CATEGORIES = [
  {
    title: "ユーザー管理",
    description: "システム利用者の登録・編集・停止を管理します",
    icon: Users,
    color: "blue",
    href: "/common/users",
  },
  {
    title: "組織管理",
    description: "部署・チーム・組織ツリーを管理します",
    icon: Building,
    color: "green",
    href: "/common/org",
  },
  {
    title: "権限管理",
    description: "ロール定義と機能モジュールへのアクセス権限を管理します",
    icon: Key,
    color: "purple",
    href: "/common/roles",
  },
  {
    title: "マスタデータ",
    description: "資材・単価・作業種別のマスタ情報を管理します",
    icon: Database,
    color: "orange",
    href: "/common/master/materials",
  },
  {
    title: "認証設定",
    description: "SSO・MFA・AD/Entra ID連携の認証設定を管理します",
    icon: Settings,
    color: "red",
    href: "/common/auth/sso",
  },
  {
    title: "API設定",
    description: "APIクライアントとWebhookエンドポイントを管理します",
    icon: Webhook,
    color: "teal",
    href: "/common/api/clients",
  },
];

const COLOR_MAP: Record<string, { bg: string; icon: string; btn: string }> = {
  blue: {
    bg: "bg-blue-50",
    icon: "text-blue-600",
    btn: "bg-blue-600 hover:bg-blue-700",
  },
  green: {
    bg: "bg-green-50",
    icon: "text-green-600",
    btn: "bg-green-600 hover:bg-green-700",
  },
  purple: {
    bg: "bg-purple-50",
    icon: "text-purple-600",
    btn: "bg-purple-600 hover:bg-purple-700",
  },
  orange: {
    bg: "bg-orange-50",
    icon: "text-orange-600",
    btn: "bg-orange-600 hover:bg-orange-700",
  },
  red: {
    bg: "bg-red-50",
    icon: "text-red-600",
    btn: "bg-red-600 hover:bg-red-700",
  },
  teal: {
    bg: "bg-teal-50",
    icon: "text-teal-600",
    btn: "bg-teal-600 hover:bg-teal-700",
  },
};

type ServiceStatus = {
  name: string;
  status: string;
  latency?: string;
  version?: string;
};

const SERVICES_DISPLAY = [
  {
    name: "PostgreSQL",
    type: "データベース",
    status: "running",
    latency: "2ms",
  },
  { name: "Redis", type: "キャッシュ", status: "running", latency: "0.5ms" },
  {
    name: "MinIO",
    type: "オブジェクトストレージ",
    status: "running",
    latency: "8ms",
  },
  {
    name: "Kafka",
    type: "メッセージブローカー",
    status: "warning",
    latency: "45ms",
  },
];

export default function CommonPage() {
  const [services, setServices] = useState<ServiceStatus[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const json = await get<{
        services?: Record<string, unknown>[];
        data?: Record<string, unknown>[];
      }>("/health/services");
      const rawServices: Record<string, unknown>[] =
        json?.services ?? json?.data ?? [];
      setServices(
        Array.isArray(rawServices)
          ? rawServices.map((s: Record<string, unknown>) => ({
              name: String(s.name ?? ""),
              status: String(s.status ?? "operational"),
              latency: s.latency ? String(s.latency) : undefined,
              version: s.version ? String(s.version) : undefined,
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

  const getServiceDisplay = (svcName: string) => {
    return SERVICES_DISPLAY.find((s) => s.name === svcName);
  };

  return (
    <div className="space-y-6 p-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">共通設定</h1>
        <p className="text-sm text-gray-500 mt-1">
          システム全体の設定・管理機能
        </p>
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {CATEGORIES.map((cat) => {
          const colors = COLOR_MAP[cat.color];
          const Icon = cat.icon;
          return (
            <div
              key={cat.title}
              className="bg-white rounded-xl border border-gray-200 p-5 flex flex-col gap-4"
            >
              <div className="flex items-center gap-3">
                <div className={`p-3 rounded-xl ${colors.bg}`}>
                  <Icon className={`w-6 h-6 ${colors.icon}`} />
                </div>
                <h2 className="text-base font-semibold text-gray-900">
                  {cat.title}
                </h2>
              </div>
              <p className="text-sm text-gray-500 flex-1">{cat.description}</p>
              <Link
                href={cat.href}
                className={`text-center px-4 py-2 rounded-lg text-white text-sm font-medium ${colors.btn} transition-colors`}
              >
                管理
              </Link>
            </div>
          );
        })}
      </div>

      {error && (
        <div role="alert" aria-live="assertive" className="rounded-xl border border-danger-500/30 bg-danger-50 px-4 py-3 text-sm text-danger-700">
          {error}
        </div>
      )}
      {!loading && !error && services.length === 0 && (
        <div className="rounded-xl border border-gray-200 bg-white px-4 py-8 text-center text-sm text-gray-500">
          該当データがありません。
        </div>
      )}

      <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
        <div className="px-5 py-4 border-b border-gray-200">
          <h2 className="text-base font-semibold text-gray-900">
            システムステータス
            {loading && (
              <span className="ml-2 text-xs text-gray-400 font-normal">
                読み込み中...
              </span>
            )}
          </h2>
        </div>
        <div className="divide-y divide-gray-100">
          {services.map((svc) => {
            const display = getServiceDisplay(svc.name);
            const type = display?.type ?? "";
            const latency = svc.latency ?? display?.latency ?? "";
            return (
              <div
                key={svc.name}
                className="flex items-center justify-between px-5 py-3"
              >
                <div className="flex items-center gap-3">
                  <div
                    className={`w-2 h-2 rounded-full ${svc.status === "running" || svc.status === "operational" ? "bg-green-500" : "bg-yellow-500"}`}
                  />
                  <span className="text-sm font-medium text-gray-900">
                    {svc.name}
                  </span>
                  <span className="text-xs text-gray-400">{type}</span>
                </div>
                <div className="flex items-center gap-4">
                  {latency && (
                    <span className="text-xs text-gray-500">
                      レイテンシ: {latency}
                    </span>
                  )}
                  {svc.status === "running" || svc.status === "operational" ? (
                    <span className="flex items-center gap-1 text-green-700 text-xs font-medium">
                      <CheckCircle className="w-4 h-4" /> 正常稼働
                    </span>
                  ) : (
                    <span className="flex items-center gap-1 text-yellow-700 text-xs font-medium">
                      <AlertTriangle className="w-4 h-4" /> 警告
                    </span>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
