"""テスト用ヘルパー（ネットワーク非依存）"""

import json
import time
from typing import Any

import jwt
from src.services.upstream import UpstreamResult

TEST_JWT_KEY = "test-only-mcp-key-0123456789abcdef"
ORG_ID = "00000000-0000-0000-0000-0000000000aa"

MCP_ACCEPT = "application/json, text/event-stream"

INITIALIZE_PARAMS = {
    "protocolVersion": "2025-03-26",
    "capabilities": {},
    "clientInfo": {"name": "ceos-mcp-test", "version": "0.0.1"},
}


def _configured_key() -> str:
    """署名に使う鍵。テスト用の固定値ではなく**その環境の設定**に合わせる。

    `conftest` は `JWT_PUBLIC_KEY` を `setdefault` で入れるため、CI やローカル
    （鍵が未設定）では従来どおり `TEST_JWT_KEY` と一致する。
    一方、stg のように実環境で `JWT_PUBLIC_KEY` が設定されている場合、
    固定値で署名するとアプリ側の検証鍵と食い違い `INVALID_TOKEN` になる。
    上流結合テスト（`live_upstream`）は**上流が起動している実環境でしか走らない**ため、
    固定値のままだとその目的を果たせない（2026-10-14 実測）。
    """
    from src.config import get_settings

    return get_settings().jwt_public_key


def make_token(
    sub: str = "user-1",
    token_type: str = "user",
    *,
    key: str | None = None,
    expires_in: int = 3600,
    **extra: Any,
) -> str:
    """テスト用 JWT を発行する。`key` を省略すると環境の設定鍵で署名する。"""
    payload: dict[str, Any] = {
        "sub": sub,
        "type": token_type,
        "org": ORG_ID,
        "roles": ["project_manager"],
        "scopes": [],
        "exp": int(time.time()) + expires_in,
    }
    payload.update(extra)
    return jwt.encode(payload, key or _configured_key(), algorithm="HS256")


def mcp_headers(token: str | None = None) -> dict[str, str]:
    """MCP POST 用のヘッダーを返す。"""
    headers = {"Accept": MCP_ACCEPT, "Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def parse_mcp_response(response: Any) -> dict[str, Any]:
    """Streamable HTTP（SSE または JSON）の応答から JSON-RPC メッセージを取り出す。"""
    text = response.text.strip()
    if text.startswith("event:"):
        for line in text.splitlines():
            if line.startswith("data:"):
                return json.loads(line[len("data:") :].strip())
    return json.loads(text)


def initialize(client: Any, token: str | None) -> dict[str, Any]:
    """MCP の initialize ハンドシェイクを実行して応答を返す。"""
    response = client.post(
        "/mcp/",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": INITIALIZE_PARAMS,
        },
        headers=mcp_headers(token),
    )
    return parse_mcp_response(response)


def call_tool(
    client: Any, token: str | None, name: str, arguments: dict[str, Any] | None = None
) -> dict[str, Any]:
    """tools/call を実行し JSON-RPC 結果を返す。"""
    response = client.post(
        "/mcp/",
        json={
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments or {}},
        },
        headers=mcp_headers(token),
    )
    return parse_mcp_response(response)


def list_tools(client: Any, token: str | None) -> dict[str, Any]:
    """tools/list を実行し JSON-RPC 結果を返す。"""
    response = client.post(
        "/mcp/",
        json={"jsonrpc": "2.0", "id": 3, "method": "tools/list"},
        headers=mcp_headers(token),
    )
    return parse_mcp_response(response)


class FakeUpstreamClient:
    """上流呼び出しを記録するフェイククライアント。"""

    def __init__(
        self,
        response: UpstreamResult | None = None,
        error: Exception | None = None,
    ) -> None:
        self.calls: list[dict[str, Any]] = []
        self.response = response or UpstreamResult(
            status_code=200, data={"items": [], "total": 0}, ok=True
        )
        self.error = error

    async def get(
        self,
        service: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        authorization: str | None = None,
    ) -> UpstreamResult:
        self.calls.append(
            {
                "service": service,
                "path": path,
                "params": params or {},
                "authorization": authorization,
            }
        )
        if self.error is not None:
            raise self.error
        return self.response
