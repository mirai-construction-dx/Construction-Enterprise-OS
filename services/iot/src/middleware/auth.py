"""認証ミドルウェア - JWTトークン検証"""

from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field


class TokenData(BaseModel):
    sub: str
    type: str  # "user" or "client"
    org: str | None = None
    roles: list[str] = Field(default_factory=list)
    scopes: list[str] = Field(default_factory=list)


security = HTTPBearer(auto_error=False)


def decode_token(token: str) -> TokenData | None:
    import jwt
    from jwt import InvalidTokenError as JWTError
    from ..config import get_settings

    settings = get_settings()
    try:
        payload = jwt.decode(
            token,
            settings.jwt_public_key,
            algorithms=[settings.JWT_ALGORITHM],
            options={"verify_exp": True},
        )
        return TokenData(
            sub=payload.get("sub", ""),
            type=payload.get("type", "user"),
            org=payload.get("org"),
            roles=payload.get("roles", []),
            scopes=payload.get("scopes", []),
        )
    except JWTError:
        return None


async def get_current_user(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(security)],
) -> TokenData:
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


async def get_current_client(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(security)],
) -> TokenData:
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

    if token_data.type not in ("client", "user"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "FORBIDDEN",
                "message": "このAPIにはクライアントトークンが必要です。",
            },
        )

    return token_data


def require_organization_id(token_data: TokenData) -> UUID:
    """トークンの org を必須化して UUID で返す（fail-closed）。"""
    if not token_data.org:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "ORG_REQUIRED", "message": "Organization claim is required."},
        )
    try:
        return UUID(token_data.org)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "ORG_INVALID", "message": "Organization claim is invalid."},
        ) from exc
