#!/usr/bin/env python3
"""stg の Pages Functions を、stg の API アップストリームへ向けて描画する。

なぜ必要か（2026-10-14 の実測）:
    `webui/functions/api/[[path]].ts`（Cloudflare Pages Function）は `/api/*` を
    **単一の固定アップストリーム**へ無条件に転送する。その値は**本番 API** である。

        const target = new URL(`https://construction-os-api.mirai-dx-platform.com/api/${path}`);

    この 1 ファイルは prod の Pages（`construction-os-web`）と stg の Pages
    （`construction-os-stg`）が**同じソースを共有**する。したがって
    `docs/operations/staging-deploy.workflow.yml` が `webui/functions` を
    そのままコピーして `construction-os-stg` へ配ると、**stg の画面が本番 API を叩く**。

    実測（2026-10-14、workflow と同一手順で組み立てた `.deploy-webui` に対して）:

        $ grep -c construction-os-api.mirai-dx-platform.com .deploy-webui/functions/api/[[path]].ts
        2       # 本番 API ホスト
        $ grep -c construction-os-stg .deploy-webui/functions/api/[[path]].ts
        0       # stg ホスト

    これは `ADR-0005` §3（stg と prod で入口を共有しない）と
    `docs/operations/staging.md` §8-5（stg から prod の DB・DNS・secret へ触れない）に反する。
    stg のデプロイ経路でこのファイルを**そのまま使えないようにする**ため、
    アップストリームを明示的に注入して描画する。

    さらに `staging-deploy.workflow.yml` の preflight は DNS と Access しか見ておらず、
    **この越境を検出しない**。つまり DNS ブロッカーが解けた瞬間に、
    stg が本番 API を叩く構成が「そのまま緑で」デプロイされる。本スクリプトはその罠を閉じる。

安全性（fail closed）:
    - `--upstream` は必須。既定値を持たない（うっかり本番を指さないため）。
    - `--upstream` が本番ホスト（`PROD_HOSTS`）なら**描画せずに終了コード 2**。
    - 描画後に出力ツリーを走査し、本番ホストが 1 つでも残っていれば**削除して終了コード 2**。

使い方:
    python3 scripts/stg/render_pages_functions.py \\
        --src webui/functions \\
        --dst .deploy-webui/functions \\
        --upstream https://construction-os-stg-api.mirai-dx-platform.com

    検査（不変条件）は `scripts/stg/check_pages_upstream.py` が行う。
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path
from urllib.parse import urlsplit

REPO = Path(__file__).resolve().parents[2]

# 本番（prod / MVP）の入口。stg の成果物に**残っていてはならない**ホスト。
# 新しい本番ホストを増やしたらここへ足す（`check_pages_upstream.py` が同期を検査する）。
PROD_HOSTS: tuple[str, ...] = (
    "construction-os-api.mirai-dx-platform.com",  # 本番 API（Tunnel）
    "construction-os.mirai-dx-platform.com",  # 本番 画面（Pages）
    "construction-os-mvp.mirai-dx-platform.com",  # MVP 画面（Pages）
)

DEFAULT_SRC = REPO / "webui" / "functions"


def _die(message: str) -> None:
    print(f"NG: {message}", file=sys.stderr)
    raise SystemExit(2)


def parse_upstream(raw: str) -> str:
    """`--upstream` を検証し、ホスト名を返す。本番ホストは拒否する。"""
    raw = raw.strip().rstrip("/")
    if not raw:
        _die("--upstream が空である。stg の API 入口を明示すること。")
    parts = urlsplit(raw)
    if parts.scheme != "https":
        _die(f"--upstream は https でなければならない: {raw!r}")
    if parts.path not in ("", "/") or parts.query or parts.fragment:
        _die(f"--upstream にパス・クエリ・フラグメントを含めない（オリジンのみ）: {raw!r}")
    host = parts.hostname or ""
    if not host:
        _die(f"--upstream からホストを取り出せない: {raw!r}")
    if host in PROD_HOSTS:
        _die(
            f"--upstream が本番ホストを指している: {host}\n"
            "    stg の成果物を本番 API へ向けてはならない（ADR-0005 §3 / staging.md §8-5）。"
        )
    return host


def render(src: Path, dst: Path, host: str) -> dict[str, int]:
    """`src` を `dst` へ複製し、本番ホストを `host` へ置換する。"""
    if not src.is_dir():
        _die(f"--src がディレクトリではない: {src}")
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)

    files = 0
    replacements = 0
    for path in sorted(dst.rglob("*")):
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        original = text
        for prod in PROD_HOSTS:
            if prod in text:
                replacements += text.count(prod)
                text = text.replace(prod, host)
        if text != original:
            path.write_text(text, encoding="utf-8")
        files += 1
    return {"files": files, "replacements": replacements}


def remaining_prod_hosts(dst: Path) -> list[str]:
    """`dst` の全ファイルに残る本番ホストを列挙する。"""
    found: list[str] = []
    for path in sorted(dst.rglob("*")):
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for prod in PROD_HOSTS:
            if prod in text:
                found.append(f"{path.relative_to(dst)}: {prod}")
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--src", default=str(DEFAULT_SRC), help="描画元（既定: webui/functions）")
    parser.add_argument("--dst", required=True, help="描画先（デプロイ用ディレクトリ）")
    parser.add_argument("--upstream", required=True, help="stg の API オリジン（例: https://construction-os-stg-api.mirai-dx-platform.com）")
    args = parser.parse_args(argv)

    src = Path(args.src).resolve()
    dst = Path(args.dst).resolve()
    host = parse_upstream(args.upstream)

    stats = render(src, dst, host)

    leftovers = remaining_prod_hosts(dst)
    if leftovers:
        shutil.rmtree(dst, ignore_errors=True)
        print("NG: 描画後も本番ホストが残っている。出力を削除した:", file=sys.stderr)
        for item in leftovers:
            print(f"    {item}", file=sys.stderr)
        return 2

    print(f"OK: {src} -> {dst}")
    print(f"    アップストリーム: https://{host}")
    print(f"    走査ファイル: {stats['files']} / 置換: {stats['replacements']} / 残存する本番ホスト: 0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
