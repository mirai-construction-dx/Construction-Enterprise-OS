"""プロキシルーター - 全リクエストの振り分け"""

import re

import structlog
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from ..config import get_settings
from ..services.proxy_service import ProxyService

router = APIRouter()
settings = get_settings()
proxy_service = ProxyService()

logger = structlog.get_logger(__name__)


def _match_upstream(path: str) -> tuple[str, str] | None:
    """パスにマッチする上流サービスを検索"""
    for pattern, upstream_url in settings.UPSTREAM_SERVICES.items():
        if re.match(pattern, path):
            return pattern, upstream_url
    return None


# パス境界の正規表現（例: "(?:/|$)"）を上流名（X-Upstream-Service）に含めない
_BOUNDARY_SUFFIX = "(?:/|$)"


def _upstream_name(pattern: str) -> str:
    """ルーティングパターンから上流名を生成する（例: ^/api/v1/ocr(?:/|$) -> api-v1-ocr）"""
    if pattern.endswith(_BOUNDARY_SUFFIX):
        pattern = pattern[: -len(_BOUNDARY_SUFFIX)]
    return pattern.lstrip("^/").replace("/", "-")


@router.api_route(
    "/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"],
)
async def proxy_request(request: Request, path: str) -> Response:
    """全パスを捕捉し、上流サービスに転送"""
    full_path = f"/{path}"

    match = _match_upstream(full_path)
    if not match:
        return JSONResponse(
            status_code=404,
            content={
                "success": False,
                "error": {
                    "code": "NOT_FOUND",
                    "message": f"リクエストされたパス '{full_path}' に対応するサービスが見つかりません。",
                },
            },
        )

    pattern, upstream_url = match
    upstream_name = _upstream_name(pattern)
    return await proxy_service.forward(request, upstream_url, upstream_name)
