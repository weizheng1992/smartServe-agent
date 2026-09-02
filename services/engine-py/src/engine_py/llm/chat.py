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

TODO(Phase 1b):移植 CircuitBreaker 熔断、指数退避重试、p-timeout 超时、
token 统计上报(TS: agentEventEmitter.addTokens)。
"""

from __future__ import annotations

import os
import threading
from functools import lru_cache

from langchain_core.embeddings import Embeddings
from langchain_openai import ChatOpenAI, OpenAIEmbeddings

from ..config import settings


@lru_cache(maxsize=1)
def get_chat_model() -> ChatOpenAI:
    return ChatOpenAI(
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
            return HuggingFaceEmbeddings(
                model_name=settings.embedding_model,
                model_kwargs={"local_files_only": True},
            )
        except Exception as cache_err:  # noqa: BLE001 — 缓存未命中回退镜像在线拉取
            print(
                f"[LLM] 本地权重缓存未命中({cache_err}),"
                f"经 {os.environ['HF_ENDPOINT']} 在线拉取 {settings.embedding_model}"
            )
            return HuggingFaceEmbeddings(model_name=settings.embedding_model)
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
        except Exception as warm_err:  # noqa: BLE001
            print(f"[LLM] embedding 预热失败,降级为请求时懒加载: {warm_err}")

    threading.Thread(target=_warm, name="embedding-warm", daemon=True).start()
