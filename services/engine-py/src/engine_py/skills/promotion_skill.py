"""优惠活动/优惠券查询技能(20 号;商城用户新权益接入客服对话)。

triggerIntents: promotion_query / coupon_query(意图注册表新增;general_query
暂不触发,优惠券使用说明走 RAG 直答)。执行面:商户库真实查询(在售活动 +
当前用户已领未用券),输出自动抵扣说明 —— 数据诚实铁律适用(无活动/无券
诚实空,不编造)。
"""

from __future__ import annotations

from sqlalchemy import text

from ..tools_registry import order_domain
from .base_skill import BaseSkill
from .contract import SkillContext, SkillResult


def _promo_rule_line(p: dict) -> str:
    ptype = p["promo_type"]
    value = float(p["discount_value"])
    if ptype == "full_reduction":
        return f"满 ¥{float(p['threshold_amount'] or 0):.0f} 减 ¥{value:.0f}"
    if ptype == "discount":
        return f"{value / 10:g} 折"
    return f"¥{value:.0f} 券"


class PromotionQuerySkill(BaseSkill):
    metadata = {
        "id": "skill_promotion_query",
        "name": "优惠活动与优惠券查询 SOP",
        "description": "查询在售优惠活动(满减/折扣/券)与当前用户已领未用券;只读",
        "category": "pre_sale",
        "triggerIntents": ["promotion_query", "coupon_query"],
        "requiredTools": [],
        "version": "1.0.0",
    }

    async def execute(self, context: SkillContext) -> SkillResult:
        ctx = await order_domain.OrderDomainService.get_thread_session_context(context.thread_id)
        user_id = context.user_id or ctx.get("userId") or ""

        try:
            # 运行时读模块属性(测试替换 reader 工厂才能生效)
            async with order_domain._merchant_reader_engine().connect() as conn:
                promos = (
                    await conn.execute(
                        text(
                            "SELECT name, promo_type, threshold_amount, discount_value FROM promotions "
                            "WHERE status = 'active' AND (end_at IS NULL OR end_at > NOW()) "
                            "ORDER BY created_at DESC LIMIT 10"
                        )
                    )
                ).mappings().all()
                my_coupons = (
                    await conn.execute(
                        text(
                            "SELECT p.name, p.discount_value FROM user_coupons uc "
                            "JOIN promotions p ON p.id = uc.promotion_id "
                            "WHERE uc.user_id = :u AND uc.status = 'claimed' AND p.promo_type = 'coupon' "
                            "ORDER BY uc.claimed_at DESC"
                        ).bindparams(u=user_id)
                    )
                ).mappings().all()
        except Exception as err:
            return SkillResult(success=True, output=f"优惠数据暂时查询不到({err})", next_action="finish")

        lines = []
        if promos:
            lines.append("🎁 在售优惠活动：")
            for p in promos:
                lines.append(f"• {p['name']}（{_promo_rule_line(p)}）")
        else:
            lines.append("当前没有进行中的优惠活动。")
        if my_coupons:
            lines.append("")
            lines.append("🎫 我的优惠券（下单自动抵扣）：")
            for cpn in my_coupons:
                lines.append(f"• ¥{float(cpn['discount_value']):.0f} 券 · {cpn['name']}")
        lines.append("")
        lines.append("下单时系统会自动应用最优优惠，无需手动操作。")
        return SkillResult(success=True, output="\n".join(lines), next_action="finish")
