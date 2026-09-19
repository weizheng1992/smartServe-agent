"""确定性兜底分发器(2026-09-19;「兜底什么回答什么」)。

LLM 熔断/图异常降级时,不再一律罐头道歉 —— 对词面可路由到**确定性能力**的
问题,仍给出真实答案:

- 优惠/券词面(PROMOTION_KEYWORDS_RE,单一事实源)→ PromotionQuerySkill
  (在售活动 + 用户已领未用券);
- 显式订单号(EXPLICIT_ORDER_ID_RE)→ 该订单状态快照(含用户归属校验,
  非本人订单如实告知);
- 复合句(如「查订单9081 顺便看看优惠券」)→ 分段回答両部分;
- 无确定性能力命中 → None(调用方保留原罐头,并附能力指引)。

数据诚实铁律适用:只答真实查到的,查不到如实说。
"""

from __future__ import annotations

import re

from sqlalchemy import text

from ..tools_registry import order_domain
from ..triage.intent_registry import (
    EXPLICIT_ORDER_ID_RE,
    PROMOTION_KEYWORDS_RE,
)
from .promotion_skill import PromotionQuerySkill

_ORDER_QUERY_HINT = re.compile(r"查|物流|到哪|状态|发货", re.IGNORECASE)


async def _order_section(conn, order_id: str, user_id: str) -> str:
    row = (
        await conn.execute(
            text(
                "SELECT status, total_amount, shipping_address FROM merchant_orders "
                "WHERE order_id = :o AND customer_id = :u LIMIT 1"
            ).bindparams(o=order_id, u=user_id)
        )
    ).mappings().first()
    if not row:
        return f"• 订单 {order_id}:未找到(或不在你的名下)"
    status_map = {"PAID": "待发货", "SHIPPED": "运输中", "DELIVERED": "已签收", "REFUNDED": "已退款", "CANCELLED": "已取消"}
    status = status_map.get(row["status"], row["status"])
    addr = row["shipping_address"] if isinstance(row["shipping_address"], dict) else {}
    full_addr = addr.get("fullAddress") or ""
    return (
        f"• 订单 {order_id}:{status} · ¥{float(row['total_amount']):.2f}"
        + (f" · 收货:{full_addr}" if full_addr else "")
    )


async def deterministic_fallback_answer(
    question: str, thread_id: str | None, user_id: str, business_id: str = "aurora"
) -> str | None:
    """LLM 不可达时的确定性兜底:能答的真答,不能答返回 None。"""
    q = (question or "").strip()
    if not q:
        return None
    user = user_id or ""
    sections: list[str] = []

    wants_promo = bool(PROMOTION_KEYWORDS_RE.search(q))
    order_hit = EXPLICIT_ORDER_ID_RE.search(q)
    wants_order = bool(order_hit) or (_ORDER_QUERY_HINT.search(q) and "订单" in q)

    async with order_domain._merchant_reader_engine().connect() as conn:
        if wants_promo:
            skill = PromotionQuerySkill()
            from .contract import SkillContext

            result = await skill.execute(
                SkillContext(thread_id=thread_id, user_id=user, tenant_id=business_id, input=q)
            )
            if result.success and result.output:
                sections.append(result.output)

        if wants_order and user:
            order_id = order_hit.group(0) if order_hit else ""
            if not order_id:
                sections.append("📦 请提供订单号(可在「订单履约」页复制完整单号),我帮你查状态")
                return "\n\n".join(sections)
            try:
                sections.append("📦 订单状态：")
                sections.append(await _order_section(conn, order_id, user))
            except Exception as err:
                sections.append(f"• 订单 {order_id}:查询失败({err})")

    if not sections:
        return None
    return "\n\n".join(sections)
