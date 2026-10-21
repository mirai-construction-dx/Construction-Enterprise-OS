#!/usr/bin/env python3
"""18 サービスに複製された `tenant.py` が**同じ分離の振る舞い**をするか検証する。

なぜ必要か（2026-10-14 の実測）:
    `services/*/src/middleware/tenant.py` は **18 サービスに複製**され、
    内容は **5 変種に分裂**していた。

        | 変種 | 件数 | 差分 |
        |---|---|---|
        | A | 7 | `is_cross_org_admin` が `CROSS_ORG_ROLE in user.roles` |
        | B | 8 | 同 `in (user.roles or [])` |
        | C | 1 (erp) | B ＋ コメント |
        | D | 1 (partner) | A だが `TokenData` を `..schemas` から import |
        | E | 1 (bim) | B ＋ コメント |

    差は `user.roles` と `(user.roles or [])` の 1 点だけで、各サービスの
    `TokenData` は常にリストを供給するため**現時点で実害は無い**。
    しかし**ドリフトを検出する仕組みは無かった**。次に誰かが 1 つの複製だけを
    直すと、その差が分離の穴になり得る。

    stg の分離試験（`scripts/stg/check_tenant_isolation.py`）は
    **erp の API 1 本**しか見ていない。残り 17 サービスの API は未検証である。
    本検査は API を叩かずに、**18 個のヘルパの振る舞い**を直接検証する。

なぜテキスト比較ではないか:
    正当な差分（import 元・コメント・型注釈）まで落とすため。
    分離に効く**振る舞い**を `scripts/security/tenant_contract_probe.py` で叩く。

検査する内容（各サービス）:
    H-0 `src/middleware/tenant.py` が存在し、プローブが JSON を返す
    H-1 `token_org` / `scope_org` / `create_org` が import できる
    H-2 非 admin ＋ 組織未指定   → **自分の組織**が返る
    H-3 非 admin ＋ 他組織を要求 → **403 ORG_FORBIDDEN**
    H-4 非 admin ＋ 他組織へ作成 → **403 ORG_FORBIDDEN**
    H-5 非 admin ＋ 自組織へ作成 → **自分の組織**が返る
    H-6 admin ＋ 組織未指定      → **None**（全組織。設計どおり）
    H-7 admin ＋ 他組織を要求    → **その組織**（設計どおり）
    H-8 組織クレームが無い       → **403 ORG_REQUIRED**（fail closed）
    H-9 組織クレームが UUID 文字列でない → **403 ORG_INVALID**（fail closed）
    H-10 組織クレームが整数 → **403 ORG_INVALID**（TypeError を 500 にしない。2026-10-21 追加）
    H-11 組織クレームが配列 → **403 ORG_INVALID**（AttributeError を 500 にしない。2026-10-21 追加）
    H-12 `tenant.py` を持たないのに `organization_id` を参照するサービスは、
        `INLINE_ORG_SCOPING` に**理由つきで宣言**されている（独自実装の見落としを防ぐ）

`SKIP` を作らない。import できないサービスも FAIL として報告する
（「読めなかったから安全」とはしない。`AGENTS.md` §4.7）。

使い方:
    python3 scripts/security/check_tenant_helper_conformance.py
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SERVICES = REPO / "services"
PROBE = REPO / "scripts" / "security" / "tenant_contract_probe.py"

OWN = "00000000-0000-0000-0000-000000000001"
OTHER = "20000000-0000-0000-0000-000000000004"

# 期待する振る舞い（プローブの出力キー → 期待値）
EXPECTED: dict[str, str] = {
    "n_scope_none": OWN,
    "n_scope_other": "403:ORG_FORBIDDEN",
    "n_create_other": "403:ORG_FORBIDDEN",
    "n_create_own": OWN,
    "a_scope_none": "None",
    "a_scope_other": OTHER,
    "no_org": "403:ORG_REQUIRED",
    "bad_org": "403:ORG_INVALID",
    "bad_org_int": "403:ORG_INVALID",
    "bad_org_list": "403:ORG_INVALID",
}

# tenant.py を持たないが `organization_id` を参照するサービス。
# **理由を必ず書く。** ここに足すときは「なぜ tenant ヘルパを使わないのか」を
# 実測で説明できることにする（`scripts/ci/check_coverage.py` の
# INDIRECTLY_COVERED と同じ扱い）。
INLINE_ORG_SCOPING: dict[str, str] = {
    "mcp": (
        "組織スコープを**実装していない**。`src/tools/definitions.py` がツール引数として"
        "`organization_id` を宣言しているだけである。MCP は呼び出し元の Authorization を"
        "そのまま上流へ渡し（`src/api/mcp.py`）、上流が呼び出し元自身の権限で分離を効かせる。"
        "**バイパスしないことを実測した**: audience 束縛トークンの場合は RFC 8693 で交換するが、"
        "auth の `token_exchange_service.py:108-112` が `sub` / `org` / `roles` / `scopes` を"
        "被交換トークンから引き継ぎ、権限を昇格させない（有効期限も `min(subject.exp, now+ttl)` で延命しない）"
    ),
    "workflow": (
        "`src/api/workflows.py` の `_organization_id()` が JWT の org を取り出し、"
        "本文の organization_id と照合して不一致を拒否する（2026-10-14 実測）。"
        "tenant.py と同等の統制を独自実装で持つ。**相違点**: admin でも他組織を拒否する"
        "（erp の scope_org は admin にクロス組織を許す）。厳い側なので穴ではないが、"
        "サービス間で同じ役割の権限が異なることは記録に値する"
    ),
    "auth": (
        "組織そのものの正本（`auth.organizations` / `auth.users`）であり、"
        "テナントフィルタの対象ではない。organization_id は台帳の列として現れる"
    ),
}


def targets() -> list[str]:
    return sorted(
        path.parents[2].name
        for path in SERVICES.glob("*/src/middleware/tenant.py")
    )


def probe(service: str) -> dict:
    result = subprocess.run(
        [sys.executable, str(PROBE)],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
        env={"PYTHONPATH": f"{SERVICES / service}", "PATH": "/usr/bin:/bin"},
    )
    if result.returncode != 0:
        return {"import": f"FAIL:exit{result.returncode}:{result.stderr.strip()[-200:]}"}
    try:
        return json.loads(result.stdout.strip().splitlines()[-1])
    except (json.JSONDecodeError, IndexError):
        return {"import": f"FAIL:unparsable:{result.stdout.strip()[-200:]}"}


def main() -> int:
    names = targets()
    if not names:
        print("NG: tenant.py を持つサービスが 1 つも見つからない（検査が空回りしている）", file=sys.stderr)
        return 1

    failures: list[str] = []
    print(f"tenant.py を持つサービス: {len(names)} 件")
    for name in names:
        observed = probe(name)
        if observed.get("import") != "OK":
            failures.append(f"{name}: H-1 import できない（{observed.get('import')}）")
            print(f"  NG {name}: import できない（{observed.get('import')}）")
            continue
        if observed.get("funcs") is not True:
            failures.append(f"{name}: H-1 token_org / scope_org / create_org が揃っていない")
            print(f"  NG {name}: 関数が揃っていない")
            continue

        deviations = [
            f"H-{index}:{key}={observed.get(key)!r}（期待 {expected!r}）"
            for index, (key, expected) in enumerate(EXPECTED.items(), start=2)
            if observed.get(key) != expected
        ]
        if deviations:
            failures.append(f"{name}: " + " / ".join(deviations))
            print(f"  NG {name}: " + " / ".join(deviations))
        else:
            print(f"  OK {name}: H-1〜H-11 適合")

    # 参考: tenant.py を持たないが auth.py を持つサービス（欠落の可能性を可視化する）
    with_auth = {
        path.parents[2].name for path in SERVICES.glob("*/src/middleware/auth.py")
    }
    missing = sorted(with_auth - set(names))
    if missing:
        print(f"  参考: auth.py はあるが tenant.py が無いサービス: {missing}")

    # ---- H-12 独自実装の見落としを検出する ----
    # tenant.py を持たないサービスが organization_id を参照しているなら、
    # 分離の統制を**独自に**実装している。宣言されていなければ FAIL とする
    # （新しいサービスが独自実装で分離を忘れても、これまでは検出できなかった）。
    print()
    print("H-12 独自に組織スコープを持つサービスが宣言されているか")
    inline: list[str] = []
    for service_dir in sorted(p for p in SERVICES.iterdir() if (p / "src").is_dir()):
        if service_dir.name in names:
            continue
        hit = subprocess.run(
            ["grep", "-rl", "organization_id", str(service_dir / "src"), "--include=*.py"],
            capture_output=True,
            text=True,
            check=False,
        )
        if hit.stdout.strip():
            inline.append(service_dir.name)
    undeclared = [name for name in inline if name not in INLINE_ORG_SCOPING]
    for name in inline:
        if name in INLINE_ORG_SCOPING:
            print(f"  OK {name}: 宣言済み — {INLINE_ORG_SCOPING[name]}")
        else:
            print(f"  NG {name}: 独自に organization_id を使うが宣言が無い")
    if undeclared:
        failures.append(
            "H-12 tenant.py を持たず organization_id を参照するサービスが未宣言: "
            f"{undeclared}。実測して INLINE_ORG_SCOPING に理由つきで宣言するか、tenant ヘルパを使わせること"
        )
    elif not inline:
        print("  OK 独自実装は無い")

    print()
    if failures:
        print(f"NG: {len(failures)} 件のずれ", file=sys.stderr)
        for item in failures:
            print(f"  - {item}", file=sys.stderr)
        return 1
    print(f"OK: {len(names)} サービスの tenant ヘルパが同じ分離の振る舞いをする（H-1〜H-11）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
