"""
Construction-Enterprise-OS 統合認証基盤 (Auth Service)

建設・土木業向け統合OSの認証・認可サービス。
全サービスの認証起点として機能する。
"""

import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from .config import get_settings
from .api import (
    auth,
    users,
    roles,
    permissions,
    clients,
    audit,
    ad,
    entra,
    health,
    organizations,
    internal,
    token_exchange,
)
from .models.base import engine, get_db

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """アプリケーションライフサイクル管理"""
    settings = get_settings()
    logger.info(f"Starting Auth Service on {settings.HOST}:{settings.PORT}")

    # Initialize shared auth middleware
    try:
        from construction_enterprise_os_auth import configure_auth  # type: ignore[import-not-found]

        configure_auth(
            jwt_public_key=getattr(
                settings,
                "jwt_public_key",
                getattr(settings, "JWT_PUBLIC_KEY", "dev-key"),
            ),
            jwt_algorithm=getattr(settings, "JWT_ALGORITHM", "HS256"),
        )
    except ImportError:
        pass  # Auth package not installed, using local middleware

    # 開発環境: テーブルはAlembicマイグレーションで管理
    # 必要な場合は 'alembic upgrade head' を実行すること

    yield

    logger.info("Shutting down Auth Service")
    await engine.dispose()


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="Construction-Enterprise-OS Auth Service",
        description="建設業統合OS 認証・認可サービス",
        version="0.1.0",
        docs_url="/docs" if settings.ENVIRONMENT == "development" else None,
        redoc_url="/redoc" if settings.ENVIRONMENT == "development" else None,
        openapi_url="/openapi.json" if settings.ENVIRONMENT == "development" else None,
        lifespan=lifespan,
    )

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ルーター登録
    app.include_router(auth.router, prefix="/api/v1/auth", tags=["auth"])
    app.include_router(token_exchange.router, prefix="/api/v1/auth", tags=["auth"])
    app.include_router(users.router, prefix="/api/v1/users", tags=["users"])
    app.include_router(roles.router, prefix="/api/v1/roles", tags=["roles"])
    app.include_router(
        permissions.router, prefix="/api/v1/permissions", tags=["permissions"]
    )
    app.include_router(
        clients.router, prefix="/api/v1/api-clients", tags=["api-clients"]
    )
    app.include_router(audit.router, prefix="/api/v1/audit-logs", tags=["audit"])
    app.include_router(ad.router, prefix="/api/v1/auth/ad", tags=["ad"])
    app.include_router(entra.router, prefix="/api/v1/auth/entra", tags=["entra"])
    app.include_router(health.router, prefix="/api/v1/health", tags=["health"])
    app.include_router(
        organizations.router, prefix="/api/v1/users", tags=["organizations"]
    )
    app.include_router(
        internal.router, prefix="/api/v1/internal", tags=["internal"]
    )

    # ヘルスチェック
    # DB へ到達できない場合は 503 を返す。到達性を確認せずに常に 200 を返すと
    # healthcheck が DB 断を検知できず、監視が機能しない。
    @app.get("/health")
    async def health_check(db: AsyncSession = Depends(get_db)):
        try:
            await db.execute(text("SELECT 1"))
        except Exception as exc:
            raise HTTPException(
                status_code=503, detail="database unavailable"
            ) from exc
        return {"status": "healthy", "service": "auth-service"}

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
