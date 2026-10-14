#!/usr/bin/env python3
"""クエリの `organization_id` が**必ずテナントヘルパを通っている**か AST で検証する。

なぜ必要か（2026-10-14 の実測）:
    `scripts/security/check_tenant_helper_conformance.py` は
    **18 個のヘルパが正しく振る舞う**ことを保証するが、
    「各エンドポイントがそのヘルパを実際に使っているか」は見ていない。
    67 のエンドポイントが `organization_id: UUID | None = Query(None)` を受け取る。
    もし 1 つが `scope_org()` を通さず生の値を使えば、
    **非 admin が他組織のデータを読める**（それ以外の統制が全部正しくても）。

    stg の動的試験（`check_tenant_isolation.py`）は erp の 1 本しか見ていない。
    残りは API を叩かずに**呼び出しの形**で検査する。

検査する内容:
    Q-1 `src/api/*.py` の関数が `organization_id` という名前の引数を持ち、
        その既定値が `Query(...)` である（＝クライアントが指定できる）とき、
        **関数本体でのその名前の使用はすべて `scope_org` / `create_org` の引数**であること。
    Q-2 陰性対照: 生の値を使う合成コードを**検出できる**こと
    Q-3 陽性対照: `scope_org` を通す合成コードを**検出しない**こと
    Q-4 `DECLARED_EXCEPTIONS` の宣言が**実在すること**（陳腐化した免除を許さない）

例外（`DECLARED_EXCEPTIONS`）:
    規約どおりでないが安全な形が 2 つある。**理由つきで宣言**し、
    宣言が実体と合っていることを毎回検証する（Q-4）。
      - `own-guard`: サービスが**独自に**同一のガードを持つ。
        関数のソースに `ORG_FORBIDDEN` が現れることを要求する。
      - `internal` : 利用者向けではなく**内部 API**（サービス間通信用）。

なぜ AST か:
    文字列検索では「`scope_org` を import しているが使っていない」を見逃す。
    名前の**使われ方**を構文木で見る。

限界（正直な記録）:
    - 見るのは **クエリ引数**だけである。リクエスト**本文**の `organization_id`
      （`body.organization_id`）は属性アクセスであり、正当な読み出し
      （レスポンス整形・保存値の参照）と区別が難しいため対象外にした。
      本文については `create_org` の使用を各サービスのテストが担保する。
    - 対象は `services/*/src/api/*.py` のみ（ルータの置き場所の規約）。

`SKIP` を作らない。解析できないファイルは FAIL として報告する。

使い方:
    python3 scripts/security/check_org_query_scoping.py
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SERVICES = REPO / "services"
PARAM = "organization_id"
SCOPE_CALLS = {"scope_org", "create_org"}

# 規約どおりでないが安全な形。**理由を必ず書く。**
# キーは "<service>:<function>"。Q-4 が実在を検証する。
DECLARED_EXCEPTIONS: dict[str, tuple[str, str]] = {
    "workflow:list_definitions": (
        "own-guard",
        (
            "workflow は tenant.py を持たず、`_organization_id(current_user)` で JWT の org を取り出し"
            " `organization_id != authenticated_org` を 403 ORG_FORBIDDEN で拒否する"
            "（2026-10-14 実測。check_tenant_helper_conformance.py の H-10 で宣言済み）"
        ),
    ),
    "workflow:list_instances": (
        "own-guard",
        "同上（workflow の独自ガード）",
    ),
    "auth:list_notification_recipients": (
        "internal",
        (
            "auth の `/internal/...` は利用者向けではなく、組織を**指定して**利用者を引く"
            "サービス間 API である（organization_id は `Query(...)` 必須で、JWT の org では絞らない"
            "ことが仕様）。利用者向けの分離対象ではない"
        ),
    ),
}

NEGATIVE_CONTROL = """
async def leak(organization_id: UUID | None = Query(None), db=Depends(get_db)):
    stmt = select(X).where(X.organization_id == organization_id)
    return await db.execute(stmt)
"""
POSITIVE_CONTROL = """
async def ok(organization_id: UUID | None = Query(None), db=Depends(get_db), user=Depends(get_current_user)):
    stmt = select(X).where(X.organization_id == scope_org(user, organization_id))
    return await db.execute(stmt)
"""


def is_query_default(node: ast.AST | None) -> bool:
    if node is None:
        return False
    if isinstance(node, ast.Call):
        func = node.func
        name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
        return name in {"Query", "Body", "Path"}
    return False


def has_query_param(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    defaults = list(node.args.defaults) + [d for d in node.args.kw_defaults if d is not None]
    return any(
        a.arg == PARAM and any(is_query_default(d) for d in defaults) for a in node.args.args
    )


def scoped_nodes(tree: ast.AST) -> set[int]:
    """`scope_org(...)` / `create_org(...)` の引数になっている Name ノードの id 集合。"""
    ids: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
        if name not in SCOPE_CALLS:
            continue
        for arg in list(node.args) + [kw.value for kw in node.keywords]:
            for inner in ast.walk(arg):
                if isinstance(inner, ast.Name) and inner.id == PARAM:
                    ids.add(id(inner))
    return ids


def analyse(source: str, label: str) -> tuple[int, list[tuple[str, int]], dict[str, str]]:
    """(クエリ引数を持つ関数の件数, [(関数名, 行)], 関数名→ソース) を返す。"""
    tree = ast.parse(source)
    scoped = scoped_nodes(tree)
    checked = 0
    violations: list[tuple[str, int]] = []
    sources: dict[str, str] = {}

    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not has_query_param(node):
            continue
        checked += 1
        sources.setdefault(node.name, ast.get_source_segment(source, node) or "")
        lines: set[int] = set()
        for inner in ast.walk(node):
            if (
                isinstance(inner, ast.Name)
                and inner.id == PARAM
                and isinstance(inner.ctx, ast.Load)
                and id(inner) not in scoped
            ):
                lines.add(inner.lineno)
        for line in sorted(lines):
            violations.append((node.name, line))
    return checked, violations, sources


def main() -> int:
    failures: list[str] = []

    # ---- 対照（検査が空回りしていないことを毎回確認する） ----
    if not analyse(NEGATIVE_CONTROL, "control")[1]:
        failures.append("Q-2 陰性対照: 生の使用を検出できなかった（検査が空回りしている）")
    if analyse(POSITIVE_CONTROL, "control")[1]:
        failures.append("Q-3 陽性対照: 正しい使用を誤検出した")
    print(f"Q-2 陰性対照: {'OK' if not any('Q-2' in f for f in failures) else 'NG'}")
    print(f"Q-3 陽性対照: {'OK' if not any('Q-3' in f for f in failures) else 'NG'}")

    files = sorted(SERVICES.glob("*/src/api/*.py"))
    if not files:
        print(f"NG: {SERVICES}/*/src/api/*.py が見つからない（検査が空回りしている）", file=sys.stderr)
        return 1

    checked = 0
    parse_errors: list[str] = []
    raw: list[tuple[str, str, int]] = []
    sources: dict[str, str] = {}
    for path in files:
        service = path.parents[2].name
        try:
            source = path.read_text(encoding="utf-8")
            count, violations, func_sources = analyse(source, str(path.relative_to(REPO)))
        except (OSError, SyntaxError) as exc:
            parse_errors.append(f"{path.relative_to(REPO)}: {type(exc).__name__}")
            continue
        checked += count
        for key, value in func_sources.items():
            sources[f"{service}:{key}"] = value
        raw.extend((service, func, line) for func, line in violations)

    print(f"Q-1 クエリで {PARAM} を受けるエンドポイント: {checked} 件")
    if checked == 0:
        failures.append("Q-1 対象エンドポイントが 0 件（検査が空回りしている）")

    # ---- 例外の適用と、宣言が実在することの検証（Q-4） ----
    used: set[str] = set()
    for service, func, line in raw:
        key = f"{service}:{func}"
        if key not in DECLARED_EXCEPTIONS:
            failures.append(
                f"Q-1 {service}:{line} `{func}()` が {PARAM} を "
                f"{'/'.join(sorted(SCOPE_CALLS))} を通さずに使っている"
            )
            continue
        kind, reason = DECLARED_EXCEPTIONS[key]
        if kind == "own-guard" and "ORG_FORBIDDEN" not in sources.get(key, ""):
            failures.append(f"Q-4 {key} は own-guard と宣言されているが ORG_FORBIDDEN が無い")
        used.add(key)
        print(f"  免除 {key}（{kind}）: {reason[:64]}…")

    for key, (kind, reason) in DECLARED_EXCEPTIONS.items():
        if key not in used:
            failures.append(f"Q-4 宣言 {key} が実在しない（免除が陳腐化している）: {reason[:60]}")
    print(f"Q-4 宣言された免除: {len(DECLARED_EXCEPTIONS)} 件（{len(used)} 件が実在を確認）")

    for item in parse_errors:
        failures.append(f"解析できないファイルがある: {item}")

    print()
    if failures:
        print(f"NG: {len(failures)} 件", file=sys.stderr)
        for item in failures:
            print(f"  - {item}", file=sys.stderr)
        return 1
    print(f"OK: クエリの {PARAM} はすべてスコープされている（{checked} 件・免除 {len(used)} 件）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
