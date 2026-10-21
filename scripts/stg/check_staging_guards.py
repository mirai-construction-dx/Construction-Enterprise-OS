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
  G-9  stg compose に**可変タグ**（`:latest` など）のイメージが無い（再現性。2026-10-14 追加）。
  G-10 stg compose の**全サービスに再起動方針**がある（長時間動く環境。2026-10-14 追加）。
  G-11 上流の**名前解決を DNS に依存させていない**（静的 IP ＋ gateway の extra_hosts。2026-10-14 追加）。
  G-12 訓練スクリプトに**実行記録**がある（reports/staging/。2026-10-14 追加）。
  G-13 API Tunnel の値が文書・workflow・スクリプト・compose で一致している（2026-10-14 追加）。
  G-14 全サービスの資源上限宣言が静的方針に適合する（実行時適用・負荷妥当性は未確認）。

`SKIP` を作らない。判定できないものは FAIL として報告する（AGENTS.md「未確認を成功と書かない」）。

使い方:
    python3 scripts/stg/check_staging_guards.py
"""

from __future__ import annotations

import re
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


def check_no_mutable_tags(stg: dict) -> None:
    """stg compose のイメージが可変タグ（:latest など）を指していないか。

    なぜ必要か（2026-10-14 実測）:
        `minio/minio:latest` が dev と stg の両方にあり、stg はそれを配っていた。
        `latest` は再現しない。**同じ手順で作り直しても別の環境になる**ため、
        「staging で検証した」という記録の意味が失われる。
        （稼働していた実体は RELEASE.2025-09-07T16-13-09Z だった。）

    何を可変とみなすか:
        `latest` / タグ無し。`redis:7-alpine` のようなバージョンタグは可変ではあるが、
         digest 固定は release 工程（IMAGE_DIGESTS）の領分であり、ここでは要求しない。
    """
    mutable: list[str] = []
    for name, service in sorted(stg["services"].items()):
        image = service.get("image")
        if not image:
            continue  # ローカルビルド（build:）はタグを持たない
        tag = image.rsplit("/", 1)[-1]
        if ":" not in tag or tag.endswith(":latest"):
            mutable.append(f"{name}={image}")
    record(
        "G-9 no mutable image tags",
        not mutable,
        f"{len(stg['services'])} サービスのうち最新タグ 0 件"
        if not mutable
        else f"可変タグ: {mutable}",
    )


def check_restart_policy(stg: dict) -> None:
    """全サービスに再起動方針があるか。

    なぜ必要か（2026-10-14 実測）:
        docker compose の既定は `restart: no` である。`docker-compose.yml` は
        基盤サービス（redis / rabbitmq / kafka / elasticsearch / kibana / minio）に
        restart を指定していなかった（dev でも 8 件が未指定）。
        stg は長時間動き続ける環境なので、**落ちたら誰かが起こすまで止まったまま**になる。
        実際、アプリ 26 サービスには方針があり基盤 6 つには無い、という非対称があった。

    対策:
        `render_stg_compose.py` が stg の全サービスへ `unless-stopped` を与える
        （明示がある場合はそれを尊重する）。ここでは**漏れ**を検査する。
    """
    missing = [name for name, s in sorted(stg["services"].items()) if not s.get("restart")]
    record(
        "G-10 restart policy is present",
        not missing,
        f"{len(stg['services'])} サービスすべてに再起動方針がある"
        if not missing
        else f"方針が無いサービス: {missing}（落ちても起動しない）",
    )


def check_resource_limits(stg: dict) -> None:
    """資源上限宣言の静的検査。実行時適用や負荷妥当性は証明しない。

    Compose は mem_limit/cpus と deploy.resources.limits の両形式をサポート。
    後者への統一は本リポジトリの方針であり、前者が非対応という意味ではない。
    暫定値には負荷試験の根拠がなく、稼働コンテナへの適用確認は別工程が必要。
    """
    sys.path.insert(0, str(ROOT / "scripts" / "ci"))
    import check_memory_limits

    services = stg.get("services") if isinstance(stg, dict) else None
    failures = check_memory_limits.check_compose(STG_COMPOSE, "stg", services)
    record(
        "G-14 resource limits are present",
        not failures,
        "資源上限宣言が静的方針に適合。実行時適用・負荷妥当性は未確認。"
        if not failures
        else "; ".join(failures),
    )


def _static_ip(service: dict) -> str | None:
    """サービスの静的 IP を取り出す。無ければ None。

    `networks` は 2 通りの書き方がある:
      - マッピング形式（静的 IP あり）: {"construction-net": {"ipv4_address": "10.201.0.10"}}
      - リスト形式（静的 IP なし）    : ["construction-net"]

    2026-10-14 の実測: 前者だけを想定していたため、後者で `.get` が
    リストに当たって **AttributeError で検査ごと落ちていた**（FAIL を報告せず、
    トレースバックだけが出る）。形式を明示的に扱う。
    """
    networks = service.get("networks")
    if isinstance(networks, dict):
        entry = networks.get("construction-net")
        if isinstance(entry, dict):
            value = entry.get("ipv4_address")
            return str(value) if value else None
    return None


def check_static_ip_and_hosts(stg: dict) -> None:
    """上流の名前解決を DNS に依存させていないか（静的 IP ＋ extra_hosts）。

    なぜ必要か（2026-10-14 実測）:
        停止したコンテナの名前は Docker の DNS が答えられず、外部リゾルバへ
        転送されて **約 16 秒**で失敗する（起動中の名前は 6ms）。
        ゲートウェイは上流を名前で呼ぶため、上流が落ちると 1 リクエストごとに
        16 秒待たされる。httpx の timeout は名前解決を制限しないので
        タイムアウトを短くしても直らない。

    検査:
        - `db-bridge`（network_mode: host）以外の全サービスが静的 IP を持つ
        - IP が重複していない
        - ゲートウェイの `extra_hosts` が**全サービス**を網羅している
          （これが無いと名前解決が DNS に戻り、16 秒が再発する）
    """
    services = stg["services"]
    on_network = {name: s for name, s in services.items() if name != "db-bridge"}

    missing_ip = [name for name, s in sorted(on_network.items()) if not _static_ip(s)]
    record(
        "G-11a static ipv4_address",
        not missing_ip,
        f"{len(on_network)} サービスすべてに静的 IP がある"
        if not missing_ip
        else f"静的 IP が無いサービス: {missing_ip}（名前解決が DNS に戻る）",
    )

    ips = [_static_ip(s) for s in on_network.values()]
    duplicates = sorted({ip for ip in ips if ip and ips.count(ip) > 1})
    record(
        "G-11b unique ipv4_address",
        not duplicates and all(ips),
        "IP は一意" if not duplicates else f"IP が重複: {duplicates}",
    )

    gateway = services.get("gateway")
    if gateway is None:
        record("G-11c gateway extra_hosts", False, "gateway サービスが無い")
        return
    entries = {
        entry.split(":", 1)[0]
        for entry in (gateway.get("extra_hosts") or [])
        if isinstance(entry, str) and ":" in entry
    }
    expected = set(on_network) - {"gateway"}
    missing_hosts = sorted(expected - entries)
    stale_hosts = sorted(entries - expected)
    record(
        "G-11c gateway extra_hosts",
        not missing_hosts and not stale_hosts,
        f"gateway は {len(entries)} サービスを /etc/hosts で解決する"
        if not missing_hosts and not stale_hosts
        else f"extra_hosts の不足: {missing_hosts} / 余剰: {stale_hosts}",
    )


def check_drill_records() -> None:
    """訓練スクリプトに**実行記録**があるか。

    なぜ必要か（2026-10-14 の実測）:
        `docs/operations/staging.md` は「ロールバックは訓練する。実行記録は
        `reports/staging/rollback-YYYYMMDD.md` に残す」と定めていたが、
        **`reports/staging/` は一度も作られておらず、記録は 1 件も無かった**。
        訓練は実行されていた（§6 の表が実測を引用している）のに、証跡が残っていない。
        文書に書いてあるだけの運用は守られないので、機械的に検査する。

    規則:
        `scripts/stg/<name>_drill.sh` に対して
        `reports/staging/<name の _ を - にしたもの>-*.md` が 1 件以上あること。
    """
    drill_dir = ROOT / "scripts" / "stg"
    record_dir = ROOT / "reports" / "staging"
    drills = sorted(drill_dir.glob("*_drill.sh"))
    if not drills:
        record("G-12 drill records", False, "訓練スクリプトが 1 つも無い（検査が空回りしている）")
        return
    missing: list[str] = []
    for path in drills:
        prefix = path.stem.replace("_drill", "").replace("_", "-")
        if not sorted(record_dir.glob(f"{prefix}-*.md")):
            missing.append(f"{path.name} → reports/staging/{prefix}-*.md")
    record(
        "G-12 drill records",
        not missing,
        f"{len(drills)} 本の訓練すべてに実行記録がある"
        if not missing
        else f"記録が無い訓練: {missing}（文書が定めた証跡が残っていない）",
    )


def check_api_tunnel_consistency(stg: dict) -> None:
    """API Tunnel の値が 3 か所で一致しているか。

    なぜ必要か（2026-10-14 の実測）:
        §6.4 はホスト名・トンネル名・転送先を定め、`staging-deploy.workflow.yml` の
        `STG_API_UPSTREAM` は「§6.4 と同じ値でなければならない」と書いてある。
        さらに本ラウンドで unit と準備スクリプトを足した。**同じ値を 4 か所
        （文書・workflow・スクリプト・compose）に書く**ため、片方だけ直すと
        静かに食い違う。機械的に突き合わせる。

    検査:
        G-13a 準備スクリプトの転送先ポートが stg compose のゲートウェイの公開ポートと一致
        G-13b 準備スクリプトの公開ホストが `STG_API_UPSTREAM` のホストと一致
        G-13c 公開ホストが §6.4 に書かれている（文書が追随している）
    """
    script_path = ROOT / "scripts" / "stg" / "prepare_api_tunnel.sh"
    workflow_path = ROOT / "docs" / "operations" / "staging-deploy.workflow.yml"
    doc_path = ROOT / "docs" / "operations" / "staging.md"
    for path in (script_path, workflow_path, doc_path):
        if not path.exists():
            record("G-13 api tunnel consistency", False, f"{path.name} が無い")
            return

    script = script_path.read_text(encoding="utf-8")
    workflow = workflow_path.read_text(encoding="utf-8")
    doc = doc_path.read_text(encoding="utf-8")

    target = re.search(r'^TARGET="http://127\.0\.0\.1:(\d+)"', script, re.MULTILINE)
    host = re.search(r'^PUBLIC_HOST="([^"]+)"', script, re.MULTILINE)
    upstream = re.search(r"STG_API_UPSTREAM:\s*https?://(\S+)", workflow)

    # stg compose のゲートウェイ公開ポート（ホスト側）
    published: set[str] = set()
    for entry in stg["services"].get("gateway", {}).get("ports") or []:
        parts = str(entry).split(":")
        if len(parts) == 3:
            published.add(parts[1])

    if not (target and host and upstream):
        record(
            "G-13 api tunnel consistency",
            False,
            f"値を取り出せない（script={bool(target)}/{bool(host)} workflow={bool(upstream)}）",
        )
        return

    port, host_value, upstream_host = target.group(1), host.group(1), upstream.group(1)
    ok_port = port in published
    ok_host = host_value == upstream_host
    ok_doc = host_value in doc
    detail = (
        f"転送先 :{port} / 公開ホスト {host_value}"
        f"（compose={'一致' if ok_port else published} /"
        f" upstream={'一致' if ok_host else upstream_host} /"
        f" 文書={'あり' if ok_doc else 'なし'}）"
    )
    record("G-13 api tunnel consistency", ok_port and ok_host and ok_doc, detail)


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
    results.clear()
    for required in (STG_COMPOSE, BASE_COMPOSE):
        if not required.exists():
            record("G-0 prerequisites", False, f"{required.name} が無い")
            break
    else:
        try:
            stg = load_stg()
            if not isinstance(stg, dict) or not isinstance(stg.get("services"), dict) or not stg["services"]:
                raise ValueError("services は空でない mapping でなければならない")
            if any(not isinstance(name, str) or not name or not isinstance(body, dict)
                   for name, body in stg["services"].items()):
                raise ValueError("service 名と service mapping が不正")
        except (OSError, ValueError, yaml.YAMLError) as exc:
            record("G-0 prerequisites", False, f"stg compose の読み込み/構造が不正: {exc}")
            print(f"FAIL: G-0 prerequisites: {exc}")
            return 1
        check_compose_in_sync()
        check_loopback_only(stg)
        check_environment(stg)
        check_no_dev_secrets(stg)
        check_database_target(stg)
        check_replaced_services_absent(stg)
        check_service_guards()
        check_no_mutable_tags(stg)
        check_restart_policy(stg)
        check_resource_limits(stg)
        check_static_ip_and_hosts(stg)
        check_drill_records()
        check_api_tunnel_consistency(stg)
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
