import { describe, expect, it } from "vitest";

import {
  formatLatency,
  normalizeService,
  normalizeServices,
  toHealthLevel,
} from "../service-health";

/**
 * 2026-10-14 の実測で見つかった食い違いを固定する。
 *
 * - API は `status: "healthy"` を返すのに、画面は `"running"` / `"operational"`
 *   だけを正常として扱っており、**健全なサービスが「警告」と黄色で表示されていた**。
 * - API のフィールド名は `latency_ms` なのに、画面は `latency` を読んでいたため
 *   **レイテンシが一度も表示されていなかった**。
 */
describe("toHealthLevel", () => {
  it("API の語彙（healthy）を正常として扱う（回帰: 以前は警告になっていた）", () => {
    expect(toHealthLevel("healthy")).toBe("healthy");
  });

  it("degraded は警告にする", () => {
    expect(toHealthLevel("degraded")).toBe("degraded");
  });

  it("unhealthy と未知の語彙は停止として扱う（fail-closed）", () => {
    expect(toHealthLevel("unhealthy")).toBe("down");
    expect(toHealthLevel("unknown")).toBe("down");
    expect(toHealthLevel("")).toBe("down");
  });

  it("旧実装が想定していた語彙も後方互換で受ける", () => {
    expect(toHealthLevel("running")).toBe("healthy");
    expect(toHealthLevel("operational")).toBe("healthy");
  });
});

describe("formatLatency", () => {
  it("数値の latency_ms を表示文字列にする", () => {
    expect(formatLatency(12)).toBe("12ms");
    expect(formatLatency(0)).toBe("0ms");
  });

  it("数値でなければ undefined（嘘の値を作らない）", () => {
    expect(formatLatency(undefined)).toBeUndefined();
    expect(formatLatency("12")).toBeUndefined();
    expect(formatLatency(Number.NaN)).toBeUndefined();
    expect(formatLatency(null)).toBeUndefined();
  });
});

describe("normalizeService", () => {
  it("API の応答（auth の /health/services の 1 件）を正しく写す", () => {
    expect(
      normalizeService({
        name: "auth",
        status: "healthy",
        latency_ms: 2,
        version: "0.1.0",
      }),
    ).toEqual({
      name: "auth",
      status: "healthy",
      level: "healthy",
      latency: "2ms",
      version: "0.1.0",
    });
  });

  it("latency_ms が無いときは latency を埋めない（モック値で埋めない）", () => {
    const result = normalizeService({ name: "redis", status: "healthy" });
    expect(result.latency).toBeUndefined();
  });

  it("status が無いときは unknown（＝停止）として扱う", () => {
    expect(normalizeService({ name: "x" }).level).toBe("down");
  });
});

describe("normalizeServices", () => {
  it("services 配列を写す", () => {
    const result = normalizeServices({
      services: [
        { name: "auth", status: "healthy", latency_ms: 2 },
        { name: "vision", status: "unhealthy", latency_ms: 2024 },
      ],
      overall: "unhealthy",
    });
    expect(result.map((s) => [s.name, s.level])).toEqual([
      ["auth", "healthy"],
      ["vision", "down"],
    ]);
    expect(result[1].latency).toBe("2024ms");
  });

  it("data 配列でも受ける（APIResponse 形式）", () => {
    expect(
      normalizeServices({ data: [{ name: "a", status: "healthy" }] }),
    ).toHaveLength(1);
  });

  it("配列でなければ空を返す（画面を壊さない）", () => {
    expect(normalizeServices(null)).toEqual([]);
    expect(normalizeServices({ services: "x" })).toEqual([]);
    expect(normalizeServices(undefined)).toEqual([]);
  });
});
