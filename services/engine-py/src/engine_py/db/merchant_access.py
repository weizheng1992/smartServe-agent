"""agent_merchant 商户库连接单点(架构审查 #4 步1,2026-10-04)。

连接串解析与引擎构造此前两包各写一份(gateway ``merchant_db`` 的 QueuePool
读写位 + engine ``order_domain`` 的 NullPool 只读/写穿透位,URL 解析逐行同构,
注释互指),收敛为本 module:

- ``merchant_database_url()``:连接串解析唯一实现 —— MERCHANT_DATABASE_URL →
  DATABASE_URL 改库名为 agent_merchant → 默认;postgres(ql):// 统一改写
  asyncpg 驱动。
- ``reader_engine()`` / ``writer_engine()``:engine 侧只读纵深位(会话级
  READ ONLY + 3s 语句超时,wayfinder 09-D4 阶段①收口;写穿透一律走 writer,
  严禁复用 reader)与写穿透位。NullPool 而非 QueuePool:引擎被 lru_cache
  跨事件循环复用 —— 池化 asyncpg 连接绑定建连时的循环,测试端每个测试独立
  asyncio.run,复用必炸(conftest 同款教训);NullPool 每次取用新建连接、
  归还即关,循环安全。
- ``gateway_engine()``:gateway 商户域读写位(QueuePool + pre_ping,DDL 自愈
  与门店写入用)。与 engine 侧 NullPool 的语义差异是刻意的,严禁互相图省事。

依赖方向:gateway → engine(单向);engine 严禁 import gateway。
"""

from __future__ import annotations

import os
import re
from functools import lru_cache

from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from ..config import settings


def merchant_database_url() -> str:
    """商户库连接串(读写共用解析,单点实现)。"""
    url = os.environ.get("MERCHANT_DATABASE_URL")
    if not url:
        base = settings.database_url or "postgres://agent_user:agent_password@localhost:5432/agent_platform"
        url = re.sub(r"/[^/]+$", "/agent_merchant", base)
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+asyncpg://", 1)
    elif url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return url


@lru_cache(maxsize=1)
def reader_engine():
    """只读引擎:会话级 READ ONLY + 3s 语句超时(纵深语义,勿换读写位)。"""
    return create_async_engine(
        merchant_database_url(),
        poolclass=NullPool,
        connect_args={
            "server_settings": {
                "default_transaction_read_only": "on",
                "statement_timeout": "3000",
            }
        },
    )


@lru_cache(maxsize=1)
def writer_engine():
    """写穿透引擎:不带任何只读标记(与 reader 同 URL 不同位)。"""
    return create_async_engine(merchant_database_url(), poolclass=NullPool)


@lru_cache(maxsize=1)
def gateway_engine():
    """gateway 商户域读写引擎(QueuePool + pre_ping;单进程语义)。"""
    return create_async_engine(merchant_database_url(), pool_size=10, max_overflow=0, pool_pre_ping=True)
