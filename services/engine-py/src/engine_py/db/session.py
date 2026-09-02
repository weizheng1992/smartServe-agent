"""异步 SQLAlchemy 会话 — Drizzle 仍是 schema 唯一所有者,本层只是投影(禁止建表/迁移)。"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ..config import settings

_engine = create_async_engine(settings.database_url, pool_size=10, max_overflow=10, pool_pre_ping=True)
_session_factory = async_sessionmaker(_engine, class_=AsyncSession, expire_on_commit=False)


async def get_session() -> AsyncSession:
    return _session_factory()
