"""MCP ツールレジストリ パッケージ

``REGISTRY`` は 5 つの読み取り専用ツール定義を保持する。
サーバー起動時に :func:`load_registry` を呼び、ハッシュ欠落・不一致を検知する。
"""

from .definitions import TOOL_DEFINITIONS
from .executor import (
    RESULT_ARGUMENT_INVALID,
    RESULT_OK,
    RESULT_SERVER_DISABLED,
    RESULT_TOOL_NOT_ALLOWED,
    RESULT_TOOL_NOT_FOUND,
    RESULT_UPSTREAM_AUTH_UNAVAILABLE,
    RESULT_UPSTREAM_ERROR,
    RESULT_UPSTREAM_UNAVAILABLE,
    ToolArgumentError,
    ToolCallRefused,
    UpstreamClientProtocol,
    build_upstream_request,
    execute_tool,
    validate_arguments,
)
from .models import (
    ALLOWED_EFFECTS,
    ALLOWED_TIERS,
    FORBIDDEN_EFFECTS,
    ToolCallOutcome,
    ToolDefinition,
)
from .policy import (
    describe_policy,
    effective_allowlist,
    is_server_enabled,
    is_tool_allowed,
)
from .registry import (
    RegistryIntegrityError,
    ToolNotFoundError,
    ToolRegistry,
    canonical_json,
    compute_binding_sha256,
    compute_definition_sha256,
    tool_contract_sha256,
)

REGISTRY = ToolRegistry(TOOL_DEFINITIONS)


def load_registry() -> ToolRegistry:
    """定義を検証してレジストリをロードする（違反時は例外）。"""
    return REGISTRY.load()


__all__ = [
    "ALLOWED_EFFECTS",
    "ALLOWED_TIERS",
    "FORBIDDEN_EFFECTS",
    "REGISTRY",
    "RESULT_ARGUMENT_INVALID",
    "RESULT_OK",
    "RESULT_SERVER_DISABLED",
    "RESULT_TOOL_NOT_ALLOWED",
    "RESULT_TOOL_NOT_FOUND",
    "RESULT_UPSTREAM_AUTH_UNAVAILABLE",
    "RESULT_UPSTREAM_ERROR",
    "RESULT_UPSTREAM_UNAVAILABLE",
    "TOOL_DEFINITIONS",
    "RegistryIntegrityError",
    "ToolArgumentError",
    "ToolCallOutcome",
    "ToolCallRefused",
    "ToolDefinition",
    "ToolNotFoundError",
    "ToolRegistry",
    "UpstreamClientProtocol",
    "build_upstream_request",
    "canonical_json",
    "compute_binding_sha256",
    "compute_definition_sha256",
    "describe_policy",
    "effective_allowlist",
    "execute_tool",
    "is_server_enabled",
    "is_tool_allowed",
    "load_registry",
    "tool_contract_sha256",
    "validate_arguments",
]
