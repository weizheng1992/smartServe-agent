"""本地 embedding 并发推理回归 — 2026-09-05 段错误事故。

事故:本地 torch embedding(sentence-transformers)在两个线程同时 encode 时
进程级 SIGSEGV(exit 139)。触发面极广 —— 网关任意两个并发聊天请求的 triage
向量化、审批恢复 + 新聊天同跑、worker 一次对账派发多条事件,均可触雷,整个
进程连同全部 SSE 连接一起死。

修复:``llm/chat.py`` 的 ``_SerializedEmbeddings`` 以进程内 asyncio.Lock
串行化 aembed_* 推理。本用例钉死:≥2 个并发任务经统一入口 aembed 不再崩溃。

修复前本用例的表现是 pytest 进程直接被 SIGSEGV 杀死(整个套件中断),
比断言失败更"红"。

密封化(2026-09-20 CI 实证):CI 无本地权重缓存且 hf-mirror.com 不可达,
真模型用例每轮必挂 OSError。被测对象是 ``_SerializedEmbeddings`` 的串行化
语义而非模型本体 —— 桩掉底层模型(保留真实包装层),断言从「维度一致」
加强为「同一时刻至多一个在飞」。

后端迁移(2026-10-15 台账 #1):torch → fastembed/ONNX(竞态根治),本用例
随之把桩从 HuggingFaceEmbeddings 换到 fastembed.TextEmbedding —— 串行护栏
语义不变,继续作为防御纵深钉死(fastembed embed 为同步调用,经 langchain
默认 run_in_executor 进线程池,锁串行化语义同构)。
"""

from __future__ import annotations

import asyncio
import time

import numpy as np
import pytest

from engine_py.llm.chat import get_embedding_model

pytestmark = pytest.mark.asyncio


class _FakeFastembed:
    """底层模型替身:可观测并发重叠(在飞计数),定长向量。"""

    def __init__(self, **kwargs) -> None:
        self.inflight = 0
        self.max_inflight = 0

    def embed(self, texts: list[str]) -> list[np.ndarray]:
        self.inflight += 1
        self.max_inflight = max(self.max_inflight, self.inflight)
        time.sleep(0.01)
        self.inflight -= 1
        return [np.array([1.0, 0.5, 0.25]) for _ in texts]


async def test_concurrent_aembed_does_not_segfault(monkeypatch: pytest.MonkeyPatch) -> None:
    # get_embedding_model 是 lru_cache 单例:全量跑里可能已被前面的测试用真模型
    # 填充 —— 清空让本测的桩工厂真正生效;收尾再清,不留假模型给后续测试
    get_embedding_model.cache_clear()
    try:
        stub = _FakeFastembed()
        monkeypatch.setattr("fastembed.TextEmbedding", lambda **kwargs: stub)
        model = get_embedding_model()

        async def one(i: int) -> int:
            vec = await model.aembed_query(f"并发向量化任务 {i}")
            return len(vec)

        dims = await asyncio.gather(*(one(i) for i in range(3)))

        assert all(d > 0 for d in dims), f"向量化维度异常: {dims}"
        assert len(set(dims)) == 1, f"同模型并发产出维度不一致: {dims}"
        # 串行化语义硬钉:asyncio.Lock 锁内同一时刻至多一个在飞
        assert stub.max_inflight == 1, f"并发推理未被串行化: max_inflight={stub.max_inflight}"
    finally:
        get_embedding_model.cache_clear()
