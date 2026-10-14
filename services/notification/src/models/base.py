from collections.abc import AsyncGenerator

from sqlalchemy import MetaData, event
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


@event.listens_for(engine.sync_engine, "connect")
def _set_search_path(dbapi_connection, _connection_record) -> None:
    """notification スキーマの ENUM 型を非修飾で解決できるよう search_path を設定する。

    モデルは Enum(..., name="notification_...") を非修飾名で発行するため、接続の
    search_path に notification が無いと
    'type "notification_..." does not exist' (asyncpg UndefinedObjectError) で失敗する。
    2026-10-14 実測: stg で notification が起動時に既定テンプレートを投入できず
    再起動を繰り返した。auth の models/base.py と同じ対処である。
    """
    cursor = dbapi_connection.cursor()
    cursor.execute("SET search_path TO notification, public")
    cursor.close()


class Base(DeclarativeBase):
    metadata = MetaData(schema="notification")


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
