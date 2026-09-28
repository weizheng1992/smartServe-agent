"""密封测试环境 — 移植 apps/server/test/helpers/sealedEnv.ts。

pytest 收集测试模块之前先导入本文件,顶层即完成
「容器启动 → 环境变量注入 → Alembic 建表」,保证后续任何模块
(engine_py.config / gateway_py.main)导入时读到的就是容器地址。

外部环境直连:AGENT_ALL_TEST_USE_EXTERNAL=1 时不启容器,直接使用
DATABASE_URL / REDIS_URL(用于无 Docker 的 CI)。
"""

from __future__ import annotations

import asyncio
import atexit
import contextlib
import os
import sys
import tempfile
import time
import uuid
from pathlib import Path

import httpx
import pytest_asyncio

REPO_ROOT = Path(__file__).resolve().parents[3]
ENGINE_DIR = REPO_ROOT / "services" / "engine-py"

_TS = str(int(time.time()))
CONTRACT_THREAD = f"contract_thread_{_TS}"
# Python 侧 ApprovalGatekeeper 校验审批单 ID 为 UUID 格式(TS 契约用 app_contract_${TS},
# 该断言在 TS 侧从未真正跑过;此处按 Python 真实契约钉死)
CONTRACT_APPROVAL = str(uuid.uuid4())
RT_THREAD = f"rt_contract_thread_{_TS}"

_CONTAINERS: list = []


def _stop_containers() -> None:
    """ryuk 禁用时的兜底回收(正常退出路径;SIGKILL 仍会泄漏,重跑前 docker rm 即可)。"""
    for c in _CONTAINERS:
        with contextlib.suppress(Exception):
            c.stop()
    _CONTAINERS.clear()


def _bootstrap_sealed_env() -> None:
    # 上传契约隔离(wayfinder multimodal-image-chat 002):默认目录是仓库 public/uploads,
    # 测试写入会污染工作区,统一重定向临时目录;须先于 gateway_py 导入生效
    os.environ.setdefault("UPLOADS_DIR", tempfile.mkdtemp(prefix="agent_all_uploads_"))
    # 关后台 embedding 预热:预热线程与请求线程并发 encode 在 Py3.14 + torch 下
    # 曾触发 SIGSEGV(本地 bge 单例本就只该串行);测试按需走请求时懒加载
    os.environ.setdefault("AI_EMBEDDING_WARMUP", "0")
    if not _CONTAINERS and os.environ.get("AGENT_ALL_TEST_USE_EXTERNAL") != "1":
        # Docker Desktop(macOS)默认 context 指向 ~/.docker/run/docker.sock,该路径挂进
        # ryuk 容器不通(Desktop 仅对 /var/run/docker.sock 做特权 socket 转发)→ ryuk
        # 启动即死:轻则容器泄漏无人回收,重则 Reaper 竞态失败直接 ConnectionError。
        # 此时禁用 ryuk,由 atexit 兜底回收;Linux / 已启用默认 socket 的机器不受影响。
        if sys.platform == "darwin" and not os.path.exists("/var/run/docker.sock"):
            os.environ.setdefault("TESTCONTAINERS_RYUK_DISABLED", "true")
        from testcontainers.postgres import PostgresContainer
        from testcontainers.redis import RedisContainer

        pg = PostgresContainer("postgres:15-alpine")
        pg.start()
        redis = RedisContainer("redis:7-alpine")
        redis.start()
        _CONTAINERS.extend([pg, redis])
        atexit.register(_stop_containers)
        os.environ["DATABASE_URL"] = pg.get_connection_url().replace("postgresql+psycopg2", "postgresql+asyncpg")
        os.environ["REDIS_URL"] = f"redis://{redis.get_container_host_ip()}:{redis.get_exposed_port(6379)}/0"
        # 商户独立库(agent_merchant)由 merchant_db 自愈建库,与平台库同实例,无需单独容器


def _upgrade_schema() -> None:
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(ENGINE_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(ENGINE_DIR / "alembic"))
    command.upgrade(cfg, "head")


SEED_TENANTS = [
    ("ecommerce", "通用电商主站 (Default)"),
    ("nike", "Nike 官方旗舰店"),
    ("adidas", "Adidas 运动专营"),
]


async def seed_tenants() -> None:
    from engine_py.db import get_session
    from sqlalchemy import text

    async with get_session() as session:
        for business_id, name in SEED_TENANTS:
            await session.execute(
                text(
                    "INSERT INTO tenants (id, business_id, name, plan_tier, status) "
                    "VALUES (CAST(:id AS uuid), :bid, :name, 'free', 'active') ON CONFLICT (business_id) DO NOTHING"
                ).bindparams(id=str(uuid.uuid4()), bid=business_id, name=name)
            )
        await session.commit()


async def create_thread(thread_id: str, user_id: str, business_id: str) -> None:
    from engine_py.db import get_session
    from sqlalchemy import text

    async with get_session() as session:
        await session.execute(
            text(
                "INSERT INTO threads (id, user_id, business_id, status) "
                "VALUES (:tid, :uid, :bid, 'active') ON CONFLICT (id) DO NOTHING"
            ).bindparams(tid=thread_id, uid=user_id, bid=business_id)
        )
        await session.commit()


# ---- 密封环境装配(必须发生在任何 engine_py / gateway_py 导入之前)----
_bootstrap_sealed_env()
_upgrade_schema()


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def seeded():
    await seed_tenants()


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def staff_auth():
    """商户管理面身份闸(A4 收口)测试基建:aurora 种子员工直签 JWT。

    ensure_defaults 幂等种 aurora 菜单/角色/员工(身份唯一来源 staff_members);
    另种 aurora 租户行 —— 会话/审批族路由过身份闸后还有 check_tenant_registered
    (未注册租户 403),dev 环境 aurora 是注册租户(merchant-admin 硬编码 x-tenant-id)。
    直签而非走 /api/auth/login —— 本 fixture 只关心「在职员工」这一身份事实,
    密码链路归 auth 契约测试。"""
    import uuid as _uuid

    from engine_py.analytics import rbac
    from engine_py.db import get_session
    from sqlalchemy import text

    from gateway_py.routers.auth import issue_token

    await rbac.ensure_defaults("aurora")
    async with get_session() as session:
        await session.execute(
            text(
                "INSERT INTO tenants (id, business_id, name, plan_tier, status) "
                "VALUES (CAST(:id AS uuid), 'aurora', 'Aurora 极光(测试种子)', 'free', 'active') "
                "ON CONFLICT (business_id) DO NOTHING"
            ).bindparams(id=str(_uuid.uuid4()))
        )
        await session.commit()
    return {"Authorization": f"Bearer {issue_token('u_staff_auth', 'test@example.com')}"}


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def nike_operator(seeded):
    """socket.io 坐席身份绑定(02 安全先行)测试基建:nike 租户在职员工直签 JWT。

    realtime 侧 role=operator 连接自此要求员工 JWT 且 staff.business_id 与
    connect tenantId 一致 —— 本 fixture 提供恰好满足绑定的 nike 员工。直插员工行
    而非 rbac.ensure_defaults:其种子员工 id 固定(staff_owner 等),同一库
    跨租户二次调用会撞主键;菜单/角色面无此约束,经 ensure_menu_seed 幂等补齐
    (live-desk P2 起接管/发言/释放三路过 live_desk:operate perm 闸,admin 角色
    的权限闭包来自 nike 的 role_menus ⨝ menus)。"""
    from engine_py.analytics import rbac
    from engine_py.db import StaffMember, get_session

    from gateway_py.routers.auth import issue_token

    await rbac.ensure_menu_seed("nike")
    email = f"op-nike-{_TS}@nike.test"
    async with get_session() as session:
        session.add(StaffMember(
            id=f"staff_nike_{_TS}", business_id="nike", email=email,
            display_name="耐克坐席", role="admin", status="enabled", password_hash=None,
        ))
        await session.commit()
    return {
        "email": email,
        "name": "耐克坐席",
        "token": issue_token(f"staff_nike_{_TS}", email),
    }


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def client(seeded):
    """ASGI 直连 HTTP 客户端(等价 TS Test.createTestingModule + supertest)。"""
    from gateway_py.main import app as asgi_app

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=asgi_app), base_url="http://testserver") as c:
        yield c


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def contract_fixtures(seeded):
    """契约 fixtures:contract 线程 + 消息 + 待审批单(等价 TS beforeAll 尾段)。"""
    import json

    from engine_py.db import get_session
    from sqlalchemy import text

    from gateway_py import conversation_repo

    await create_thread(CONTRACT_THREAD, "u_contract", "nike")
    await conversation_repo.append_message(
        {
            "threadId": CONTRACT_THREAD,
            "businessId": "nike",
            "userId": "u_contract",
            "role": "user",
            "content": "contract fixture message",
        }
    )
    async with get_session() as session:
        await session.execute(
            text(
                "INSERT INTO pending_approvals (id, thread_id, business_id, status, action_type, reason, "
                "action_payload, deadline) VALUES (CAST(:id AS uuid), :tid, :bid, 'waiting', 'processRefund', "
                ":reason, CAST(:payload AS jsonb), NOW() + INTERVAL '24 hours') ON CONFLICT (id) DO NOTHING"
            ).bindparams(
                id=CONTRACT_APPROVAL,
                tid=CONTRACT_THREAD,
                bid="nike",
                reason="契约测试 fixture",
                payload=json.dumps({"orderId": "ORD-CONTRACT-1", "amount": 300}, ensure_ascii=False),
            )
        )
        await session.commit()


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def live_server(seeded):
    """随机端口的真实 uvicorn 服务(socket.io / SSE 需要真网络栈)。"""
    import uvicorn

    from gateway_py.main import app as asgi_app

    config = uvicorn.Config(asgi_app, host="127.0.0.1", port=0, log_level="warning", lifespan="off")
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())
    for _ in range(200):
        if server.started:
            break
        await asyncio.sleep(0.05)
    if not server.started:
        raise RuntimeError("uvicorn test server failed to start")
    port = server.servers[0].sockets[0].getsockname()[1]
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    await asyncio.wait_for(task, 10)


async def wait_for(predicate, timeout: float = 5.0, interval: float = 0.05) -> None:
    """等价 TS helpers/waitFor:轮询断言直到超时。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        await asyncio.sleep(interval)
    raise AssertionError(f"waitFor timed out after {timeout}s")
