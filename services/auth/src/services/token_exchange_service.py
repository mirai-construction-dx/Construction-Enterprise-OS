"""トークン交換（RFC 8693）— MCP の audience 分離（ADR-0003）

許可する方向は 2 つだけ。

1. 通常ユーザートークン（aud 無し）→ MCP 用（aud=MCP_AUDIENCE）。クライアント認証不要。
2. MCP 用トークン → 上流用（aud 無し・act 付き）。クライアント認証とスコープが必須。

発行トークンの有効期限は subject_token の有効期限を超えない（交換による延命の防止）。
act を持つ（交換済みの）トークンは再交換できない。
"""

import hashlib
import hmac
import time
import uuid
from dataclasses import dataclass
from typing import Any

import jwt
from jwt import InvalidTokenError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..models import ApiClient
from .token_service import TOKEN_ISSUER

GRANT_TYPE_TOKEN_EXCHANGE = "urn:ietf:params:oauth:grant-type:token-exchange"
TOKEN_TYPE_ACCESS_TOKEN = "urn:ietf:params:oauth:token-type:access_token"
TOKEN_TYPE_JWT = "urn:ietf:params:oauth:token-type:jwt"
ACCEPTED_SUBJECT_TOKEN_TYPES = frozenset({TOKEN_TYPE_ACCESS_TOKEN, TOKEN_TYPE_JWT})

# 存在しないクライアントでも比較処理を行い、応答時間から存在有無を推測されにくくする
_DUMMY_SECRET_HASH = hashlib.sha256(b"ceos-token-exchange-dummy").hexdigest()


class TokenExchangeError(Exception):
    """RFC 6749 §5.2 形式のエラー（error / error_description / HTTP ステータス）。"""

    def __init__(self, error: str, description: str, status_code: int = 400) -> None:
        super().__init__(description)
        self.error = error
        self.description = description
        self.status_code = status_code


@dataclass(frozen=True)
class ExchangedToken:
    access_token: str
    expires_in: int
    audience: str
    subject: str
    jti: str


def decode_subject_token(token: str, *, expected_audience: str | None) -> dict[str, Any]:
    """subject_token を検証する。

    expected_audience が None の場合は aud を持たないトークンのみ受理する
    （PyJWT は audience 未指定で aud 付きトークンを拒否する）。
    """
    settings = get_settings()
    try:
        if expected_audience is None:
            payload = jwt.decode(
                token,
                settings.jwt_public_key,
                algorithms=[settings.JWT_ALGORITHM],
                options={"require": ["exp", "sub"]},
            )
        else:
            payload = jwt.decode(
                token,
                settings.jwt_public_key,
                algorithms=[settings.JWT_ALGORITHM],
                audience=expected_audience,
                options={"require": ["exp", "sub", "aud"]},
            )
    except InvalidTokenError as exc:
        raise TokenExchangeError("invalid_grant", "subject_token が無効です。") from exc

    if payload.get("iss") != TOKEN_ISSUER:
        raise TokenExchangeError("invalid_grant", "subject_token の発行者が不正です。")
    if payload.get("type", "user") != "user":
        raise TokenExchangeError("invalid_grant", "subject_token はユーザートークンである必要があります。")
    if "act" in payload:
        raise TokenExchangeError("invalid_grant", "交換済みトークンは再交換できません。")
    return payload


def issue_exchanged_token(
    subject: dict[str, Any],
    *,
    audience: str | None,
    ttl_minutes: int,
    actor: str | None = None,
    label: str,
) -> ExchangedToken:
    """subject の主体情報を引き継いだ短命トークンを発行する。"""
    settings = get_settings()
    now = int(time.time())
    expires_at = min(int(subject["exp"]), now + ttl_minutes * 60)
    if expires_at <= now:
        raise TokenExchangeError("invalid_grant", "subject_token の有効期限が切れています。")

    jti = str(uuid.uuid4())
    payload: dict[str, Any] = {
        "sub": subject["sub"],
        "type": "user",
        "org": subject.get("org"),
        "roles": subject.get("roles", []),
        "scopes": subject.get("scopes", []),
        "iat": now,
        "exp": expires_at,
        "iss": TOKEN_ISSUER,
        "jti": jti,
    }
    if audience is not None:
        payload["aud"] = audience
    if actor is not None:
        payload["act"] = {"sub": actor}

    token = jwt.encode(payload, settings.jwt_private_key, algorithm=settings.JWT_ALGORITHM)
    return ExchangedToken(
        access_token=token,
        expires_in=expires_at - now,
        audience=label,
        subject=str(subject["sub"]),
        jti=jti,
    )


def _hash_secret(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


async def authenticate_client(
    db: AsyncSession, client_id: str, client_secret: str
) -> ApiClient:
    """クライアント資格情報を検証する（失敗理由は区別せず invalid_client）。"""
    result = await db.execute(select(ApiClient).where(ApiClient.client_id == client_id))
    client = result.scalar_one_or_none()
    stored = client.client_secret_hash if client is not None else _DUMMY_SECRET_HASH
    matches = hmac.compare_digest(_hash_secret(client_secret), stored)
    if client is None or not matches or client.status != "active":
        raise TokenExchangeError("invalid_client", "クライアント認証に失敗しました。", 401)
    return client


async def exchange_token(
    db: AsyncSession,
    *,
    subject_token: str,
    subject_token_type: str,
    audience: str,
    client_credentials: tuple[str, str] | None,
) -> tuple[ExchangedToken, str | None]:
    """許可された 2 方向のいずれかで交換する。戻り値は (発行トークン, 認証済み client_id)。"""
    settings = get_settings()
    if subject_token_type not in ACCEPTED_SUBJECT_TOKEN_TYPES:
        raise TokenExchangeError("invalid_request", "subject_token_type が不正です。")

    client: ApiClient | None = None
    if client_credentials is not None:
        client = await authenticate_client(db, *client_credentials)
    client_id = client.client_id if client is not None else None

    if audience == settings.MCP_AUDIENCE:
        subject = decode_subject_token(subject_token, expected_audience=None)
        issued = issue_exchanged_token(
            subject,
            audience=settings.MCP_AUDIENCE,
            ttl_minutes=settings.MCP_TOKEN_EXPIRE_MINUTES,
            label=settings.MCP_AUDIENCE,
        )
        return issued, client_id

    if audience == settings.UPSTREAM_EXCHANGE_AUDIENCE:
        if client is None:
            raise TokenExchangeError("invalid_client", "クライアント認証が必要です。", 401)
        if settings.UPSTREAM_EXCHANGE_SCOPE not in (client.scopes or []):
            raise TokenExchangeError("unauthorized_client", "このクライアントには交換権限がありません。")
        subject = decode_subject_token(subject_token, expected_audience=settings.MCP_AUDIENCE)
        issued = issue_exchanged_token(
            subject,
            audience=None,
            ttl_minutes=settings.UPSTREAM_TOKEN_EXPIRE_MINUTES,
            actor=client.client_id,
            label=settings.UPSTREAM_EXCHANGE_AUDIENCE,
        )
        return issued, client_id

    raise TokenExchangeError("invalid_target", "許可されていない audience です。")
