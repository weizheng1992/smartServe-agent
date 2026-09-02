"""异步 SQLAlchemy 会话 — schema 由 Alembic 管(见 services/engine-py/alembic)。"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ..config import settings

_engine = create_async_engine(settings.database_url, pool_size=10, max_overflow=10, pool_pre_ping=True)
_session_factory = async_sessionmaker(_engine, class_=AsyncSession, expire_on_commit=False)


@asynccontextmanager
async def get_session() -> AsyncIterator[AsyncSession]:
    """产出一次性会话;事务提交由调用方显式 commit,退出时自动 close(未提交即回滚)。"""
    async with _session_factory() as session:
        yield session
