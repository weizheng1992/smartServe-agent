"""技能层类型化契约 — SkillContext / SkillResult 是技能与调用方之间的唯一接口。

背景(2026-09-15 架构深化②):此前技能进出是一袋字符串键 dict,契约被
8 个文件手工拆包,guide/cart/order 三键的 state↔契约键翻译在 4 处各写一遍;
「本轮加购行(addedThisTurn)」一个概念要穿五层口头约定才能活下来,其中
一层还是断的(与 2026-09-12 幻影 Nike 同根因的死写)。类型化后:

- 两个调用方(triage 快轨、step 执行引擎)是两个真实适配器,各自在边缘
  翻译一次;线上 dict 契约(SSE/TaskMemory,驼形)在适配器边界逐字节不变,
  形状由 tests/test_skill_contract_golden.py 黄金快照钉死;
- 领域上下文(导购候选/购物车/订单)是字段不是键名约定 —— 下一个
  「上下文在哪层丢了」的诊断,答案只可能在两个适配器里。

技能实现消费 SkillContext、返回 SkillResult;tests 直接构造类型,
不再手拼 dict。"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class SkillContext:
    """技能调用环境:调用方装配一次,技能只读。"""

    thread_id: str | None = None
    user_id: str | None = None
    tenant_id: str = "ecommerce"
    input: str = ""
    slots: dict = field(default_factory=dict)
    image_urls: list[str] | None = None
    # 领域上下文总线(上一轮/同轮前序技能写入,调用方负责跨轮持久化)
    guide_context: dict = field(default_factory=dict)
    cart_context: dict = field(default_factory=dict)
    order_context: dict | None = None
    damage_assessment: dict | None = None
    is_approved: bool = False
    short_memory: list[dict] = field(default_factory=list)
    # 未建模的调用方附加物(准入要克制:新概念应立字段而非塞这里)
    extra: dict = field(default_factory=dict)


@dataclass
class SkillResult:
    """技能履约结果;to_dict() 是冻结的线上契约形状(黄金快照钉死)。"""

    output: str = ""
    success: bool = True
    next_action: str = "finish"
    skill_id: str | None = None
    error: str | None = None
    cards: list | None = None
    # 挂起计划随结果带回(HITL):run_agent 回合收口用 result.task_plan
    # 覆盖 TaskMemory,审批 resume 由此恢复
    task_plan: dict | None = None
    approval_payload: dict | None = None
    # 领域上下文写回;None = 本轮未刷新(调用方保持原值)
    guide_context: dict | None = None
    cart_context: dict | None = None
    order_context: dict | None = None

    def to_dict(self) -> dict:
        """线上契约形状。缺席键与 None 语义一致(get 安全);extra 仅在
        任一领域上下文存在时出现 —— 与历史返回 dict 逐键兼容。"""
        d: dict = {
            "success": self.success,
            "output": self.output,
            "nextAction": self.next_action,
        }
        if self.skill_id is not None:
            d["skillId"] = self.skill_id
        if self.error is not None:
            d["error"] = self.error
        if self.cards is not None:
            d["cards"] = self.cards
        if self.task_plan is not None:
            d["taskPlan"] = self.task_plan
        if self.approval_payload is not None:
            d["approvalPayload"] = self.approval_payload
        extra: dict = {}
        if self.guide_context is not None:
            extra["guideContext"] = self.guide_context
        if self.cart_context is not None:
            extra["cartContext"] = self.cart_context
        if self.order_context is not None:
            extra["orderContext"] = self.order_context
        if extra:
            d["extra"] = extra
        return d
