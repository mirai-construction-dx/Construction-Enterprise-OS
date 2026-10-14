#!/usr/bin/env python3
"""`/api/v1/health/services` が**ゲートウェイの全上流**を見ているか検証する。

なぜ必要か（2026-10-14 の実測）:
    auth サービスの `GET /api/v1/health/services` は `HEALTH_SERVICE_URLS` に
    並べた先だけを叩き、その範囲で `overall` を決める。ところが実際の値は
    **3 件（document / workflow / notification）だけ**で、ゲートウェイの
    上流 **21 件のうち 17 件を見ていなかった**。

    それにもかかわらず:

        docs/operations/deployment.md:        「✅ 全サービス healthy(auth 12ms 等)」
        docs/operations/api-auth-db-verification.md: 「✅ 全サービス healthy」
        apps/web のダッシュボード:               この endpoint を表示する

    と、**「全サービス」として提示されていた**。見ていないサービスが落ちても
    `overall: healthy` のままなので、**緑を見て安心する**構造になっていた。
    （stg で実測: `vision` を止めても修正前は overall が healthy のまま。
      修正後は overall=unhealthy / vision=unhealthy になる。）

検査する内容:
    C-1 docker-compose.yml からゲートウェイの `UPSTREAM_SERVICES` を読めること
    C-2 auth の `HEALTH_SERVICE_URLS` を読めること
    C-3 **ゲートウェイの全上流（auth 自身を除く）が `HEALTH_SERVICE_URLS` に含まれる**
        （＝「全サービス」と名乗れる）
    C-4 `HEALTH_SERVICE_URLS` に**上流に無いホスト**が混ざっていない（残骸の検出）
    C-5 陰性対照: 欠落を作った合成入力で C-3 が**落ちる**こと（検査が空回りしていない）

`SKIP` を作らない。解釈できない入力は FAIL として報告する。

使い方:
    python3 scripts/ci/check_health_coverage.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
BASE_COMPOSE = REPO / "docker-compose.yml"
# auth 自身は HEALTH_SERVICE_URLS ではなく DB 到達性で判定する（実装済み）
SELF_SERVICE = "auth"


def host_of(url: str) -> str:
    return url.split("//", 1)[-1].split("/", 1)[0].split(":", 1)[0]


def coverage(upstreams: set[str], health: set[str]) -> tuple[list[str], list[str]]:
    """(不足, 余剰) を返す。"""
    expected = {h for h in upstreams if h != SELF_SERVICE}
    return sorted(expected - health), sorted(health - expected)


def main() -> int:
    failures: list[str] = []

    if not BASE_COMPOSE.exists():
        print(f"NG: {BASE_COMPOSE.name} が無い", file=sys.stderr)
        return 1
    document = yaml.safe_load(BASE_COMPOSE.read_text(encoding="utf-8"))
    services = document.get("services", {})

    # ---- C-1 ゲートウェイの上流 ----
    try:
        raw = services["gateway"]["environment"]["UPSTREAM_SERVICES"]
        routes = json.loads(raw) if isinstance(raw, str) else raw
        upstreams = {host_of(url) for url in routes.values()}
    except (KeyError, TypeError, ValueError) as exc:
        failures.append(f"C-1 gateway の UPSTREAM_SERVICES を読めない: {type(exc).__name__}: {exc}")
        upstreams = set()
    print(f"C-1 ゲートウェイの上流: {len(upstreams)} 件")

    # ---- C-2 auth のヘルス対象 ----
    try:
        raw = services["auth"]["environment"]["HEALTH_SERVICE_URLS"]
        health_map = json.loads(raw) if isinstance(raw, str) else raw
        health = {host_of(url) for url in health_map.values()}
    except (KeyError, TypeError, ValueError) as exc:
        failures.append(f"C-2 auth の HEALTH_SERVICE_URLS を読めない: {type(exc).__name__}: {exc}")
        health = set()
    print(f"C-2 auth が実際に叩く先: {len(health)} 件")

    if not upstreams or not health:
        failures.append("C-1/C-2 対象が 0 件（検査が空回りしている）")

    # ---- C-3 / C-4 網羅と残骸 ----
    missing, extra = coverage(upstreams, health)
    print(f"C-3 見ていない上流: {len(missing)} 件 {missing if missing else ''}")
    if missing:
        failures.append(
            f"C-3 ゲートウェイの上流 {missing} を /api/v1/health/services が見ていない。"
            "「全サービス healthy」と名乗れない（docker-compose.yml の "
            "auth.HEALTH_SERVICE_URLS に追加すること）"
        )
    print(f"C-4 上流に無いホスト: {len(extra)} 件 {extra if extra else ''}")
    if extra:
        failures.append(f"C-4 HEALTH_SERVICE_URLS に上流に無いホストがある: {extra}（残骸）")

    # ---- C-5 陰性対照 ----
    control_missing, _ = coverage({"auth", "document", "erp"}, {"document"})
    if control_missing != ["erp"]:
        failures.append(f"C-5 陰性対照: 欠落を検出できない（{control_missing}）")
    print(f"C-5 陰性対照: 欠落 {control_missing} を検出できる" if control_missing == ["erp"] else "C-5 陰性対照: NG")

    print()
    if failures:
        print(f"NG: {len(failures)} 件", file=sys.stderr)
        for item in failures:
            print(f"  - {item}", file=sys.stderr)
        return 1
    print(
        f"OK: /api/v1/health/services はゲートウェイの全上流を網羅している"
        f"（{len(health)} + 自身 = {len(health) + 1} サービス）"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
