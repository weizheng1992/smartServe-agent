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

韧性三件套(熔断/指数退避/超时)已由 resilience.py 承担(2026-09-07,
wayfinder 003),经 _ResilientChatOpenAI 公共 invoke/ainvoke 全覆盖注入;
token 统计上报由 telemetry.py 的 LlmCallTelemetryHandler 承担
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
from .resilience import resilient_ainvoke, resilient_invoke
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


# 「始终思考」模型的自适应开关(glm-5.3-flash 实弹,2026-09-22):AI_THINKING
# 默认 disabled 是 glm-4.7 时代的时延调优;换用拒收 disabled 的模型时,首个
# 400/1210 触发一次剥除重试并进程内记住 —— 统一 env 仍是唯一配置面,这里只
# 兜「模型与 env 组合不兼容」的迁移期,不引入第二配置源。
_THINKING_REJECTED = False


def _is_thinking_rejection(err: Exception) -> bool:
    text = str(err)
    return "1210" in text and ("思考" in text or "thinking" in text.lower())


class _ResilientChatOpenAI(ChatOpenAI):
    """usage 遥测注入 + 熔断/退避/超时韧性层 —— 覆写公共 invoke 入口,直调与组合调用全覆盖。

    构造期 callbacks 仅在该实例为顶层调用对象时生效;被 with_structured_output
    等外层 Runnable 组合后不会向子运行传播(实测 triage 的 classify 调用漏采,
    2026-09-05)。RunnableSequence 调度子步骤同样走公共 invoke/ainvoke,故在
    此统一注入 config.callbacks 是唯一全覆盖挂点。韧性层(resilience.py)挂
    同一入口:结构化调用的模型子步骤与直调获得同等的熔断拦截/退避/超时。
    """

    def invoke(self, input, config=None, **kwargs):
        # 零参 super() 不进 lambda 帧(无 __class__ cell)——须先在方法体内绑定代理
        sup = super()
        try:
            return resilient_invoke(lambda: sup.invoke(input, _inject_telemetry(config), **kwargs))
        except Exception as err:
            if _is_thinking_rejection(err) and settings.llm_thinking == "disabled":
                global _THINKING_REJECTED
                _THINKING_REJECTED = True
                print("[LLM] 模型拒收 thinking:disabled → 本次起剥除该参数(AI_THINKING 仍为 disabled)")
                return resilient_invoke(lambda: sup.invoke(input, _inject_telemetry(config), **kwargs))
            raise

    async def ainvoke(self, input, config=None, **kwargs):
        sup = super()
        try:
            return await resilient_ainvoke(lambda: sup.ainvoke(input, _inject_telemetry(config), **kwargs))
        except Exception as err:
            if _is_thinking_rejection(err) and settings.llm_thinking == "disabled":
                global _THINKING_REJECTED
                _THINKING_REJECTED = True
                print("[LLM] 模型拒收 thinking:disabled → 本次起剥除该参数(AI_THINKING 仍为 disabled)")
                return await resilient_ainvoke(lambda: sup.ainvoke(input, _inject_telemetry(config), **kwargs))
            raise

    def _get_request_payload(self, input_, *, stop=None, **kwargs):
        payload = super()._get_request_payload(input_, stop=stop, **kwargs)
        # bigmodel 兼容(实测 glm-4.7,2026-09-09;glm-4.6v 均收,vision 通路幸免):
        # - parallel_tool_calls → 任意组合 400 code 1210;
        # - stream: false 与 tools 同现 → 400 code 1210(单独出现无害);
        # - tool_choice 对象形式({"type":"function",...} 与 {"type":"auto"})
        #   → 400 code 1210;字符串 "required"/"auto" 均收 —— 改写为
        #   "required" 保住 with_structured_output 的强制调用语义(实测
        #   直接剥除时模型遇闲聊 prompt 不调工具,结构化解析即失败)。
        # with_structured_output(function_calling) 三者皆发,此前 triage
        # 分类器/商品消歧等全部结构化调用 400,被关键词兜底静默掩盖。
        payload.pop("parallel_tool_calls", None)
        # stream:false 仅与 tools 同现才 400(1210);单独出现无害,且 SDK 的
        # response_format 路径(base.py ``if "response_format" in payload:
        # payload.pop("stream")``)依赖该键存在 —— 无条件剥除令默认 method 的
        # with_structured_output 全量 KeyError('stream'),结构化调用被静默
        # 打落到 prompt 兜底(2026-09-10 修复,1b15979 的过剥回归)。
        if payload.get("stream") is False and payload.get("tools"):
            payload.pop("stream")
        if isinstance(payload.get("tool_choice"), dict):
            payload["tool_choice"] = "required"
        # 思维链关闭(2026-09-09):glm-4.7 默认开 thinking,琐碎调用也先生成大量
        # reasoning token(裸测"只回复ok" 131-239 token,同题 79.9s vs 关闭 7.5-18s),
        # 客服管线 3 次串行调用即 1-2 分钟回复。thinking 非 openai SDK 标准参数,
        # 顶层直塞 create(**payload) 即炸"unexpected keyword argument",必须经
        # extra_body 通道由 SDK 合并进请求体;setdefault 尊重调用方显式覆写。
        # AI_THINKING 是唯一配置面;「始终思考」模型拒收 disabled 时由
        # _THINKING_REJECTED 自适应剥除(见类上方注释),不新增第二配置源。
        if settings.llm_thinking == "disabled" and not _THINKING_REJECTED:
            extra_body = payload.get("extra_body") or {}
            extra_body.setdefault("thinking", {"type": "disabled"})
            payload["extra_body"] = extra_body
        return payload


@lru_cache(maxsize=1)
def get_chat_model() -> ChatOpenAI:
    return _ResilientChatOpenAI(
        model=settings.llm_model,
        api_key=settings.llm_api_key,
        base_url=settings.llm_base_url,
    )


@lru_cache(maxsize=1)
def get_vision_model() -> ChatOpenAI:
    """视觉模型工厂(wayfinder multimodal 003):独立模型名/超时,复用 AI_* 的
    base_url 与 key。刻意不走 _ResilientChatOpenAI —— vision 失败域独立,自带
    启发式兜底,不入全局熔断与逐调用遥测。"""
    return ChatOpenAI(
        model=settings.vision_model,
        api_key=settings.llm_api_key,
        base_url=settings.llm_base_url,
        temperature=0.1,
        request_timeout=settings.vision_timeout_seconds,
        max_retries=0,  # 失败即降级启发式,上游重试只会放大首响延迟
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


@lru_cache(maxsize=1)
def get_intent_classifier():
    """意图分类头缝(wayfinder 11-D1 三缝之①):返回 triage 锚点打分的可替换实现。

    默认 = AnchorIntentClassifier(现状锚点余弦打分,行为零变化);训练完成后
    (scripts/training/ 的意图头 run)在此按 AI_INTENT_CLASSIFIER 分派新 adapter,
    回滚 = 去掉环境变量。custom 档显式报 NotImplementedError —— 未注册的切换
    必须响亮失败,禁止静默落回默认(掩盖影子跑对比结果)。"""
    import os

    from ..triage.intent_classifier import AnchorIntentClassifier

    impl = os.environ.get("AI_INTENT_CLASSIFIER", "anchor").strip().lower()
    if impl in ("", "anchor", "default"):
        return AnchorIntentClassifier()
    raise NotImplementedError(f"AI_INTENT_CLASSIFIER={impl} 尚未注册(意图头 adapter 未接入;回滚请移除该环境变量)")
