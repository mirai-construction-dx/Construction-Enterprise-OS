"""認証ミドルウェア — Auth Service発行のJWTを検証"""

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
import jwt
from jwt import InvalidTokenError as JWTError
from ..config import get_settings

settings = get_settings()
security = HTTPBearer(auto_error=False)


@dataclass
class TokenData:
    sub: str
    type: str
    org: str | None = None
    roles: list[str] | None = None
    scopes: list[str] | None = None


def decode_token(token: str) -> TokenData | None:
    try:
        payload = jwt.decode(
            token,
            settings.JWT_PUBLIC_KEY,
            algorithms=[settings.JWT_ALGORITHM],
            options={"verify_exp": True},
        )
        return TokenData(
            sub=payload["sub"],
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


# rbac-role-model.md: 削除（delete）は admin / site_manager
MANAGEMENT_ROLES = frozenset({"admin", "site_manager"})


def require_any_role(token_data: TokenData, allowed_roles: frozenset[str]) -> None:
    """トークンが allowed_roles のいずれかを保持することを要求する（fail-closed）。"""
    roles = set(token_data.roles or [])
    if not (roles & allowed_roles):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "FORBIDDEN",
                "message": "この操作に必要なロールがありません。",
            },
        )
