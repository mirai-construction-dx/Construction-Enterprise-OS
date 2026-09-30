"""HTTPプロキシサービス"""

import httpx
import structlog
from fastapi import Request, Response
from fastapi.responses import JSONResponse

logger = structlog.get_logger(__name__)

# RFC 9110 §7.6.1: connection-specific header fields that a proxy must not forward.
HOP_BY_HOP_HEADERS = frozenset(
    {
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailer",
        "transfer-encoding",
        "upgrade",
    }
)

# httpx returns an already-decoded body from ``response.content``, so the
# upstream encoding and length no longer describe what we send. Starlette
# recomputes content-length from the body when it is not supplied.
# HEAD responses carry no body, so there is nothing to re-encode or measure;
# the upstream values are the only correct representation metadata and are
# kept (Starlette does not overwrite a supplied content-length).
_STALE_ENTITY_HEADERS = frozenset({"content-encoding", "content-length"})


def _connection_tokens(values: list[str]) -> set[str]:
    """Return lower-cased header names listed in ``Connection`` header values."""
    return {token.strip().lower() for value in values for token in value.split(",") if token.strip()}


class ProxyService:
    """上流マイクロサービスへのリクエスト転送を担当"""

    def __init__(self, timeout: float = 30.0):
        self._timeout = timeout

    async def forward(
        self,
        request: Request,
        upstream_url: str,
        upstream_name: str | None = None,
    ) -> Response:
        """リクエストを上流サービスに転送してレスポンスを返す"""
        path = request.url.path
        if request.url.query:
            path = f"{path}?{request.url.query}"

        target_url = f"{upstream_url.rstrip('/')}{path}"

        headers = self._prepare_headers(request)

        body = await request.body() if request.method in ("POST", "PUT", "PATCH", "DELETE") else None

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                upstream_response = await client.request(
                    method=request.method,
                    url=target_url,
                    headers=headers,
                    content=body,
                    follow_redirects=False,
                )

                # Drop hop-by-hop headers (RFC 9110 §7.6.1), anything the upstream
                # listed in Connection, and entity headers that no longer match
                # the decoded body (except for HEAD, whose body is always empty).
                excluded = HOP_BY_HOP_HEADERS | _connection_tokens(
                    upstream_response.headers.get_list("connection")
                )
                if request.method != "HEAD":
                    excluded = excluded | _STALE_ENTITY_HEADERS
                response_headers = {
                    key: value
                    for key, value in upstream_response.headers.items()
                    if key.lower() not in excluded
                }

                if upstream_name:
                    response_headers["X-Upstream-Service"] = upstream_name

                return Response(
                    content=upstream_response.content,
                    status_code=upstream_response.status_code,
                    headers=response_headers,
                )

        except httpx.TimeoutException:
            logger.error("upstream timeout", target_url=target_url)
            return JSONResponse(
                status_code=504,
                content={
                    "success": False,
                    "error": {
                        "code": "GATEWAY_TIMEOUT",
                        "message": "上流サービスがタイムアウトしました。",
                    },
                },
            )
        except httpx.ConnectError:
            logger.error("upstream unavailable", target_url=target_url)
            return JSONResponse(
                status_code=502,
                content={
                    "success": False,
                    "error": {
                        "code": "BAD_GATEWAY",
                        "message": "上流サービスに接続できません。",
                    },
                },
            )
        except Exception as exc:
            logger.exception("proxy error", target_url=target_url, error=str(exc))
            return JSONResponse(
                status_code=502,
                content={
                    "success": False,
                    "error": {
                        "code": "BAD_GATEWAY",
                        "message": "上流サービスでエラーが発生しました。",
                    },
                },
            )

    @staticmethod
    def _prepare_headers(request: Request) -> dict[str, str]:
        """転送用ヘッダーを準備（host・hop-by-hop・Connection 列挙ヘッダーを除外）"""
        excluded = {"host"} | HOP_BY_HOP_HEADERS | _connection_tokens(request.headers.getlist("connection"))

        # The request ID resolved by LoggingMiddleware wins; drop any incoming
        # variant (any casing) so exactly one X-Request-ID reaches the upstream.
        request_id = getattr(request.state, "request_id", None)
        if request_id:
            excluded = excluded | {"x-request-id"}

        headers = {
            key: value
            for key, value in request.headers.items()
            if key.lower() not in excluded
        }

        if request_id:
            headers["X-Request-ID"] = request_id

        return headers
