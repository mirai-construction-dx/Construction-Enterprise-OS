"""認証ミドルウェア — Auth Service 発行の JWT を検証する

services/construction と同じ JWT/OIDC パターンを踏襲する。
MCP の読み取りツールは有効なユーザートークンを必須とする。
"""

from dataclasses import dataclass
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import InvalidTokenError as JWTError
from jwt import MissingRequiredClaimError

from ..config import get_settings

security = HTTPBearer(auto_error=False)


@dataclass
class TokenData:
    sub: str
    type: str
    org: str | None = None
    roles: list[str] | None = None
    scopes: list[str] | None = None
    # aud=MCP_AUDIENCE のトークン（上流呼び出し時に交換が必要）
    audience_bound: bool = False


def _decode_payload(token: str) -> tuple[dict, bool] | None:
    """署名・有効期限・audience を検証する（ADR-0003）。

    - aud=MCP_AUDIENCE: 受理（audience_bound=True）
    - aud 無し: MCP_REQUIRE_AUDIENCE=false のときのみ受理（従来トークン）
    - 別の aud: 拒否
    """
    settings = get_settings()
    try:
        payload = jwt.decode(
            token,
            settings.jwt_public_key,
            algorithms=[settings.JWT_ALGORITHM],
            audience=settings.MCP_AUDIENCE,
            options={"verify_exp": True, "require": ["aud"]},
        )
        return payload, True
    except MissingRequiredClaimError as exc:
        if exc.claim != "aud" or settings.MCP_REQUIRE_AUDIENCE:
            return None
    except JWTError:
        return None

    # aud を持たない従来トークン（Phase 0/1 の互換）
    try:
        payload = jwt.decode(
            token,
            settings.jwt_public_key,
            algorithms=[settings.JWT_ALGORITHM],
            options={"verify_exp": True},
        )
    except JWTError:
        return None
    return payload, False


def decode_token(token: str) -> TokenData | None:
    """JWT を検証してペイロードを返す。無効・期限切れ・audience 不一致の場合は None。"""
    decoded = _decode_payload(token)
    if decoded is None:
        return None
    payload, audience_bound = decoded
    try:
        return TokenData(
            sub=payload["sub"],
            type=payload.get("type", "user"),
            org=payload.get("org"),
            roles=payload.get("roles", []),
            scopes=payload.get("scopes", []),
            audience_bound=audience_bound,
        )
    except KeyError:
        return None


def extract_bearer_token(authorization: str | None) -> str | None:
    """Authorization ヘッダーから Bearer トークンを取り出す。"""
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return None
    return token.strip()


def authenticate_bearer(authorization: str | None) -> TokenData | None:
    """Authorization ヘッダーを検証し、ユーザートークンなら TokenData を返す。"""
    token = extract_bearer_token(authorization)
    if token is None:
        return None
    data = decode_token(token)
    if data is None or data.type != "user":
        return None
    return data


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(security)],
) -> TokenData:
    """FastAPI 依存関係としてのユーザー認証（未認証は 401/403）。"""
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "AUTH_REQUIRED", "message": "認証が必要です。"},
        )

    token_data = decode_token(credentials.credentials)
    if not token_data:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "INVALID_TOKEN",
                "message": "トークンが無効または期限切れです。",
            },
        )

    if token_data.type != "user":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "FORBIDDEN",
                "message": "このAPIにはユーザートークンが必要です。",
            },
        )

    return token_data
