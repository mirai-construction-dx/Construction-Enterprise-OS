#!/usr/bin/env python3
"""stg の Pages デプロイが**本番 API を向いていない**ことを機械的に検証する。

なぜ必要か（2026-10-14 の実測）:
    `webui/functions/api/[[path]].ts` は `/api/*` を本番 API へ無条件転送する
    （`construction-os-api.mirai-dx-platform.com`）。prod と stg の Pages は
    この 1 ファイルを共有するため、**そのまま配れば stg が本番 API を叩く**。

    `staging-deploy.workflow.yml` の preflight は DNS と Access しか見ない。
    したがって DNS ブロッカー（Zone→DNS→Edit 権限）が解けた瞬間に、
    越境したまま「緑で」デプロイされ得る。人の記憶ではなく検査で止める。

検査する内容:
    C-1 共有ソース `webui/functions` が本番ホストを含むこと
        （＝描画ステップが必須である前提が崩れていないこと）。
    C-2 stg のデプロイ定義が `render_pages_functions.py` を通すこと。
        かつ `webui/functions` を**そのまま**コピーしていないこと。
    C-3 `STG_API_UPSTREAM` が定義され、本番ホストを指していないこと。
    C-4 陽性対照: stg の入口で描画すると本番ホストが 0 件になること。
    C-5 陰性対照: 本番ホストを入口に指定すると**拒否**されること。
    C-6 共有ソースに現れる `mirai-dx-platform.com` のホストが
        すべて `PROD_HOSTS` に登録されていること（本番ホストの追加漏れ検出）。

`SKIP` を作らない。判定できないものは FAIL として報告する（`AGENTS.md` §4.7）。

使い方:
    python3 scripts/stg/check_pages_upstream.py
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SHARED_FUNCTIONS = REPO / "webui" / "functions"
FUNCTION_FILE = SHARED_FUNCTIONS / "api" / "[[path]].ts"
WORKFLOW = REPO / "docs" / "operations" / "staging-deploy.workflow.yml"
RENDERER = REPO / "scripts" / "stg" / "render_pages_functions.py"

HOST_RE = re.compile(r"[a-z0-9][a-z0-9.-]*\.mirai-dx-platform\.com")

# stg の API 入口（家族パターン: `<name>-stg(-api).mirai-dx-platform.com`）
STG_API_HOST = "construction-os-stg-api.mirai-dx-platform.com"


def load_prod_hosts() -> tuple[str, ...]:
    """`render_pages_functions.py` の `PROD_HOSTS` を唯一の正本として読む。"""
    sys.path.insert(0, str(RENDERER.parent))
    try:
        import render_pages_functions  # type: ignore[import-not-found]
    finally:
        sys.path.pop(0)
    return tuple(render_pages_functions.PROD_HOSTS)


def render(dst: Path, upstream: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(RENDERER),
            "--src",
            str(SHARED_FUNCTIONS),
            "--dst",
            str(dst),
            "--upstream",
            upstream,
        ],
        capture_output=True,
        text=True,
        check=False,
    )


def main() -> int:
    failures: list[str] = []
    prod_hosts = load_prod_hosts()

    # ---- C-1 共有ソースに本番ホストが含まれる（描画が必須である前提） ----
    source = FUNCTION_FILE.read_text(encoding="utf-8")
    source_prod = [h for h in prod_hosts if h in source]
    if len(source_prod) < 1:
        failures.append(
            "C-1 共有ソース webui/functions に本番ホストが 1 つも無い。"
            "アップストリームの持ち方が変わった可能性がある。render_pages_functions.py と本検査を実測で見直すこと。"
        )
    print(f"C-1 共有ソースが含む本番ホスト: {len(source_prod)} 種 {source_prod}")

    # ---- C-6 共有ソースのホストがすべて PROD_HOSTS に登録されている ----
    declared = set(prod_hosts)
    seen = set(HOST_RE.findall(source))
    undeclared = sorted(seen - declared)
    if undeclared:
        failures.append(
            f"C-6 共有ソースに未登録の mirai-dx-platform.com ホストがある: {undeclared}。"
            "render_pages_functions.py の PROD_HOSTS へ追加すること（追加しないと stg へ残る）。"
        )
    print(f"C-6 共有ソースのホスト {sorted(seen)} / 未登録: {len(undeclared)}")

    # ---- C-2 デプロイ定義が描画を通す ----
    workflow = WORKFLOW.read_text(encoding="utf-8")
    if RENDERER.name not in workflow:
        failures.append(
            f"C-2 stg のデプロイ定義が {RENDERER.name} を呼んでいない: {WORKFLOW.relative_to(REPO)}"
        )
    if re.search(r"cp\s+-r\s+webui/functions\s+\.deploy-webui/functions", workflow):
        failures.append(
            "C-2 stg のデプロイ定義が webui/functions をそのままコピーしている"
            "（本番 API を指したまま stg へ配られる）。"
        )
    print(f"C-2 描画ステップの呼び出し: {RENDERER.name in workflow}")

    # ---- C-3 STG_API_UPSTREAM の定義と非本番性 ----
    if "STG_API_UPSTREAM" not in workflow:
        failures.append("C-3 stg のデプロイ定義に STG_API_UPSTREAM が無い。")
    else:
        values = re.findall(r"STG_API_UPSTREAM:\s*(\S+)", workflow)
        if not values:
            failures.append("C-3 STG_API_UPSTREAM が定義されているが値が読めない。")
        for value in values:
            host = value.split("://", 1)[-1].split("/", 1)[0]
            if host in prod_hosts:
                failures.append(f"C-3 STG_API_UPSTREAM が本番ホストを指している: {host}")
            elif host != STG_API_HOST:
                failures.append(
                    f"C-3 STG_API_UPSTREAM が想定の stg 入口と異なる: {host}（想定 {STG_API_HOST}）"
                )
        print(f"C-3 STG_API_UPSTREAM: {values}")

    # ---- C-4 陽性対照 / C-5 陰性対照 ----
    tmp = Path(tempfile.mkdtemp(prefix="ceos-stg-pages-"))
    try:
        ok = render(tmp / "good", f"https://{STG_API_HOST}")
        if ok.returncode != 0:
            failures.append(f"C-4 stg の入口で描画できない（exit={ok.returncode}）: {ok.stderr.strip()}")
        else:
            leftover = [h for h in prod_hosts if h in (tmp / "good" / "api" / "[[path]].ts").read_text(encoding="utf-8")]
            if leftover:
                failures.append(f"C-4 描画後も本番ホストが残っている: {leftover}")
            if STG_API_HOST not in (tmp / "good" / "api" / "[[path]].ts").read_text(encoding="utf-8"):
                failures.append(f"C-4 描画後に stg の入口 {STG_API_HOST} が入っていない")
            print(f"C-4 陽性対照: exit={ok.returncode} / 残存本番ホスト={len(leftover)}")

        bad = render(tmp / "bad", f"https://{prod_hosts[0]}")
        if bad.returncode == 0:
            failures.append(
                f"C-5 陰性対照が失敗しない（本番ホスト {prod_hosts[0]} を入口に指定しても描画できてしまう）。"
            )
        print(f"C-5 陰性対照: exit={bad.returncode}（0 以外が正しい）")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print()
    if failures:
        print(f"NG: {len(failures)} 件", file=sys.stderr)
        for item in failures:
            print(f"  - {item}", file=sys.stderr)
        return 1
    print("OK: stg の Pages デプロイ経路は本番 API を向いていない（C-1〜C-6）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
