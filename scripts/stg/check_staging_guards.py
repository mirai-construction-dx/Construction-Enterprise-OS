#!/usr/bin/env python3
"""stg（staging）環境の統制が緩んでいないことを機械的に検査する。

検査する不変条件:
  G-1  docker-compose.stg.yml が docker-compose.yml から再生成した内容と一致する（乖離検出）。
  G-2  stg compose の公開ポートがすべて 127.0.0.1 バインドである（LAN へ開かない）。
  G-3  stg compose の ENVIRONMENT が全サービスで staging である。
  G-4  stg compose に開発用の既定資格情報が残っていない。
  G-5  stg compose の DATABASE_URL がホスト PostgreSQL 18 の db-bridge を指す。
  G-6  stg compose が開発用 postgres / timescaledb を起動しない。
  G-7  全サービスが ENVIRONMENT != development/test で開発用既定鍵を拒否する（guard が残っている）。
  G-8  dev(compose) の ENVIRONMENT が staging へ書き換わっていない（stg が dev を汚染していない）。

`SKIP` を作らない。判定できないものは FAIL として報告する（AGENTS.md「未確認を成功と書かない」）。

使い方:
    python3 scripts/stg/check_staging_guards.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
BASE_COMPOSE = ROOT / "docker-compose.yml"
STG_COMPOSE = ROOT / "docker-compose.stg.yml"
SERVICES_DIR = ROOT / "services"

DEV_SECRET_FINGERPRINTS = ("construction-os_dev", "minioadmin", "dev-only")
REPLACED_SERVICES = ("postgres", "timescaledb")

results: list[tuple[str, str, str]] = []


def record(check: str, ok: bool, detail: str) -> None:
    results.append((check, "PASS" if ok else "FAIL", detail))


def load_stg() -> dict:
    return yaml.safe_load(STG_COMPOSE.read_text(encoding="utf-8"))


def check_compose_in_sync() -> None:
    sys.path.insert(0, str(ROOT / "scripts" / "stg"))
    import render_stg_compose

    expected = render_stg_compose.render()
    actual = STG_COMPOSE.read_text(encoding="utf-8")
    record(
        "G-1 compose is in sync",
        expected == actual,
        "docker-compose.stg.yml == render(docker-compose.yml)"
        if expected == actual
        else "乖離している。python3 scripts/stg/render_stg_compose.py を実行すること",
    )


def check_loopback_only(stg: dict) -> None:
    offenders: list[str] = []
    for name, service in stg["services"].items():
        for entry in service.get("ports") or []:
            if not str(entry).startswith("127.0.0.1:"):
                offenders.append(f"{name}: {entry}")
    record(
        "G-2 ports are loopback-only",
        not offenders,
        "全公開ポートが 127.0.0.1 バインド" if not offenders else f"LAN へ露出: {offenders}",
    )


def check_environment(stg: dict) -> None:
    wrong = {
        name: (service.get("environment") or {}).get("ENVIRONMENT")
        for name, service in stg["services"].items()
        if name != "db-bridge" and (service.get("environment") or {}).get("ENVIRONMENT") != "staging"
    }
    record(
        "G-3 ENVIRONMENT=staging",
        not wrong,
        "全サービスが staging" if not wrong else f"staging でない: {wrong}",
    )


def check_no_dev_secrets(stg: dict) -> None:
    offenders: list[str] = []
    for name, service in stg["services"].items():
        for key, value in (service.get("environment") or {}).items():
            if not isinstance(value, str) or "${" in value:
                continue
            for fingerprint in DEV_SECRET_FINGERPRINTS:
                if fingerprint in value:
                    offenders.append(f"{name}.{key}={value!r}")
    record(
        "G-4 no dev credentials",
        not offenders,
        "開発用既定資格情報なし" if not offenders else f"残存: {offenders}",
    )


def check_database_target(stg: dict) -> None:
    import render_stg_compose

    # 期待する接続先: stg ネットワークのゲートウェイ経由でホスト PostgreSQL 18 のポートへ。
    # サービス名 `db-bridge` は network_mode: host のため名前解決に載らないので、
    # compose は IP を直接埋め込む（render_stg_compose.py を正本とする）。
    expected = f"{render_stg_compose.NETWORK_GATEWAY}:{render_stg_compose.HOST_PG_PORT}"
    urls = {
        (service.get("environment") or {}).get("DATABASE_URL")
        for service in stg["services"].values()
        if (service.get("environment") or {}).get("DATABASE_URL")
    }
    bad = sorted(url for url in urls if expected not in str(url))
    record(
        "G-5 DB is the host PostgreSQL 18",
        not bad and bool(urls),
        f"{len(urls)} 種類すべて {expected} 経由" if not bad and urls else f"期待 {expected} と不一致: {bad}",
    )


def check_replaced_services_absent(stg: dict) -> None:
    present = [name for name in REPLACED_SERVICES if name in stg["services"]]
    record(
        "G-6 no dev database container",
        not present,
        "postgres / timescaledb を起動しない" if not present else f"残存: {present}",
    )


def check_service_guards() -> None:
    missing_guard: list[str] = []
    missing_dev_docs_guard: list[str] = []
    total = 0
    for config in sorted(SERVICES_DIR.glob("*/src/config.py")):
        total += 1
        text = config.read_text(encoding="utf-8")
        if 'ENVIRONMENT not in ("development", "test")' not in text:
            missing_guard.append(str(config.relative_to(ROOT)))
    for main in sorted(SERVICES_DIR.glob("*/src/main.py")):
        text = main.read_text(encoding="utf-8")
        if "docs_url" in text and 'ENVIRONMENT == "development"' not in text:
            missing_dev_docs_guard.append(str(main.relative_to(ROOT)))
    record(
        "G-7 dev-key guards present",
        not missing_guard,
        f"{total} サービスすべてに fail-fast guard がある"
        if not missing_guard
        else f"guard 欠落: {missing_guard}",
    )
    record(
        "G-7b API docs disabled outside development",
        not missing_dev_docs_guard,
        "docs_url は development 以外で None"
        if not missing_dev_docs_guard
        else f"guard 欠落: {missing_dev_docs_guard}",
    )


def check_dev_not_polluted() -> None:
    base = yaml.safe_load(BASE_COMPOSE.read_text(encoding="utf-8"))
    environments = {
        (service.get("environment") or {}).get("ENVIRONMENT")
        for service in base["services"].values()
    }
    polluted = "staging" in environments
    record(
        "G-8 dev compose not polluted",
        not polluted,
        f"dev compose の ENVIRONMENT={sorted(e for e in environments if e)}"
        if not polluted
        else "dev compose に staging が混入している",
    )


def main() -> int:
    for required in (STG_COMPOSE, BASE_COMPOSE):
        if not required.exists():
            record("G-0 prerequisites", False, f"{required.name} が無い")
            break
    else:
        stg = load_stg()
        check_compose_in_sync()
        check_loopback_only(stg)
        check_environment(stg)
        check_no_dev_secrets(stg)
        check_database_target(stg)
        check_replaced_services_absent(stg)
        check_service_guards()
        check_dev_not_polluted()

    failed = 0
    for check, status, detail in results:
        print(f"{status}: {check}: {detail}")
        if status != "PASS":
            failed += 1

    print()
    if failed:
        print(f"NG: {failed} 件が失敗。stg の統制が緩んでいる。")
        return 1
    print(f"OK: {len(results)} 件すべて PASS。stg の統制は維持されている。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
