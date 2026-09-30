"""Tests for scripts/tools/check_web_api_routes.py (stdlib + pytest only)."""

from __future__ import annotations

import importlib.util
import json
import sys
import textwrap
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[1] / "check_web_api_routes.py"
_spec = importlib.util.spec_from_file_location("check_web_api_routes", _SCRIPT)
assert _spec and _spec.loader
cwar = importlib.util.module_from_spec(_spec)
sys.modules["check_web_api_routes"] = cwar
_spec.loader.exec_module(cwar)


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(content), encoding="utf-8")


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    """Minimal repo: one 'notification' service and one web client."""
    svc = tmp_path / "services/notification/src"
    _write(
        svc / "main.py",
        """
        from fastapi import FastAPI
        from .api import notifications, health
        from .api.templates import router as templates_router

        def create_app():
            app = FastAPI()
            app.include_router(health.router, tags=["health"])
            app.include_router(notifications.router, prefix="/api/v1/notifications")
            app.include_router(templates_router, prefix="/api/v1/notification-templates")

            @app.get("/health")
            async def h():
                return {}

            return app
        """,
    )
    _write(svc / "api/__init__.py", "")
    _write(
        svc / "api/health.py",
        """
        from fastapi import APIRouter
        router = APIRouter()

        @router.get("/health")
        async def health():
            return {}
        """,
    )
    _write(
        svc / "api/notifications.py",
        """
        from fastapi import APIRouter
        router = APIRouter()

        @router.get("")
        async def list_():
            ...

        @router.get("/unread-count")
        async def unread():
            ...

        @router.patch("/{notification_id}/read")
        async def read(notification_id: int):
            ...

        @router.api_route("/read-all", methods=["PATCH", "POST"])
        async def read_all():
            ...
        """,
    )
    _write(
        svc / "api/templates.py",
        """
        from fastapi import APIRouter
        router = APIRouter()

        @router.get("")
        async def list_():
            ...

        @router.post("/")
        async def create():
            ...

        @router.put("/{template_id}")
        async def update(template_id: str):
            ...
        """,
    )
    # gateway catch-all must not hide mismatches
    _write(
        tmp_path / "services/gateway/src/main.py",
        """
        from fastapi import FastAPI
        from .routes.proxy import router as proxy_router
        app = FastAPI()
        app.include_router(proxy_router)
        """,
    )
    _write(
        tmp_path / "services/gateway/src/routes/proxy.py",
        """
        from fastapi import APIRouter
        router = APIRouter()

        @router.api_route("/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
        async def proxy(path: str):
            ...
        """,
    )
    return tmp_path


def _client(root: Path, body: str, name: str = "notification.ts") -> None:
    _write(root / "apps/web/src/lib/api" / name, body)


def _run(root: Path, allowlist: Path | None = None) -> cwar.Result:
    return cwar.check(root, allowlist or root / "allowlist.txt")


def test_matching_calls_pass(repo: Path) -> None:
    _client(
        repo,
        """
        import { get, patch, put } from "../api-client";
        function withQuery(path: string, q: URLSearchParams) { return path; }
        export const a = () => get<Resp<{ unread_count: number; x: string }>>(
          "/notifications/unread-count",
        );
        export const b = (q: URLSearchParams) => get<X>(withQuery("/notifications", q));
        export const c = (id: number) => patch<X>(`/notifications/${id}/read`, {});
        export const d = () => patch<X>("/notifications/read-all", {});
        export const e = (q: string) =>
          get<X>(`/notification-templates${q ? `?${q}` : ""}`);
        export const f = (id: string) =>
          put<X>(`/notification-templates/${encodeURIComponent(id)}`, {});
        const params = new URLSearchParams(); params.get("x");
        """,
    )
    res = _run(repo)
    assert res.mismatches == []
    assert len(res.calls) == 6
    assert {c.method for c in res.calls} == {"GET", "PATCH", "PUT"}


def test_unknown_path_and_wrong_method_are_errors(repo: Path) -> None:
    # The PR #105 bug class: path/method the service does not serve.
    _client(
        repo,
        """
        import { get, post, del } from "../api-client";
        export const a = () => get<X>("/notifications/policies");
        export const b = (id: number) => post<X>(`/notifications/${id}/read`, {});
        export const c = (id: string) => del<void>(`/notification-templates/${id}`);
        """,
    )
    res = _run(repo)
    got = {(c.method, c.path) for c in res.mismatches}
    assert got == {
        ("GET", "/api/v1/notifications/policies"),
        ("POST", "/api/v1/notifications/{}/read"),
        ("DELETE", "/api/v1/notification-templates/{}"),
    }
    assert all(
        c.source.startswith("apps/web/src/lib/api/notification.ts:")
        for c in res.mismatches
    )
    assert cwar.main(["--root", str(repo), "--allowlist", str(repo / "none.txt")]) == 1


def test_gateway_catch_all_is_excluded(repo: Path) -> None:
    res = _run(repo)
    assert not any(r.service == "gateway" for r in res.routes)


def test_path_parameter_normalisation() -> None:
    assert cwar.normalize_path("/a/{id}/b/{x:path}") == "/a/{}/b/{}"
    assert cwar.normalize_path("/a/b/") == "/a/b/"
    assert cwar.normalize_path("/a//b") == "/a/b"
    assert cwar.normalize_path("/") == "/"
    parts = [("lit", "/items/"), ("expr", "item.id"), ("lit", "/sub?x=1")]
    assert cwar._template_to_path(parts) == ("/items/{}/sub", True)
    assert cwar._template_to_path([("lit", "/items-"), ("expr", "id")]) == (
        "/items-{}",
        False,
    )


def test_trailing_slash_is_significant(repo: Path) -> None:
    # FastAPI joins prefix + "" -> /x and prefix + "/" -> /x/, and answers the
    # other form with a 307 that the gateway relays (internal Location), so a
    # call differing only by the trailing slash is a mismatch.
    _client(
        repo,
        """
        import { get, post } from "../api-client";
        export const a = () => get<X>("/notification-templates");
        export const b = () => post<X>("/notification-templates/", {});
        export const c = () => get<X>("/notification-templates/");
        export const d = () => post<X>("/notification-templates", {});
        export const e = () => get<X>("/notifications/unread-count/");
        """,
    )
    res = _run(repo)
    assert {(c.method, c.path) for c in res.mismatches} == {
        ("GET", "/api/v1/notification-templates/"),
        ("POST", "/api/v1/notification-templates"),
        ("GET", "/api/v1/notifications/unread-count/"),
    }


def test_trailing_slash_follows_fastapi_concatenation(tmp_path: Path) -> None:
    svc = tmp_path / "services/svc/src"
    _write(
        svc / "main.py",
        """
        from fastapi import FastAPI
        from .api import items
        app = FastAPI()
        app.include_router(items.router, prefix="/api/v1")
        """,
    )
    _write(
        svc / "api/items.py",
        """
        from fastapi import APIRouter
        router = APIRouter(prefix="/items")

        @router.get("")
        async def list_(): ...

        @router.post("/")
        async def create(): ...

        @router.get("/{item_id}/")
        async def get_(item_id: int): ...
        """,
    )
    routes = {(r.method, r.path) for r in cwar.collect_service_routes(tmp_path, [])}
    assert routes == {
        ("GET", "/api/v1/items"),
        ("POST", "/api/v1/items/"),
        ("GET", "/api/v1/items/{}/"),
    }


def test_allowlist_trailing_slash_is_exact(repo: Path) -> None:
    _client(
        repo,
        """
        import { get } from "../api-client";
        export const a = () => get<X>("/notifications/policies/");
        """,
    )
    allow = repo / "allow.txt"
    allow.write_text("GET /api/v1/notifications/policies  # tracked\n", encoding="utf-8")
    res = _run(repo, allow)
    assert [(c.method, c.path) for c in res.mismatches] == [
        ("GET", "/api/v1/notifications/policies/")
    ]
    assert res.stale_allowlist == ["GET /api/v1/notifications/policies"]


def test_prefix_composition(tmp_path: Path) -> None:
    svc = tmp_path / "services/svc/src"
    _write(
        svc / "main.py",
        """
        from fastapi import FastAPI
        from .api import outer
        app = FastAPI()
        app.include_router(outer.router, prefix="/api/v1/svc")
        app.include_router(outer.other_router, prefix="/api/v1/other")
        """,
    )
    _write(
        svc / "api/outer.py",
        """
        from fastapi import APIRouter
        from .inner import router as inner_router
        router = APIRouter(prefix="/outer")
        other_router = APIRouter()
        router.include_router(inner_router, prefix="/nested")

        @router.get("/{oid}")
        async def get_outer(oid: str): ...

        @other_router.delete(path="/x/{x_id}")
        async def rm(x_id: str): ...
        """,
    )
    _write(
        svc / "api/inner.py",
        """
        from fastapi import APIRouter
        router = APIRouter(prefix="/inner")

        @router.post("/items")
        async def create(): ...
        """,
    )
    routes = {(r.method, r.path) for r in cwar.collect_service_routes(tmp_path, [])}
    assert routes == {
        ("GET", "/api/v1/svc/outer/{}"),
        ("POST", "/api/v1/svc/outer/nested/inner/items"),
        ("DELETE", "/api/v1/other/x/{}"),
    }


def test_dynamic_prefix_is_warned_not_guessed(tmp_path: Path) -> None:
    svc = tmp_path / "services/svc/src"
    _write(
        svc / "main.py",
        """
        from fastapi import FastAPI
        from .api import a
        PREFIX = "/api/v1/a"
        app = FastAPI()
        app.include_router(a.router, prefix=PREFIX)
        app.mount("/sub", object())
        """,
    )
    _write(
        svc / "api/a.py",
        """
        from fastapi import APIRouter
        router = APIRouter()
        @router.get("/x")
        async def x(): ...
        """,
    )
    warnings: list[str] = []
    assert cwar.collect_service_routes(tmp_path, warnings) == []
    assert any("prefix is not a string literal" in w for w in warnings)
    assert any("mount" in w for w in warnings)


def test_non_literal_web_path_is_warned(repo: Path) -> None:
    _client(
        repo,
        """
        import { get } from "../api-client";
        export const a = (url: string) => get<X>(url);
        """,
    )
    res = _run(repo)
    assert res.calls == []
    assert any("not a literal" in w for w in res.warnings)


def test_allowlist_suppresses_known_and_reports_stale(repo: Path) -> None:
    _client(
        repo,
        """
        import { get, post } from "../api-client";
        export const a = () => get<X>("/notifications/policies?x=1");
        export const b = (id: number) => post<X>(`/notifications/${id}/read`, {});
        """,
    )
    allow = repo / "allowlist.txt"
    allow.write_text(
        "# comment\n"
        "GET /api/v1/notifications/policies  # not implemented yet\n"
        "DELETE /api/v1/gone/{}  # fixed already\n",
        encoding="utf-8",
    )
    res = _run(repo, allow)
    assert [(c.method, c.path) for c in res.allowlisted] == [
        ("GET", "/api/v1/notifications/policies")
    ]
    assert [(c.method, c.path) for c in res.mismatches] == [
        ("POST", "/api/v1/notifications/{}/read")
    ]
    assert res.stale_allowlist == ["DELETE /api/v1/gone/{}"]


def test_json_output_and_exit_code(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _client(
        repo,
        'import { get } from "../api-client";\nexport const a = () => get<X>("/notifications");\n',
    )
    rc = cwar.main(
        ["--root", str(repo), "--allowlist", str(repo / "none.txt"), "--json"]
    )
    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert payload["summary"]["mismatches"] == 0
    assert payload["summary"]["web_calls"] == 1


def test_repository_baseline_is_clean() -> None:
    """The real repo must have no mismatch outside the allowlist."""
    res = cwar.check(cwar.DEFAULT_ROOT, cwar.DEFAULT_ALLOWLIST)
    assert res.calls, "no web API calls found; scanner is broken"
    assert res.mismatches == [], [
        f"{c.method} {c.path} ({c.source})" for c in res.mismatches
    ]
