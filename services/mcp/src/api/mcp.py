"""MCP Streamable HTTP エンドポイント（読み取り専用）

公式 MCP Python SDK (``mcp``) の低レベル :class:`mcp.server.lowlevel.Server` と
``StreamableHTTPSessionManager`` を用いて、MCP の ``initialize`` / ``tools/list`` /
``tools/call`` を提供する。ツール定義は :mod:`src.tools` のレジストリを唯一の正本とする。
"""

import json
import logging
import time
from dataclasses import dataclass
from typing import Any

from mcp import types
from mcp.server.lowlevel import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from starlette.applications import Starlette
from starlette.routing import Mount
from starlette.types import Receive, Scope, Send

from ..config import Settings, get_settings
from ..middleware.auth import authenticate_bearer
from ..services import token_exchange, upstream
from ..tools import (
    REGISTRY,
    ToolCallOutcome,
    ToolCallRefused,
    ToolRegistry,
    execute_tool,
    is_server_enabled,
    is_tool_allowed,
)

logger = logging.getLogger(__name__)
audit_logger = logging.getLogger("ceos_mcp.audit")


def _to_mcp_tool(definition: Any) -> types.Tool:
    """レジストリ定義を MCP の Tool へ変換する。

    name / title / description / inputSchema / annotations は Core 形式のツール契約
    （contracts/mcp-tools/ceos.json）と同一の値を返し、Tool Gateway 等が tools/list の応答と
    契約を突き合わせて記述の差し替えを検知できるようにする（x-mirai は契約側のみに持つ）。
    """
    return types.Tool(
        name=definition.name,
        title=definition.title,
        description=definition.description,
        inputSchema=definition.input_schema,
        annotations=types.ToolAnnotations(**definition.annotations()),
    )


def _current_authorization(server: Server) -> str | None:
    """現在の MCP リクエストの Authorization ヘッダーを取得する。"""
    try:
        request = server.request_context.request
    except LookupError:
        return None
    if request is None:
        return None
    return request.headers.get("authorization")


def _current_caller(authorization: str | None) -> str:
    """監査ログ用の呼び出し元識別子（sub）。トークン本文は記録しない。"""
    data = authenticate_bearer(authorization)
    return data.sub if data is not None else "anonymous"


def create_mcp_server(
    registry: ToolRegistry,
    settings: Settings,
) -> Server:
    """読み取り専用 MCP サーバーを構築する。"""
    server: Server = Server(
        settings.MCP_SERVER_NAME,
        version=settings.MCP_SERVER_VERSION,
    )

    @server.list_tools()
    async def _list_tools() -> list[types.Tool]:
        if not is_server_enabled(settings):
            return []
        return [
            _to_mcp_tool(definition)
            for definition in registry.definitions
            if is_tool_allowed(definition.name, registry, settings)
        ]

    @server.call_tool()
    async def _call_tool(name: str, arguments: dict[str, Any]) -> list[types.Content]:
        authorization = _current_authorization(server)
        caller = _current_caller(authorization)
        started = time.perf_counter()
        outcome = ToolCallOutcome(
            result_code="INTERNAL_ERROR",
            error_message="内部エラーが発生しました。",
        )
        try:
            outcome = await execute_tool(
                name,
                arguments,
                authorization=authorization,
                client=upstream.get_upstream_client(),
                registry=registry,
                settings=settings,
                resolve_authorization=(
                    token_exchange.get_token_exchanger().upstream_authorization
                ),
            )
        except Exception:  # pragma: no cover - 予期しない障害の最終防衛線
            logger.exception("MCP tools/call で予期しない例外が発生しました")
        finally:
            latency_ms = (time.perf_counter() - started) * 1000.0
            audit_logger.info(
                "mcp_tools_call caller=%s tool=%s latency_ms=%.2f result=%s"
                " http_status=%s",
                caller,
                name,
                latency_ms,
                outcome.result_code,
                outcome.http_status,
            )

        if outcome.is_error:
            # 拒否は MCP の isError=true として返す（業務データは info で記録しない）
            raise ToolCallRefused(outcome.error_message or outcome.result_code)

        payload_text = json.dumps(
            outcome.payload or {}, ensure_ascii=False, default=str
        )
        return [types.TextContent(type="text", text=payload_text)]

    return server


@dataclass
class McpRuntime:
    """MCP サーバー・セッションマネージャー・ASGI アプリの束。"""

    server: Server
    session_manager: StreamableHTTPSessionManager
    asgi_app: Starlette


def build_mcp_runtime(
    settings: Settings | None = None,
    registry: ToolRegistry | None = None,
) -> McpRuntime:
    """MCP ランタイムを構築する（lifespan で session_manager.run() を起動する）。"""
    resolved = settings or get_settings()
    resolved_registry = registry or REGISTRY
    server = create_mcp_server(resolved_registry, resolved)
    session_manager = StreamableHTTPSessionManager(
        app=server,
        stateless=resolved.MCP_STATELESS,
    )

    async def handle_streamable_http(
        scope: Scope, receive: Receive, send: Send
    ) -> None:
        await session_manager.handle_request(scope, receive, send)

    asgi_app = Starlette(routes=[Mount("/", app=handle_streamable_http)])
    return McpRuntime(
        server=server,
        session_manager=session_manager,
        asgi_app=asgi_app,
    )
