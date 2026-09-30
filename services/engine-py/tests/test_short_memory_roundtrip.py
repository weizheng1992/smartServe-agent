"""短期记忆 roundtrip 与线程租户不变量(2026-09-28 夜审补,四象限最薄一环)。

钉三件事:
1. add_message 写入 → get_messages 读回的 roundtrip(此前仅 timeline 顺序一例)。
2. 线程自愈 upsert 冲突分支**不得覆盖既有线程 business_id** —— 与 run_agent
   _ensure_thread 同一不变量:审批恢复等缺省派发路径推断出的租户(关键词
   嗅探/入口上下文)不得把既有线程静默搬家。2026-09-28 修复(ce67af9 前
   upsert 带 business_id = EXCLUDED.business_id)。
3. max_turns 截断窗口取最近 N*2 条。
"""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import text

from engine_py.memory.short_memory import ShortMemory

pytestmark = pytest.mark.usefixtures("pg_factory")

_THREAD = "thread_shortmem_roundtrip"


async def _seed_thread(business_id: str) -> None:
    from engine_py.db import get_session

    async with get_session() as s:
        await s.execute(
            text(
                'INSERT INTO threads (id, "user_id", "business_id", status, "created_at", "updated_at") '
                "VALUES (:tid, 'CUST-Roundtrip', :bid, 'active', NOW(), NOW())"
            ).bindparams(tid=_THREAD, bid=business_id)
        )
        await s.commit()


async def _thread_business_id() -> str | None:
    from engine_py.db import get_session

    async with get_session() as s:
        return (
            await s.execute(text('SELECT "business_id" FROM threads WHERE id = :t').bindparams(t=_THREAD))
        ).scalar()


async def _cleanup() -> None:
    from engine_py.db import get_session

    async with get_session() as s:
        await s.execute(text("DELETE FROM messages WHERE thread_id = :t").bindparams(t=_THREAD))
        await s.execute(text("DELETE FROM threads WHERE id = :t").bindparams(t=_THREAD))
        await s.commit()


def test_add_message_roundtrip_preserves_role_and_content() -> None:
    asyncio.run(_seed_thread("aurora"))
    try:
        mem = ShortMemory(_THREAD, 10, "aurora")
        asyncio.run(mem.add_message("assistant", "本店帐篷有三款…", [{"type": "product"}]))
        asyncio.run(mem.add_message("assistant", "第二款带防风绳。"))
        msgs = asyncio.run(mem.get_messages())
        assert [m["role"] for m in msgs][-2:] == ["assistant", "assistant"]
        assert msgs[-2]["content"] == "本店帐篷有三款…"
        assert msgs[-2]["cards"] == [{"type": "product"}]
        assert msgs[-1]["content"] == "第二款带防风绳。"
    finally:
        asyncio.run(_cleanup())


def test_thread_selfheal_never_overwrites_business_id() -> None:
    """已存在线程被另一租户推断值的 add_message 触碰后,归属不得搬家。"""
    asyncio.run(_seed_thread("aurora"))
    try:
        # 模拟审批恢复缺省派发:推断兜底嗅探出不同租户
        mem = ShortMemory(_THREAD, business_id="nike")
        asyncio.run(mem.add_message("assistant", "审批已通过,退款已执行。"))
        assert asyncio.run(_thread_business_id()) == "aurora", (
            "线程自愈 upsert 覆盖了既有 business_id —— 缺省派发路径会把线程静默搬家"
        )
        msgs = asyncio.run(mem.get_messages())
        assert any("审批已通过" in m["content"] for m in msgs), "消息本身必须照常落库"
    finally:
        asyncio.run(_cleanup())


def test_max_turns_window_keeps_most_recent() -> None:
    asyncio.run(_seed_thread("aurora"))
    try:
        mem = ShortMemory(_THREAD, 2, "aurora")
        for i in range(6):
            asyncio.run(mem.add_message("assistant", f"历史消息 {i}"))
        msgs = asyncio.run(mem.get_messages())
        contents = [m["content"] for m in msgs]
        assert len(contents) == 4, f"max_turns=2 应截取最近 4 条,实得 {len(contents)}"
        assert contents[-1] == "历史消息 5"
        assert "历史消息 1" not in contents
    finally:
        asyncio.run(_cleanup())
