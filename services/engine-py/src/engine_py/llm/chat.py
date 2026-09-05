"""LLM / Embedding 统一入口 — 对齐 packages/engine/src/llm/callLLMWithRetry.ts。

所有 LLM 与向量调用必须走本模块(与 TS 侧「统一调用入口」规则一致)。

Embedding 双提供方:
- local(默认): 进程内 sentence-transformers 本地推理,免费离线可用;
- openai: 走 AI_BASE_URL 的 /embeddings 端点(需账号资源包)。
torch 依赖较重,采用懒加载 — 未触发向量化前不 import。

local 构造策略(防事件循环冻结):
- 权重已在本地 HF 缓存时强制离线加载(local_files_only),跳过 Hub 网络检查
  —— 默认构造会同步连 huggingface.co 做 etag 检查,受限网络下 connect
  挂死且发生在事件循环线程时冻结整个网关;
- 缓存未命中才回退在线拉取,默认镜像 hf-mirror.com(HF_ENDPOINT 须在
  huggingface_hub 导入前设置才生效;用户已显式配置则不覆盖)。

TODO(Phase 1b):移植 CircuitBreaker 熔断、指数退避重试、p-timeout 超时。
token 统计上报已由 telemetry.py 的 LlmCallTelemetryHandler 承担
(2026-09-05 起,每次调用真实 usage 落盘 llm_call_logs)。
"""

from __future__ import annotations

import asyncio
import os
import threading
from functools import lru_cache
from typing import Any

from langchain_core.callbacks import BaseCallbackManager
from langchain_core.embeddings import Embeddings
from langchain_openai import ChatOpenAI, OpenAIEmbeddings

from ..config import settings
from .telemetry import LlmCallTelemetryHandler


class _SerializedEmbeddings(Embeddings):
    """本地 embedding 并发护栏(2026-09-05 段错误事故)。

    本地 torch 推理(sentence-transformers)在两个线程同时 encode 时进程级
    SIGSEGV(exit 139)——网关任意两个并发聊天请求的 triage 向量化即可触雷,
    整个进程连同全部 SSE 连接一起死。以进程内 asyncio.Lock 串行化异步推理;
    同步方法保持透传(引擎全链路仅走 aembed_*)。

    openai 提供方为网络客户端,线程安全,不经本包装。
    """

    def __init__(self, inner: Embeddings) -> None:
        self._inner = inner
        self._lock = asyncio.Lock()

    async def aembed_query(self, text: str) -> list[float]:
        async with self._lock:
            return await self._inner.aembed_query(text)

    async def aembed_documents(self, texts: list[str]) -> list[list[float]]:
        async with self._lock:
            return await self._inner.aembed_documents(texts)

    def embed_query(self, text: str) -> list[float]:
        return self._inner.embed_query(text)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._inner.embed_documents(texts)


# 进程级单例 handler:直调与组合调用共享同一份 run_id 计时占位
_TELEMETRY_HANDLER = LlmCallTelemetryHandler()


def _inject_telemetry(config: Any) -> dict:
    """把遥测 handler 并入运行配置(等价浅拷贝,不改写调用方原 config)。"""
    merged = dict(config or {})
    existing = merged.get("callbacks")
    if isinstance(existing, BaseCallbackManager):
        # 子步骤收到的是父级 CallbackManager,拷贝后追加,避免污染兄弟步骤;
        # handler 内部已全量兜错,manager 默认 raise_on_error=False 即静默降级
        mgr = existing.copy()
        mgr.add_handler(_TELEMETRY_HANDLER)
        merged["callbacks"] = mgr
    else:
        handlers = list(existing or [])
        if _TELEMETRY_HANDLER not in handlers:
            handlers.append(_TELEMETRY_HANDLER)
        merged["callbacks"] = handlers
    return merged


class _TelemetryChatOpenAI(ChatOpenAI):
    """usage 遥测注入层 —— 覆写公共 invoke 入口,直调与组合调用全覆盖。

    构造期 callbacks 仅在该实例为顶层调用对象时生效;被 with_structured_output
    等外层 Runnable 组合后不会向子运行传播(实测 triage 的 classify 调用漏采,
    2026-09-05)。RunnableSequence 调度子步骤同样走公共 invoke/ainvoke,故在
    此统一注入 config.callbacks 是唯一全覆盖挂点。
    """

    def invoke(self, input, config=None, **kwargs):
        return super().invoke(input, _inject_telemetry(config), **kwargs)

    async def ainvoke(self, input, config=None, **kwargs):
        return await super().ainvoke(input, _inject_telemetry(config), **kwargs)


@lru_cache(maxsize=1)
def get_chat_model() -> ChatOpenAI:
    return _TelemetryChatOpenAI(
        model=settings.llm_model,
        api_key=settings.llm_api_key,
        base_url=settings.llm_base_url,
    )


@lru_cache(maxsize=1)
def get_embedding_model() -> Embeddings:
    if settings.embedding_provider == "local":
        # huggingface_hub 在导入时读取 HF_ENDPOINT,须在 import 前设置;
        # 默认镜像 hf-mirror.com,用户已显式配置则不覆盖
        os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
        # 懒加载:仅在实际向量化时加载 torch 与模型权重
        from langchain_huggingface import HuggingFaceEmbeddings

        try:
            return _SerializedEmbeddings(
                HuggingFaceEmbeddings(
                    model_name=settings.embedding_model,
                    model_kwargs={"local_files_only": True},
                )
            )
        except Exception as cache_err:
            print(
                f"[LLM] 本地权重缓存未命中({cache_err}),"
                f"经 {os.environ['HF_ENDPOINT']} 在线拉取 {settings.embedding_model}"
            )
            return _SerializedEmbeddings(HuggingFaceEmbeddings(model_name=settings.embedding_model))
    return OpenAIEmbeddings(
        model=settings.embedding_model,
        api_key=settings.llm_api_key,
        base_url=settings.llm_base_url,
    )


def warm_embedding_model_in_background() -> None:
    """后台线程预热 embedding 单例(网关 / Temporal Worker 启动时调用)。

    首次构造含 torch 导入、权重加载与缓存未命中时的在线拉取(秒级到分钟级),
    放后台线程可避免首个向量化请求在事件循环线程同步承担这段耗时。
    预热失败不阻断启动,降级为请求时懒加载。
    """

    def _warm() -> None:
        try:
            get_embedding_model()
        except Exception as warm_err:
            print(f"[LLM] embedding 预热失败,降级为请求时懒加载: {warm_err}")

    threading.Thread(target=_warm, name="embedding-warm", daemon=True).start()
