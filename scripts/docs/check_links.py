#!/usr/bin/env python3
"""追跡下の Markdown のローカルリンクがすべて解決するかを検証する。

なぜ必要か（2026-10-14 の実測）:
    追跡下の .md 55 件を機械的に検査したところ **24 件のリンクが切れていた**。
    すべて `reports/quality-tests/` 配下で、原因は
    「リポジトリ根を基準にしたパスを、ファイル相対のリンクとして書いていた」ことである。

        [qa-construction.md](reports/quality-tests/qa-construction.md)

    これはファイル自身の位置から見ると `reports/quality-tests/reports/quality-tests/...`
    を指すため解決できない。リンクは静かに腐るので、機械的に検査する。

検査する内容:
    L-1 追跡下の `*.md` にあるローカルリンク（`http(s)`・`#`・`mailto:` 以外）が
        そのファイルの位置から解決できること。

    外部 URL の到達性は見ない（ネットワークに依存するため）。
    アンカー（`#...`）の存在確認もしない（見出しの改名を検出したい場合は別途）。

使い方:
    python3 scripts/docs/check_links.py
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
LINK = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
SKIP_PREFIXES = ("http://", "https://", "#", "mailto:")


def tracked_markdown() -> list[Path]:
    """git 追跡下の `*.md`。生成物や作業ツリーを対象にしない。"""
    raw = subprocess.run(
        ["git", "ls-files", "-z", "*.md"], cwd=REPO, capture_output=True, text=True, check=False
    ).stdout
    return [REPO / name for name in raw.split("\0") if name]


def main() -> int:
    files = tracked_markdown()
    checked = 0
    broken: list[tuple[str, str]] = []

    for path in files:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for match in LINK.finditer(text):
            target = match.group(1).strip()
            if target.startswith(SKIP_PREFIXES):
                continue
            target = target.split("#", 1)[0].strip()
            if not target:
                continue
            checked += 1
            if not (path.parent / target).resolve().exists():
                broken.append((str(path.relative_to(REPO)), target))

    print(f"追跡下の .md: {len(files)} 件 / 検査したローカルリンク: {checked} 件")
    if broken:
        print()
        for name, target in broken:
            print(f"FAIL: {name} -> {target}", file=sys.stderr)
        print()
        print(
            f"NG: リンク切れ {len(broken)} 件。リンクはそのファイルの位置からの相対パスで書くこと"
            "（リポジトリ根を基準にしたパスを書くと解決しない）。",
            file=sys.stderr,
        )
        return 1

    print("OK: すべてのローカルリンクが解決する。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
