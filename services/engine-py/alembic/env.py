"""Alembic 环境 — 接管 Drizzle 的 schema 所有权(Phase 3 翻转)。

连接串解析顺序:DATABASE_URL 环境变量 → engine_py.config.settings.database_url。
asyncpg 驱动 URL 自动归一(alembic 以 sync 方式驱动 run_sync)。
"""

from __future__ import annotations

import asyncio
import os

from sqlalchemy import pool
from sqlalchemy.engine.url import URL, make_url
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context
from engine_py.db import Base

config = context.config

url = os.environ.get("DATABASE_URL")
if url:
    config.set_main_option("sqlalchemy.url", url)
else:
    from engine_py.config import settings

    config.set_main_option("sqlalchemy.url", settings.database_url)

# asyncpg URL(asyncpg+postgresql://)归一为 alembic 可用的 postgresql+asyncpg
# 注意:str(URL) 会把密码脱敏为 ***,必须用 render_as_string(hide_password=False)
parsed: URL = make_url(config.get_main_option("sqlalchemy.url"))
if parsed.drivername in {"postgresql", "postgres"}:
    parsed = parsed.set(drivername="postgresql+asyncpg")
config.set_main_option("sqlalchemy.url", parsed.render_as_string(hide_password=False))

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=parsed.render_as_string(hide_password=False),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
