"""ゲートウェイのルーティング表の回帰テスト。

vision は /api/v1/ocr・/api/v1/vectors、workflow は /api/v1/cases を公開しているが、
ルーティング表に無いと gateway 経由で 404 になり、かつ AuthMiddleware の
「上流に一致しないパスは公開扱い」により JWT 検証も行われなかった。
"""

import pytest

from src.config import get_settings
from src.middleware.auth import AuthMiddleware
from src.routes.proxy import _match_upstream, _upstream_name

VISION = "http://localhost:8011"
WORKFLOW = "http://localhost:8002"


def _upstream_url(path: str) -> str | None:
    match = _match_upstream(path)
    return match[1] if match else None


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/ocr",
        "/api/v1/ocr/process",
        "/api/v1/ocr/results/ocr1",
        "/api/v1/vectors",
        "/api/v1/vectors/indices",
        "/api/v1/vectors/search",
    ],
)
def test_ocr_and_vectors_route_to_vision(path):
    assert _upstream_url(path) == VISION


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/cases",
        "/api/v1/cases/",
        "/api/v1/cases/R-2026-0001",
        "/api/v1/cases/R-2026-0001/submit",
    ],
)
def test_cases_route_to_workflow(path):
    assert _upstream_url(path) == WORKFLOW


@pytest.mark.parametrize(
    "path",
    ["/api/v1/casesX", "/api/v1/cases-admin", "/api/v1/ocrfoo", "/api/v1/vectorsX"],
)
def test_paths_sharing_the_prefix_do_not_match(path):
    assert _match_upstream(path) is None


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("/api/v1/vision/ocr/tasks", VISION),
        ("/api/v1/vision/analyze", VISION),
        ("/api/v1/workflow/instances", WORKFLOW),
    ],
)
def test_existing_vision_and_workflow_routes_unchanged(path, expected):
    assert _upstream_url(path) == expected


def test_new_routes_use_existing_service_upstreams():
    upstreams = get_settings().UPSTREAM_SERVICES
    assert upstreams["^/api/v1/ocr(?:/|$)"] == upstreams["^/api/v1/vision"]
    assert upstreams["^/api/v1/vectors(?:/|$)"] == upstreams["^/api/v1/vision"]
    assert upstreams["^/api/v1/cases(?:/|$)"] == upstreams["^/api/v1/workflow"]


@pytest.mark.parametrize(
    "path",
    ["/api/v1/ocr/process", "/api/v1/vectors/search", "/api/v1/cases", "/api/v1/cases/R-1/approve"],
)
def test_new_routes_require_authentication_at_gateway(path):
    assert AuthMiddleware(app=None)._is_public_path(path) is False


@pytest.mark.parametrize(
    ("pattern", "name"),
    [
        ("^/api/v1/ocr(?:/|$)", "api-v1-ocr"),
        ("^/api/v1/cases(?:/|$)", "api-v1-cases"),
        ("^/api/v1/vision", "api-v1-vision"),
    ],
)
def test_upstream_name_excludes_boundary_regex(pattern, name):
    assert _upstream_name(pattern) == name
