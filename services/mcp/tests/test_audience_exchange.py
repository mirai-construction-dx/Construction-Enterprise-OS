"""audience 分離とトークン交換のテスト（ADR-0003、ネットワーク非依存）

- aud=api://ceos-mcp は受理し、上流呼び出し時に auth で交換したトークンを使う
- 別 aud は拒否。MCP_REQUIRE_AUDIENCE=1 では aud 無し（従来）も拒否
- 交換の未設定・失敗・到達不能では上流を呼ばない（fail-closed）
- aud 無しの従来トークンは交換せずそのまま転送（Phase 0/1 の互換）
- クライアント秘密・トークンをログに出さない
"""

import base64
import logging
from collections.abc import Callable, Iterator
from urllib.parse import parse_qs

import httpx
import pytest

from src.services import token_exchange
from src.tools import RESULT_OK, RESULT_UPSTREAM_AUTH_UNAVAILABLE
from tests.helpers import call_tool, initialize, list_tools, make_token, mcp_headers

MCP_AUD = "api://ceos-mcp"
CLIENT_ID = "ceo_mcp_client"
CLIENT_SECRET = "test-only-exchange-secret"
EXCHANGED = "exchanged-upstream-token"
WBS_ARGS = {"project_id": "00000000-0000-0000-0000-000000000001"}


class AuthStub:
    """auth の /api/v1/auth/token を模擬する httpx トランスポート。"""

    def __init__(self, status_code: int = 200, body: dict | None = None) -> None:
        self.status_code = status_code
        self.body = body if body is not None else {
            "access_token": EXCHANGED,
            "issued_token_type": "urn:ietf:params:oauth:token-type:access_token",
            "token_type": "Bearer",
            "expires_in": 300,
        }
        self.requests: list[httpx.Request] = []

    def transport(self) -> httpx.MockTransport:
        def handler(request: httpx.Request) -> httpx.Response:
            self.requests.append(request)
            return httpx.Response(self.status_code, json=self.body)

        return httpx.MockTransport(handler)


@pytest.fixture
def configure(monkeypatch) -> Iterator[Callable[..., AuthStub]]:
    """交換設定を環境変数で切り替え、auth をスタブに差し替える。"""

    def _configure(
        *, credentials: bool = True, require: bool = False, stub: AuthStub | None = None
    ) -> AuthStub:
        monkeypatch.setenv("MCP_REQUIRE_AUDIENCE", "1" if require else "0")
        monkeypatch.setenv("MCP_EXCHANGE_CLIENT_ID", CLIENT_ID if credentials else "")
        monkeypatch.setenv("MCP_EXCHANGE_CLIENT_SECRET", CLIENT_SECRET if credentials else "")
        stub = stub or AuthStub()
        token_exchange.set_token_exchanger(
            token_exchange.TokenExchanger(transport=stub.transport())
        )
        return stub

    yield _configure
    token_exchange.set_token_exchanger(None)


def _list_status(client, token: str) -> int:
    return client.post(
        "/mcp/",
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        headers=mcp_headers(token),
    ).status_code


# --- 受信トークンの audience 検証 -------------------------------------------


def test_mcp_audience_token_is_accepted(build_client, configure):
    configure()
    client = build_client()
    token = make_token(aud=MCP_AUD)
    initialize(client, token)
    assert len(list_tools(client, token)["result"]["tools"]) == 5


@pytest.mark.parametrize("aud", ["api://mcip-tool-api", ["api://other"], "urn:ceos:upstream"])
def test_foreign_audience_is_rejected(build_client, configure, aud):
    configure()
    client = build_client()
    assert _list_status(client, make_token(aud=aud)) == 401


def test_legacy_token_accepted_by_default(build_client, configure):
    configure(require=False)
    client = build_client()
    assert _list_status(client, make_token()) == 200


def test_legacy_token_rejected_when_audience_required(build_client, configure):
    configure(require=True)
    client = build_client()
    assert _list_status(client, make_token()) == 401
    assert _list_status(client, make_token(aud=MCP_AUD)) == 200


def test_expired_audience_token_is_rejected(build_client, configure):
    configure()
    client = build_client()
    assert _list_status(client, make_token(aud=MCP_AUD, expires_in=-60)) == 401


# --- 上流呼び出し時のトークン交換 ---------------------------------------------


def test_audience_token_is_exchanged_before_upstream_call(build_client, configure, fake_upstream):
    stub = configure()
    client = build_client()
    token = make_token(aud=MCP_AUD)
    initialize(client, token)
    result = call_tool(client, token, "ceos.wbs.get_tree", WBS_ARGS)

    assert result["result"]["isError"] is False
    # 上流には交換後のトークンだけが渡り、MCP 用トークンは渡らない
    assert fake_upstream.calls[0]["authorization"] == f"Bearer {EXCHANGED}"
    assert token not in str(fake_upstream.calls)

    # 交換リクエストの内容（RFC 8693 + client_secret_basic）
    assert len(stub.requests) == 1
    request = stub.requests[0]
    assert request.url.path == "/api/v1/auth/token"
    form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
    assert form["grant_type"] == "urn:ietf:params:oauth:grant-type:token-exchange"
    assert form["audience"] == "urn:ceos:upstream"
    assert form["subject_token"] == token
    expected = base64.b64encode(f"{CLIENT_ID}:{CLIENT_SECRET}".encode()).decode()
    assert request.headers["authorization"] == f"Basic {expected}"


def test_legacy_token_is_forwarded_without_exchange(build_client, configure, fake_upstream):
    stub = configure()
    client = build_client()
    token = make_token()
    initialize(client, token)
    call_tool(client, token, "ceos.wbs.get_tree", WBS_ARGS)
    assert stub.requests == []
    assert fake_upstream.calls[0]["authorization"] == f"Bearer {token}"


@pytest.mark.parametrize(
    "setup",
    [
        {"credentials": False},
        {"stub": AuthStub(status_code=401, body={"error": "invalid_client"})},
        {"stub": AuthStub(status_code=200, body={"token_type": "Bearer"})},
    ],
    ids=["not-configured", "exchange-refused", "malformed-response"],
)
def test_exchange_failure_is_fail_closed(build_client, configure, fake_upstream, caplog, setup):
    configure(**setup)
    client = build_client()
    token = make_token(aud=MCP_AUD)
    initialize(client, token)
    with caplog.at_level(logging.INFO):
        result = call_tool(client, token, "ceos.wbs.get_tree", WBS_ARGS)

    assert result["result"]["isError"] is True
    assert fake_upstream.calls == []  # 上流は呼ばない
    assert f"result={RESULT_UPSTREAM_AUTH_UNAVAILABLE}" in caplog.text
    assert CLIENT_SECRET not in caplog.text
    assert token not in caplog.text


def test_exchange_unreachable_is_fail_closed(build_client, configure, fake_upstream, monkeypatch):
    configure()

    def unreachable(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down", request=request)

    token_exchange.set_token_exchanger(
        token_exchange.TokenExchanger(transport=httpx.MockTransport(unreachable))
    )
    client = build_client()
    token = make_token(aud=MCP_AUD)
    initialize(client, token)
    result = call_tool(client, token, "ceos.wbs.get_tree", WBS_ARGS)
    assert result["result"]["isError"] is True
    assert fake_upstream.calls == []


def test_no_exchange_for_refused_calls(build_client, configure, fake_upstream):
    """許可されていない・引数不正の呼び出しでは交換しない（不要なトークン発行を避ける）。"""
    stub = configure()
    client = build_client(allowlist="ceos.ledger.get_summary")
    token = make_token(aud=MCP_AUD)
    initialize(client, token)
    assert call_tool(client, token, "ceos.wbs.get_tree", WBS_ARGS)["result"]["isError"] is True
    assert call_tool(client, token, "ceos.unknown", {})["result"]["isError"] is True
    assert stub.requests == []
    assert fake_upstream.calls == []


def test_successful_exchange_is_audited_as_ok(build_client, configure, fake_upstream, caplog):
    configure()
    client = build_client()
    token = make_token(aud=MCP_AUD)
    initialize(client, token)
    with caplog.at_level(logging.INFO):
        call_tool(client, token, "ceos.wbs.get_tree", WBS_ARGS)
    assert f"result={RESULT_OK}" in caplog.text
    assert EXCHANGED not in caplog.text
    assert CLIENT_SECRET not in caplog.text
