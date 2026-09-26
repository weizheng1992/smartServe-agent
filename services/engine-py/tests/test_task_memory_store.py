"""任务记忆真实实现契约(task_memory 表 upsert;2026-09-26 夜审 ④ 测试补强)。

TaskMemory 是 HITL 挂起/恢复的任务态底盘,此前只有引用方测试间接路过:
自身的首存 INSERT / 复存 UPDATE 两分支、未知线程返回 None、异常吞没
(存取失败静默降级,严禁炸状态机 —— agent-engine 准则 4)零直接断言。
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
from sqlalchemy import func, select, text

from engine_py.memory.task_memory import TaskMemory

pytestmark = pytest.mark.usefixtures("pg_factory")


def _tid() -> str:
    return f"tm_{uuid.uuid4().hex[:12]}"


def _seed_thread(thread_id: str) -> None:
    """task_memory.thread_id 外键指向 threads:挂任务态前先落属主线程行。"""

    async def _run() -> None:
        from engine_py.db import get_session

        async with get_session() as session:
            await session.execute(
                text(
                    'INSERT INTO threads (id, "user_id", "business_id", status, "created_at", "updated_at") '
                    "VALUES (:tid, 'u_task_mem', 'aurora', 'active', NOW(), NOW())"
                ).bindparams(tid=thread_id)
            )
            await session.commit()

    asyncio.run(_run())


def _row_count(thread_id: str) -> int:
    from engine_py.db import TaskMemoryRow, get_session

    async def _run() -> int:
        async with get_session() as session:
            return (
                await session.execute(
                    select(func.count()).select_from(TaskMemoryRow).where(TaskMemoryRow.thread_id == thread_id)
                )
            ).scalar_one()

    return asyncio.run(_run())


class TestTaskMemoryStore:
    def test_save_then_get_roundtrip(self):
        tid = _tid()
        _seed_thread(tid)
        tm = TaskMemory(tid)
        state = {"pendingSteps": [{"tool": "processRefund", "status": "waiting_approval"}], "orderId": "ORD-1"}

        asyncio.run(tm.save_task_state(state))
        assert asyncio.run(tm.get_task_state()) == state
        assert _row_count(tm.thread_id) == 1

    def test_second_save_updates_single_row(self):
        tid = _tid()
        _seed_thread(tid)
        tm = TaskMemory(tid)
        asyncio.run(tm.save_task_state({"step": 1}))
        asyncio.run(tm.save_task_state({"step": 2, "finished": True}))

        assert asyncio.run(tm.get_task_state()) == {"step": 2, "finished": True}
        assert _row_count(tm.thread_id) == 1, "复存必须走 UPDATE,严禁同线程多行"

    def test_unknown_thread_returns_none(self):
        assert asyncio.run(TaskMemory(_tid()).get_task_state()) is None
