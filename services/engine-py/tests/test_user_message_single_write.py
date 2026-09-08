"""用户消息单次落库(wayfinder multimodal 005 治理)— 引擎不重复写用户行。

双插考古:网关 dispatch_chat/SPI 持久化用户消息(带 imageUrls,Ticket 004),
run_agent 又沿 TS 基线 shortMemory.addMessage 盲插一遍(无图)—— TS 树里
appendMessage 并不存在,网关侧插入是 Python 移植新增,引擎侧插入是移植保留,
两者叠加后每条消息时间线出现两行 user(一行带图一行不带)。

裁决:用户行持久化归网关(唯一持有 imageUrls 的入口);引擎零写用户行,
assistant 行仍归引擎。本文件钉死该所有权边界。
"""

from __future__ import annotations

import asyncio
import importlib

import pytest
from sqlalchemy import select

from engine_py.db import Message

pytestmark = pytest.mark.usefixtures("pg_factory")


class _StubGraph:
    """伪图:最小结果字典,走通 run_agent 持久化收口(session_metrics 等)。"""

    async def ainvoke(self, _state):
        return {
            "output": "已为您查询到订单状态。",
            "task_plan": {"subtasks": [], "currentStepIndex": 0},
            "loop_count": 1,
            "global_transitions_count": 2,
            "tool_errors_count": 0,
        }


class _NoopEpisodic:
    def __init__(self, *args, **kwargs):
        pass

    async def add_event(self, *args, **kwargs):
        return None

    async def retrieve_events(self, *args, **kwargs):
        return []


class _NoopLong:
    def __init__(self, *args, **kwargs):
        pass

    async def extract_and_store_fact(self, *args, **kwargs):
        return None

    async def search_relevant_facts(self, *args, **kwargs):
        return []


@pytest.fixture(autouse=True)
def _isolate_llm_and_memory(monkeypatch):
    """替身记忆避开 embedding/LLM(同 test_circuit_breaker_badcase 套路)。"""
    run_agent_module = importlib.import_module("engine_py.run_agent")
    monkeypatch.setattr(run_agent_module, "EpisodicMemory", _NoopEpisodic)
    monkeypatch.setattr(run_agent_module, "LongMemory", _NoopLong)
    yield


def _run(monkeypatch, thread_id: str, message: str) -> dict:
    run_agent_module = importlib.import_module("engine_py.run_agent")
    monkeypatch.setattr(run_agent_module, "build_graph", lambda: _StubGraph())
    job = run_agent_module.AgentJobInput(
        job_id="",  # 空值:跳过 Redis 事件发布,测试零外联
        threadId=thread_id,
        userId="CUST-SINGLE-WRITE",
        businessId="aurora",
        message=message,
    )
    return asyncio.run(run_agent_module.run_agent(job))


async def _fetch_roles(thread_id: str) -> list[str]:
    from engine_py.db import get_session

    async with get_session() as session:
        rows = (
            await session.execute(
                select(Message.role).where(Message.thread_id == thread_id).order_by(Message.created_at)
            )
        ).scalars().all()
        return list(rows)


def test_主链不写用户行_仅落assistant(monkeypatch):
    """网关已持久化用户消息(带 imageUrls),引擎直调 run_agent 不得再插
    无图副本 —— 时间线每条消息只应有一行 user(网关的)。"""
    thread_id = "dbg_thread_user_single_main"
    result = _run(monkeypatch, thread_id, "帮我查一下 ORD-12345 的物流状态")

    assert "订单" in result["output"]
    roles = asyncio.run(_fetch_roles(thread_id))
    assert roles.count("user") == 0  # 所有权在网关;引擎零写用户行
    assert roles.count("assistant") == 1


def test_问候旁路同样不写用户行(monkeypatch):
    """极速问候旁路(_is_quick_greeting)与主链同规:不插用户行,问候
    assistant 行照常落库。"""
    thread_id = "dbg_thread_user_single_greet"
    result = _run(monkeypatch, thread_id, "你好")

    assert "智能客服助理" in result["output"]
    roles = asyncio.run(_fetch_roles(thread_id))
    assert roles.count("user") == 0
    assert roles.count("assistant") == 1
