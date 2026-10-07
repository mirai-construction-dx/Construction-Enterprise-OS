"""トークンエンドポイント — OAuth 2.0 Token Exchange（RFC 8693、ADR-0003）

`POST /api/v1/auth/token`（application/x-www-form-urlencoded）。
応答・エラーは RFC 6749 形式で返し、`Cache-Control: no-store` を付ける。
トークン本体・クライアント秘密はログ・監査ログに記録しない。
"""

import base64
import binascii
import logging
import uuid
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..models.base import get_db
from ..services.auth_service import create_audit_log
from ..services.token_exchange_service import (
    GRANT_TYPE_TOKEN_EXCHANGE,
    TOKEN_TYPE_ACCESS_TOKEN,
    TokenExchangeError,
    exchange_token,
)

logger = logging.getLogger(__name__)
router = APIRouter()

_NO_STORE = {"Cache-Control": "no-store", "Pragma": "no-cache"}


def _error(exc: TokenExchangeError) -> JSONResponse:
    headers = dict(_NO_STORE)
    if exc.status_code == 401:
        headers["WWW-Authenticate"] = 'Basic realm="ceos-auth"'
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": exc.error, "error_description": exc.description},
        headers=headers,
    )


def _client_credentials(request: Request, form: Any) -> tuple[str, str] | None:
    """client_secret_basic または client_secret_post を取り出す（併用は不可）。"""
    header = request.headers.get("authorization", "")
    form_id, form_secret = form.get("client_id"), form.get("client_secret")
    basic: tuple[str, str] | None = None
    if header.lower().startswith("basic "):
        try:
            decoded = base64.b64decode(header[6:].strip(), validate=True).decode("utf-8")
        except (binascii.Error, UnicodeDecodeError) as exc:
            raise TokenExchangeError("invalid_client", "クライアント認証に失敗しました。", 401) from exc
        client_id, sep, client_secret = decoded.partition(":")
        if not sep or not client_id or not client_secret:
            raise TokenExchangeError("invalid_client", "クライアント認証に失敗しました。", 401)
        basic = (client_id, client_secret)
    if basic is not None and (form_id or form_secret):
        raise TokenExchangeError("invalid_request", "クライアント認証方式は 1 つだけ指定してください。")
    if basic is not None:
        return basic
    if form_id or form_secret:
        if not (isinstance(form_id, str) and isinstance(form_secret, str) and form_id and form_secret):
            raise TokenExchangeError("invalid_client", "クライアント認証に失敗しました。", 401)
        return (form_id, form_secret)
    return None


def _form_str(form: Any, key: str) -> str:
    value = form.get(key)
    return value if isinstance(value, str) else ""


def _user_uuid(sub: str | None) -> uuid.UUID | None:
    try:
        return uuid.UUID(sub) if sub else None
    except ValueError:
        return None


@router.post("/token")
async def token(request: Request, db: AsyncSession = Depends(get_db)) -> JSONResponse:
    """トークン交換。許可された 2 方向以外は拒否する。"""
    settings = get_settings()
    audience = ""
    client_id: str | None = None
    try:
        form = await request.form()
        grant_type = _form_str(form, "grant_type")
        if not settings.TOKEN_EXCHANGE_ENABLED or grant_type != GRANT_TYPE_TOKEN_EXCHANGE:
            raise TokenExchangeError("unsupported_grant_type", "サポートされていない grant_type です。")

        requested = _form_str(form, "requested_token_type")
        if requested and requested != TOKEN_TYPE_ACCESS_TOKEN:
            raise TokenExchangeError("invalid_request", "requested_token_type が不正です。")
        audience = _form_str(form, "audience")
        subject_token = _form_str(form, "subject_token")
        if not audience or not subject_token:
            raise TokenExchangeError("invalid_request", "audience と subject_token は必須です。")

        credentials = _client_credentials(request, form)
        client_id = credentials[0] if credentials else None
        issued, client_id = await exchange_token(
            db,
            subject_token=subject_token,
            subject_token_type=_form_str(form, "subject_token_type"),
            audience=audience,
            client_credentials=credentials,
        )
    except TokenExchangeError as exc:
        # 失敗も監査する（トークン・秘密は記録しない）
        if audience or client_id:
            await create_audit_log(
                db,
                user_id=None,
                event_type="auth.token.exchange",
                event_data={"audience": audience, "client_id": client_id, "error": exc.error},
                ip_address=request.client.host if request.client else None,
                user_agent=request.headers.get("user-agent"),
                success=False,
            )
        logger.info("token exchange refused: error=%s audience=%s", exc.error, audience)
        return _error(exc)

    await create_audit_log(
        db,
        user_id=_user_uuid(issued.subject),
        event_type="auth.token.exchange",
        event_data={"audience": issued.audience, "client_id": client_id, "jti": issued.jti},
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    return JSONResponse(
        content={
            "access_token": issued.access_token,
            "issued_token_type": TOKEN_TYPE_ACCESS_TOKEN,
            "token_type": "Bearer",
            "expires_in": issued.expires_in,
        },
        headers=_NO_STORE,
    )
