#!/usr/bin/env python3
"""`Mirai-Platform-Infra` の `envs/stg/releases.yaml` に載せる CEOS エントリを組み立てる。

なぜ必要か:
    Infra は `tools/check_deploy_readiness.py --environment stg` でデプロイ前提を検査し、
    `envs/stg/releases.yaml` が無い間は **NOT_READY（デプロイ不能）** とする。
    その manifest は「digest 固定イメージ・`v*` タグ・署名/来歴・ITSM 変更番号」を要求する。
    Infra の `AGENTS.md` は**値の創作を禁じている**ため、CEOS 側が実測値から機械的に
    組み立てて渡す必要がある。

このツールの立場:
    **足りないものを創作しない。** 実測できない項目は `--check` で欠落として列挙し、
    `--out` での出力は「全部そろっている」ときだけ行う。SKIP を成功として扱わない
    （`AGENTS.md` §4.7）。

使い方:
    # 何が足りないかを知る（読み取りのみ・既定）
    python3 scripts/stg/gen_release_manifest.py --check

    # 実測値から manifest を書き出す
    python3 scripts/stg/gen_release_manifest.py \\
        --tag v1.0.0 \\
        --itsm-change CHG-2026-00042 \\
        --hosts stg-host-01 \\
        --images contracts/release-images.stg.json \\
        --out /path/to/envs/stg/releases.yaml

`--images` の JSON 形式（オペレーターが push 後に実測して用意する）:
    {
      "ceos-auth":      "ghcr.io/mirai-construction-dx/ceos-auth@sha256:<64hex>",
      "ceos-gateway":   "ghcr.io/mirai-construction-dx/ceos-gateway@sha256:<64hex>"
    }
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LOCK_PATH = ROOT / "contracts" / "harness-core.lock.json"
ATTESTATION_WORKFLOW = ".github/workflows/release.yml"

SEMVER = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
DIGEST_IMAGE = re.compile(
    r"^(ghcr\.io|miraiacr\.azurecr\.io)/[a-z0-9]+(?:[._-][a-z0-9]+)*(?:/[a-z0-9]+(?:[._-][a-z0-9]+)*)*@sha256:[0-9a-f]{64}$"
)
ITSM_CHANGE = re.compile(r"^CHG-[0-9]{4}-[0-9]{5}$")
HOST = re.compile(r"^[a-z][a-z0-9-]+$")


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True, text=True, check=False
    ).stdout.strip()


def core_version() -> str:
    return json.loads(LOCK_PATH.read_text(encoding="utf-8"))["core_version"]


def latest_tag() -> str:
    """`main` 上で到達可能な最新の `v<semver>` タグ。無ければ空文字。"""
    for tag in git("tag", "--merged", "HEAD", "--sort=-v:refname").splitlines():
        if re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+", tag):
            return tag
    return ""


def tag_exists(tag: str) -> bool:
    return bool(git("rev-parse", "--verify", f"refs/tags/{tag}"))


def tag_commit(tag: str) -> str:
    return git("rev-list", "-n1", tag)


def check(tag: str | None, images_path: Path | None, itsm: str | None, hosts: list[str]) -> list[tuple[str, bool, str]]:
    """(項目, 充足, 説明) を返す。実測できないものは False のまま残す。"""
    rows: list[tuple[str, bool, str]] = []

    resolved_tag = tag or latest_tag()
    rows.append(
        (
            "RELEASE_TAG",
            bool(resolved_tag and tag_exists(resolved_tag)),
            f"{resolved_tag or '(なし)'} — `v<semver>` タグが必要（Release は Human Gate: MCDX-ADR-0004 決定 4）",
        )
    )

    version_ok = bool(resolved_tag) and bool(SEMVER.fullmatch(resolved_tag.lstrip("v")))
    rows.append(("SEMVER", version_ok, f"{resolved_tag.lstrip('v') if resolved_tag else '(なし)'}"))

    cv = core_version()
    rows.append(("CORE_VERSION", bool(SEMVER.fullmatch(cv)), f"{cv}（contracts/harness-core.lock.json）"))

    workflow_ok = (ROOT / ATTESTATION_WORKFLOW).exists()
    rows.append(
        (
            "ATTESTATION_WORKFLOW",
            workflow_ok,
            f"{ATTESTATION_WORKFLOW} — 署名・来歴を発行する workflow が要る"
            if not workflow_ok
            else f"{ATTESTATION_WORKFLOW} が存在する（署名を実際に発行しているかは別途確認）",
        )
    )

    if images_path is None or not images_path.exists():
        rows.append(
            (
                "IMAGE_DIGESTS",
                False,
                "--images で digest 固定イメージの JSON を渡す（ghcr.io 等へ push した実測値）",
            )
        )
    else:
        data = json.loads(images_path.read_text(encoding="utf-8"))
        bad = [k for k, v in data.items() if not DIGEST_IMAGE.fullmatch(str(v))]
        rows.append(
            (
                "IMAGE_DIGESTS",
                bool(data) and not bad,
                f"{len(data)} 件" if not bad else f"形式違反: {bad}",
            )
        )

    rows.append(
        (
            "ITSM_CHANGE",
            bool(itsm and ITSM_CHANGE.fullmatch(itsm)),
            f"{itsm or '(未指定)'} — CHG-YYYY-NNNNN。変更管理（人間）が発行する",
        )
    )
    rows.append(
        (
            "DEPLOY_HOSTS",
            bool(hosts) and all(HOST.fullmatch(h) for h in hosts),
            ", ".join(hosts) if hosts else "compose では hosts が必須（R-06）",
        )
    )
    return rows


def build(tag: str, itsm: str, hosts: list[str], images: dict[str, str]) -> dict:
    version = tag.lstrip("v")
    return {
        "apiVersion": "infra.mirai/v1",
        "kind": "Releases",
        "environment": "stg",
        "profile": "onprem",
        "core_version": core_version(),
        "itsm_change": itsm,
        "systems": [
            {
                "system_id": "ceos",
                "version": version,
                "core_version": core_version(),
                "images": images,
                "attestation": {
                    "repo": "mirai-construction-dx/Construction-Enterprise-OS",
                    "workflow": ATTESTATION_WORKFLOW,
                    "ref": f"refs/tags/v{version}",
                },
                "deploy": {"method": "compose", "hosts": hosts},
            }
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="足りない項目を列挙するだけ（既定）")
    parser.add_argument("--tag", help="対象のタグ（例 v1.0.0）。省略時は main 到達可能な最新の v* タグ")
    parser.add_argument("--itsm-change", help="変更管理番号（CHG-YYYY-NNNNN）")
    parser.add_argument("--hosts", nargs="*", default=["stg-host-01"], help="配置先ホスト名（R-06）")
    parser.add_argument("--images", type=Path, help="digest 固定イメージの JSON")
    parser.add_argument("--out", type=Path, help="出力先（全項目がそろっているときだけ書く）")
    args = parser.parse_args(argv)

    rows = check(args.tag, args.images, args.itsm_change, args.hosts)
    print("== envs/stg/releases.yaml の前提（CEOS） ==")
    for name, ok, detail in rows:
        print(f"{'PASS' if ok else 'FAIL'}: {name}: {detail}")

    missing = [name for name, ok, _ in rows if not ok]
    print()
    if missing:
        print(f"NOT_READY: {len(missing)} 件が未充足: {', '.join(missing)}")
        print("創作せずに停止した。値を用意してから再実行すること。")
        if args.out:
            print(f"NG: 未充足のため {args.out} は書き出さない。", file=sys.stderr)
            return 1
        return 0

    if not args.check and args.out:
        images = json.loads(args.images.read_text(encoding="utf-8"))  # type: ignore[union-attr]
        document = build(args.tag or latest_tag(), args.itsm_change or "", args.hosts, images)
        import yaml  # 遅延 import（--check だけなら yaml は不要）

        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(
            "# 生成物: scripts/stg/gen_release_manifest.py\n"
            f"# 生成元タグ: {args.tag or latest_tag()} (commit {tag_commit(args.tag or latest_tag())})\n"
            + yaml.safe_dump(document, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )
        print(f"READY: 書き出した → {args.out}")
        print("次: Mirai-Platform-Infra で `python3 tools/check_deploy_readiness.py --environment stg`")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
