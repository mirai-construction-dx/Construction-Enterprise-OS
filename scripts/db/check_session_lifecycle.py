#!/usr/bin/env python3
"""リポジトリ不変条件の検査: DB セッションのトランザクション確定。

背景（実際に発生した障害）:
    `get_db` に `commit()` が無いサービスでは、サービス層で `flush()` 済みの
    書き込みが `session.close()` 時に暗黙ロールバックされ、API が 201/200 を
    返すのにデータが永続化されない（サイレントなデータ消失）。
    maintenance / security / vision の 3 サービスで発生し、修正済み。

不変条件:
    各サービスの `get_db` は次のいずれかを満たすこと。
      (a) 正常終了時に `session.commit()` を呼ぶ、または
      (b) ルート/サービス層で明示的に `commit()` を呼ぶ運用である
          （例: services/workflow は 20 件超の明示 commit を持つ）

使い方:
    python3 scripts/db/check_session_lifecycle.py      # 違反があれば非ゼロ
"""

from __future__ import annotations

import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]
SERVICES = REPO / "services"


def _read(path: pathlib.Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def get_db_commits(service_dir: pathlib.Path) -> bool:
    """get_db が正常終了時に commit しているか。"""
    base = service_dir / "src" / "models" / "base.py"
    if not base.exists():
        return True  # ORM を持たないサービスは対象外
    source = _read(base)
    match = re.search(r"async def get_db\(.*?\n(?=\nasync def |\Z)", source, re.S)
    if not match:
        return False
    return "session.commit()" in match.group(0)


def explicit_commits(service_dir: pathlib.Path) -> int:
    """src 配下の明示的な commit() 呼び出し数。"""
    count = 0
    for path in (service_dir / "src").rglob("*.py"):
        count += len(re.findall(r"\bcommit\(\)", _read(path)))
    return count


def main() -> int:
    violations: list[str] = []
    checked = 0

    for service_dir in sorted(p for p in SERVICES.iterdir() if p.is_dir()):
        base = service_dir / "src" / "models" / "base.py"
        if not base.exists():
            continue
        checked += 1
        if get_db_commits(service_dir):
            continue
        commits = explicit_commits(service_dir)
        if commits == 0:
            violations.append(
                f"{service_dir.name}: get_db に commit が無く、明示的な commit() も 0 件 "
                "→ 書き込みが暗黙ロールバックされ消失する"
            )
        else:
            print(
                f"ok {service_dir.name}: get_db に commit は無いが明示 commit {commits} 件"
            )

    if violations:
        print("セッション確定の不変条件に違反:", file=sys.stderr)
        for violation in violations:
            print(f"  - {violation}", file=sys.stderr)
        return 1

    print(f"セッション確定の不変条件を満たしています（get_db を持つ {checked} サービス）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
