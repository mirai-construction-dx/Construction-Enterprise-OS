#!/usr/bin/env python3
"""docker-compose.yml から staging 用の docker-compose.stg.yml を決定論的に生成する。

背景（docs/architecture/ADR-0005-staging-environment.md）:
  - stg の system of record はホスト PostgreSQL 18（クラスタ `18/infra_stg`, port 55438, loopback 限定）。
    開発用 compose の `postgres` / `timescaledb` は stg では使わない。
  - コンテナからホストの loopback へ届かないため、loopback へ転送する `db-bridge`（socat）を
    stg 専用ネットワークのゲートウェイ IP にだけ bind する。LAN へは公開しない。
  - 公開ポートはすべて `127.0.0.1:19xxx` に移す（家族パターン。CSSP は 55432/5311 を使用）。
  - `ENVIRONMENT=staging` を全サービスへ入れ、開発用既定鍵での起動を fail-closed にする。

compose の override（`-f a.yml -f b.yml`）ではなく**完全な独立ファイル**を生成する理由:
  `ports` は compose のマージで加算されるため、override では「base の 0.0.0.0:8000」を
  除去できず衝突する。`depends_on` の除去も anchor 展開後の構造に対して行う必要がある。
  決定的な生成 + CI での `--check` により乖離を検出する。

使い方:
    python3 scripts/stg/render_stg_compose.py            # 生成して書き出す
    python3 scripts/stg/render_stg_compose.py --check    # 差分があれば exit 1（CI 用）
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "docker-compose.yml"
OUTPUT = ROOT / "docker-compose.stg.yml"

PROJECT_NAME = "ceos-stg"
CONTAINER_PREFIX = "ceos-stg-"

# stg 専用ネットワーク。既存の 172.17-172.31/16 と 192.168.x/20 は使用済みのため
# 10.201.0.0/24 を使う（ホストの既存 route と衝突しないことを実測で確認済み）。
NETWORK_SUBNET = "10.201.0.0/24"
NETWORK_GATEWAY = "10.201.0.1"

# stg ネットワークの静的 IP 払い出し（決定論的）。
#
# なぜ必要か（2026-10-14 の実測）:
#   停止したコンテナの名前は Docker の DNS が答えられず、外部リゾルバへ
#   転送されて **約 16 秒**で失敗する（起動中の名前は 6ms）。
#   ゲートウェイは上流を名前で呼ぶため、上流が落ちると 1 リクエストごとに
#   16 秒待たされる。httpx の timeout は名前解決を制限しないので、
#   タイムアウトを短くしても直らない（staging.md §6.14）。
#
#   そこで IP を決定論的に払い出し、ゲートウェイの /etc/hosts（extra_hosts）へ
#   静的に書く。**名前解決を DNS に依存させない。**
NETWORK_PREFIX = "10.201.0"
# .1 はネットワークゲートウェイ（db-bridge が bind する）。.2-.9 は予約。
IP_FIRST_HOST = 10

GATEWAY_SERVICE = "gateway"

# ホスト PostgreSQL 18 クラスタ（Mirai-Platform-Infra 管理）の loopback ポート。
HOST_PG_PORT = 55438
DB_BRIDGE_SERVICE = "db-bridge"

# socat は digest 固定（MCDX-ADR-0002 決定 2「イメージを digest で固定し latest を使わない」）。
DB_BRIDGE_IMAGE = "alpine/socat@sha256:a6be4c0262b339c53ddad723cdd178a1a13271e1137c65e27f90a08c16de02b8"

# stg では使わないサービス。ホスト PostgreSQL 18 が置き換える。
REPLACED_SERVICES = ("postgres", "timescaledb")
DROP_VOLUMES = ("pgdata", "tsdata")

# 公開ポートの stg マッピング。(service, container_port) -> stg host port（loopback）。
# 未登録の組み合わせは「サービス追加時の登録漏れ」としてエラーにする（気付かず素通りを防ぐ）。
STG_PORTS: dict[tuple[str, int], int] = {
    ("gateway", 9000): 19500,
    ("auth", 8000): 19501,
    ("document", 8000): 19502,
    ("workflow", 8000): 19503,
    ("gis", 8000): 19504,
    ("iot", 8000): 19505,
    ("ai", 8000): 19506,
    ("field-dx", 8000): 19507,
    ("bim", 8000): 19508,
    ("maintenance", 8000): 19509,
    ("autonomous", 8000): 19510,
    ("vision", 8000): 19511,
    ("platform", 8000): 19512,
    ("advanced", 8000): 19513,
    ("analytics", 8000): 19514,
    ("automation", 8000): 19515,
    ("construction", 8000): 19516,
    ("notification", 8000): 19517,
    ("partner", 8000): 19518,
    ("safety", 8000): 19519,
    ("erp", 8000): 19520,
    ("security", 8000): 19521,
    ("mcp", 8022): 19522,
    ("web", 3100): 19530,
    ("mobile", 3101): 19531,
    ("redis", 6379): 19540,
    ("rabbitmq", 5672): 19541,
    ("rabbitmq", 15672): 19542,
    ("kafka", 9092): 19543,
    ("elasticsearch", 9200): 19544,
    ("kibana", 5601): 19545,
    ("minio", 9000): 19546,
    ("minio", 9001): 19547,
}

# サービスへ差し替える環境変数。値は ~/.config/ceos/stg.env から渡す（リポジトリに置かない）。
STG_ENV_OVERRIDES: dict[str, str] = {
    "ENVIRONMENT": "staging",
    "DEBUG": "false",
    # コンテナ -> db-bridge -> ホスト PostgreSQL 18。asyncpg を明示する。
    # db-bridge は network_mode: host のため construction-net のサービス名解決に載らない。
    # 名前ではなく stg ネットワークのゲートウェイ IP を直接指す（サブネットは固定）。
    "DATABASE_URL": (
        f"${{STG_DATABASE_URL:-postgresql+asyncpg://ceos_stg_app@"
        f"{NETWORK_GATEWAY}:{HOST_PG_PORT}/ceos_stg}}"
    ),
    "JWT_PUBLIC_KEY": "${STG_JWT_PUBLIC_KEY:?set STG_JWT_PUBLIC_KEY (see .env.stg.example)}",
    "JWT_PRIVATE_KEY": "${STG_JWT_PRIVATE_KEY:?set STG_JWT_PRIVATE_KEY (see .env.stg.example)}",
    "JWT_SECRET_KEY": "${STG_JWT_SECRET_KEY:?set STG_JWT_SECRET_KEY (see .env.stg.example)}",
    "INTERNAL_API_KEY": "${STG_INTERNAL_API_KEY:-}",
    # ミドルウェアの資格情報は dev の既定値を持ち込まない。
    "RABBITMQ_URL": (
        "${STG_RABBITMQ_URL:-amqp://ceos_stg:"
        "${STG_RABBITMQ_DEFAULT_PASS:?set STG_RABBITMQ_DEFAULT_PASS}@rabbitmq:5672/}"
    ),
    "RABBITMQ_DEFAULT_USER": "${STG_RABBITMQ_DEFAULT_USER:-ceos_stg}",
    "RABBITMQ_DEFAULT_PASS": "${STG_RABBITMQ_DEFAULT_PASS:?set STG_RABBITMQ_DEFAULT_PASS}",
    "MINIO_ROOT_USER": "${STG_MINIO_ROOT_USER:-ceos_stg}",
    "MINIO_ROOT_PASSWORD": "${STG_MINIO_ROOT_PASSWORD:?set STG_MINIO_ROOT_PASSWORD}",
    "MINIO_ACCESS_KEY": "${STG_MINIO_ROOT_USER:-ceos_stg}",
    "MINIO_SECRET_KEY": "${STG_MINIO_ROOT_PASSWORD:?set STG_MINIO_ROOT_PASSWORD}",
}

# stg では持ち込まない環境変数（置換元のサービスが消えるため）。
STG_ENV_REMOVALS = ("TIMESCALE_URL",)

# 開発用の既定資格情報。1 つでも残っていれば生成を中止する（stg へ dev の鍵を持ち込まない）。
DEV_SECRET_FINGERPRINTS = (
    "construction-os_dev",
    "minioadmin",
    "dev-only",
)

GENERATED_HEADER = """\
# ==============================================================================
# Construction-Enterprise-OS — STAGING (stg) stack
#
# このファイルは生成物である。直接編集しない。
#   生成: python3 scripts/stg/render_stg_compose.py
#   検証: python3 scripts/stg/render_stg_compose.py --check
#   起動: scripts/stg/up.sh
#   設計: docs/architecture/ADR-0005-staging-environment.md / docs/operations/staging.md
#
# 方針:
#   - system of record はホスト PostgreSQL 18 クラスタ `18/infra_stg`（localhost:55438）。
#     開発用 postgres / timescaledb コンテナは stg では起動しない。
#   - 公開ポートはすべて 127.0.0.1:19xxx。LAN へ開かない。外部公開は Cloudflare のみ。
#   - ENVIRONMENT=staging（development/test 以外）なので開発用既定鍵では起動しない。
# ==============================================================================
"""


def fail(message: str) -> None:
    print(f"render_stg_compose: {message}", file=sys.stderr)
    raise SystemExit(1)


def render() -> str:
    base = yaml.safe_load(BASE.read_text(encoding="utf-8"))
    services: dict[str, dict] = base["services"]

    missing = [name for name in REPLACED_SERVICES if name not in services]
    if missing:
        fail(f"docker-compose.yml に {missing} が無い。構成が変わった可能性がある。")

    # 名前解決を DNS に依存させないため、ネットワークに載るサービスへ
    # 決定論的に IP を払い出す（名前の昇順）。db-bridge は network_mode: host
    # のため対象外。
    on_network = sorted(n for n in services if n not in REPLACED_SERVICES)
    ip_plan: dict[str, str] = {}
    for index, svc_name in enumerate(on_network):
        octet = IP_FIRST_HOST + index
        if octet > 254:
            fail("stg ネットワーク（/24）の IP が枯渇した。サブネットを見直すこと。")
        ip_plan[svc_name] = f"{NETWORK_PREFIX}.{octet}"

    out_services: dict[str, dict] = {}

    # ホスト PostgreSQL 18 の loopback を stg ネットワークのゲートウェイへ転送する。
    # network_mode: host でゲートウェイ IP にだけ bind するため、
    # stg ネットワーク以外のコンテナからは到達できない（LAN へは公開しない）。
    out_services[DB_BRIDGE_SERVICE] = {
        "image": DB_BRIDGE_IMAGE,
        "container_name": f"{CONTAINER_PREFIX}{DB_BRIDGE_SERVICE}",
        "network_mode": "host",
        "restart": "unless-stopped",
        "command": [
            f"TCP-LISTEN:{HOST_PG_PORT},bind={NETWORK_GATEWAY},fork,reuseaddr",
            f"TCP:127.0.0.1:{HOST_PG_PORT}",
        ],
        "healthcheck": {
            # busybox nc は -z を持たないため、stdin を閉じて接続だけを試す。
            "test": ["CMD-SHELL", f"nc -w 3 127.0.0.1 {HOST_PG_PORT} </dev/null"],
            "interval": "30s",
            "timeout": "5s",
            "retries": 3,
            "start_period": "5s",
        },
        # 資源上限（2026-10-14 実測: 全 33 サービスに上限が無かった）。
        # db-bridge は compose に存在しない stg 専用サービスなので、base の
        # anchor では受け取れない。ここで明示する。
        # 検査: scripts/ci/check_memory_limits.py
        "deploy": {
            "resources": {
                "limits": {
                    "cpus": "${CEOS_CPU_LIMIT:-1.0}",
                    "memory": "${CEOS_MEM_LIMIT:-768M}",
                }
            }
        },
    }

    for name, service in services.items():
        if name in REPLACED_SERVICES:
            continue
        service = dict(service)
        service["container_name"] = f"{CONTAINER_PREFIX}{name}"

        # stg は長時間動き続ける環境である。docker compose の既定は `restart: no` であり、
        # 基盤サービス（redis / rabbitmq / kafka / elasticsearch / kibana / minio）は
        # docker-compose.yml で restart を指定していない（2026-10-14 実測: dev でも 8 件が未指定）。
        # 落ちても誰も起こさないため、stg では**全サービスへ方針を与える**。
        # 明示がある場合はそれを尊重する（db-bridge は上で指定済み）。
        # 検査: scripts/stg/check_staging_guards.py の G-10
        service.setdefault("restart", "unless-stopped")

        env = dict(service.get("environment") or {})
        for key in STG_ENV_REMOVALS:
            env.pop(key, None)
        env.update(STG_ENV_OVERRIDES)
        service["environment"] = env

        ports = service.get("ports") or []
        if ports:
            stg_ports = []
            for entry in ports:
                # "8000:8000" 形式のみを想定（docker-compose.yml はこの形式だけを使う）。
                _, _, container_part = str(entry).partition(":")
                if not container_part.isdigit():
                    fail(f"service {name}: 解釈できない ports エントリ {entry!r}")
                container_port = int(container_part)
                mapped = STG_PORTS.get((name, container_port))
                if mapped is None:
                    fail(
                        f"service {name}: container port {container_port} の stg ポートが未登録。"
                        "STG_PORTS に追加すること（新規サービス追加時の登録漏れ検出）。"
                    )
                stg_ports.append(f"127.0.0.1:{mapped}:{container_port}")
            service["ports"] = stg_ports
        else:
            service.pop("ports", None)

        depends = service.get("depends_on")
        if isinstance(depends, dict):
            trimmed = {k: v for k, v in depends.items() if k not in REPLACED_SERVICES}
            if DROP_VOLUMES:
                for replaced in REPLACED_SERVICES:
                    trimmed.pop(replaced, None)
            if trimmed:
                service["depends_on"] = trimmed
            else:
                service.pop("depends_on", None)
        elif isinstance(depends, list):
            trimmed = [d for d in depends if d not in REPLACED_SERVICES]
            if trimmed:
                service["depends_on"] = trimmed
            else:
                service.pop("depends_on", None)

        # 開発用の既定資格情報が残っていないことを機械的に確認する。
        for key, value in env.items():
            if not isinstance(value, str) or "${" in value:
                continue  # 生成した参照（${...}）は実行時に値が入るため対象外
            for fingerprint in DEV_SECRET_FINGERPRINTS:
                if fingerprint in value:
                    fail(f"service {name}: 開発用の既定値が残っている ({key}={value!r})")

        # 静的 IP（名前解決を DNS に依存させないため。上の ip_plan を参照）。
        service["networks"] = {
            "construction-net": {"ipv4_address": ip_plan[name]},
        }

        out_services[name] = service

    # ゲートウェイは上流を**名前で**呼ぶ。停止した上流の名前解決に 16 秒
    # かかる問題（staging.md §6.14）を避けるため、/etc/hosts へ静的に書く。
    # これで名前解決は DNS を経由しない（接続は即座に失敗し、httpx の
    # タイムアウトで上限が決まる）。
    if GATEWAY_SERVICE not in out_services:
        fail(f"docker-compose.yml に {GATEWAY_SERVICE} が無い。上流の名前解決を固定できない。")
    out_services[GATEWAY_SERVICE]["extra_hosts"] = [
        f"{name}:{ip}" for name, ip in sorted(ip_plan.items()) if name != GATEWAY_SERVICE
    ]

    document = {
        "name": PROJECT_NAME,
        "services": out_services,
        "networks": {
            "construction-net": {
                "driver": "bridge",
                "ipam": {"config": [{"subnet": NETWORK_SUBNET, "gateway": NETWORK_GATEWAY}]},
            }
        },
        "volumes": {
            key: value
            for key, value in (base.get("volumes") or {}).items()
            if key not in DROP_VOLUMES
        },
    }

    body = yaml.safe_dump(document, sort_keys=False, allow_unicode=True, width=120)
    return GENERATED_HEADER + body


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="差分があれば exit 1（CI 用）")
    args = parser.parse_args(argv)

    rendered = render()
    if args.check:
        if not OUTPUT.exists():
            print(f"{OUTPUT} が無い。python3 scripts/stg/render_stg_compose.py を実行すること。")
            return 1
        current = OUTPUT.read_text(encoding="utf-8")
        if current != rendered:
            print(f"{OUTPUT} が docker-compose.yml と乖離している。再生成すること。")
            return 1
        print(f"OK: {OUTPUT.name} は docker-compose.yml と一致している。")
        return 0

    OUTPUT.write_text(rendered, encoding="utf-8")
    print(f"wrote {OUTPUT.relative_to(ROOT)} ({len(rendered.splitlines())} lines)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
