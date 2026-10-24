"""情景记忆三因子打分册(2026-10-24 SOTA 对齐 P0-1,docs/memory-sota-upgrade.md)。

钉面:检索分 = max(余弦,关键词) × 时近性(30 天常数) × 重要性 —— importance
字段此前落库但检索完全不用;乘法降级不灭失(90 天旧事件仍可凭高相关过阈)。
向量全桩同形(余弦恒 1),排序差异完全由 recency/importance 驱动 —— 测试
隔离地钉住两个新因子。
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
from sqlalchemy import text

from engine_py.db import get_session
from engine_py.memory import episodic_memory as ep_module
from engine_py.memory.episodic_memory import EpisodicMemory

pytestmark = pytest.mark.usefixtures("pg_factory")


@pytest.fixture(autouse=True)
def _fake_embedding(monkeypatch):
    """全事件同向量:余弦恒 1,排序差异完全由 recency×importance 驱动。"""

    class _StubEmbed:
        async def aembed_query(self, _text: str) -> list[float]:
            return [1.0, 0.0]

    monkeypatch.setattr(ep_module, "get_embedding_model", lambda: _StubEmbed())


def _age_event(user: str, content: str, days: int) -> None:
    async def run():
        async with get_session() as session:
            await session.execute(
                text(
                    "UPDATE episodic_events SET timestamp = NOW() - CAST(:d || ' days' AS interval) "
                    "WHERE user_id = :u AND content = :c"
                ).bindparams(d=str(days), u=user, c=content)
            )
            await session.commit()

    asyncio.run(run())


def _add(mem: EpisodicMemory, content: str, importance: int) -> None:
    asyncio.run(mem.add_event(content, importance))


def _recall(mem: EpisodicMemory) -> list[str]:
    return [e["event"] for e in asyncio.run(mem.retrieve_events("退款"))]


def test_recency_and_importance_reorder_events():
    user = f"eps_{uuid.uuid4().hex[:8]}"
    mem = EpisodicMemory(user, "aurora")
    _add(mem, "退款事件A(importance9)", 9)
    _add(mem, "退款事件B(importance3)", 3)
    _age_event(user, "退款事件B(importance3)", 90)  # 旧且不重要 → 沉底

    recalled = _recall(mem)
    assert recalled[0] == "退款事件A(importance9)"
    # 乘法降级不灭失:90 天 × 低重要性 ≈ 0.74 > 0.55 阈值,仍可召回
    assert len(recalled) == 2


def test_freshness_alone_reorders_equal_importance():
    user = f"eps_{uuid.uuid4().hex[:8]}"
    mem = EpisodicMemory(user, "aurora")
    _add(mem, "退款事件旧", 5)
    _add(mem, "退款事件新", 5)
    _age_event(user, "退款事件旧", 90)

    assert _recall(mem)[0] == "退款事件新"


def test_importance_alone_reorders_equal_age():
    user = f"eps_{uuid.uuid4().hex[:8]}"
    mem = EpisodicMemory(user, "aurora")
    _add(mem, "退款事件低权", 3)
    _add(mem, "退款事件高权", 9)

    assert _recall(mem)[0] == "退款事件高权"


def test_importance_zero_not_falsy_swallowed():
    """importance=0 是合法分值:`or 3` 会吞成 3 反而提权(code-review 2026-10-24)。"""
    user = f"eps_{uuid.uuid4().hex[:8]}"
    mem = EpisodicMemory(user, "aurora")
    _add(mem, "退款事件零权", 0)
    _add(mem, "退款事件低权", 3)
    # 同时间戳下 importance=0 应排最后(0.8 档 vs 3 的 0.867 档)
    recalled = _recall(mem)
    assert recalled[-1] == "退款事件零权"
