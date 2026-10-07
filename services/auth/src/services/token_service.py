"""JWTトークン発行・検証サービス"""

import uuid
from datetime import datetime, timedelta, timezone

import jwt
from jwt import InvalidTokenError as JWTError

from ..config import get_settings
from ..schemas import TokenData

settings = get_settings()

# 本サービスが発行するトークンの iss（トークン交換の subject 検証でも使用）
TOKEN_ISSUER = "construction-enterprise-os-auth"


def create_access_token(
    *,
    subject: str,
    token_type: str = "user",
    org: str | None = None,
    roles: list[str] | None = None,
    scopes: list[str] | None = None,
    device_id: str | None = None,
    expires_minutes: int | None = None,
) -> str:
    """アクセストークン発行"""
    now = datetime.now(timezone.utc)
    expires = now + timedelta(
        minutes=expires_minutes or settings.ACCESS_TOKEN_EXPIRE_MINUTES
    )

    payload = {
        "sub": subject,
        "type": token_type,
        "org": org,
        "roles": roles or [],
        "scopes": scopes or [],
        "device_id": device_id,
        "iat": int(now.timestamp()),
        "exp": int(expires.timestamp()),
        "iss": TOKEN_ISSUER,
        "jti": str(uuid.uuid4()),
    }
    return jwt.encode(payload, settings.jwt_private_key, algorithm=settings.JWT_ALGORITHM)


def create_m2m_token(
    *,
    client_id: str,
    org: str,
    scopes: list[str],
    expires_hours: int | None = None,
) -> str:
    """サービス間通信用 M2Mトークン発行"""
    now = datetime.now(timezone.utc)
    expires = now + timedelta(hours=expires_hours or settings.M2M_TOKEN_EXPIRE_HOURS)

    payload = {
        "sub": client_id,
        "type": "client",
        "org": org,
        "scopes": scopes,
        "iat": int(now.timestamp()),
        "exp": int(expires.timestamp()),
        "iss": TOKEN_ISSUER,
        "jti": str(uuid.uuid4()),
    }
    return jwt.encode(payload, settings.jwt_private_key, algorithm=settings.JWT_ALGORITHM)


def decode_token(token: str) -> TokenData | None:
    """トークン検証・デコード"""
    try:
        payload = jwt.decode(
            token,
            settings.jwt_public_key,
            algorithms=[settings.JWT_ALGORITHM],
            options={"verify_exp": True},
        )
        return TokenData(
            sub=payload["sub"],
            type=payload.get("type", "user"),
            org=payload.get("org"),
            roles=payload.get("roles", []),
            scopes=payload.get("scopes", []),
            device_id=payload.get("device_id"),
        )
    except JWTError:
        return None
