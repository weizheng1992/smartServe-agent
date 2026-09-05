"""本地 embedding 并发推理回归 — 2026-09-05 段错误事故。

事故:本地 torch embedding(sentence-transformers)在两个线程同时 encode 时
进程级 SIGSEGV(exit 139)。触发面极广 —— 网关任意两个并发聊天请求的 triage
向量化、审批恢复 + 新聊天同跑、worker 一次对账派发多条事件,均可触雷,整个
进程连同全部 SSE 连接一起死。

修复:``llm/chat.py`` 的 ``_SerializedEmbeddings`` 以进程内 asyncio.Lock
串行化 aembed_* 推理。本用例钉死:≥2 个并发任务经统一入口 aembed 不再崩溃。

修复前本用例的表现是 pytest 进程直接被 SIGSEGV 杀死(整个套件中断),
比断言失败更"红"。
"""

from __future__ import annotations

import asyncio

import pytest

from engine_py.llm.chat import get_embedding_model

pytestmark = pytest.mark.asyncio


async def test_concurrent_aembed_does_not_segfault() -> None:
    model = get_embedding_model()

    async def one(i: int) -> int:
        vec = await model.aembed_query(f"并发向量化任务 {i}")
        return len(vec)

    dims = await asyncio.gather(*(one(i) for i in range(3)))

    assert all(d > 0 for d in dims), f"向量化维度异常: {dims}"
    assert len(set(dims)) == 1, f"同模型并发产出维度不一致: {dims}"
