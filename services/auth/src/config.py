"""設定管理（環境変数ベース）"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # アプリケーション
    ENVIRONMENT: str = "development"
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    DEBUG: bool = True

    # CORS
    CORS_ORIGINS: list[str] = ["http://localhost:3000"]
    HEALTH_SERVICE_URLS: dict[str, str] = {}
    HEALTH_TIMEOUT_SECONDS: float = 2.0

    # データベース
    DATABASE_URL: str = "postgresql+asyncpg://construction-os:construction-os_dev@localhost:5432/construction-os"
    DATABASE_POOL_SIZE: int = 20
    DATABASE_MAX_OVERFLOW: int = 10

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"

    # JWT
    JWT_PRIVATE_KEY: str = ""  # 本番では必ず設定
    JWT_PUBLIC_KEY: str = ""
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30
    M2M_TOKEN_EXPIRE_HOURS: int = 24

    # トークン交換（RFC 8693、ADR-0003）。既定は無効（Phase 0）。
    TOKEN_EXCHANGE_ENABLED: bool = False
    # ① 通常ユーザートークン → MCP 用（aud=MCP_AUDIENCE）
    MCP_AUDIENCE: str = "api://ceos-mcp"
    MCP_TOKEN_EXPIRE_MINUTES: int = 10
    # ② MCP 用 → 上流用（aud 無し・act 付き）。クライアント認証とスコープが必須
    UPSTREAM_EXCHANGE_AUDIENCE: str = "urn:ceos:upstream"
    UPSTREAM_EXCHANGE_SCOPE: str = "token-exchange:ceos-upstream"
    UPSTREAM_TOKEN_EXPIRE_MINUTES: int = 5

    # MFA
    MFA_ISSUER: str = "Construction-Enterprise-OS"
    MFA_TOKEN_VALIDITY_SECONDS: int = 30

    # セキュリティ
    BCRYPT_ROUNDS: int = 12
    MAX_LOGIN_ATTEMPTS: int = 5
    LOGIN_LOCKOUT_MINUTES: int = 15
    INTERNAL_API_KEY: str = ""

    # 開発用JWT秘密鍵 (本番では絶対に使わないこと)
    @property
    def jwt_private_key(self) -> str:
        if self.JWT_PRIVATE_KEY:
            return self.JWT_PRIVATE_KEY
        # 開発用の固定鍵 (本番では必ず環境変数から注入)
        return "dev-only-do-not-use-in-production"

    @property
    def jwt_public_key(self) -> str:
        if self.JWT_PUBLIC_KEY:
            return self.JWT_PUBLIC_KEY
        return "dev-only-do-not-use-in-production"


@lru_cache()
def get_settings() -> Settings:
    settings = Settings()
    # 開発用既定鍵での起動を防止する。ENVIRONMENT が development/test の場合は
    # ローカル開発を妨げないようフォールバックを許容する。
    if settings.ENVIRONMENT not in ("development", "test"):
        insecure = [
            name
            for name, key in (
                ("JWT_PRIVATE_KEY", settings.jwt_private_key),
                ("JWT_PUBLIC_KEY", settings.jwt_public_key),
            )
            if not key or "dev-only" in key
        ]
        if insecure:
            raise RuntimeError(
                f"{', '.join(insecure)} が未設定のため起動を中止します"
                f" (ENVIRONMENT={settings.ENVIRONMENT})。"
                "環境変数で鍵を設定してください。"
            )
    return settings

