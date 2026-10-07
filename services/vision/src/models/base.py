"""Database connection base with vision schema."""

from sqlalchemy import MetaData
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from ..config import get_settings

settings = get_settings()

engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,
    pool_size=settings.DATABASE_POOL_SIZE,
    max_overflow=settings.DATABASE_MAX_OVERFLOW,
)

async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    metadata = MetaData(schema="vision")


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session() as session:
        try:
            yield session
            # 18サービス（construction/erp/gis 等）と同じくリクエスト正常終了時に確定する。
            # これが無いと close() 時に暗黙ロールバックされ、flush 済みの書き込みが失われる。
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
