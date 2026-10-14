"""ツール実行エンジン — 検証・上流呼び出し・結果コード返却

実行結果は必ず :class:`ToolCallOutcome` として返し、呼び出し側（MCP ハンドラー）が
監査ログへ result_code を記録できるようにする。
"""

from collections.abc import Awaitable, Callable
from typing import Any, Protocol
from urllib.parse import quote

from ..config import Settings
from ..services.token_exchange import UpstreamAuthError
from ..services.upstream import UpstreamResult, UpstreamUnavailableError
from .models import ToolCallOutcome, ToolDefinition
from .policy import is_server_enabled, is_tool_allowed
from .registry import ToolNotFoundError, ToolRegistry

RESULT_OK = "OK"
RESULT_SERVER_DISABLED = "SERVER_DISABLED"
RESULT_TOOL_NOT_FOUND = "TOOL_NOT_FOUND"
RESULT_TOOL_NOT_ALLOWED = "TOOL_NOT_ALLOWED"
RESULT_ARGUMENT_INVALID = "TOOL_ARGUMENT_INVALID"
RESULT_UPSTREAM_ERROR = "UPSTREAM_ERROR"
RESULT_UPSTREAM_UNAVAILABLE = "UPSTREAM_UNAVAILABLE"
RESULT_UPSTREAM_AUTH_UNAVAILABLE = "UPSTREAM_AUTH_UNAVAILABLE"

# 呼び出し元の Authorization から上流用 Authorization を解決する（ADR-0003 のトークン交換）
AuthorizationResolver = Callable[[str | None], Awaitable[str | None]]


class ToolArgumentError(ValueError):
    """入力引数がスキーマに適合しない。"""


class ToolCallRefused(RuntimeError):
    """tools/call を拒否したことを MCP 層（isError=true）へ伝える例外。"""


class UpstreamClientProtocol(Protocol):
    """上流クライアントの最小インターフェース（テストで差し替え可能）。"""

    async def get(
        self,
        service: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        authorization: str | None = None,
    ) -> UpstreamResult: ...


def validate_arguments(
    definition: ToolDefinition, arguments: dict[str, Any] | None
) -> dict[str, Any]:
    """JSON Schema（抜粋）に基づいて引数を検証・正規化する。"""
    if arguments is None:
        arguments = {}
    if not isinstance(arguments, dict):
        raise ToolArgumentError("arguments はオブジェクトである必要があります。")

    schema = definition.input_schema
    properties: dict[str, Any] = schema.get("properties", {})
    required: list[str] = schema.get("required", [])
    additional_allowed = bool(schema.get("additionalProperties", True))

    unknown = sorted(set(arguments) - set(properties))
    if unknown and not additional_allowed:
        raise ToolArgumentError(f"未定義の引数です: {', '.join(unknown)}")

    missing = [key for key in required if key not in arguments]
    if missing:
        raise ToolArgumentError(f"必須引数が不足しています: {', '.join(missing)}")

    validated: dict[str, Any] = {}
    for key, value in arguments.items():
        if key in properties:
            validated[key] = _coerce_value(key, value, properties[key])
    return validated


def _coerce_value(key: str, value: Any, spec: dict[str, Any]) -> Any:
    expected = spec.get("type")
    if expected == "string":
        if not isinstance(value, str):
            raise ToolArgumentError(f"引数 {key} は文字列である必要があります。")
        return value
    if expected == "integer":
        if isinstance(value, bool):
            raise ToolArgumentError(f"引数 {key} は整数である必要があります。")
        if isinstance(value, int):
            number = value
        elif isinstance(value, str) and value.strip().lstrip("-").isdigit():
            number = int(value)
        else:
            raise ToolArgumentError(f"引数 {key} は整数である必要があります。")
        minimum = spec.get("minimum")
        maximum = spec.get("maximum")
        if minimum is not None and number < int(minimum):
            raise ToolArgumentError(f"引数 {key} は {minimum} 以上である必要があります。")
        if maximum is not None and number > int(maximum):
            raise ToolArgumentError(f"引数 {key} は {maximum} 以下である必要があります。")
        return number
    return value


def build_upstream_request(
    definition: ToolDefinition, arguments: dict[str, Any]
) -> tuple[str, dict[str, Any]]:
    """パスパラメータを解決し、(path, query_params) を返す。"""
    path = definition.upstream_path
    query: dict[str, Any] = {}
    for key, value in arguments.items():
        token = "{" + key + "}"
        if token in path:
            path = path.replace(token, quote(str(value), safe=""))
        else:
            query[key] = value
    return path, query


async def execute_tool(
    name: str,
    arguments: dict[str, Any] | None,
    *,
    authorization: str | None,
    client: UpstreamClientProtocol,
    registry: ToolRegistry,
    settings: Settings | None = None,
    resolve_authorization: AuthorizationResolver | None = None,
) -> ToolCallOutcome:
    """読み取り専用ツールを実行する。すべての拒否は outcome の result_code で返す。"""
    if not is_server_enabled(settings):
        return ToolCallOutcome(
            result_code=RESULT_SERVER_DISABLED,
            error_message="MCP サーバーは無効化されています。",
        )

    try:
        definition = registry.require(name)
    except ToolNotFoundError:
        return ToolCallOutcome(
            result_code=RESULT_TOOL_NOT_FOUND,
            error_message="未登録のツールです。",
        )

    if not is_tool_allowed(name, registry, settings):
        return ToolCallOutcome(
            result_code=RESULT_TOOL_NOT_ALLOWED,
            error_message="許可されていないツールです。",
        )

    try:
        validated = validate_arguments(definition, arguments)
    except ToolArgumentError as exc:
        return ToolCallOutcome(
            result_code=RESULT_ARGUMENT_INVALID,
            error_message=str(exc),
        )

    path, query = build_upstream_request(definition, validated)
    # 交換は検証をすべて通過し、上流を呼ぶ直前にだけ行う
    upstream_authorization = authorization
    if resolve_authorization is not None:
        try:
            upstream_authorization = await resolve_authorization(authorization)
        except UpstreamAuthError:
            return ToolCallOutcome(
                result_code=RESULT_UPSTREAM_AUTH_UNAVAILABLE,
                error_message="上流呼び出し用の資格情報を取得できません。",
            )

    try:
        result = await client.get(
            definition.upstream_service,
            path,
            params=query,
            authorization=upstream_authorization,
        )
    except UpstreamUnavailableError:
        return ToolCallOutcome(
            result_code=RESULT_UPSTREAM_UNAVAILABLE,
            error_message="上流サービスに到達できません。",
        )

    if not result.ok:
        return ToolCallOutcome(
            result_code=RESULT_UPSTREAM_ERROR,
            error_message="上流サービスがエラーを返しました。",
            http_status=result.status_code,
        )

    payload = result.data if isinstance(result.data, dict) else {"data": result.data}
    return ToolCallOutcome(
        result_code=RESULT_OK,
        payload=payload,
        http_status=result.status_code,
    )
