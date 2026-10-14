#!/usr/bin/env python3
"""stg の MCP サーバーを実際に叩き、契約どおりに使えることを検証する。

なぜ必要か:
    `smoke.sh` の S-8 は `/health` の `registered_tools` が契約
    `contracts/mcp-tools/ceos.json` と一致することまでしか見ていない。
    **ツールが実際に呼べて上流のデータを返すか**は未検証だった。
    この契約は姉妹リポジトリ（Construction-Site-Spatial-Platform 等）が
    read 系 MCP として消費する対象であり、名前が一致していても呼べなければ意味がない。

検証する内容:
    M-1 `/mcp/` が未認証で 401（fail-closed）
    M-2 認証ありで `initialize` が成功する
    M-3 `tools/list` が契約と同じ 5 ツールを返す
    M-4 `tools/call` が実際に上流から応答を得る（`ceos.ledger.get_summary`）
        - 上流がエラーを返す場合も、**MCP のプロトコルエラーではなく上流の応答**であること
          （認証・ルーティングが通っている証拠）。区別して報告する。

資格情報は `~/.config/ceos/stg.env` から読み、コマンドラインへ出さない。
メールアドレスは秘密ではないため定数（RFC 2606 の予約ドメインは EmailStr が 422 にする）。

使い方:
    python3 scripts/stg/check_mcp_e2e.py [--base http://127.0.0.1:19522]
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
ENV_FILE = Path.home() / ".config" / "ceos" / "stg.env"
ADMIN_EMAIL = "stg-admin@stg.mirai-dx-platform.com"
PROTOCOL_VERSION = "2025-06-18"

failures: list[str] = []


def post(url: str, payload: dict, token: str | None = None, session: str | None = None) -> tuple[int, dict | None, dict]:
    """JSON-RPC を送る。SSE（text/event-stream）で返る場合も JSON を取り出す。"""
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if session:
        headers["Mcp-Session-Id"] = session
    request = urllib.request.Request(url, data=json.dumps(payload).encode(), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            body = response.read().decode()
            content_type = response.headers.get("content-type", "")
            resp_headers = {k.lower(): v for k, v in response.headers.items()}
            status = response.status
    except urllib.error.HTTPError as exc:
        body = exc.read().decode()
        content_type = exc.headers.get("content-type", "") if exc.headers else ""
        resp_headers = {k.lower(): v for k, v in (exc.headers or {}).items()}
        status = exc.code

    parsed: dict | None = None
    if "text/event-stream" in content_type:
        for line in body.splitlines():
            if line.startswith("data:"):
                try:
                    parsed = json.loads(line[5:].strip())
                except json.JSONDecodeError:
                    continue
                break
    else:
        try:
            parsed = json.loads(body)
        except json.JSONDecodeError:
            parsed = None
    return status, parsed, resp_headers


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base", default="http://127.0.0.1:19522")
    parser.add_argument("--gateway", default="http://127.0.0.1:19500")
    args = parser.parse_args(argv)

    mcp_url = f"{args.base}/mcp/"
    contract = json.loads((REPO / "contracts" / "mcp-tools" / "ceos.json").read_text(encoding="utf-8"))
    expected_tools = sorted(t["name"] for t in contract["tools"])

    # --- M-1 未認証は 401 ---
    status, _, _ = post(mcp_url, {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    if status == 401:
        print("PASS: M-1 /mcp/ は未認証で 401（fail-closed）")
    else:
        failures.append(f"M-1 未認証の応答が 401 ではない（{status}）")
        print(f"FAIL: M-1 未認証の応答が 401 ではない（{status}）", file=sys.stderr)

    # --- トークン取得 ---
    if not ENV_FILE.exists():
        print(f"NG: {ENV_FILE} が無い。scripts/stg/gen_stg_env.sh を実行すること。", file=sys.stderr)
        return 1
    password = ""
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        if line.startswith("STG_SMOKE_ADMIN_PASSWORD="):
            password = line.split("=", 1)[1]
    if not password:
        print(f"NG: {ENV_FILE} に STG_SMOKE_ADMIN_PASSWORD が無い。", file=sys.stderr)
        return 1

    login = urllib.request.Request(
        f"{args.gateway}/api/v1/auth/login",
        data=json.dumps({"email": ADMIN_EMAIL, "password": password}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(login, timeout=20) as response:
            body = json.loads(response.read().decode())
    except Exception as exc:  # noqa: BLE001 - 失敗はそのまま報告する
        print(f"NG: ログインに失敗した（{exc}）。scripts/stg/seed_stg.sh を実行したか確認。", file=sys.stderr)
        return 1
    token = body.get("access_token") or (body.get("data") or {}).get("access_token")
    if not token:
        print("NG: アクセストークンを取得できない。", file=sys.stderr)
        return 1

    # --- M-2 initialize ---
    status, parsed, headers = post(
        mcp_url,
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "ceos-stg-check", "version": "0.1.0"},
            },
        },
        token=token,
    )
    session = headers.get("mcp-session-id")
    if status == 200 and parsed and "result" in parsed:
        print(f"PASS: M-2 initialize 成功（session={'あり' if session else 'なし'}）")
    else:
        failures.append(f"M-2 initialize が失敗（status={status}, body={str(parsed)[:120]}）")
        print(f"FAIL: M-2 initialize が失敗（status={status}）", file=sys.stderr)

    # initialize 後の initialized 通知（仕様上必要。失敗しても続行する）
    if session:
        post(mcp_url, {"jsonrpc": "2.0", "method": "notifications/initialized"}, token=token, session=session)

    # --- M-3 tools/list ---
    status, parsed, _ = post(mcp_url, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, token=token, session=session)
    names: list[str] = []
    if parsed and isinstance(parsed.get("result"), dict):
        names = sorted(t.get("name", "") for t in parsed["result"].get("tools", []))
    if names == expected_tools and names:
        print(f"PASS: M-3 tools/list が契約と一致（{len(names)} 件）")
    else:
        failures.append(f"M-3 tools/list が契約と一致しない（got={names}, want={expected_tools}）")
        print(f"FAIL: M-3 tools/list が契約と一致しない（status={status}）", file=sys.stderr)

    # --- M-4 tools/call（引数が不要な 2 ツールを実際に呼ぶ） ---
    # `isError: true` は「上流に到達できない」等の失敗であり、result が返ること自体を
    # 成功とみなしてはならない（2026-10-14 実測: 上流 URL 未設定のとき
    # {"content":[{"type":"text","text":"上流サービスに到達できません。"}],"isError":true}
    # が result として返り、初版の検査はこれを通してしまっていた）。
    for index, tool in enumerate(("ceos.ledger.get_summary", "ceos.contract.list"), start=3):
        status, parsed, _ = post(
            mcp_url,
            {"jsonrpc": "2.0", "id": index, "method": "tools/call", "params": {"name": tool, "arguments": {}}},
            token=token,
            session=session,
        )
        result = (parsed or {}).get("result")
        error = (parsed or {}).get("error")
        if error is not None:
            failures.append(f"M-4 {tool} がプロトコルエラー（{json.dumps(error, ensure_ascii=False)[:120]}）")
            print(f"FAIL: M-4 {tool} がプロトコルエラー（status={status}）", file=sys.stderr)
            continue
        if result is None:
            failures.append(f"M-4 {tool} の応答を解釈できない（status={status}）")
            print(f"FAIL: M-4 {tool} の応答を解釈できない（status={status}）", file=sys.stderr)
            continue
        if result.get("isError"):
            text = " ".join(c.get("text", "") for c in result.get("content", []) if isinstance(c, dict))[:120]
            failures.append(f"M-4 {tool} が isError を返した（{text}）")
            print(f"FAIL: M-4 {tool} が isError を返した（{text}）", file=sys.stderr)
            continue
        text = json.dumps(result, ensure_ascii=False)[:140]
        print(f"PASS: M-4 {tool} が上流から応答を得た（{text}）")

    print()
    if failures:
        for item in failures:
            print(f"NG: {item}", file=sys.stderr)
        return 1
    print("OK: MCP サーバーは契約どおりに初期化・一覧・呼び出しができる。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
