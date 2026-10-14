"use client";

import { useState, useEffect, useCallback } from "react";
import { Users, UserPlus, UserCheck, Shield } from "lucide-react";
import { get, ApiError } from "@/lib/api-client";

type User = {
  id: number;
  name: string;
  email: string;
  title: string;
  role: string;
  lastLogin: string;
  status: string;
};

const STATUS_STYLES: Record<string, string> = {
  active: "bg-green-100 text-green-800",
  inactive: "bg-gray-100 text-gray-700",
  locked: "bg-red-100 text-red-800",
};

const STATUS_LABELS: Record<string, string> = {
  active: "アクティブ",
  inactive: "非アクティブ",
  locked: "ロック",
};

const ROLE_STYLES: Record<string, string> = {
  admin: "bg-red-100 text-red-800",
  manager: "bg-purple-100 text-purple-800",
  field: "bg-blue-100 text-blue-800",
  viewer: "bg-gray-100 text-gray-700",
};

const ROLE_LABELS: Record<string, string> = {
  admin: "管理者",
  manager: "マネージャー",
  field: "現場担当",
  viewer: "閲覧のみ",
};

function Avatar({ name }: { name: string }) {
  const initials = name
    .split(" ")
    .map((p) => p[0])
    .join("")
    .slice(0, 2);
  return (
    <div className="w-8 h-8 rounded-full bg-blue-500 text-white flex items-center justify-center text-xs font-bold flex-shrink-0">
      {initials}
    </div>
  );
}

export default function UsersPage() {
  const [users, setUsers] = useState<User[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const json = await get<{
        data?: { items?: Record<string, unknown>[] };
        items?: Record<string, unknown>[];
      }>("/users?per_page=50");
      const data = json?.data?.items ?? json?.items ?? json?.data ?? [];
      setUsers(
        Array.isArray(data)
          ? data.map((item: Record<string, unknown>) => ({
              id: Number(item.id ?? 0),
              name: String(item.full_name ?? item.username ?? ""),
              email: String(item.email ?? ""),
              title: String(item.title ?? item.role ?? ""),
              role: String(item.role ?? "field"),
              lastLogin: String(item.last_login_at ?? item.updated_at ?? ""),
              status: String(item.status ?? "active"),
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

  const total = users.length;
  const active = users.filter((u) => u.status === "active").length;
  const inactive = users.filter((u) => u.status === "inactive").length;
  const locked = users.filter((u) => u.status === "locked").length;

  return (
    <div className="space-y-6 p-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">ユーザー管理</h1>
          <p className="text-sm text-gray-500 mt-1">
            システム利用者の管理
            {loading && (
              <span className="ml-2 text-blue-500 animate-pulse">
                読み込み中...
              </span>
            )}
          </p>
        </div>
        <button className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white text-sm rounded-lg hover:bg-blue-700">
          <UserPlus className="w-4 h-4" />
          ユーザー招待
        </button>
      </div>

      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        <div className="bg-white rounded-xl border border-gray-200 p-4 flex items-center gap-3">
          <div className="p-2 bg-blue-50 rounded-lg">
            <Users className="w-5 h-5 text-blue-600" />
          </div>
          <div>
            <p className="text-xs text-gray-500">総ユーザー数</p>
            <p className="text-2xl font-bold text-gray-900">{total}</p>
          </div>
        </div>
        <div className="bg-white rounded-xl border border-gray-200 p-4 flex items-center gap-3">
          <div className="p-2 bg-green-50 rounded-lg">
            <UserCheck className="w-5 h-5 text-green-600" />
          </div>
          <div>
            <p className="text-xs text-gray-500">アクティブ</p>
            <p className="text-2xl font-bold text-gray-900">{active}</p>
          </div>
        </div>
        <div className="bg-white rounded-xl border border-gray-200 p-4 flex items-center gap-3">
          <div className="p-2 bg-gray-50 rounded-lg">
            <Users className="w-5 h-5 text-gray-500" />
          </div>
          <div>
            <p className="text-xs text-gray-500">非アクティブ</p>
            <p className="text-2xl font-bold text-gray-900">{inactive}</p>
          </div>
        </div>
        <div className="bg-white rounded-xl border border-gray-200 p-4 flex items-center gap-3">
          <div className="p-2 bg-red-50 rounded-lg">
            <Shield className="w-5 h-5 text-red-600" />
          </div>
          <div>
            <p className="text-xs text-gray-500">ロック</p>
            <p className="text-2xl font-bold text-gray-900">{locked}</p>
          </div>
        </div>
      </div>

      {error && (
        <div role="alert" aria-live="assertive" className="rounded-xl border border-danger-500/30 bg-danger-50 px-4 py-3 text-sm text-danger-700">
          {error}
        </div>
      )}
      {!loading && !error && users.length === 0 && (
        <div className="rounded-xl border border-gray-200 bg-white px-4 py-8 text-center text-sm text-gray-500">
          該当データがありません。
        </div>
      )}

      <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-gray-50 border-b border-gray-200">
                <th className="px-4 py-3 text-left font-semibold text-gray-600">
                  氏名
                </th>
                <th className="px-4 py-3 text-left font-semibold text-gray-600 whitespace-nowrap">
                  メール
                </th>
                <th className="px-4 py-3 text-left font-semibold text-gray-600 whitespace-nowrap">
                  役職
                </th>
                <th className="px-4 py-3 text-left font-semibold text-gray-600 whitespace-nowrap">
                  権限
                </th>
                <th className="px-4 py-3 text-left font-semibold text-gray-600 whitespace-nowrap">
                  最終ログイン
                </th>
                <th className="px-4 py-3 text-left font-semibold text-gray-600 whitespace-nowrap">
                  ステータス
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {users.map((user) => (
                <tr key={user.id} className="hover:bg-gray-50">
                  <td className="px-4 py-3 whitespace-nowrap">
                    <div className="flex items-center gap-3">
                      <Avatar name={user.name} />
                      <span className="font-medium text-gray-900">
                        {user.name}
                      </span>
                    </div>
                  </td>
                  <td className="px-4 py-3 text-gray-600 whitespace-nowrap">
                    {user.email}
                  </td>
                  <td className="px-4 py-3 text-gray-600 whitespace-nowrap">
                    {user.title}
                  </td>
                  <td className="px-4 py-3 whitespace-nowrap">
                    <span
                      className={`px-2 py-0.5 rounded-full text-xs font-medium ${ROLE_STYLES[user.role]}`}
                    >
                      {ROLE_LABELS[user.role]}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-gray-500 whitespace-nowrap text-xs">
                    {user.lastLogin}
                  </td>
                  <td className="px-4 py-3 whitespace-nowrap">
                    <span
                      className={`px-2 py-0.5 rounded-full text-xs font-medium ${STATUS_STYLES[user.status]}`}
                    >
                      {STATUS_LABELS[user.status]}
                    </span>
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
