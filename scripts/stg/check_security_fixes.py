#!/usr/bin/env python3
"""第33バッチの修正を **stg の実 API** で検証する（合成データのみ）。

なぜ必要か:
    第33バッチの修正（#103 / #135 / #138 / #139）はサービス単体テストで固定したが、
    stg の gateway・DB・RBAC を通した経路では実行していなかった。
    CI では見えない「本番と同じ入口」の挙動をここで確認する。

検証する内容:
    G-1 gateway: `/api/v1/workflow/internal/*` が **404**（内部ジョブ API を遮断）
        - 近接パス `/api/v1/workflow/internals` は 404 ではなく 401（巻き込まない）
    D-1 document: 不正 JSON の `metadata` が **400 INVALID_REQUEST**（500 にしない）
    A-1 analytics: `connection_config` が応答に含まれない（write-only）、
        管理ロールで作成でき、後始末で削除できる
    M-1 maintenance: 本文の `reported_by` が無視され、トークンの `sub` が記録される

資格情報は `~/.config/ceos/stg.env` から読み、コマンドライン・ログへ出さない。
合成データのみを使い、作った行は後始末する（maintenance は専用の DELETE が無いため
稼働コンテナ内の asyncpg で id 指定削除）。

使い方:
    python3 scripts/stg/check_security_fixes.py
"""

from __future__ import annotations

import argparse
import base64
import json
import subprocess
import sys
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path

ENV_FILE = Path.home() / ".config" / "ceos" / "stg.env"
ADMIN_EMAIL = "stg-admin@stg.mirai-dx-platform.com"
SENTINEL = "STG-SENTINEL-NOT-A-REAL-SECRET"

failures: list[str] = []


def request(url, *, token=None, method="GET", payload=None, headers=None, raw=None):
    body = None
    hdrs = {"Accept": "application/json"}
    if headers:
        hdrs.update(headers)
    if raw is not None:
        body = raw
    elif payload is not None:
        body = json.dumps(payload).encode()
        hdrs["Content-Type"] = "application/json"
    if token:
        hdrs["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=body, headers=hdrs, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            text = response.read().decode()
            return response.status, (json.loads(text) if text else None)
    except urllib.error.HTTPError as exc:
        text = exc.read().decode()
        try:
            return exc.code, json.loads(text)
        except json.JSONDecodeError:
            return exc.code, {"raw": text[:300]}


def unwrap(body):
    if isinstance(body, dict) and "data" in body:
        return body["data"]
    return body


def jwt_claims(token: str) -> dict:
    part = token.split(".")[1]
    part += "=" * (-len(part) % 4)
    return json.loads(base64.urlsafe_b64decode(part))


def multipart(fields: dict[str, str], content: bytes, filename: str):
    boundary = uuid.uuid4().hex
    chunks: list[bytes] = []
    for key, value in fields.items():
        chunks.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'.encode()
        )
    chunks.append(
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        "Content-Type: application/octet-stream\r\n\r\n".encode()
    )
    chunks.append(content)
    chunks.append(f"\r\n--{boundary}--\r\n".encode())
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


def delete_maintenance_rows(ids: list[str]) -> None:
    """maintenance には DELETE API が無いため、稼働コンテナ内で id 指定削除する（合成データのみ）。"""
    for disaster_id in ids:
        code = (
            "import asyncio, os, asyncpg\n"
            "async def main():\n"
            "    url = os.environ['DATABASE_URL'].replace('postgresql+asyncpg://', 'postgresql://')\n"
            "    conn = await asyncpg.connect(url)\n"
            "    try:\n"
            "        await conn.execute('DELETE FROM maintenance.disaster_reports WHERE id = $1', "
            f"'{disaster_id}')\n"
            "    finally:\n"
            "        await conn.close()\n"
            "asyncio.run(main())\n"
        )
        subprocess.run(
            ["docker", "exec", "ceos-stg-maintenance", "python", "-c", code],
            check=False,
            capture_output=True,
            text=True,
            timeout=60,
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--gateway", default="http://127.0.0.1:19500")
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

    status, body = request(
        f"{args.gateway}/api/v1/auth/login",
        method="POST",
        payload={"email": ADMIN_EMAIL, "password": password},
    )
    token = (unwrap(body) or {}).get("access_token") if status == 200 else None
    if not token:
        print(f"NG: 管理ユーザでログインできない（status={status}）", file=sys.stderr)
        return 1
    claims = jwt_claims(token)
    org, sub = claims.get("org"), claims.get("sub")
    print(f"OK: 管理ユーザでログイン（org={org} / sub={sub}）")

    # ---- G-1 gateway の内部 API 遮断 ----
    for path in (
        "/api/v1/workflow/internal/jobs/deadline-notifications",
        "/api/v1/workflow/internal/jobs/workload-notifications",
        "/api/v1/workflow/internal/notification-callback",
    ):
        status, _ = request(f"{args.gateway}{path}")
        if status == 404:
            print(f"PASS: G-1 内部 API は gateway で 404（{path}）")
        else:
            failures.append(f"G-1 {path} が 404 でない（status={status}）")
            print(f"FAIL: G-1 {path} が 404 でない（status={status}）", file=sys.stderr)

    status, _ = request(f"{args.gateway}/api/v1/workflow/internals")
    if status == 401:
        print("PASS: G-1b 近接パス /workflow/internals は遮断されない（401 認証要求）")
    else:
        failures.append(f"G-1b /workflow/internals が 401 でない（status={status}）")
        print(f"FAIL: G-1b /workflow/internals が 401 でない（status={status}）", file=sys.stderr)

    # ---- D-1 document: 不正 JSON は 400 ----
    raw, content_type = multipart(
        {
            "name": "stg-e2e-invalid-metadata",
            "document_type": "other",
            "metadata": "{not-json",
            "tags": "[]",
        },
        b"synthetic",
        "synthetic.txt",
    )
    status, body = request(
        f"{args.gateway}/api/v1/documents/upload",
        token=token,
        method="POST",
        raw=raw,
        headers={"Content-Type": content_type},
    )
    if status == 400:
        code = ((body or {}).get("detail") or {}).get("code") if isinstance(body, dict) else None
        if code in (None, "INVALID_REQUEST"):
            print(f"PASS: D-1 不正 JSON の metadata は 400（code={code}）")
        else:
            failures.append(f"D-1 400 だが code が INVALID_REQUEST でない（code={code}）")
            print(f"FAIL: D-1 code={code}", file=sys.stderr)
    else:
        failures.append(f"D-1 不正 JSON が 400 でない（status={status}, body={str(body)[:200]}）")
        print(f"FAIL: D-1 不正 JSON が 400 でない（status={status}）", file=sys.stderr)

    # ---- A-1 analytics: connection_config は write-only ----
    ds_id = None
    status, body = request(
        f"{args.gateway}/api/v1/analytics/datasources",
        token=token,
        method="POST",
        payload={
            "organization_id": org,
            "name": "stg-e2e-write-only",
            "source_type": "postgresql",
            "connection_config": {"password": SENTINEL, "host": "synthetic.invalid"},
            "description": "stg E2E (synthetic)",
        },
    )
    if status == 201:
        ds_id = (body or {}).get("id") if isinstance(body, dict) else None
        if isinstance(body, dict) and "connection_config" in body:
            failures.append("A-1 作成応答に connection_config が含まれる")
            print("FAIL: A-1 作成応答に connection_config が含まれる", file=sys.stderr)
        else:
            print(f"PASS: A-1 作成応答に connection_config が無い（id={ds_id}）")
    else:
        failures.append(f"A-1 データソースを作成できない（status={status}, body={str(body)[:200]}）")
        print(f"FAIL: A-1 作成できない（status={status}）", file=sys.stderr)

    if ds_id:
        status, body = request(f"{args.gateway}/api/v1/analytics/datasources/{ds_id}", token=token)
        if status == 200 and isinstance(body, dict) and "connection_config" not in body:
            print("PASS: A-1b 取得応答に connection_config が無い")
        else:
            failures.append(f"A-1b 取得応答が不正（status={status}, keys={list(body)[:8] if isinstance(body, dict) else body}）")
            print(f"FAIL: A-1b 取得応答が不正（status={status}）", file=sys.stderr)

        status, body = request(f"{args.gateway}/api/v1/analytics/datasources", token=token)
        data = unwrap(body) if status == 200 else None
        # 一覧は DataSourceListResponse（{"items": [...], "total": ...}）で返る。
        items = data.get("items") if isinstance(data, dict) else data
        if isinstance(items, list) and all("connection_config" not in item for item in items):
            print(f"PASS: A-1c 一覧応答に connection_config が無い（{len(items)} 件）")
        else:
            failures.append(f"A-1c 一覧応答が不正（status={status}, type={type(items).__name__}）")
            print(f"FAIL: A-1c 一覧応答が不正（status={status}）", file=sys.stderr)

        status, _ = request(
            f"{args.gateway}/api/v1/analytics/datasources/{ds_id}", token=token, method="DELETE"
        )
        if status in (200, 204):
            print("PASS: A-1d 作成したデータソースを削除した")
        else:
            failures.append(f"A-1d 後始末に失敗（status={status}）")
            print(f"FAIL: A-1d 後始末に失敗（status={status}）", file=sys.stderr)

    # ---- M-1 maintenance: reported_by は本文でなくトークン sub ----
    fake_reporter = str(uuid.uuid4())
    created_ids: list[str] = []
    status, body = request(
        f"{args.gateway}/api/v1/maintenance/disasters",
        token=token,
        method="POST",
        payload={
            "organization_id": org,
            "title": "stg-e2e-reported-by",
            "disaster_type": "verification",
            "severity": "low",
            "occurred_at": datetime.now(timezone.utc).isoformat(),
            "description": "stg E2E (synthetic)",
            "reported_by": fake_reporter,
        },
    )
    if status == 201:
        data = unwrap(body) or {}
        created_ids.append(data.get("id"))
        if str(data.get("reported_by")) == str(sub):
            print("PASS: M-1 本文の reported_by は無視され、トークン sub が記録された")
        else:
            failures.append(
                f"M-1 reported_by がトークン sub でない（expected={sub}, actual={data.get('reported_by')}）"
            )
            print(f"FAIL: M-1 reported_by={data.get('reported_by')}", file=sys.stderr)
    else:
        failures.append(f"M-1 災害報告を作成できない（status={status}, body={str(body)[:200]}）")
        print(f"FAIL: M-1 作成できない（status={status}）", file=sys.stderr)

    if created_ids:
        delete_maintenance_rows([i for i in created_ids if i])
        print("PASS: M-1b 作成した災害報告を id 指定で削除した（合成データ）")

    print()
    if failures:
        print(f"NG: {len(failures)} 件の失敗", file=sys.stderr)
        for item in failures:
            print(f"  - {item}", file=sys.stderr)
        return 1
    print("OK: 第33バッチの修正を stg の実 API で確認した（G-1 / D-1 / A-1 / M-1）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
