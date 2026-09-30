#!/usr/bin/env python3
"""Static contract check: web API client calls vs. FastAPI service routes.

Detects calls in ``apps/web/src/lib/api/*.ts`` whose (METHOD, path) is not
served by any backend service (the class of bug fixed in PR #105).

Server side
    Parses ``services/*/src/main.py`` with :mod:`ast` (no service dependencies
    are imported or installed). Routes are built from
    ``<app>.include_router(<router>, prefix=...)`` + ``APIRouter(prefix=...)``
    + ``@<router>.<method>("...")`` / ``@<router>.api_route(..., methods=[...])``,
    including nested ``<router>.include_router(...)`` and ``@app.<method>`` in
    main.py. ``services/gateway`` is excluded: its ``/{path:path}`` catch-all is a
    reverse proxy, not an API contract. Anything that cannot be resolved
    statically (non-constant prefix/path, ``app.mount``, unresolved router) is
    reported as a warning and is never guessed.

Web side
    Scans calls to the api-client helpers ``get/post/put/patch/del`` and takes
    the first argument when it is a string literal, a template literal, or
    ``withQuery("<literal>", ...)``. ``/api/v1`` (api-client base) is prepended,
    ``${...}`` becomes ``{}`` and the query string is dropped. Other argument
    forms are reported as warnings.

Matching
    Strict equality of the normalised (METHOD, path). Path parameters
    (``{x}``, ``{x:path}``) are normalised to ``{}``. Trailing slashes are
    ignored on both sides (FastAPI ``redirect_slashes``).

Known mismatches can be accepted in ``web_api_routes_allowlist.txt``
(``METHOD /api/v1/path  # reason``). Exit code is 1 when a mismatch that is
not allowlisted exists, 0 otherwise. Stale allowlist entries are warnings.

Usage::

    python3 scripts/tools/check_web_api_routes.py [--root DIR] [--allowlist FILE] [--json]
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

API_BASE = "/api/v1"
HTTP_METHODS = ("get", "post", "put", "patch", "delete")
WEB_HELPERS = {
    "get": "GET",
    "post": "POST",
    "put": "PUT",
    "patch": "PATCH",
    "del": "DELETE",
}
EXCLUDED_SERVICES = frozenset({"gateway"})
DEFAULT_ALLOWLIST = Path(__file__).resolve().parent / "web_api_routes_allowlist.txt"
DEFAULT_ROOT = Path(__file__).resolve().parents[2]

_PARAM_RE = re.compile(r"\{[^{}]*\}")


@dataclass(frozen=True)
class Route:
    service: str
    method: str
    path: str
    source: str


@dataclass(frozen=True)
class WebCall:
    method: str
    path: str
    source: str


@dataclass
class Result:
    routes: list[Route] = field(default_factory=list)
    calls: list[WebCall] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    mismatches: list[WebCall] = field(default_factory=list)
    allowlisted: list[WebCall] = field(default_factory=list)
    stale_allowlist: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------
# Normalisation
# --------------------------------------------------------------------------


def normalize_path(path: str) -> str:
    """Collapse path params to ``{}``, squash ``//`` and drop trailing ``/``."""
    path = _PARAM_RE.sub("{}", path)
    path = re.sub(r"/{2,}", "/", path)
    if len(path) > 1:
        path = path.rstrip("/") or "/"
    return path


def join_paths(*parts: str) -> str:
    return "".join(p for p in parts if p)


# --------------------------------------------------------------------------
# Server side (ast)
# --------------------------------------------------------------------------


class _Module:
    """Parsed Python module with its APIRouter definitions and routes."""

    def __init__(self, path: Path, rel: str) -> None:
        self.path = path
        self.rel = rel
        self.tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        # router variable -> prefix (None when not statically resolvable)
        self.routers: dict[str, str | None] = {}
        # router variable -> list of (method, path, line)
        self.routes: dict[str, list[tuple[str, str, int]]] = {}
        # router variable -> list of (child expr, prefix|None, line)
        self.includes: dict[str, list[tuple[ast.expr, str | None, int]]] = {}
        # relative import aliases: local name -> (module base path w/o suffix, attr)
        self.imports: dict[str, tuple[Path, str]] = {}


def _const_str(node: ast.expr | None) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _kwarg(call: ast.Call, name: str) -> ast.expr | None:
    for kw in call.keywords:
        if kw.arg == name:
            return kw.value
    return None


def _is_apirouter_call(node: ast.expr) -> bool:
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    return (isinstance(func, ast.Name) and func.id == "APIRouter") or (
        isinstance(func, ast.Attribute) and func.attr == "APIRouter"
    )


def _analyse_module(mod: _Module, warnings: list[str]) -> None:
    for node in ast.walk(mod.tree):
        if isinstance(node, ast.ImportFrom) and node.level >= 1:
            # Resolve relative to the importing module's package.
            pkg = mod.path.parent
            for _ in range(node.level - 1):
                pkg = pkg.parent
            base = pkg.joinpath(*node.module.split(".")) if node.module else pkg
            for alias in node.names:
                local = alias.asname or alias.name
                mod.imports[local] = (base, alias.name)
        elif isinstance(node, ast.Assign) and _is_apirouter_call(node.value):
            call = node.value
            assert isinstance(call, ast.Call)
            prefix_node = _kwarg(call, "prefix")
            prefix: str | None = ""
            if prefix_node is not None:
                prefix = _const_str(prefix_node)
                if prefix is None:
                    warnings.append(
                        f"{mod.rel}:{node.lineno}: APIRouter prefix is not a string literal; "
                        "routes of this router are skipped"
                    )
            for target in node.targets:
                if isinstance(target, ast.Name):
                    mod.routers[target.id] = prefix
                    mod.routes.setdefault(target.id, [])
                    mod.includes.setdefault(target.id, [])

    for node in ast.walk(mod.tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for deco in node.decorator_list:
                _collect_decorator(mod, deco, warnings)
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            owner = node.func.value
            if node.func.attr == "include_router" and isinstance(owner, ast.Name):
                if not node.args:
                    warnings.append(
                        f"{mod.rel}:{node.lineno}: include_router without router argument"
                    )
                    continue
                prefix_node = _kwarg(node, "prefix")
                prefix: str | None = ""
                if prefix_node is not None:
                    prefix = _const_str(prefix_node)
                    if prefix is None:
                        warnings.append(
                            f"{mod.rel}:{node.lineno}: include_router prefix is not a string "
                            "literal; router is skipped"
                        )
                mod.includes.setdefault(owner.id, []).append(
                    (node.args[0], prefix, node.lineno)
                )
            elif node.func.attr == "mount":
                warnings.append(
                    f"{mod.rel}:{node.lineno}: {ast.unparse(node.func)}(...) mounts a sub-application; "
                    "its routes are not analysed"
                )
            elif node.func.attr == "add_api_route":
                warnings.append(
                    f"{mod.rel}:{node.lineno}: add_api_route is not analysed"
                )


def _collect_decorator(mod: _Module, deco: ast.expr, warnings: list[str]) -> None:
    if not (isinstance(deco, ast.Call) and isinstance(deco.func, ast.Attribute)):
        return
    owner = deco.func.value
    attr = deco.func.attr
    if not isinstance(owner, ast.Name) or attr not in (
        *HTTP_METHODS,
        "api_route",
        "websocket",
    ):
        return
    if attr == "websocket":
        return
    path_node = deco.args[0] if deco.args else _kwarg(deco, "path")
    path = _const_str(path_node)
    if path is None:
        warnings.append(
            f"{mod.rel}:{deco.lineno}: @{owner.id}.{attr} path is not a string literal; skipped"
        )
        return
    if attr == "api_route":
        methods_node = _kwarg(deco, "methods")
        if not isinstance(methods_node, (ast.List, ast.Tuple)):
            warnings.append(
                f"{mod.rel}:{deco.lineno}: @{owner.id}.api_route methods not a literal list; skipped"
            )
            return
        methods = []
        for elt in methods_node.elts:
            m = _const_str(elt)
            if m is None:
                warnings.append(
                    f"{mod.rel}:{deco.lineno}: @{owner.id}.api_route has a non-literal method; skipped"
                )
                return
            methods.append(m.upper())
    else:
        methods = [attr.upper()]
    for m in methods:
        mod.routes.setdefault(owner.id, []).append((m, path, deco.lineno))


class _ServiceAnalyzer:
    def __init__(
        self, service: str, src: Path, root: Path, warnings: list[str]
    ) -> None:
        self.service = service
        self.src = src
        self.root = root
        self.warnings = warnings
        self.modules: dict[Path, _Module | None] = {}

    def load(self, path: Path) -> _Module | None:
        if path not in self.modules:
            try:
                mod = _Module(path, path.relative_to(self.root).as_posix())
            except (OSError, SyntaxError) as exc:
                self.warnings.append(
                    f"{path.relative_to(self.root).as_posix()}: cannot parse ({exc})"
                )
                self.modules[path] = None
                return None
            _analyse_module(mod, self.warnings)
            self.modules[path] = mod
        return self.modules[path]

    @staticmethod
    def resolve_module(base: Path) -> Path | None:
        for candidate in (base.with_suffix(".py"), base / "__init__.py"):
            if candidate.is_file():
                return candidate
        return None

    def resolve_router(
        self, mod: _Module, expr: ast.expr
    ) -> tuple[_Module, str] | None:
        """Resolve ``name`` / ``module.attr`` to (module defining router, variable)."""
        if isinstance(expr, ast.Name):
            if expr.id in mod.routers:
                return mod, expr.id
            imp = mod.imports.get(expr.id)
            if imp is None:
                return None
            base, attr = imp
            target = self.resolve_module(base)
            if target is not None:
                tmod = self.load(target)
                if tmod is not None and attr in tmod.routers:
                    return tmod, attr
            return None
        if isinstance(expr, ast.Attribute) and isinstance(expr.value, ast.Name):
            imp = mod.imports.get(expr.value.id)
            if imp is None:
                return None
            base, attr = imp
            target = self.resolve_module(base / attr)
            if target is None:
                return None
            tmod = self.load(target)
            if tmod is not None and expr.attr in tmod.routers:
                return tmod, expr.attr
        return None

    def emit(
        self, mod: _Module, var: str, prefix: str, out: list[Route], depth: int = 0
    ) -> None:
        if depth > 10:
            self.warnings.append(f"{mod.rel}: include_router nesting too deep at {var}")
            return
        router_prefix = mod.routers.get(var, "")
        if router_prefix is None:
            return
        full_prefix = join_paths(prefix, router_prefix)
        for method, path, line in mod.routes.get(var, []):
            out.append(
                Route(
                    service=self.service,
                    method=method,
                    path=normalize_path(join_paths(full_prefix, path)),
                    source=f"{mod.rel}:{line}",
                )
            )
        for child, child_prefix, line in mod.includes.get(var, []):
            if child_prefix is None:
                continue
            resolved = self.resolve_router(mod, child)
            if resolved is None:
                self.warnings.append(
                    f"{mod.rel}:{line}: cannot resolve router {ast.unparse(child)!r}; skipped"
                )
                continue
            cmod, cvar = resolved
            self.emit(cmod, cvar, join_paths(full_prefix, child_prefix), out, depth + 1)

    def run(self) -> list[Route]:
        main = self.src / "main.py"
        mod = self.load(main)
        routes: list[Route] = []
        if mod is None:
            return routes
        # Routes declared directly on the app object (e.g. @app.get("/health")).
        app_names = set(mod.includes) - set(mod.routers)
        for name in app_names | {n for n in mod.routes if n not in mod.routers}:
            for method, path, line in mod.routes.get(name, []):
                routes.append(
                    Route(
                        self.service, method, normalize_path(path), f"{mod.rel}:{line}"
                    )
                )
            for child, child_prefix, line in mod.includes.get(name, []):
                if child_prefix is None:
                    continue
                resolved = self.resolve_router(mod, child)
                if resolved is None:
                    self.warnings.append(
                        f"{mod.rel}:{line}: cannot resolve router {ast.unparse(child)!r}; skipped"
                    )
                    continue
                cmod, cvar = resolved
                self.emit(cmod, cvar, child_prefix, routes)
        return routes


def collect_service_routes(root: Path, warnings: list[str]) -> list[Route]:
    routes: list[Route] = []
    for main in sorted(root.glob("services/*/src/main.py")):
        service = main.parents[1].name
        if service in EXCLUDED_SERVICES:
            continue
        routes.extend(_ServiceAnalyzer(service, main.parent, root, warnings).run())
    for r in routes:
        if ":path}" in r.path:  # pragma: no cover - normalised away, defensive
            warnings.append(f"{r.source}: path converter route {r.path}")
    return routes


# --------------------------------------------------------------------------
# Web side (scanner)
# --------------------------------------------------------------------------

_CALL_RE = re.compile(r"(?<![\w$.])(get|post|put|patch|del)\s*(?=[<(])")


def _skip_ws(src: str, i: int) -> int:
    while i < len(src) and src[i].isspace():
        i += 1
    return i


def _skip_generics(src: str, i: int) -> int | None:
    """``src[i] == '<'``: return index after the matching ``>``.

    Object types inside the type arguments (``{ a: string; b: number }``) are
    allowed; ``=>`` is not treated as a closing bracket.
    """
    depth = 0
    j = i
    while j < len(src):
        c = src[j]
        if c in "'\"`":
            r = _read_quoted(src, j) if c != "`" else _read_template(src, j)
            if r is None:
                return None
            j = r[1]
            continue
        if c == "<":
            depth += 1
        elif c == ">" and src[j - 1] != "=":
            depth -= 1
            if depth == 0:
                return j + 1
        j += 1
    return None


def _read_quoted(src: str, i: int) -> tuple[str, int] | None:
    q = src[i]
    j = i + 1
    buf = []
    while j < len(src):
        c = src[j]
        if c == "\\":
            buf.append(src[j : j + 2])
            j += 2
            continue
        if c == q:
            return "".join(buf), j + 1
        if c == "\n":
            return None
        buf.append(c)
        j += 1
    return None


def _read_template(src: str, i: int) -> tuple[list[tuple[str, str]], int] | None:
    """Parse a template literal at ``src[i] == '`'``.

    Returns (parts, end) where parts are ("lit", text) / ("expr", code).
    """
    j = i + 1
    parts: list[tuple[str, str]] = []
    buf: list[str] = []
    while j < len(src):
        c = src[j]
        if c == "\\":
            buf.append(src[j : j + 2])
            j += 2
            continue
        if c == "`":
            if buf:
                parts.append(("lit", "".join(buf)))
            return parts, j + 1
        if c == "$" and src.startswith("${", j):
            if buf:
                parts.append(("lit", "".join(buf)))
                buf = []
            end = _skip_expr(src, j + 2)
            if end is None:
                return None
            parts.append(("expr", src[j + 2 : end]))
            j = end + 1
            continue
        buf.append(c)
        j += 1
    return None


def _skip_expr(src: str, i: int) -> int | None:
    """Return index of the ``}`` closing a ``${`` expression starting at ``i``."""
    depth = 0
    j = i
    while j < len(src):
        c = src[j]
        if c in "'\"":
            r = _read_quoted(src, j)
            if r is None:
                return None
            j = r[1]
            continue
        if c == "`":
            r2 = _read_template(src, j)
            if r2 is None:
                return None
            j = r2[1]
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            if depth == 0:
                return j
            depth -= 1
        j += 1
    return None


_QUERY_EXPR_RE = re.compile(r"""[`'"]\?""")


def _template_to_path(parts: list[tuple[str, str]]) -> tuple[str, bool]:
    """Return (path, ok). ``ok`` is False when an interpolation is embedded in a
    path segment (not ``/${x}``), which cannot be matched reliably."""
    out: list[str] = []
    ok = True
    for kind, text in parts:
        if kind == "lit":
            if "?" in text:
                out.append(text.split("?", 1)[0])
                break
            out.append(text)
        else:
            if _QUERY_EXPR_RE.search(text):
                break  # conditional query-string suffix, e.g. ${qs ? `?${qs}` : ""}
            prev = "".join(out)
            if not prev.endswith("/"):
                ok = False
            out.append("{}")
    return "".join(out), ok


def _line_of(src: str, idx: int) -> int:
    return src.count("\n", 0, idx) + 1


def collect_web_calls(root: Path, warnings: list[str]) -> list[WebCall]:
    calls: list[WebCall] = []
    for ts in sorted((root / "apps/web/src/lib/api").glob("*.ts")):
        rel = ts.relative_to(root).as_posix()
        src = ts.read_text(encoding="utf-8")
        for m in _CALL_RE.finditer(src):
            line = _line_of(src, m.start())
            line_text = src[src.rfind("\n", 0, m.start()) + 1 : m.start()]
            if line_text.lstrip().startswith(("import", "//", "*", "/*")):
                continue
            i = m.end()
            if src[i] == "<":
                end = _skip_generics(src, i)
                if end is None:
                    warnings.append(
                        f"{rel}:{line}: cannot parse type arguments of {m.group(1)}<...>; skipped"
                    )
                    continue
                i = _skip_ws(src, end)
            if i >= len(src) or src[i] != "(":
                warnings.append(
                    f"{rel}:{line}: {m.group(1)}<...> is not followed by a call; skipped"
                )
                continue
            i = _skip_ws(src, i + 1)
            method = WEB_HELPERS[m.group(1)]
            path, ok = _parse_path_arg(src, i)
            source = f"{rel}:{line}"
            if path is None:
                snippet = src[i : i + 60].split("\n", 1)[0]
                warnings.append(
                    f"{source}: {method} path argument is not a literal ({snippet!r}); skipped"
                )
                continue
            if not path.startswith("/"):
                warnings.append(
                    f"{source}: {method} path {path!r} is not absolute; skipped"
                )
                continue
            if not ok:
                warnings.append(
                    f"{source}: {method} {path} has an interpolation inside a path segment; "
                    "matched as-is"
                )
            calls.append(WebCall(method, normalize_path(API_BASE + path), source))
    return calls


def _parse_path_arg(src: str, i: int) -> tuple[str | None, bool]:
    if i >= len(src):
        return None, True
    c = src[i]
    if c in "'\"":
        r = _read_quoted(src, i)
        if r is None:
            return None, True
        return r[0].split("?", 1)[0], True
    if c == "`":
        t = _read_template(src, i)
        if t is None:
            return None, True
        return _template_to_path(t[0])
    if src.startswith("withQuery(", i):
        return _parse_path_arg(src, _skip_ws(src, i + len("withQuery(")))
    return None, True


# --------------------------------------------------------------------------
# Allowlist and matching
# --------------------------------------------------------------------------


def load_allowlist(path: Path, warnings: list[str]) -> dict[tuple[str, str], str]:
    entries: dict[tuple[str, str], str] = {}
    if not path.is_file():
        return entries
    for n, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        body, _, reason = raw.partition("#")
        body = body.strip()
        if not body:
            continue
        fields = body.split()
        if len(fields) != 2 or fields[0].upper() not in WEB_HELPERS.values():
            warnings.append(f"{path.name}:{n}: malformed allowlist entry {raw!r}")
            continue
        key = (fields[0].upper(), normalize_path(fields[1]))
        if not reason.strip():
            warnings.append(f"{path.name}:{n}: allowlist entry without reason")
        entries[key] = reason.strip()
    return entries


def check(root: Path, allowlist_path: Path) -> Result:
    res = Result()
    res.routes = collect_service_routes(root, res.warnings)
    res.calls = collect_web_calls(root, res.warnings)
    allow = load_allowlist(allowlist_path, res.warnings)
    served = {(r.method, r.path) for r in res.routes}
    used_allow: set[tuple[str, str]] = set()
    for call in res.calls:
        key = (call.method, call.path)
        if key in served:
            continue
        if key in allow:
            res.allowlisted.append(call)
            used_allow.add(key)
        else:
            res.mismatches.append(call)
    for key in sorted(set(allow) - used_allow):
        res.stale_allowlist.append(f"{key[0]} {key[1]}")
        res.warnings.append(
            f"stale allowlist entry (no longer a mismatch): {key[0]} {key[1]}"
        )
    return res


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    ap.add_argument("--root", type=Path, default=DEFAULT_ROOT, help="repository root")
    ap.add_argument("--allowlist", type=Path, default=None, help="allowlist file")
    ap.add_argument("--json", action="store_true", help="print result as JSON")
    args = ap.parse_args(argv)
    root = args.root.resolve()
    allowlist = args.allowlist or DEFAULT_ALLOWLIST
    res = check(root, allowlist)

    if args.json:
        payload = {
            "summary": {
                "routes": len(res.routes),
                "web_calls": len(res.calls),
                "mismatches": len(res.mismatches),
                "allowlisted": len(res.allowlisted),
                "stale_allowlist": len(res.stale_allowlist),
                "warnings": len(res.warnings),
            },
            "mismatches": [asdict(c) for c in res.mismatches],
            "allowlisted": [asdict(c) for c in res.allowlisted],
            "stale_allowlist": res.stale_allowlist,
            "warnings": res.warnings,
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        for w in res.warnings:
            print(f"WARNING: {w}")
        for c in res.allowlisted:
            print(f"ALLOWED: {c.method} {c.path}  ({c.source})")
        for c in res.mismatches:
            print(
                f"ERROR: {c.method} {c.path} is not served by any service ({c.source})"
            )
        print(
            f"routes={len(res.routes)} web_calls={len(res.calls)} "
            f"mismatches={len(res.mismatches)} allowlisted={len(res.allowlisted)} "
            f"warnings={len(res.warnings)}"
        )
    return 1 if res.mismatches else 0


if __name__ == "__main__":
    sys.exit(main())
