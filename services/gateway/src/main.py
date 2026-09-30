"""
Construction-Enterprise-OS API Gateway

建設・土木業向け統合OSのAPIゲートウェイサービス。
全クライアントリクエストの単一入口として機能する。
"""

import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .config import get_settings
from .middleware.auth import AuthMiddleware
from .middleware.cors import setup_cors
from .middleware.logging import LoggingMiddleware
from .middleware.rate_limit import RateLimitMiddleware
from .routes.proxy import router as proxy_router

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    settings = get_settings()
    logger.info(f"Starting API Gateway on {settings.GATEWAY_HOST}:{settings.GATEWAY_PORT}")

    # Initialize shared auth middleware
    try:
        from construction_enterprise_os_auth import configure_auth  # type: ignore[import-not-found]
        configure_auth(
            jwt_public_key=getattr(settings, 'jwt_public_key', getattr(settings, 'JWT_PUBLIC_KEY', "dev-key")),
            jwt_algorithm=getattr(settings, 'JWT_ALGORITHM', "HS256"),
        )
    except ImportError:
        pass  # Auth package not installed, using local middleware

    upstream_count = len(settings.UPSTREAM_SERVICES)
    logger.info(f"Registered {upstream_count} upstream services")
    for pattern, url in settings.UPSTREAM_SERVICES.items():
        logger.info(f"  {pattern} -> {url}")

    yield

    logger.info("Shutting down API Gateway")


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="Construction-Enterprise-OS API Gateway",
        description="建設業統合OS APIゲートウェイ",
        version="0.1.0",
        docs_url="/docs" if settings.ENVIRONMENT == "development" else None,
        redoc_url="/redoc" if settings.ENVIRONMENT == "development" else None,
        lifespan=lifespan,
    )

    # ミドルウェア（後から追加したものほど外側。外側 -> 内側:
    # CORS -> Auth -> RateLimit -> Logging）
    app.add_middleware(LoggingMiddleware)
    app.add_middleware(RateLimitMiddleware)
    app.add_middleware(AuthMiddleware)

    # CORS は最外側に置く（Issue #107）。preflight（Origin +
    # Access-Control-Request-Method 付き OPTIONS）は認証前に CORSMiddleware が応答し、
    # 401/429 などの内側のエラー応答にも CORS ヘッダーが付与される。
    # preflight 以外のリクエストは素通しされるため、引き続き Auth が認証を強制する。
    setup_cors(app)

    # ヘルスチェック（catch-all プロキシルートより先に定義）
    @app.get("/health")
    async def health():
        return {"status": "healthy", "service": "api-gateway"}

    # プロキシルーター
    app.include_router(proxy_router)

    # グローバルエラーハンドラ
    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        logger.exception(f"Unhandled exception: {exc}")
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "error": {
                    "code": "INTERNAL_ERROR",
                    "message": "内部エラーが発生しました。管理者に連絡してください。",
                },
            },
        )

    return app


app = create_app()
