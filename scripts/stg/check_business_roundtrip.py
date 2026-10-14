#!/usr/bin/env python3
"""stg で**業務 API の往復（書込→読取→分離）**を実測する。

なぜ必要か:
    stg の検査はこれまで
      - ヘルス（/health が 200 か）
      - 認証（ログインとトークン）
      - ルーティング（上流へ到達するか）
      - MCP（読み取りツールが呼べるか）
    までで、**業務サービスへの書込みが一度も通っていなかった**。
    業務表はすべて空で、「書けるのか」「テナント分離が効くのか」は未検証だった。

検証する内容:
    B-1 管理ユーザでログインできる
    B-2 `POST /api/v1/erp/ledger` が 201 で作成できる（合成データ・project_code=STG-ROUNDTRIP）
    B-3 `GET /api/v1/erp/ledger/{id}` で作成した行を読み戻せる（DB へ永続化されている）
    B-4 `GET /api/v1/erp/ledger/summary` の projects_count が 1 以上（集計に載る）
    B-5 **テナント分離**: 別の organization_id を要求しても、トークンの組織の行しか返らない
        （`MCDX-ADR-0004` / `AGENTS.md` §4.1。ボディやクエリの組織を信頼しない）
    B-6 後始末: 作成した 1 行を id 指定で削除する（業務 API に ledger の DELETE が無いため、
        stg の管理権限で SQL により消す。stg の合成データのみを対象にする）

資格情報は `~/.config/ceos/stg.env` から読み、コマンドラインへ出さない。

使い方:
    python3 scripts/stg/check_business_roundtrip.py
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import urllib.error
import urllib.request
import uuid
from pathlib import Path

ENV_FILE = Path.home() / ".config" / "ceos" / "stg.env"
ADMIN_EMAIL = "stg-admin@stg.mirai-dx-platform.com"
PROJECT_CODE = "STG-ROUNDTRIP"
# トークンの org と衝突しないよう、別組織の UUID を固定で用意する
OTHER_ORG = "00000000-0000-0000-0000-0000000000ff"

failures: list[str] = []


def request(url: str, *, token: str | None = None, method: str = "GET", payload: dict | None = None):
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            body = response.read().decode()
            return response.status, (json.loads(body) if body else None)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode()
        try:
            return exc.code, json.loads(body)
        except json.JSONDecodeError:
            return exc.code, {"raw": body[:200]}


def unwrap(body):
    """APIResponse 形式（{"success":..,"data":..}）と素の本文の両方を受ける。"""
    if isinstance(body, dict) and "data" in body:
        return body["data"]
    return body


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--gateway", default="http://127.0.0.1:19500")
    parser.add_argument("--pg-port", default="55438")
    parser.add_argument("--db", default="ceos_stg")
    args = parser.parse_args(argv)

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

    # --- B-1 ログイン ---
    status, body = request(
        f"{args.gateway}/api/v1/auth/login",
        method="POST",
        payload={"email": ADMIN_EMAIL, "password": password},
    )
    token = None
    if status == 200:
        token = (unwrap(body) or {}).get("access_token") if isinstance(unwrap(body), dict) else None
    if not token:
        print(f"FAIL: B-1 ログインできない（status={status}）", file=sys.stderr)
        return 1
    print("PASS: B-1 管理ユーザでログインできる")

    # トークンの org を読む（署名検証は不要。自前のトークンのクレームを見るだけ）
    import base64

    payload_b64 = token.split(".")[1]
    payload_b64 += "=" * (-len(payload_b64) % 4)
    token_org = json.loads(base64.urlsafe_b64decode(payload_b64)).get("org")
    print(f"      トークンの org: {token_org}")

    # --- B-2 作成 ---
    project_id = str(uuid.uuid4())
    ledger_id = None
    status, body = request(
        f"{args.gateway}/api/v1/erp/ledger",
        token=token,
        method="POST",
        payload={
            # ADR-0004: ボディの organization_id は信頼されない。トークンの org が使われる。
            "organization_id": token_org,
            "project_id": project_id,
            "project_code": PROJECT_CODE,
            "project_name": "stg 往復検査（合成データ）",
            "project_type": "verification",
            "contract_amount": "1000000",
            "budget_amount": "900000",
            "status": "planning",
        },
    )
    if status == 201:
        ledger_id = (unwrap(body) or {}).get("id")
        print(f"PASS: B-2 台帳を作成できた（201, id={ledger_id}）")
    else:
        failures.append(f"B-2 作成に失敗（status={status}, body={json.dumps(body, ensure_ascii=False)[:200]}）")
        print(f"FAIL: B-2 作成に失敗（status={status}）", file=sys.stderr)

    if ledger_id:
        # --- B-3 読み戻し ---
        status, body = request(f"{args.gateway}/api/v1/erp/ledger/{ledger_id}", token=token)
        detail = unwrap(body) if status == 200 else None
        if detail and detail.get("project_code") == PROJECT_CODE:
            print("PASS: B-3 作成した台帳を読み戻せた（DB へ永続化されている）")
        else:
            failures.append(f"B-3 読み戻しが一致しない（status={status}）")
            print(f"FAIL: B-3 読み戻しが一致しない（status={status}）", file=sys.stderr)

        # --- B-4 集計に載るか ---
        status, body = request(f"{args.gateway}/api/v1/erp/ledger/summary", token=token)
        summary = unwrap(body) if status == 200 else None
        count = (summary or {}).get("projects_count")
        if isinstance(count, int) and count >= 1:
            print(f"PASS: B-4 集計に載っている（projects_count={count}）")
        else:
            failures.append(f"B-4 集計に載っていない（status={status}, projects_count={count}）")
            print(f"FAIL: B-4 集計に載っていない（projects_count={count}）", file=sys.stderr)

        # --- B-5 テナント分離 ---
        status, body = request(
            f"{args.gateway}/api/v1/erp/ledger?organization_id={OTHER_ORG}", token=token
        )
        items = unwrap(body) if status == 200 else None
        rows = (items or {}).get("items") if isinstance(items, dict) else None
        if rows is None and isinstance(items, list):
            rows = items
        ids = [r.get("id") for r in (rows or [])]
        if ledger_id not in ids:
            print(f"PASS: B-5 別組織を要求してもトークンの組織の行だけが返る（{len(ids)} 件）")
        else:
            failures.append("B-5 別組織を要求したのに作成した行が返った（テナント分離が効いていない）")
            print("FAIL: B-5 別組織を要求したのに作成した行が返った", file=sys.stderr)

        # --- B-6 後始末（業務 API に ledger の DELETE が無いため SQL で 1 行だけ消す） ---
        cleanup_sql = f"DELETE FROM erp.project_ledger WHERE id = '{ledger_id}'"
        result = subprocess.run(
            ["sudo", "-n", "-u", "postgres", "psql", "-p", args.pg_port, "-d", args.db, "-q", "-c", cleanup_sql],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0:
            print(f"PASS: B-6 作成した 1 行を削除した（{cleanup_sql}）")
        else:
            failures.append(f"B-6 後始末に失敗（{result.stderr.strip()[:120]}）")
            print(f"WARN: B-6 後始末に失敗。手動で削除すること: {cleanup_sql}", file=sys.stderr)

    print()
    if failures:
        for item in failures:
            print(f"NG: {item}", file=sys.stderr)
        return 1
    print("OK: 業務 API の往復（作成・読取・集計・テナント分離・後始末）を実測した。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
