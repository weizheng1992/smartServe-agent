"""LLM 调用遥测 — TS 侧 callLLMWithRetry 的 addTokens 语义移植(Phase 1b 收尾)。

挂接于 ``get_chat_model()`` 单例的回调 handler,把每次对话模型调用的真实
usage / 延迟 / 模型名写入 ``llm_call_logs``(此前为全库零写入的死表):
- ``/api/logs`` 的 ``llm_call`` 类型据此返回每次调用的真值(不再以
  session_metrics 会话汇总拼装、token 记 0、模型名硬编码);
- ``run_agent`` 的 session_metrics ``total_tokens`` 改由本模块计数器聚合。

归因上下文:LangGraph 以 ``ainvoke(initial_state)`` 无 config 方式驱动,
thread_id 不在 run metadata 中,故用 ContextVar 携带 thread_id / business_id
(asyncio 子任务在创建时刻快照继承,画像审计等后台任务同样覆盖);
node 取 run metadata 的 ``langgraph_node``。

落盘策略:fire-and-forget(asyncio.create_task),严禁阻塞主状态机关键路径
(observability 规范);失败 print 留痕、静默降级,绝不影响宿主 LLM 调用。
Embedding 调用不落本表(本地提供方零成本;远端走 API 侧账单)。
"""

from __future__ import annotations

import asyncio
import time
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from langchain_core.callbacks import BaseCallbackHandler

from ..config import settings
from ..db import LlmCallLog, get_session

# 与 TS 基线 / run_agent 成本换算一致的统一单价($ / M tokens)
COST_PER_MTOK_USD = 0.15


@dataclass(frozen=True)
class CallContext:
    """单次 run_agent 运行内全部 LLM 调用共享的归因上下文。"""

    thread_id: str | None
    business_id: str | None


_call_context: ContextVar[CallContext | None] = ContextVar("llm_call_context", default=None)


def bind_llm_call_context(thread_id: str | None, business_id: str | None) -> None:
    """为当前任务设置调用归因上下文(run_agent 主链路、RAG 摄取等入口调用)。

    无需显式 reset:每个入口在任何 LLM 调用发生前都会重设本值,跨运行串味
    不可能发生;create_task 派生的后台任务(画像审计)在创建时刻快照继承。
    """
    _call_context.set(CallContext(thread_id=thread_id, business_id=business_id))


# ---- 落盘任务登记:run_agent 聚合前可等待写完(同进程内同源) ----
_PENDING_WRITES: dict[str, set[asyncio.Task]] = {}
_THREAD_TOKEN_TOTALS: dict[str, int] = {}


def _register_pending(thread_id: str | None, task: asyncio.Task, total_tokens: int | None) -> None:
    if thread_id is None:
        return
    bucket = _PENDING_WRITES.setdefault(thread_id, set())
    bucket.add(task)
    task.add_done_callback(bucket.discard)
    if total_tokens:
        _THREAD_TOKEN_TOTALS[thread_id] = _THREAD_TOKEN_TOTALS.get(thread_id, 0) + total_tokens


async def drain_llm_call_writes(thread_id: str) -> None:
    """等待该线程在当前进程内尚未完成的调用日志落盘(run_agent 聚合前调用)。"""
    bucket = _PENDING_WRITES.get(thread_id)
    if bucket:
        await asyncio.gather(*list(bucket), return_exceptions=True)


def take_thread_token_total(thread_id: str) -> int:
    """取走并清零本次运行累计的真实 token 总量(与落盘行同源计数)。"""
    return _THREAD_TOKEN_TOTALS.pop(thread_id, 0)


async def _persist(row: dict[str, Any]) -> None:
    try:
        async with get_session() as session:
            session.add(LlmCallLog(**row))
            await session.commit()
    except Exception as err:
        print(f"[LLM Telemetry] Failed to persist llm_call_logs row: {err}")


def _extract_usage(generation: Any) -> tuple[int | None, int | None]:
    """从 ChatGeneration 提取真实 token 计数(新版 usage_metadata 优先,老版 token_usage 兜底)。"""
    message = getattr(generation, "message", None)
    usage = getattr(message, "usage_metadata", None) or {}
    tokens_in = usage.get("input_tokens")
    tokens_out = usage.get("output_tokens")
    if tokens_in is None and tokens_out is None:
        legacy = (getattr(generation, "generation_info", None) or {}).get("token_usage") or {}
        tokens_in = legacy.get("prompt_tokens")
        tokens_out = legacy.get("completion_tokens")
    return (int(tokens_in) if tokens_in is not None else None,
            int(tokens_out) if tokens_out is not None else None)


class LlmCallTelemetryHandler(BaseCallbackHandler):
    """get_chat_model() 单例的调用捕获 handler —— llm_call_logs 的唯一写入方。"""

    def __init__(self) -> None:
        self._starts: dict[UUID, float] = {}
        self._nodes: dict[UUID, str | None] = {}

    def on_llm_start(self, serialized: dict, prompts: list[str], *, run_id: UUID, **kwargs: Any) -> None:
        self._starts[run_id] = time.monotonic()
        self._nodes[run_id] = (kwargs.get("metadata") or {}).get("langgraph_node")

    async def on_llm_end(self, response: Any, *, run_id: UUID, **kwargs: Any) -> None:
        started = self._starts.pop(run_id, None)
        node = self._nodes.pop(run_id, None)
        generations = getattr(response, "generations", None) or []
        generation = generations[0][0] if generations and generations[0] else None
        if generation is None:
            return

        tokens_in, tokens_out = _extract_usage(generation)
        message = getattr(generation, "message", None)
        model_name = (getattr(message, "response_metadata", None) or {}).get("model_name") or settings.llm_model
        latency_ms = round((time.monotonic() - started) * 1000) if started is not None else None
        has_usage = tokens_in is not None or tokens_out is not None
        total_tokens = (tokens_in or 0) + (tokens_out or 0) if has_usage else None
        # usage 缺失(提供方未回传)时 cost 记 NULL —— 真实值而非假数
        cost_usd = (total_tokens / 1_000_000) * COST_PER_MTOK_USD if total_tokens is not None else None

        ctx = _call_context.get()
        row = {
            "thread_id": ctx.thread_id if ctx else None,
            "business_id": ctx.business_id if ctx else None,
            "node": node,
            "model": model_name,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "cost_usd": cost_usd,
            "latency_ms": latency_ms,
        }
        task = asyncio.create_task(_persist(row))
        _register_pending(ctx.thread_id if ctx else None, task, total_tokens)

    def on_llm_error(self, error: BaseException, *, run_id: UUID, **kwargs: Any) -> None:
        # 失败调用无 usage 可采,只清理计时占位防泄漏
        self._starts.pop(run_id, None)
        self._nodes.pop(run_id, None)
