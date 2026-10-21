#!/usr/bin/env python3
"""Compose の資源上限宣言を静的に検査する（実行時適用の証明ではない）。

Compose は service-level の mem_limit/cpus と deploy.resources.limits の
両形式をサポートする。本リポジトリは後者に統一する方針を選んでいる。
既定値は暫定値であり、負荷試験による容量根拠や稼働コンテナへの適用証跡はない。
環境変数式は ${VAR:-default} の既定値だけを検査するため、実際の環境値や
HostConfig.Memory/NanoCpus の確認は別の承認済み運用工程で必要となる。

R-1 全サービスに deploy.resources.limits.memory/cpus がある。
R-2 正の有限値である（単位無しの memory は bytes）。
R-3 暫定のポリシー上限 memory <= 4GiB / cpus <= 4.0 を満たす。
R-4 base と stg の共通サービスの宣言が一致する。
R-5 不正な構造や空の services は FAIL（SKIP しない）。
R-6 上限を外した合成入力を検出する。

使い方: python3 scripts/ci/check_memory_limits.py
"""

from __future__ import annotations

import math
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "docker-compose.yml"
STG = ROOT / "docker-compose.stg.yml"

# 暫定のリポジトリ方針。負荷試験で妥当性を検証した容量値ではない。
MAX_MEMORY_MIB = 4096
MAX_CPUS = 4.0
MEMORY_UNITS = {"": 1 / (1024 * 1024), "b": 1 / (1024 * 1024),
                "k": 1 / 1024, "kb": 1 / 1024, "m": 1, "mb": 1,
                "g": 1024, "gb": 1024}
VAR_PATTERN = re.compile(r"^\$\{[A-Za-z_][A-Za-z0-9_]*:-([^}]*)\}$")


def unvar(value: object) -> tuple[str, bool]:
    """${VAR:-default} の既定値を返す（実際の環境は参照しない）。"""
    m = VAR_PATTERN.fullmatch(str(value).strip())
    if m:
        return m.group(1), True
    return str(value).strip(), False


def parse_memory(raw: object) -> float | None:
    """正の有限値を MiB に変換する。単位無しは bytes。"""
    if isinstance(raw, bool) or not isinstance(raw, (str, int, float)):
        return None
    value, _ = unvar(raw)
    m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*([a-zA-Z]*)", value)
    if not m or m.group(2).lower() not in MEMORY_UNITS:
        return None
    result = float(m.group(1)) * MEMORY_UNITS[m.group(2).lower()]
    return result if math.isfinite(result) and result > 0 else None


def parse_cpus(raw: object) -> float | None:
    if isinstance(raw, bool) or not isinstance(raw, (str, int, float)):
        return None
    value, _ = unvar(raw)
    try:
        result = float(value)
    except (ValueError, OverflowError):
        return None
    return result if math.isfinite(result) and result > 0 else None


def limits_of(service: object) -> dict:
    """要求した階層がマッピング以外なら ValueError とする。"""
    if not isinstance(service, dict):
        raise ValueError("service は mapping でなければならない")
    node = service
    for key in ("deploy", "resources", "limits"):
        if key not in node:
            return {}
        node = node[key]
        if not isinstance(node, dict):
            raise ValueError(f"{key} は mapping でなければならない")
    return node


def check_compose(path: Path, label: str, services: object) -> list[str]:
    failures: list[str] = []
    if not isinstance(services, dict) or not services:
        return [f"{label}: services は空でない mapping でなければならない"]
    for name, body in sorted(services.items(), key=lambda item: str(item[0])):
        if not isinstance(name, str) or not name:
            failures.append(f"{label}: service 名が不正: {name!r}")
            continue
        try:
            limits = limits_of(body)
        except ValueError as exc:
            failures.append(f"{label}:{name} の構造が不正: {exc}")
            continue
        mem_raw, cpu_raw = limits.get("memory"), limits.get("cpus")
        if mem_raw is None or cpu_raw is None:
            failures.append(
                f"{label}:{name} に方針上必要な deploy.resources.limits が無い"
                f"（memory={mem_raw} cpus={cpu_raw}）。mem_limit/cpus も Compose で"
                "サポートされるが、このリポジトリは deploy 形式に統一する。"
            )
            continue
        mem, cpu = parse_memory(mem_raw), parse_cpus(cpu_raw)
        if mem is None:
            failures.append(f"{label}:{name} の memory は正の有限値でない/解釈不能: {mem_raw!r}")
        elif mem > MAX_MEMORY_MIB:
            failures.append(f"{label}:{name} の memory 上限が方針を超える: {mem_raw}（{mem:.0f}MiB > {MAX_MEMORY_MIB}MiB）")
        if cpu is None:
            failures.append(f"{label}:{name} の cpus は正の有限値でない/解釈不能: {cpu_raw!r}")
        elif cpu > MAX_CPUS:
            failures.append(f"{label}:{name} の cpus 上限が方針を超える: {cpu_raw}（{cpu} > {MAX_CPUS}）")
        # 両形式を併記する場合も矛盾した値を通さない。
        for key, expected, parser in (("mem_limit", mem, parse_memory), ("cpus", cpu, parse_cpus)):
            if key in body:
                actual = parser(body[key])
                if actual is None or actual != expected:
                    failures.append(f"{label}:{name} の {key} と deploy 上限が不一致/不正")
    return failures


def negative_control(base: object) -> list[str]:
    """非空・妥当な入力だけで上限除去の陰性対照を行う。"""
    if check_compose(BASE, "negative-control-input", base):
        return ["陰性対照 R-6: base が不正なため対照を作れない"]
    synthetic = {k: dict(v) for k, v in base.items()}
    synthetic[sorted(synthetic)[0]].pop("deploy", None)
    if not check_compose(BASE, "synthetic", synthetic):
        return ["陰性対照 R-6: 上限を外しても検出できない"]
    return []


def load_services(path: Path) -> dict:
    """YAML/構造の不正を分かりやすい FAIL に変換するための読み込み。"""
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(doc, dict):
        raise ValueError("Compose 文書は mapping でなければならない")
    services = doc.get("services")
    if not isinstance(services, dict) or not services:
        raise ValueError("services は空でない mapping でなければならない")
    return services


def main() -> int:
    failures: list[str] = []
    loaded: list[dict] = []
    for path, label in ((BASE, "compose"), (STG, "stg")):
        try:
            services = load_services(path)
        except (OSError, ValueError, yaml.YAMLError) as exc:
            failures.append(f"{label}: {path.name} を読めない/構造が不正: {exc}")
            services = {}
        loaded.append(services)
        failures += check_compose(path, label, services)
    base, stg = loaded
    for name in sorted(set(base) & set(stg), key=str):
        try:
            b_limits, s_limits = limits_of(base[name]), limits_of(stg[name])
        except ValueError:
            continue  # 構造不正は上の検査で FAIL 済み。
        b = tuple(unvar(b_limits.get(key, ""))[0] for key in ("memory", "cpus"))
        s = tuple(unvar(s_limits.get(key, ""))[0] for key in ("memory", "cpus"))
        if b != s:
            failures.append(f"stg:{name} の上限が base と違う（compose={b} stg={s}）")
    failures += negative_control(base)
    print(f"  - 検査したサービス: compose {len(base)} 件 / stg {len(stg)} 件")
    if failures:
        for failure in failures:
            print(f"FAIL: {failure}", file=sys.stderr)
        print(f"NG: {len(failures)} 件。資源上限の宣言が方針に適合しない。", file=sys.stderr)
        return 1
    print("OK: 資源上限の宣言が静的方針に適合（compose/stg 一致）。実行時適用・負荷妥当性は未確認。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
