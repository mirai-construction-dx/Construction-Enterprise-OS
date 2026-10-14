/**
 * `/api/v1/health/services`（auth サービス）の応答を画面表示用に正規化する。
 *
 * なぜ独立させるか（2026-10-14 の実測）:
 *   stg のダッシュボードで、**健全なサービスが「警告」と黄色で表示されていた**。
 *   API は `status: "healthy"` を返すのに、画面は `"running"` / `"operational"`
 *   だけを正常として扱っていたためである。同時に、API のフィールド名は
 *   `latency_ms` なのに画面は `latency` を読んでいたため、
 *   **レイテンシが一度も表示されていなかった**。
 *
 *   この写像は page.tsx に直書きされていてテストが無く、食い違いが残っていた。
 *   ここへ切り出してテストで固定する。
 */

export type ServiceHealthLevel = "healthy" | "degraded" | "down";

export type ServiceHealth = {
  name: string;
  status: string;
  level: ServiceHealthLevel;
  latency?: string;
  version?: string;
};

/** API の status 語彙を表示用の 3 段階へ写す。 */
export function toHealthLevel(status: string): ServiceHealthLevel {
  // API の語彙（healthy / degraded / unhealthy）。
  // running / operational は旧実装が想定していた語彙で、後方互換のため受ける。
  if (
    status === "healthy" ||
    status === "running" ||
    status === "operational"
  ) {
    return "healthy";
  }
  if (status === "degraded") {
    return "degraded";
  }
  return "down";
}

/** API の `latency_ms`（数値）を表示文字列にする。数値でなければ undefined。 */
export function formatLatency(latencyMs: unknown): string | undefined {
  return typeof latencyMs === "number" && Number.isFinite(latencyMs)
    ? `${latencyMs}ms`
    : undefined;
}

/** 1 件のサービスを正規化する。 */
export function normalizeService(raw: Record<string, unknown>): ServiceHealth {
  const status = String(raw.status ?? "unknown");
  return {
    name: String(raw.name ?? ""),
    status,
    level: toHealthLevel(status),
    latency: formatLatency(raw.latency_ms),
    version: raw.version ? String(raw.version) : undefined,
  };
}

/** 応答本文（`services` / `data` のどちらでも）から一覧を取り出す。 */
export function normalizeServices(payload: unknown): ServiceHealth[] {
  const body = payload as
    | { services?: unknown; data?: unknown }
    | null
    | undefined;
  const raw = body?.services ?? body?.data ?? [];
  return Array.isArray(raw)
    ? raw.map((item) => normalizeService(item as Record<string, unknown>))
    : [];
}
