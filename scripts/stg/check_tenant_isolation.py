#!/usr/bin/env python3
"""stg で**テナント分離が実際に効いているか**を実測する。

なぜ必要か（2026-10-14 の実測）:
    `scripts/stg/check_business_roundtrip.py` の B-5 は
    「別組織を要求してもトークンの組織の行だけが返る」と表示していたが、
    **分離の証拠になっていなかった**。

    同スクリプトが使うのは stg の管理ユーザで、そのトークンは `roles: ['admin']` である。
    `services/erp/src/middleware/tenant.py` の `scope_org()` は
    **admin には要求された組織をそのまま返す**（クロス組織アクセスは設計）。
    したがって `?organization_id=<他組織>` が 0 件になるのは
    「他組織にデータが無い」だけで、分離が効いていることの証明にはならない。

    実測（2026-10-14）:

        # 管理ユーザ（roles: ['admin']）
        パラメータ無し        status=200 件数=1 自分の行を含む=True
        自分の org を指定     status=200 件数=1 自分の行を含む=True
        他組織を指定          status=200 件数=0 自分の行を含む=False   ← これが B-5 の「PASS」

    本来の分離は **非 admin** でしか測れない。stg には管理ユーザ 1 人しかおらず、
    非 admin の経路は**一度も実行されていなかった**。

検証する内容:
    T-1 非 admin ユーザーでログインでき、トークンに admin が含まれない
    T-2a **陽性対照**: 管理ユーザの一覧には検体（本社組織の行）が含まれる
        （これが無いと T-2 は「行が無い」「一覧が常に空」でも通ってしまう）
    T-2 **他組織のデータが見えない**: 管理ユーザが本社組織に作った行が、
        現場組織のユーザーの一覧に現れない（＝分離が効いている）
    T-3 他組織を要求すると **403 ORG_FORBIDDEN**（クエリ）
    T-4 他組織を指定した作成は **403 ORG_FORBIDDEN**（ボディ）
    T-5 後始末: 作成した 1 行を削除する

なぜ 403 を期待するか:
    `scope_org()` と `create_org()` は、非 admin が自分の組織以外を要求したら
    `ORG_FORBIDDEN` を返す（`MCDX-ADR-0004` / `AGENTS.md` §4.1）。
    erp の台帳 API は権限チェックを持たず `get_current_user` と
    `scope_org()` / `create_org()` だけで守られているため、
    403 の理由が「権限不足」と混同されない（エラーコードで判別する）。

資格情報は `~/.config/ceos/stg.env` から読み、コマンドラインへ出さない。
分離試験用ユーザーのパスワードは**合成の定数**である（stg 専用。実在の資格情報ではない）。

使い方:
    python3 scripts/stg/check_tenant_isolation.py
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
from pathlib import Path

ENV_FILE = Path.home() / ".config" / "ceos" / "stg.env"

# 管理ユーザ（本社組織 00000000-0000-0000-0000-000000000001）
ADMIN_EMAIL = "stg-admin@stg.mirai-dx-platform.com"
# 分離試験用の非 admin ユーザー。現場組織に置く（本社とは別組織）。
ISOLATION_EMAIL = "stg-site@stg.mirai-dx-platform.com"
ISOLATION_USERNAME = "stg-site"
# 合成の定数。stg の合成データ専用であり、実在の資格情報ではない。
# （リポジトリには `AdminPass123!` という検証用作成資格情報の前例がある）
ISOLATION_PASSWORD = "StgSitePass123!"
# 現場組織（scripts/db/seed/00-bootstrap.sql が作る合成データ）
ISOLATION_ORG = "20000000-0000-0000-0000-000000000004"
# 管理ユーザの組織（本社）
ADMIN_ORG = "00000000-0000-0000-0000-000000000001"
PROJECT_CODE = "STG-ISOLATION"

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
    if isinstance(body, dict) and "data" in body:
        return body["data"]
    return body


def error_code(body) -> str:
    """エラー本文から code を取り出す（形状が複数あるため寛容に）。"""
    if not isinstance(body, dict):
        return ""
    for key in ("detail", "error"):
        value = body.get(key)
        if isinstance(value, dict) and value.get("code"):
            return str(value["code"])
    return str(body.get("code") or "")


def claims(token: str) -> dict:
    part = token.split(".")[1]
    part += "=" * (-len(part) % 4)
    return json.loads(base64.urlsafe_b64decode(part))


def login(gateway: str, email: str, password: str):
    status, body = request(
        f"{gateway}/api/v1/auth/login", method="POST", payload={"email": email, "password": password}
    )
    if status == 200:
        data = unwrap(body) or {}
        return data.get("access_token")
    return None


def ensure_isolation_user(gateway: str, admin_token: str) -> bool:
    """分離試験用の非 admin ユーザーを冪等に用意する。"""
    status, body = request(
        f"{gateway}/api/v1/users",
        token=admin_token,
        method="POST",
        payload={
            "organization_id": ISOLATION_ORG,
            "email": ISOLATION_EMAIL,
            "username": ISOLATION_USERNAME,
            "password": ISOLATION_PASSWORD,
            "display_name": "stg 分離試験（合成）",
            "role_ids": [],
        },
    )
    if status == 201:
        print(f"      分離試験用ユーザーを作成した（{ISOLATION_EMAIL} / 現場組織 / role なし）")
        return True
    if status == 409:
        print(f"      分離試験用ユーザーは既にある（{ISOLATION_EMAIL}）")
        return True
    print(
        f"FAIL: T-0 分離試験用ユーザーを用意できない（status={status}, "
        f"{json.dumps(body, ensure_ascii=False)[:200]}）",
        file=sys.stderr,
    )
    return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--gateway", default="http://127.0.0.1:19500")
    parser.add_argument("--pg-port", default="55438")
    parser.add_argument("--db", default="ceos_stg")
    args = parser.parse_args(argv)

    if not ENV_FILE.exists():
        print(f"NG: {ENV_FILE} が無い。scripts/stg/gen_stg_env.sh を実行すること。", file=sys.stderr)
        return 1
    admin_password = ""
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        if line.startswith("STG_SMOKE_ADMIN_PASSWORD="):
            admin_password = line.split("=", 1)[1]
    if not admin_password:
        print(f"NG: {ENV_FILE} に STG_SMOKE_ADMIN_PASSWORD が無い。", file=sys.stderr)
        return 1

    # --- 管理ユーザでログイン（データを作る側） ---
    admin_token = login(args.gateway, ADMIN_EMAIL, admin_password)
    if not admin_token:
        print("FAIL: 管理ユーザでログインできない", file=sys.stderr)
        return 1
    admin_claims = claims(admin_token)
    if "admin" not in (admin_claims.get("roles") or []):
        print(
            f"NG: 管理ユーザのトークンに admin が無い（roles={admin_claims.get('roles')}）。"
            " この検査は管理ユーザが admin である前提で書かれている。",
            file=sys.stderr,
        )
        return 1

    # --- T-0 非 admin ユーザーを用意する ---
    print("== T-0 分離試験用の非 admin ユーザー ==")
    if not ensure_isolation_user(args.gateway, admin_token):
        return 1

    # --- T-1 非 admin でログインする ---
    print("== T-1 非 admin でログインできる ==")
    iso_token = login(args.gateway, ISOLATION_EMAIL, ISOLATION_PASSWORD)
    if not iso_token:
        failures.append("T-1 非 admin ユーザーでログインできない")
        print("FAIL: T-1 非 admin ユーザーでログインできない", file=sys.stderr)
        return 1
    iso_claims = claims(iso_token)
    iso_roles = iso_claims.get("roles") or []
    if "admin" in iso_roles:
        failures.append(f"T-1 分離試験用ユーザーが admin になっている（roles={iso_roles}）")
        print(f"FAIL: T-1 分離試験用ユーザーが admin である（roles={iso_roles}）", file=sys.stderr)
        return 1
    if iso_claims.get("org") != ISOLATION_ORG:
        failures.append(f"T-1 トークンの org が想定と違う（{iso_claims.get('org')} != {ISOLATION_ORG}）")
        print(f"FAIL: T-1 トークンの org が想定と違う（{iso_claims.get('org')}）", file=sys.stderr)
    else:
        print(f"PASS: T-1 非 admin でログインできた（org={iso_claims.get('org')} / roles={iso_roles}）")

    # --- 本社組織に 1 行作る（リークの検体） ---
    project_id = str(uuid.uuid4())
    status, body = request(
        f"{args.gateway}/api/v1/erp/ledger",
        token=admin_token,
        method="POST",
        payload={
            "organization_id": ADMIN_ORG,
            "project_id": project_id,
            "project_code": PROJECT_CODE,
            "project_name": "stg 分離試験（合成データ）",
            "project_type": "verification",
            "contract_amount": "1000000",
            "budget_amount": "900000",
            "status": "planning",
        },
    )
    ledger_id = (unwrap(body) or {}).get("id") if status == 201 else None
    if not ledger_id:
        print(f"FAIL: 検体の作成に失敗（status={status}）", file=sys.stderr)
        return 1
    print(f"      本社組織に検体を 1 行作成した（id={ledger_id}）")

    try:
        # --- T-2a 陽性対照: 管理ユーザにはその行が見える ---
        # これが無いと T-2 は「行が作られていない」「一覧が常に空」でも通ってしまう。
        print("== T-2a 陽性対照（管理ユーザには見える） ==")
        status, body = request(f"{args.gateway}/api/v1/erp/ledger", token=admin_token)
        data = unwrap(body) if status == 200 else None
        admin_rows = (data or {}).get("items") if isinstance(data, dict) else data
        admin_ids = [r.get("id") for r in (admin_rows or [])]
        if status == 200 and ledger_id in admin_ids:
            print(f"PASS: T-2a 管理ユーザの一覧には検体が含まれる（{len(admin_ids)} 件）")
        else:
            failures.append(
                f"T-2a 陽性対照が成立しない（status={status}, 検体を含む={ledger_id in admin_ids}）。"
                " T-2 は何も測っていない可能性がある"
            )
            print(
                f"FAIL: T-2a 管理ユーザの一覧に検体が無い（status={status}, {len(admin_ids)} 件）",
                file=sys.stderr,
            )

        # --- T-2 他組織のデータが見えない ---
        print("== T-2 他組織のデータが見えない ==")
        status, body = request(f"{args.gateway}/api/v1/erp/ledger", token=iso_token)
        data = unwrap(body) if status == 200 else None
        rows = (data or {}).get("items") if isinstance(data, dict) else data
        ids = [r.get("id") for r in (rows or [])]
        if status != 200:
            failures.append(f"T-2 一覧が 200 でない（status={status}）")
            print(f"FAIL: T-2 一覧が 200 でない（status={status}）", file=sys.stderr)
        elif ledger_id in ids:
            failures.append("T-2 他組織（本社）の行が現場組織のユーザーに見えている")
            print("FAIL: T-2 他組織の行が見えている（テナント分離が効いていない）", file=sys.stderr)
        else:
            print(f"PASS: T-2 本社組織の行は見えない（現場組織のユーザーの一覧 {len(ids)} 件）")

        # --- T-3 他組織を要求すると 403 ---
        print("== T-3 他組織を要求すると 403 ==")
        status, body = request(
            f"{args.gateway}/api/v1/erp/ledger?organization_id={ADMIN_ORG}", token=iso_token
        )
        code = error_code(body)
        if status == 403 and code == "ORG_FORBIDDEN":
            print("PASS: T-3 他組織の要求は 403 ORG_FORBIDDEN で拒否された")
        else:
            failures.append(f"T-3 他組織の要求が拒否されない（status={status}, code={code!r}）")
            print(f"FAIL: T-3 他組織の要求が拒否されない（status={status}, code={code!r}）", file=sys.stderr)

        # --- T-4 他組織を指定した作成は 403 ---
        print("== T-4 他組織を指定した作成は 403 ==")
        status, body = request(
            f"{args.gateway}/api/v1/erp/ledger",
            token=iso_token,
            method="POST",
            payload={
                "organization_id": ADMIN_ORG,
                "project_id": str(uuid.uuid4()),
                "project_code": PROJECT_CODE,
                "project_name": "stg 分離試験（他組織への書込みを試みる）",
                "project_type": "verification",
                "contract_amount": "1",
                "budget_amount": "1",
                "status": "planning",
            },
        )
        code = error_code(body)
        if status == 403 and code == "ORG_FORBIDDEN":
            print("PASS: T-4 他組織への作成は 403 ORG_FORBIDDEN で拒否された")
        else:
            failures.append(f"T-4 他組織への作成が拒否されない（status={status}, code={code!r}）")
            print(f"FAIL: T-4 他組織への作成が拒否されない（status={status}, code={code!r}）", file=sys.stderr)
    finally:
        # --- T-5 後始末 ---
        cleanup_sql = f"DELETE FROM erp.project_ledger WHERE id = '{ledger_id}'"
        result = subprocess.run(
            ["sudo", "-n", "-u", "postgres", "psql", "-p", args.pg_port, "-d", args.db, "-q", "-c", cleanup_sql],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0:
            print(f"PASS: T-5 検体を削除した（{cleanup_sql}）")
        else:
            failures.append(f"T-5 後始末に失敗（{result.stderr.strip()[:120]}）")
            print(f"WARN: T-5 後始末に失敗。手動で削除すること: {cleanup_sql}", file=sys.stderr)

    print()
    if failures:
        for item in failures:
            print(f"NG: {item}", file=sys.stderr)
        return 1
    print("OK: テナント分離を**非 admin の経路で**実測した（T-1〜T-5）。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
