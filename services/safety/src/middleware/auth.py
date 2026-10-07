"""JWT authentication middleware."""

from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
import jwt
from jwt import InvalidTokenError as JWTError
from ..config import get_settings

settings = get_settings()
security = HTTPBearer(auto_error=False)


class TokenData:
    """User information extracted from JWT token."""

    def __init__(
        self,
        sub: str,
        type: str = "user",
        org: str | None = None,
        roles: list[str] | None = None,
        scopes: list[str] | None = None,
    ):
        self.sub = sub
        self.type = type
        self.org = org
        self.roles = roles or []
        self.scopes = scopes or []


def decode_token(token: str) -> TokenData | None:
    try:
        payload = jwt.decode(
            token,
            settings.jwt_public_key,
            algorithms=[settings.JWT_ALGORITHM],
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
            detail={"code": "AUTH_REQUIRED", "message": "Authentication required."},
        )

    token_data = decode_token(credentials.credentials)
    if not token_data:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "INVALID_TOKEN", "message": "Token is invalid or expired."},
        )

    if token_data.type != "user":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "FORBIDDEN",
                "message": "User token required for this API.",
            },
        )

    return token_data


def require_organization_id(token_data: TokenData) -> UUID:
    """トークンの org を必須化して UUID で返す（fail-closed）。

    org 欠落時に既定組織へフォールバックすると、組織クレームを持たない
    トークンが他組織のデータへ到達する経路になるため 403 とする。
    """
    if not token_data.org:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "ORG_REQUIRED",
                "message": "Organization claim is required.",
            },
        )
    try:
        return UUID(token_data.org)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "ORG_INVALID",
                "message": "Organization claim is invalid.",
            },
        ) from exc


def require_actor_id(token_data: TokenData) -> UUID:
    """トークンの sub を操作者として同定する（ボディ・クエリの値は信用しない）。"""
    try:
        return UUID(token_data.sub)
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "INVALID_IDENTITY",
                "message": "Authenticated user id is invalid.",
            },
        ) from exc
