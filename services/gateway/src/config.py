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
    GATEWAY_HOST: str = "0.0.0.0"
    GATEWAY_PORT: int = 9000
    DEBUG: bool = True

    CORS_ORIGINS: list[str] = [
        "http://localhost:3000",
        "http://localhost:3100",
        "http://localhost:3101",
        "http://0.0.0.0:3100",
        "http://0.0.0.0:3101",
    ]

    JWT_PUBLIC_KEY: str = ""
    JWT_ALGORITHM: str = "HS256"

    RATE_LIMIT_PER_MINUTE: int = 100

    UPSTREAM_SERVICES: dict[str, str] = {
        # Foundation layer — auth service (port 8000)
        "^/api/v1/health": "http://localhost:8000",
        "^/api/v1/auth": "http://localhost:8000",
        "^/api/v1/users": "http://localhost:8000",
        "^/api/v1/roles": "http://localhost:8000",
        "^/api/v1/permissions": "http://localhost:8000",
        "^/api/v1/api-clients": "http://localhost:8000",
        "^/api/v1/audit-logs": "http://localhost:8000",
        # Document / BIM / workflow
        "^/api/v1/documents": "http://localhost:8001",
        "^/api/v1/workflow": "http://localhost:8002",
        # 申請案件 API（workflow サービスが /api/v1/cases として公開）。
        # パス境界を明示し "/api/v1/casesX" のような近接パスを転送しない。
        "^/api/v1/cases(?:/|$)": "http://localhost:8002",
        "^/api/v1/bim": "http://localhost:8008",
        # GIS / IoT / field
        "^/api/v1/gis": "http://localhost:8003",
        "^/api/v1/iot": "http://localhost:8004",
        "^/api/v1/field": "http://localhost:8007",
        # AI / Vision / Advanced
        "^/api/v1/ai": "http://localhost:8005",
        "^/api/v1/vision": "http://localhost:8011",
        # OCR / ベクトル DB API（vision サービスが /api/v1/ocr・/api/v1/vectors として公開）
        "^/api/v1/ocr(?:/|$)": "http://localhost:8011",
        "^/api/v1/vectors(?:/|$)": "http://localhost:8011",
        "^/api/v1/advanced": "http://localhost:8013",
        # Analytics / Platform / Integrations
        "^/api/v1/analytics": "http://localhost:8014",
        "^/api/v1/integrations": "http://localhost:8012",
        # Business — ERP / Construction / Safety / Partner / Maintenance
        "^/api/v1/erp": "http://localhost:8020",
        "^/api/v1/construction": "http://localhost:8016",
        "^/api/v1/safety": "http://localhost:8019",
        "^/api/v1/partner": "http://localhost:8018",
        "^/api/v1/maintenance": "http://localhost:8009",
        # Automation / Autonomous
        "^/api/v1/automation": "http://localhost:8015",
        "^/api/v1/autonomous": "http://localhost:8010",
        # Security / Notification (infra)
        "^/api/v1/security": "http://localhost:8021",
        "^/api/v1/notification": "http://localhost:8017",
    }

    # 内部ネットワーク専用のため gateway 経由では常に 404 とするパス（認証の有無を問わない）。
    # トークン交換（ADR-0003）は MCP 等の内部サービスが auth を直接呼ぶ。外部公開は別判断。
    INTERNAL_ONLY_PATHS: list[str] = [
        r"^/+api/v1/auth/token/*$",
    ]

    PUBLIC_PATHS: list[str] = [
        "^/health$",
        # サービス稼働状況の集約。auth 側のエンドポイントは認証を要求しておらず、
        # WebUI の共通基盤ページと E2E もトークン無しで参照している。
        # (機密情報を含めない監視用エンドポイントという位置づけ)
        # パス境界を明示する(re.match のため "^/api/v1/health" だけだと
        # "/api/v1/healthcheck" のような別パスまで公開扱いになる)
        "^/api/v1/health(?:/|$)",
        "^/api/v1/auth/login$",
        "^/api/v1/auth/mfa/verify$",
        "^/api/v1/auth/refresh$",
        "^/docs$",
        "^/openapi.json$",
        "^/redoc$",
    ]

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

