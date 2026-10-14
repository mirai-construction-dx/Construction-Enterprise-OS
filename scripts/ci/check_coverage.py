#!/usr/bin/env python3
"""各サービス・パッケージが CI のどこかで検査されているかを検証する。

なぜ必要か（2026-10-14 の実測）:
    `.github/workflows/ci.yml` の各マトリクスは**手書きのサービス一覧**である。
    コメントにも "keep in sync when adding a service" と書かれているが、機械的な検査が無い。
    実際、`services/erp` は基盤 DDL の生成対象から漏れており（別の検査で検出・修正した）、
    同じ「宣言されているが配線されていない」型の欠落が CI でも起こりうる。

検査する内容:
    C-1 `services/` 配下の実サービス（`src/` を持つディレクトリ）が、
        いずれかのワークフローのマトリクス・`working-directory` のいずれかで参照されていること。
    C-2 `packages/` 配下の各パッケージが同様に参照されていること、
        または INDIRECTLY_COVERED に理由つきで宣言されていること。

`SKIP` を作らない。判定できないものは FAIL として報告する（`AGENTS.md` §4.7）。

使い方:
    python3 scripts/ci/check_coverage.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
WORKFLOWS = REPO / ".github" / "workflows"
SERVICES = REPO / "services"
PACKAGES = REPO / "packages"

# 直接の検査ジョブを持たないが、他の経路で検査されているもの（理由を必ず書く）。
# ここに足すときは「なぜ直接のジョブが不要か」を実測で説明できることにする。
INDIRECTLY_COVERED: dict[str, str] = {
    "packages/core": "apps/web の typecheck / lint が pnpm workspace 経由で src を型検査する（独自テストなし）",
    "packages/ui": "apps/web の typecheck / lint が pnpm workspace 経由で src を型検査する（独自テストなし）",
    "packages/auth-core": "services/* が依存として install し、各サービスのテストが import して実行する（独自テストなし）",
}


def collect_referenced() -> set[str]:
    """ワークフロー群が参照する `services/<name>` / `packages/<name>` を集める。"""
    referenced: set[str] = set()
    for path in sorted(WORKFLOWS.glob("*.y*ml")):
        document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for job in (document.get("jobs") or {}).values():
            if not isinstance(job, dict):
                continue
            matrix = (job.get("strategy") or {}).get("matrix") or {}
            if isinstance(matrix, dict):
                for values in matrix.values():
                    if isinstance(values, list):
                        for value in values:
                            if isinstance(value, str) and value.startswith(("services/", "packages/")):
                                referenced.add(value)
            # defaults.run.working-directory / steps[].working-directory
            defaults = ((job.get("defaults") or {}).get("run") or {}).get("working-directory")
            if isinstance(defaults, str) and defaults.startswith(("services/", "packages/")):
                referenced.add(defaults)
            for step in job.get("steps") or []:
                if not isinstance(step, dict):
                    continue
                wd = step.get("working-directory")
                if isinstance(wd, str) and wd.startswith(("services/", "packages/")):
                    referenced.add(wd)
    return referenced


def main() -> int:
    referenced = collect_referenced()
    failures: list[str] = []

    services = sorted(p for p in SERVICES.iterdir() if p.is_dir() and (p / "src").is_dir())
    packages = sorted(p for p in PACKAGES.iterdir() if p.is_dir())

    for service in services:
        rel = f"services/{service.name}"
        if rel not in referenced:
            failures.append(
                f"C-1 {rel}: どのワークフローからも参照されていない"
                "（テストと Docker ビルドが実行されない。マトリクスへ追加すること）"
            )

    for package in packages:
        rel = f"packages/{package.name}"
        if rel in referenced:
            continue
        if rel in INDIRECTLY_COVERED:
            print(f"間接的に検査: {rel} — {INDIRECTLY_COVERED[rel]}")
            continue
        failures.append(
            f"C-2 {rel}: どのワークフローからも参照されておらず、"
            "INDIRECTLY_COVERED にも理由つきで宣言されていない"
        )

    print(f"サービス {len(services)} 件 / パッケージ {len(packages)} 件を検査した。")
    print(f"ワークフローが参照している対象: {len(referenced)} 件")

    if failures:
        print()
        for item in failures:
            print(f"FAIL: {item}", file=sys.stderr)
        print()
        print(f"NG: {len(failures)} 件が CI のどこからも検査されていない。", file=sys.stderr)
        return 1

    print("OK: すべてのサービス・パッケージが CI のいずれかのジョブで検査されている。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
