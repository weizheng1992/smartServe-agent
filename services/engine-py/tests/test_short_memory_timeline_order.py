"""短期记忆时序回归 — TEXT 列 timestamp 混写两格式,答在问上(2026-09-25)。

实弹:网关写 naive 本地墙钟(UTC+8 宿主机)、引擎写 UTC 带偏移,两格式在
TEXT 列上字符串比较无意义 —— 「给一个表格显示」的分类器历史窗口因此错乱,
窗口里捡到真实单号,纯排版续聊被误路由成订单详情。本套钉死:get_messages
排序锚必须是 DB server_default now() 落库的 created_at(两写入方同钟),
TEXT 列 timestamp 只留展示用途。种子按生产双写入方格式逐字复刻。
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
from sqlalchemy import text

from engine_py.memory.short_memory import ShortMemory

pytestmark = pytest.mark.usefixtures("pg_factory")

_THREAD = "thread_shortmem_timeline_regression"

# (role, content, TEXT 列 timestamp)—— 按 conversation_repo.append_message(网关,
# naive 本地)与 short_memory.add_message(引擎,UTC 带偏移)的真实产出复刻;
# assistant 行字符串排序反而更小(09 < 17),旧行为必然答在问上。
_SEED = [
    ("user", "几个帐篷的特点和价格对比", "2026-09-25T17:58:20.852797"),
    ("assistant", "尊敬的顾客，您好！店内帐篷信息如下…", "2026-09-25T09:58:57.144000+00:00"),
    ("user", "给一个表格显示", "2026-09-25T17:58:40.100000"),
]


async def _seed() -> None:
    from engine_py.db import get_session

    async with get_session() as s:
        await s.execute(
            text(
                'INSERT INTO threads (id, "user_id", "business_id", status, "created_at", "updated_at") '
                "VALUES (:tid, 'CUST-Timeline', 'aurora', 'active', NOW(), NOW())"
            ).bindparams(tid=_THREAD)
        )
        for role, content, ts in _SEED:
            await s.execute(
                text(
                    "INSERT INTO messages (id, thread_id, business_id, role, content, timestamp) "
                    "VALUES (:mid, :tid, 'aurora', :role, :content, :ts)"
                ).bindparams(mid=str(uuid.uuid4()), tid=_THREAD, role=role, content=content, ts=ts)
            )
            # 逐行提交:生产两写入方(网关逐 HTTP 调用、引擎逐 add_message)各持
            # 独立事务,created_at=事务起点 now() 逐行不同;同事务播种会让三行
            # created_at 坍缩到同一时刻,失真于被测不变量
            await s.commit()
        n = (
            await s.execute(text("SELECT COUNT(*) FROM messages WHERE thread_id = :t").bindparams(t=_THREAD))
        ).scalar()
        assert n == len(_SEED), f"种子断言失败: 期望 {len(_SEED)} 行,实落 {n} 行"


async def _cleanup() -> None:
    from engine_py.db import get_session

    async with get_session() as s:
        await s.execute(text("DELETE FROM messages WHERE thread_id = :t").bindparams(t=_THREAD))
        await s.execute(text("DELETE FROM threads WHERE id = :t").bindparams(t=_THREAD))
        await s.commit()


def test_get_messages_keeps_question_before_answer() -> None:
    asyncio.run(_seed())
    try:
        msgs = asyncio.run(ShortMemory(_THREAD, 10, "aurora").get_messages())
        contents = [m["content"] for m in msgs]
        assert contents == [c for _, c, _ in _SEED], (
            "会话时序错乱:TEXT 列 timestamp 混格式排序不得再作排序锚(答在问上即本 bug)"
        )
    finally:
        asyncio.run(_cleanup())
