"""LLM / Embedding 统一入口 — 对齐 packages/engine/src/llm/callLLMWithRetry.ts。

所有 LLM 与向量调用必须走本模块(与 TS 侧「统一调用入口」规则一致)。

TODO(Phase 1b):移植 CircuitBreaker 熔断、指数退避重试、p-timeout 超时、
token 统计上报(TS: agentEventEmitter.addTokens)。
"""

from __future__ import annotations

from functools import lru_cache

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
def get_embedding_model() -> OpenAIEmbeddings:
    return OpenAIEmbeddings(
        model=settings.embedding_model,
        api_key=settings.llm_api_key,
        base_url=settings.llm_base_url,
    )
