from __future__ import annotations

import contextlib
from typing import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.pool import NullPool

from app.core.config import get_settings


settings = get_settings()

# Use NullPool for short-lived API workers; swap to QueuePool if you add RDS proxying.
engine = create_async_engine(
    settings.database_url,
    echo=settings.db_echo,
    poolclass=NullPool,
    future=True,
)

SessionLocal = async_sessionmaker(
    bind=engine,
    autoflush=False,
    expire_on_commit=False,
    class_=AsyncSession,
)


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency for DB session."""
    async with SessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()
