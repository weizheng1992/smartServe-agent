"""StageContext / StageVerdict — 判定管线的共享上下文与单阶段裁决形状。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class StageContext:
    """一次 triage 的共享可变上下文。

    三组字段:
    - 不变组:process() 入口即定,全程只读(input/state/记忆快照等);
    - 惰性组:前序阶段产出、后续阶段消费(视觉解析摘要、OCR 单号、
      Embedding 锚点分数等),按需填充;
    - 累积组:proposals 仲裁留痕列表,逐层追加,终局落库快照。

    可变性是刻意选择:13 个出口/41 处 state 读取的存量下,机械搬移要求
    Stage 间共享同一份可变事实,而非每步重建。
    """

    # ── 不变组 ──
    state: dict
    thread_id: str
    input_text: str
    clean_input: str
    tenant_id: str
    history_msgs: list[dict]
    engine: type  # IntentTriageEngine(复用 handle_immediate_bypass/log_intent_to_db 等静态方法)

    # ── 惰性组(process 前段已定,后续消费)──
    damage_assessment: dict | None = None
    vision_analysis: dict | None = None
    vision_order_id: str | None = None
    input_embedding: list = field(default_factory=list)

    # ── 累积组 ──
    proposals: list[dict] = field(default_factory=list)


@dataclass
class StageVerdict:
    """单阶段裁决。

    - terminal=False:本阶段不关闭会话,note 携带中间产物供后续阶段消费;
    - terminal=True:result 即 process() 的返回值,驱动循环立即返回。

    出口组装唯一入口:此前 13 处手工调 _triage_terminal_result(参数 4-6 个,
    with_order_context/state 透传时有时无),现统一走 factory —— 各判定的
    语义差异(role 覆盖 / 单号上下文透传)显式化为参数,不再靠调用点记忆。
    """

    terminal: bool
    result: dict | None = None
    note: dict = field(default_factory=dict)

    @classmethod
    def passthrough(cls, **note: Any) -> "StageVerdict":
        return cls(terminal=False, note=note)

    @classmethod
    def terminal(cls, ctx: StageContext, intents: list[dict], **kwargs: Any) -> "StageVerdict":
        from ..intent_triage_engine import _triage_terminal_result

        result = _triage_terminal_result(
            intents,
            ctx.input_text,
            ctx.history_msgs,
            kwargs.pop("damage_assessment", ctx.damage_assessment),
            **kwargs,
        )
        return cls(terminal=True, result=result)
