#!/usr/bin/env python3
"""1 サービスの `src.middleware.tenant` の**振る舞い**を JSON で出力するプローブ。

`scripts/security/check_tenant_helper_conformance.py` が
サービスごとに `PYTHONPATH=services/<name>` を付けて起動する。
判定は呼び出し側（検査側）が持つ。ここは**観測だけ**を行う。

なぜ「振る舞い」を見るか:
    `tenant.py` は 18 サービスに複製されており、2026-10-14 の実測で
    **5 変種に分裂**していた。テキストの一致を求めると正当な差分
    （import 元・コメント）まで落ちるため、**分離に効く振る舞い**を直接叩く。

観測する項目（H-1〜H-9 に対応）:
    import       モジュールを読み込めるか
    funcs        token_org / scope_org / create_org が存在するか
    n_scope_none   非 admin が組織を指定しない → 自分の組織が返る
    n_scope_other  非 admin が他組織を指定       → 403 ORG_FORBIDDEN
    n_create_other 非 admin が他組織へ作成       → 403 ORG_FORBIDDEN
    n_create_own   非 admin が自組織へ作成       → 自分の組織が返る
    a_scope_none   admin が組織を指定しない      → None（全組織）
    a_scope_other  admin が他組織を指定          → その組織
    no_org         組織クレームが無い            → 403 ORG_REQUIRED
    bad_org        組織クレームが UUID でない    → 403 ORG_INVALID

使い方（単体）:
    PYTHONPATH=services/erp python3 scripts/security/tenant_contract_probe.py
"""

from __future__ import annotations

import json
import sys
from types import SimpleNamespace
from uuid import UUID

OWN = "00000000-0000-0000-0000-000000000001"
OTHER = "20000000-0000-0000-0000-000000000004"


def outcome(call) -> str:
    """呼び出しの結果を文字列で表す（例外は `403:CODE` 形式）。

    ここで例外を広く捕まえるのは**意図的**である。観測したいのは
    「どんな失敗の仕方をするか」であり、想定外の例外（TypeError など）も
    そのまま記録して検査側へ渡す。握りつぶしているのではない。
    """
    try:
        value = call()
    except Exception as exc:  # noqa: BLE001 - 失敗の仕方そのものを観測する
        status = getattr(exc, "status_code", None)
        detail = getattr(exc, "detail", None)
        code = detail.get("code") if isinstance(detail, dict) else None
        if status is None:
            return f"EXC:{type(exc).__name__}"
        return f"{status}:{code or ''}"
    return "None" if value is None else str(value)


def main() -> int:
    out: dict[str, object] = {}
    try:
        from src.middleware.tenant import create_org, scope_org, token_org
    except Exception as exc:  # noqa: BLE001 - import の失敗も観測対象
        print(json.dumps({"import": f"FAIL:{type(exc).__name__}:{exc}"}, ensure_ascii=False))
        return 0

    out["import"] = "OK"
    out["funcs"] = all(callable(f) for f in (token_org, scope_org, create_org))

    nonadmin = SimpleNamespace(roles=[], org=OWN)
    admin = SimpleNamespace(roles=["admin"], org=OWN)
    no_org = SimpleNamespace(roles=[], org=None)
    bad_org = SimpleNamespace(roles=[], org="not-a-uuid")
    other = UUID(OTHER)

    out["n_scope_none"] = outcome(lambda: scope_org(nonadmin, None))
    out["n_scope_other"] = outcome(lambda: scope_org(nonadmin, other))
    out["n_create_other"] = outcome(lambda: create_org(nonadmin, other))
    out["n_create_own"] = outcome(lambda: create_org(nonadmin, UUID(OWN)))
    out["a_scope_none"] = outcome(lambda: scope_org(admin, None))
    out["a_scope_other"] = outcome(lambda: scope_org(admin, other))
    out["no_org"] = outcome(lambda: scope_org(no_org, None))
    out["bad_org"] = outcome(lambda: scope_org(bad_org, None))

    print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
