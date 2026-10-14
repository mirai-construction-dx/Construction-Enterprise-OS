"""JWT authentication middleware."""

from typing import Annotated

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


# 検査（合否確定）に必要なロール（auth サービスの既定ロール seed と一致）
INSPECTION_ROLES = frozenset({"admin", "inspector"})


def require_any_role(token_data: TokenData, allowed_roles: frozenset[str]) -> None:
    """トークンが allowed_roles のいずれかを保持することを要求する（fail-closed）。"""
    roles = set(token_data.roles or [])
    if not (roles & allowed_roles):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "FORBIDDEN",
                "message": "Insufficient role for this operation.",
            },
        )
