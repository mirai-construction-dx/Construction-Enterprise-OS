"""設定管理（環境変数ベース）"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    ENVIRONMENT: str = "development"
    HOST: str = "0.0.0.0"
    PORT: int = 8006
    DEBUG: bool = True

    CORS_ORIGINS: list[str] = ["http://localhost:3000"]

    DATABASE_URL: str = "postgresql+asyncpg://construction-os:construction-os_dev@localhost:5432/construction-os"
    DATABASE_POOL_SIZE: int = 20
    DATABASE_MAX_OVERFLOW: int = 10

    LLM_BASE_URL: str = "https://api.openai.com/v1"
    LLM_API_KEY: str = ""
    LLM_DEFAULT_MODEL: str = "gpt-4"
    LLM_EMBEDDING_MODEL: str = "text-embedding-ada-002"
    # 本番相当の環境（development / test / docker 以外）で LLM を直接呼ぶことを明示的に許す。
    # 既定 False。stg・本番の定義には入れない（ADR-0008、services/provider_policy.py）。
    ALLOW_DIRECT_LLM_IN_NONDEV: bool = False

    JWT_PUBLIC_KEY: str = ""
    JWT_ALGORITHM: str = "HS256"

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
        resolved = settings.jwt_public_key
        if not resolved or "dev-only" in resolved:
            raise RuntimeError(
                f"JWT_PUBLIC_KEY が未設定のため起動を中止します"
                f" (ENVIRONMENT={settings.ENVIRONMENT})。"
                "環境変数 JWT_PUBLIC_KEY を設定してください。"
            )
    return settings

