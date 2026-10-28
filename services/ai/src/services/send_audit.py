"""AI Provider への送信の監査（ADR-0008 是正: 監査に Provider 名を残す）。

外部の LLM Provider へ実際に送信するたびに、監査イベントを 1 件記録する。
記録先は専用ロガー ``ceos_ai.audit`` で、1 行の JSON を出す（MCP サービスの
``ceos_mcp.audit`` と同じ「サービス専用の監査ロガー」パターン）。

記録する項目:
    ts, event, organization_id, actor, actor_type, route, api, stream,
    provider（LLM_BASE_URL のホスト名のみ）, model, request_bytes,
    result（success / error / refused）, http_status, error_type

記録しないもの: 本文・プロンプト・応答・API キー・トークン・URL のパスやクエリ。

モック応答は外部送信が無いため記録しない。本番相当の環境での直接呼び出しの拒否（503）は
送信は無いが、設定の誤りを検知できるよう ``result=refused`` で記録する（MCP の監査が
拒否も記録しているのに合わせる）。
"""

from __future__ import annotations

import json
import logging
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal
from urllib.parse import urlsplit

import httpx

audit_logger = logging.getLogger("ceos_ai.audit")

Route = Literal["chat", "rag", "embeddings"]
Api = Literal["chat.completions", "embeddings"]
Result = Literal["success", "error", "refused"]

_MAX_FIELD = 100


@dataclass(frozen=True)
class AuditContext:
    route: Route
    organization_id: str | None
    actor: str | None
    actor_type: str | None


_context: ContextVar[AuditContext | None] = ContextVar(
    "ceos_ai_audit_context", default=None
)


def bind_audit_context(route: Route, token_data: object) -> None:
    """リクエストの経路と主体を、以後の送信監査に結び付ける。

    ``token_data`` は ``middleware.auth.TokenData``（sub / type / org）。トークン文字列は扱わない。
    """
    org = getattr(token_data, "org", None)
    _context.set(
        AuditContext(
            route=route,
            organization_id=str(org) if org else None,
            actor=_clip(getattr(token_data, "sub", None)),
            actor_type=_clip(getattr(token_data, "type", None)),
        )
    )


def current_context() -> AuditContext | None:
    return _context.get()


def provider_host(base_url: str) -> str | None:
    """URL からホスト名だけを取り出す（認証情報・ポート・パス・クエリは含めない）。"""
    try:
        host = urlsplit(base_url).hostname
    except ValueError:
        return None
    return host.lower() if host else None


def _clip(value: object) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text[:_MAX_FIELD]


def record(
    *,
    api: Api | None,
    provider: str | None,
    model: object,
    request_bytes: int | None,
    result: Result,
    http_status: int | None = None,
    error_type: str | None = None,
    stream: bool = False,
) -> dict:
    """監査イベントを 1 件記録し、記録した辞書を返す（テスト用）。"""
    ctx = _context.get()
    event = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "event": "ai.provider_send",
        "organization_id": ctx.organization_id if ctx else None,
        "actor": ctx.actor if ctx else None,
        "actor_type": ctx.actor_type if ctx else None,
        "route": ctx.route if ctx else None,
        "api": api,
        "stream": stream,
        "provider": provider,
        "model": _clip(model),
        "request_bytes": request_bytes,
        "result": result,
        "http_status": http_status,
        "error_type": _clip(error_type),
    }
    audit_logger.info(json.dumps(event, ensure_ascii=False, separators=(",", ":")))
    return event


async def audited_send(
    client: httpx.AsyncClient,
    request: httpx.Request,
    *,
    api: Api,
    provider: str | None,
    model: object,
    stream: bool = False,
) -> httpx.Response:
    """Provider へ 1 回送信し、結果にかかわらず監査イベントを 1 件記録する。

    送信バイト数は本文の長さだけを数える（本文そのものは記録しない）。
    HTTP エラー（4xx/5xx）は ``raise_for_status`` で例外にする（従来の挙動と同じ）。
    """
    request_bytes = len(request.content or b"")
    try:
        response = await client.send(request, stream=stream)
    except Exception as exc:
        record(
            api=api,
            provider=provider,
            model=model,
            request_bytes=request_bytes,
            result="error",
            error_type=type(exc).__name__,
            stream=stream,
        )
        raise
    ok = response.is_success
    record(
        api=api,
        provider=provider,
        model=model,
        request_bytes=request_bytes,
        result="success" if ok else "error",
        http_status=response.status_code,
        error_type=None if ok else "HTTPStatusError",
        stream=stream,
    )
    if not ok:
        if stream:
            await response.aclose()
        response.raise_for_status()
    return response
