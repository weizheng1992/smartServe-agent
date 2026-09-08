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


@pytest.fixture(scope="session")
def redis_factory():
    """密封 Redis:容器起一次,整个测试会话共享(镜像 gateway-py 密封测试)。"""
    if sys.platform == "darwin" and not os.path.exists("/var/run/docker.sock"):
        os.environ.setdefault("TESTCONTAINERS_RYUK_DISABLED", "true")
    from testcontainers.redis import RedisContainer

    try:
        redis = RedisContainer("redis:7-alpine")
        redis.start()
    except Exception as err:
        pytest.skip(f"Docker/Redis 容器不可用,跳过 Redis 语义测试: {err}")
    atexit.register(lambda: redis.stop())
    yield f"redis://{redis.get_container_host_ip()}:{redis.get_exposed_port(6379)}/0"


@pytest.fixture(scope="session", autouse=True)
def _purge_stale_cart_test_keys():
    """清扫历史残键:购物车隔离前缀键会写进宿主 dev Redis(测试时若 Redis 在线),
    跨轮累积。会话开头一次性 SCAN+DEL 全部 pytest:cart:*;Redis 离线时静默跳过
    (隔离本就降级纯内存,无残键)。扫完必须清 _client —— 该客户端绑定本次临时
    事件循环,留给后续测试就是跨循环毒药。
    """

    async def _purge() -> None:
        from engine_py.event_bus import get_client

        client = await get_client()
        keys = [k async for k in client.scan_iter(match="pytest:cart:*", count=100)]
        if keys:
            await client.delete(*keys)

    from engine_py import event_bus

    try:
        asyncio.run(_purge())
    except Exception:
        pass
    finally:
        event_bus._client = None


@pytest.fixture(autouse=True)
def _isolate_cart_namespace():
    """购物车状态隔离:每个测试使用唯一 Redis 键前缀并清空进程缓存。

    购物车 2026-09-08 起经 Redis 持久化(进程缓存 + 写穿透)。既有购物车测试
    直接 pop/_cart_storage 铺场,若无隔离会读写宿主 dev Redis 的默认命名空间,
    跨运行互相污染。唯一前缀使每个测试面对空命名空间,行为等价纯内存时代。
    """
    from uuid import uuid4

    from engine_py.tools_registry.mall_domain import MallDomainService

    original_prefix = getattr(MallDomainService, "_CART_REDIS_PREFIX", "agent:cart:")
    MallDomainService._CART_REDIS_PREFIX = f"pytest:cart:{uuid4().hex[:8]}:"
    MallDomainService._cart_storage.clear()
    try:
        yield
    finally:
        MallDomainService._CART_REDIS_PREFIX = original_prefix
        MallDomainService._cart_storage.clear()
