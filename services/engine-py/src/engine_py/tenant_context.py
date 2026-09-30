"""引擎侧租户上下文(ContextVar,A7 收口)。

gateway 进程有 ``TenantContextMiddleware`` 承载请求级租户;engine 进程(直跑
``run_agent``、脚本)此前没有任何租户上下文 —— 深层模块各自
``or "ecommerce"`` 静默兜底,显式租户断供时错绑主站且不留痕(潜伏面)。

- 入口注入:``run_agent`` 解析出真实 business_id(线程行
  自愈后)调 ``set_business_context``;asyncio 子任务与线程池自动继承拷贝,
  协程内 set 只影响本任务上下文,不跨作业泄漏。
- 深层解析:``resolve_business_id`` = 显式参数 > 上下文 > 平台默认(仅此路径
  告警留痕)。
- 读路径永不抛(不变量 #4 无异常冷启动):缺上下文只回退默认,不 raise。
"""

from __future__ import annotations

import logging
from contextvars import ContextVar, Token

logger = logging.getLogger(__name__)

PLATFORM_DEFAULT_BUSINESS_ID = "ecommerce"

_current_business_id: ContextVar[str | None] = ContextVar("engine_current_business_id", default=None)


def set_business_context(business_id: str | None) -> Token:
    """入口注入当前租户;返回 token 供嵌套调用方 ``reset_business_context``。"""
    return _current_business_id.set((business_id or "").strip() or None)


def reset_business_context(token: Token) -> None:
    """恢复注入前的值(长驻进程内嵌套段用;run_agent 每作业独立任务上下文,可省)。"""
    _current_business_id.reset(token)


def current_business_id() -> str | None:
    """当前上下文租户;未注入返回 None,兜底语义由调用方决定。"""
    return _current_business_id.get()


def resolve_business_id(explicit: str | None = None) -> str:
    """租户解析:显式参数 > 上下文 > 平台默认(仅兜底路径 warning 留痕)。"""
    candidate = (explicit or "").strip()
    if candidate:
        return candidate
    contextual = _current_business_id.get()
    if contextual:
        return contextual
    logger.warning(
        "[tenant-context] 无显式参数且无上下文,回落平台默认 %r —— 调用方应传 business_id 或在入口 set_business_context",
        PLATFORM_DEFAULT_BUSINESS_ID,
    )
    return PLATFORM_DEFAULT_BUSINESS_ID
