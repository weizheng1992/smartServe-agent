"""确定性兜底分发器(2026-09-19;「兜底什么回答什么」)。

LLM 熔断/图异常降级时,不再一律罐头道歉 —— 对词面可路由到**确定性能力**的
问题,仍给出真实答案:

- 优惠/券词面 → PromotionQuerySkill(在售活动 + 用户已领未用券);
- 显式订单号 → 该订单状态快照(含用户归属校验,非本人订单如实告知;
  2026-10-07 查询与渲染收口 order_domain.order_status_line);
- 复合句(如「查订单9081 顺便看看优惠券」)→ 分段回答両部分;
- 无确定性能力命中 → None(调用方保留原罐头,并附能力指引)。

路由判定(词面 → 意图)自 2026-10-07 收口 skills/routing.route_fallback
单一落点;本模块只剩执行。数据诚实铁律适用:只答真实查到的,查不到如实说。
"""

from __future__ import annotations

from ..tools_registry import order_domain
from . import routing
from .contract import SkillContext
from .promotion_skill import PromotionQuerySkill


async def deterministic_fallback_answer(
    question: str, thread_id: str | None, user_id: str, business_id: str = "aurora"
) -> str | None:
    """LLM 不可达时的确定性兜底:能答的真答,不能答返回 None。"""
    q = (question or "").strip()
    if not q:
        return None
    user = user_id or ""
    sections: list[str] = []

    wants_promo, order_id, wants_order = routing.route_fallback(q)

    if wants_promo:
        skill = PromotionQuerySkill()
        result = await skill.execute(
            SkillContext(thread_id=thread_id, user_id=user, tenant_id=business_id, input=q)
        )
        if result.success and result.output:
            sections.append(result.output)

    if wants_order and user:
        if not order_id:
            sections.append("📦 请提供订单号(可在「订单履约」页复制完整单号),我帮你查状态")
            return "\n\n".join(sections)
        try:
            sections.append("📦 订单状态：")
            sections.append(await order_domain.order_status_line(order_id, user))
        except Exception as err:
            sections.append(f"• 订单 {order_id}:查询失败({err})")

    if not sections:
        return None
    return "\n\n".join(sections)
