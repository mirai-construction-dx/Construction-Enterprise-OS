"use client";

import { useState, useEffect, useCallback } from "react";
import { get, ApiError } from "@/lib/api-client";
import { Brain, Zap, Target, TrendingUp } from "lucide-react";

type ActionPriority = "critical" | "high" | "medium" | "low";
type QueueStatus = "running" | "queued" | "completed" | "failed";
type QueueTaskType = "予測" | "分析" | "最適化" | "異常検知" | "レポート";

interface AiRecommendation {
  id: number;
  priority: ActionPriority;
  action: string;
  estimatedEffect: string;
  confidence: number; // 0-100
  deadline: string;
  category: string;
}

interface ModelMetrics {
  id: number;
  modelName: string;
  purpose: string;
  accuracy: number; // 0-100
  lastTrained: string;
  nextTraining: string;
  dataPoints: number;
  status: "active" | "retraining" | "degraded";
}

interface QueueTask {
  id: string;
  taskName: string;
  type: QueueTaskType;
  priority: ActionPriority;
  status: QueueStatus;
  startedAt: string;
  estimatedDuration: string;
  progress: number; // 0-100
}

// API response types
interface AiModel {
  id: number | string;
  name?: string;
  model_name?: string;
  purpose?: string;
  description?: string;
  accuracy?: number;
  last_trained?: string;
  next_training?: string;
  data_points?: number;
  dataPoints?: number;
  status?: "active" | "retraining" | "degraded";
}

interface Report {
  id: number | string;
  [key: string]: unknown;
}

const RECOMMENDATIONS: AiRecommendation[] = [
  {
    id: 1,
    priority: "critical",
    action: "第3工区 掘削作業の安全帯着用率向上 — 即時朝礼による再教育を実施",
    estimatedEffect: "労働災害リスク 78%低減",
    confidence: 92,
    deadline: "2026-05-24",
    category: "安全",
  },
  {
    id: 2,
    priority: "critical",
    action: "GAS-003センサー検知エリアの換気設備を緊急稼働させる",
    estimatedEffect: "CO濃度を安全基準以下に低減",
    confidence: 97,
    deadline: "2026-05-24",
    category: "IoT",
  },
  {
    id: 3,
    priority: "high",
    action: "山岳トンネル工事の工程を見直し — 掘削サイクルを1日2回に増加",
    estimatedEffect: "遅延 12日→4日に短縮見込み",
    confidence: 84,
    deadline: "2026-05-28",
    category: "工程",
  },
  {
    id: 4,
    priority: "high",
    action: "港湾設備工事の追加原価を抑制 — 下請け単価の再交渉を推奨",
    estimatedEffect: "超過コスト 0.7億円削減可能",
    confidence: 76,
    deadline: "2026-05-30",
    category: "コスト",
  },
  {
    id: 5,
    priority: "medium",
    action: "コンクリート養生テントの温度管理を自動化 — IoT連携設定を更新",
    estimatedEffect: "品質不適合件数 30%削減",
    confidence: 81,
    deadline: "2026-06-02",
    category: "品質",
  },
  {
    id: 6,
    priority: "medium",
    action: "DT-002ダンプトラックの燃料補給をスケジュール化（残量31%）",
    estimatedEffect: "稼働停止リスクを排除",
    confidence: 99,
    deadline: "2026-05-24",
    category: "重機",
  },
  {
    id: 7,
    priority: "low",
    action: "産廃リサイクル率向上のため分別指導マニュアルを更新",
    estimatedEffect: "リサイクル率 88.5%→92%目標",
    confidence: 65,
    deadline: "2026-06-15",
    category: "環境",
  },
  {
    id: 8,
    priority: "low",
    action: "BIM/CIMモデルと実工程データの自動同期設定を構築",
    estimatedEffect: "図面差異検出時間 60%短縮",
    confidence: 72,
    deadline: "2026-06-20",
    category: "DX",
  },
];

const MODEL_METRICS: ModelMetrics[] = [
  {
    id: 1,
    modelName: "工程遅延予測モデル",
    purpose: "工程遅延リスクの早期検知",
    accuracy: 87.3,
    lastTrained: "2026-05-10",
    nextTraining: "2026-06-10",
    dataPoints: 42800,
    status: "active",
  },
  {
    id: 2,
    modelName: "コスト超過予測モデル",
    purpose: "予算超過リスクのスコアリング",
    accuracy: 82.1,
    lastTrained: "2026-05-01",
    nextTraining: "2026-06-01",
    dataPoints: 31200,
    status: "active",
  },
  {
    id: 3,
    modelName: "安全インシデント予測",
    purpose: "作業員の危険行動・環境リスク検知",
    accuracy: 91.5,
    lastTrained: "2026-05-20",
    nextTraining: "2026-06-20",
    dataPoints: 158400,
    status: "active",
  },
  {
    id: 4,
    modelName: "重機故障予知モデル",
    purpose: "IoTデータによる故障予知保全",
    accuracy: 78.8,
    lastTrained: "2026-04-28",
    nextTraining: "2026-05-28",
    dataPoints: 94600,
    status: "retraining",
  },
  {
    id: 5,
    modelName: "品質不適合検知モデル",
    purpose: "コンクリート強度・寸法異常の検知",
    accuracy: 93.2,
    lastTrained: "2026-05-15",
    nextTraining: "2026-06-15",
    dataPoints: 27500,
    status: "active",
  },
  {
    id: 6,
    modelName: "環境負荷最適化モデル",
    purpose: "CO₂排出・騒音・PM2.5の最適化提案",
    accuracy: 71.4,
    lastTrained: "2026-04-15",
    nextTraining: "2026-05-15",
    dataPoints: 18900,
    status: "degraded",
  },
];

const QUEUE_TASKS: QueueTask[] = [
  {
    id: "Q001",
    taskName: "全現場 週次リスクスコア算出",
    type: "予測",
    priority: "high",
    status: "running",
    startedAt: "09:00:12",
    estimatedDuration: "8分",
    progress: 63,
  },
  {
    id: "Q002",
    taskName: "IoTセンサー異常パターン学習",
    type: "異常検知",
    priority: "high",
    status: "running",
    startedAt: "09:02:45",
    estimatedDuration: "15分",
    progress: 28,
  },
  {
    id: "Q003",
    taskName: "山岳トンネル工程最適化シミュレーション",
    type: "最適化",
    priority: "medium",
    status: "queued",
    startedAt: "—",
    estimatedDuration: "22分",
    progress: 0,
  },
  {
    id: "Q004",
    taskName: "5月度コスト分析レポート生成",
    type: "レポート",
    priority: "medium",
    status: "queued",
    startedAt: "—",
    estimatedDuration: "5分",
    progress: 0,
  },
  {
    id: "Q005",
    taskName: "重機稼働パターン分析",
    type: "分析",
    priority: "low",
    status: "completed",
    startedAt: "08:30:00",
    estimatedDuration: "12分",
    progress: 100,
  },
  {
    id: "Q006",
    taskName: "品質不適合傾向分析",
    type: "分析",
    priority: "medium",
    status: "completed",
    startedAt: "08:15:22",
    estimatedDuration: "9分",
    progress: 100,
  },
  {
    id: "Q007",
    taskName: "環境負荷最適化モデル再学習",
    type: "予測",
    priority: "low",
    status: "failed",
    startedAt: "07:45:00",
    estimatedDuration: "30分",
    progress: 42,
  },
];

const PRIORITY_CONFIG: Record<
  ActionPriority,
  { label: string; badge: string; dot: string }
> = {
  critical: {
    label: "緊急",
    badge: "bg-red-100 text-red-800",
    dot: "bg-red-500",
  },
  high: {
    label: "高",
    badge: "bg-orange-100 text-orange-800",
    dot: "bg-orange-500",
  },
  medium: {
    label: "中",
    badge: "bg-yellow-100 text-yellow-800",
    dot: "bg-yellow-500",
  },
  low: {
    label: "低",
    badge: "bg-gray-100 text-gray-600",
    dot: "bg-gray-400",
  },
};

const STATUS_CONFIG: Record<QueueStatus, { label: string; badge: string }> = {
  running: { label: "実行中", badge: "bg-blue-100 text-blue-800" },
  queued: { label: "待機中", badge: "bg-gray-100 text-gray-600" },
  completed: { label: "完了", badge: "bg-green-100 text-green-800" },
  failed: { label: "失敗", badge: "bg-red-100 text-red-800" },
};

const MODEL_STATUS_CONFIG: Record<
  ModelMetrics["status"],
  { label: string; badge: string }
> = {
  active: { label: "稼働中", badge: "bg-green-100 text-green-800" },
  retraining: { label: "再学習中", badge: "bg-blue-100 text-blue-800" },
  degraded: { label: "精度低下", badge: "bg-red-100 text-red-800" },
};

export default function AiDashboardPage() {
  const [modelMetrics, setModelMetrics] = useState<ModelMetrics[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const [modelsRes, reportsRes] = await Promise.allSettled([
        get<AiModel[] | { items: AiModel[] }>("/ai/models?per_page=10"),
        get<unknown>("/analytics/reports?per_page=5"),
      ]);

      if (modelsRes.status === "fulfilled") {
        const json = modelsRes.value;
        const items: AiModel[] = Array.isArray(json)
          ? json
          : (json?.items ?? []);

        setModelMetrics(
          items.map((m, idx) => ({
            id: typeof m.id === "number" ? m.id : idx + 1,
            modelName: m.name ?? m.model_name ?? `モデル ${idx + 1}`,
            purpose: m.purpose ?? m.description ?? "",
            accuracy: m.accuracy ?? 0,
            lastTrained: m.last_trained ?? "—",
            nextTraining: m.next_training ?? "—",
            dataPoints: m.data_points ?? m.dataPoints ?? 0,
            status: m.status ?? "active",
          })),
        );
      }
      setError(
        modelsRes.status === "fulfilled"
          ? null
          : modelsRes.reason instanceof ApiError &&
              modelsRes.reason.status === 403
            ? "権限がありません。"
            : "データを取得できませんでした。",
      );

      // reportsRes currently unused — available for future extension
      void reportsRes;
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const critical = RECOMMENDATIONS.filter(
    (r) => r.priority === "critical",
  ).length;
  const avgAccuracy =
    modelMetrics.length > 0
      ? modelMetrics.reduce((a, m) => a + m.accuracy, 0) / modelMetrics.length
      : 0;
  const running = QUEUE_TASKS.filter((t) => t.status === "running").length;
  const failed = QUEUE_TASKS.filter((t) => t.status === "failed").length;

  const stats = [
    {
      label: "緊急推奨アクション",
      value: `${critical}件`,
      sub: `全${RECOMMENDATIONS.length}件中`,
      icon: Zap,
      color: "text-red-600",
      bg: "bg-red-50",
    },
    {
      label: "平均モデル精度",
      value: `${avgAccuracy.toFixed(1)}%`,
      sub: `${modelMetrics.length}モデル稼働`,
      icon: Brain,
      color: "text-purple-600",
      bg: "bg-purple-50",
    },
    {
      label: "実行中タスク",
      value: `${running}件`,
      sub: "AIキュー内",
      icon: Target,
      color: "text-blue-600",
      bg: "bg-blue-50",
    },
    {
      label: "要確認（失敗）",
      value: `${failed}件`,
      sub: "再実行が必要",
      icon: TrendingUp,
      color: "text-orange-600",
      bg: "bg-orange-50",
    },
  ];

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">
            AI分析ダッシュボード
          </h1>
          <p className="text-sm text-gray-500 mt-1">
            ダッシュボード — AI推奨アクション・予測精度・処理キュー
          </p>
        </div>
        <div className="flex items-center gap-3">
          {loading && (
            <span className="text-xs text-blue-600 bg-blue-50 px-2 py-1 rounded-full animate-pulse">
              データ取得中...
            </span>
          )}
          <Brain className="w-8 h-8 text-purple-600" />
        </div>
      </div>

      {error && (
        <div role="alert" aria-live="assertive" className="rounded-xl border border-danger-500/30 bg-danger-50 px-4 py-3 text-sm text-danger-700">
          {error}
        </div>
      )}
      {!loading && !error && modelMetrics.length === 0 && (
        <div className="rounded-xl border border-gray-200 bg-white px-4 py-8 text-center text-sm text-gray-500">
          該当データがありません。
        </div>
      )}

      {/* 統計カード */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        {stats.map((s) => {
          const Icon = s.icon;
          return (
            <div key={s.label} className="bg-white rounded-lg border p-4">
              <div
                className={`w-10 h-10 rounded-lg ${s.bg} flex items-center justify-center mb-3`}
              >
                <Icon className={`w-5 h-5 ${s.color}`} />
              </div>
              <p className="text-xs text-gray-500">{s.label}</p>
              <p className="text-xl font-bold text-gray-900 mt-0.5">
                {s.value}
              </p>
              <p className="text-xs text-gray-400 mt-1">{s.sub}</p>
            </div>
          );
        })}
      </div>

      {/* AI推奨アクションリスト */}
      <div className="bg-white rounded-lg border overflow-hidden">
        <div className="px-4 py-3 border-b bg-gray-50 flex items-center gap-2">
          <Zap className="w-4 h-4 text-yellow-500" />
          <h2 className="font-semibold text-gray-700">
            AI推奨アクション ({RECOMMENDATIONS.length}件)
          </h2>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 border-b">
              <tr>
                <th className="px-4 py-3 text-left font-medium text-gray-600">
                  優先度
                </th>
                <th className="px-4 py-3 text-left font-medium text-gray-600">
                  アクション内容
                </th>
                <th className="px-4 py-3 text-left font-medium text-gray-600">
                  推定効果
                </th>
                <th className="px-4 py-3 text-right font-medium text-gray-600">
                  信頼度
                </th>
                <th className="px-4 py-3 text-left font-medium text-gray-600">
                  実施期限
                </th>
                <th className="px-4 py-3 text-left font-medium text-gray-600">
                  カテゴリ
                </th>
              </tr>
            </thead>
            <tbody className="divide-y">
              {RECOMMENDATIONS.map((rec) => (
                <tr
                  key={rec.id}
                  className={`hover:brightness-95 transition-all ${rec.priority === "critical" ? "bg-red-50" : rec.priority === "high" ? "bg-orange-50" : ""}`}
                >
                  <td className="px-4 py-3">
                    <span
                      className={`inline-flex items-center gap-1 px-2 py-1 rounded-full text-xs font-medium ${PRIORITY_CONFIG[rec.priority].badge}`}
                    >
                      <span
                        className={`w-1.5 h-1.5 rounded-full ${PRIORITY_CONFIG[rec.priority].dot}`}
                      />
                      {PRIORITY_CONFIG[rec.priority].label}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-gray-900 max-w-xs">
                    {rec.action}
                  </td>
                  <td className="px-4 py-3 text-gray-600 text-xs max-w-xs">
                    {rec.estimatedEffect}
                  </td>
                  <td className="px-4 py-3 text-right">
                    <span
                      className={`font-semibold text-sm ${rec.confidence >= 90 ? "text-green-700" : rec.confidence >= 75 ? "text-blue-700" : "text-gray-600"}`}
                    >
                      {rec.confidence}%
                    </span>
                  </td>
                  <td className="px-4 py-3 text-gray-600 text-xs whitespace-nowrap">
                    {rec.deadline}
                  </td>
                  <td className="px-4 py-3">
                    <span className="px-2 py-0.5 bg-purple-100 text-purple-800 text-xs rounded-full">
                      {rec.category}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* 予測精度メトリクス */}
      <div className="bg-white rounded-lg border overflow-hidden">
        <div className="px-4 py-3 border-b bg-gray-50 flex items-center gap-2">
          <Brain className="w-4 h-4 text-purple-500" />
          <h2 className="font-semibold text-gray-700">
            予測モデル精度メトリクス
          </h2>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 border-b">
              <tr>
                <th className="px-4 py-3 text-left font-medium text-gray-600">
                  モデル名
                </th>
                <th className="px-4 py-3 text-left font-medium text-gray-600">
                  用途
                </th>
                <th className="px-4 py-3 text-left font-medium text-gray-600 w-40">
                  精度
                </th>
                <th className="px-4 py-3 text-right font-medium text-gray-600">
                  学習データ数
                </th>
                <th className="px-4 py-3 text-left font-medium text-gray-600">
                  最終学習日
                </th>
                <th className="px-4 py-3 text-left font-medium text-gray-600">
                  次回学習日
                </th>
                <th className="px-4 py-3 text-left font-medium text-gray-600">
                  状態
                </th>
              </tr>
            </thead>
            <tbody className="divide-y">
              {modelMetrics.map((m) => (
                <tr key={m.id} className="hover:bg-gray-50">
                  <td className="px-4 py-3 font-medium text-gray-900 text-xs">
                    {m.modelName}
                  </td>
                  <td className="px-4 py-3 text-gray-600 text-xs">
                    {m.purpose}
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-2">
                      <div className="w-20 h-2.5 bg-gray-200 rounded-full overflow-hidden">
                        <div
                          className={`h-full rounded-full ${m.accuracy >= 90 ? "bg-green-500" : m.accuracy >= 80 ? "bg-blue-500" : m.accuracy >= 70 ? "bg-yellow-500" : "bg-red-500"}`}
                          style={{ width: `${m.accuracy}%` }}
                        />
                      </div>
                      <span className="text-xs font-semibold text-gray-700">
                        {m.accuracy}%
                      </span>
                    </div>
                  </td>
                  <td className="px-4 py-3 text-right font-mono text-xs text-gray-600">
                    {m.dataPoints.toLocaleString()}
                  </td>
                  <td className="px-4 py-3 text-gray-500 text-xs">
                    {m.lastTrained}
                  </td>
                  <td className="px-4 py-3 text-gray-500 text-xs">
                    {m.nextTraining}
                  </td>
                  <td className="px-4 py-3">
                    <span
                      className={`px-2 py-1 rounded-full text-xs font-medium ${MODEL_STATUS_CONFIG[m.status].badge}`}
                    >
                      {MODEL_STATUS_CONFIG[m.status].label}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* AI処理キュー */}
      <div className="bg-white rounded-lg border overflow-hidden">
        <div className="px-4 py-3 border-b bg-gray-50 flex items-center gap-2">
          <Target className="w-4 h-4 text-blue-500" />
          <h2 className="font-semibold text-gray-700">AI処理キュー</h2>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 border-b">
              <tr>
                <th className="px-4 py-3 text-left font-medium text-gray-600">
                  タスクID
                </th>
                <th className="px-4 py-3 text-left font-medium text-gray-600">
                  タスク名
                </th>
                <th className="px-4 py-3 text-left font-medium text-gray-600">
                  種別
                </th>
                <th className="px-4 py-3 text-left font-medium text-gray-600">
                  優先度
                </th>
                <th className="px-4 py-3 text-left font-medium text-gray-600">
                  ステータス
                </th>
                <th className="px-4 py-3 text-left font-medium text-gray-600 w-32">
                  進捗
                </th>
                <th className="px-4 py-3 text-left font-medium text-gray-600">
                  開始時刻
                </th>
                <th className="px-4 py-3 text-left font-medium text-gray-600">
                  所要時間
                </th>
              </tr>
            </thead>
            <tbody className="divide-y">
              {QUEUE_TASKS.map((task) => (
                <tr key={task.id} className="hover:bg-gray-50">
                  <td className="px-4 py-3 font-mono text-xs text-gray-500">
                    {task.id}
                  </td>
                  <td className="px-4 py-3 font-medium text-gray-900 text-xs">
                    {task.taskName}
                  </td>
                  <td className="px-4 py-3">
                    <span className="px-2 py-0.5 bg-indigo-100 text-indigo-800 text-xs rounded-full">
                      {task.type}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    <span
                      className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium ${PRIORITY_CONFIG[task.priority].badge}`}
                    >
                      {PRIORITY_CONFIG[task.priority].label}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    <span
                      className={`px-2 py-1 rounded-full text-xs font-medium ${STATUS_CONFIG[task.status].badge}`}
                    >
                      {STATUS_CONFIG[task.status].label}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    {task.status === "queued" ? (
                      <span className="text-xs text-gray-400">—</span>
                    ) : (
                      <div className="flex items-center gap-2">
                        <div className="w-16 h-2 bg-gray-200 rounded-full overflow-hidden">
                          <div
                            className={`h-full rounded-full ${task.status === "failed" ? "bg-red-500" : task.status === "completed" ? "bg-green-500" : "bg-blue-500"}`}
                            style={{ width: `${task.progress}%` }}
                          />
                        </div>
                        <span className="text-xs text-gray-500">
                          {task.progress}%
                        </span>
                      </div>
                    )}
                  </td>
                  <td className="px-4 py-3 font-mono text-xs text-gray-500">
                    {task.startedAt}
                  </td>
                  <td className="px-4 py-3 text-xs text-gray-500">
                    {task.estimatedDuration}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="px-4 py-3 border-t bg-gray-50 text-xs text-gray-500">
          全 {QUEUE_TASKS.length} タスク —{" "}
          {QUEUE_TASKS.filter((t) => t.status === "running").length} 件実行中 /{" "}
          {QUEUE_TASKS.filter((t) => t.status === "queued").length} 件待機中
        </div>
      </div>
    </div>
  );
}
