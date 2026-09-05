"""engine-py 测试共享夹具。

准则 5(见 .claude/rules/agent-engine.md):config.py 导入时读取环境变量,
任何测试基建必须先注入 DATABASE_URL / REDIS_URL 再导入 engine_py 模块。

DB 语义测试(outbox 对账 / 画像租户隔离)共用 session 级密封 PG 夹具:
testcontainers 容器 → Alembic 建真实 schema → 模块级会话工厂整体替换为
指向容器的 NullPool 引擎(每个 sync 测试各自 asyncio.run 独立事件循环,
池化连接跨循环复用必炸,NullPool 每次会话新建连接、归还即关闭)。
"""

from __future__ import annotations

import asyncio
import atexit
import os
import sys
from pathlib import Path

import pytest

# 环境变量注入必须先于任何 engine_py 导入
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://u:p@localhost:5432/test_unused")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

ENGINE_DIR = Path(__file__).resolve().parents[1]


def _upgrade_schema(url: str) -> None:
    from alembic.config import Config

    from alembic import command

    cfg = Config(str(ENGINE_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(ENGINE_DIR / "alembic"))
    os.environ["DATABASE_URL"] = url
    command.upgrade(cfg, "head")


async def _set_role_lock_timeout(engine) -> None:
    from sqlalchemy import text
    from sqlalchemy.engine import make_url

    user = make_url(str(engine.url)).username
    async with engine.connect() as conn:
        await conn.execute(text(f'ALTER ROLE "{user}" SET lock_timeout = "3s"'))


@pytest.fixture(scope="session")
def pg_factory():
    """密封 PG:容器起一次,Alembic 建表,会话工厂指向容器(整个测试会话共享)。"""
    if sys.platform == "darwin" and not os.path.exists("/var/run/docker.sock"):
        # Docker Desktop 的 socket 路径挂不进 ryuk 容器(同 gateway-py 密封测试踩坑)
        os.environ.setdefault("TESTCONTAINERS_RYUK_DISABLED", "true")
    from testcontainers.postgres import PostgresContainer

    try:
        pg = PostgresContainer("postgres:15-alpine")
        pg.start()
    except Exception as err:
        pytest.skip(f"Docker/Postgres 容器不可用,跳过 DB 语义测试: {err}")
    atexit.register(lambda: pg.stop())

    url = pg.get_connection_url().replace("postgresql+psycopg2", "postgresql+asyncpg")
    _upgrade_schema(url)

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool

    from engine_py.db import session as db_session

    engine = create_async_engine(url, poolclass=NullPool)
    asyncio.run(_set_role_lock_timeout(engine))
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    original = db_session._session_factory
    db_session._session_factory = factory
    try:
        yield factory
    finally:
        db_session._session_factory = original
        asyncio.run(engine.dispose())
