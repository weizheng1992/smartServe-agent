"""Triage 判定管线 — Stage 序列(admin-readiness 架构审视候选①/③)。

历史:process() 曾是 998 行单函数,判定 1/1.4/1.5/1.6/2/3 四代演进全部内联,
13 个终局出口各自手工组装。本包把每个语义阶段提升为独立 Stage 模块——
**行为逐字保持的机械搬移**,判定逻辑/词表/文案一律不动。

结构契约:
- `StageContext`:一次 triage 的共享可变上下文(不变组 + 惰性组 + 累积组)。
- `StageVerdict`:单阶段裁决 —— `terminal=True` 携带终局 result(process 立即
  返回),否则 `note` 携带供后续阶段消费的中间产物。
- 每个 Stage 一个模块,暴露 `async def judge(ctx) -> StageVerdict`;
  下方 *Stage 包装类仅为驱动循环提供统一形态。
- `STAGES` 列表即判定顺序(架构事实显式化)。

词表与判定逻辑的单一事实源收口(intent_registry 归一)是后续独立工单,本包
搬移阶段不合并、不改写任何判定表达式。
"""

from __future__ import annotations

from . import confirmation_resume, duplicate_intercept, system_resume
from .context import StageContext, StageVerdict


class _Stage:
    """裸函数模块 → 统一 `.judge` 类形态的薄适配(无状态)。

    Stage.judge(ctx) 类方法直接委托模块级 judge 函数 —— 调用方无感知。
    """

    module: object

    @classmethod
    async def judge(cls, ctx: "StageContext") -> "StageVerdict":
        return await cls.module.judge(ctx)


class ConfirmationResumeStage(_Stage):
    module = confirmation_resume


class SystemResumeStage(_Stage):
    module = system_resume


class DuplicateInterceptStage(_Stage):
    module = duplicate_intercept


__all__ = [
    "StageContext",
    "StageVerdict",
    "ConfirmationResumeStage",
    "SystemResumeStage",
    "DuplicateInterceptStage",
]
