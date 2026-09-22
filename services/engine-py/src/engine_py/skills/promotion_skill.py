"""优惠活动/优惠券查询技能(20 号;商城用户新权益接入客服对话)。

triggerIntents: promotion_query / coupon_query(意图注册表新增;general_query
暂不触发,优惠券使用说明走 RAG 直答)。执行面:商户库真实查询(在售活动 +
当前用户已领未用券),输出自动抵扣说明 —— 数据诚实铁律适用(无活动/无券
诚实空,不编造)。
"""

from __future__ import annotations

import re
from datetime import UTC

from sqlalchemy import text

from ..tools_registry import order_domain
from .base_skill import BaseSkill
from .contract import SkillContext, SkillResult


def _fmt_local(value) -> str:
    """naive 时间按 UTC 补时区后转本地(与订单接口 _iso 同纪律:库内 TIMESTAMP
    无时区且 TimeZone=UTC,直接 strftime 会比本地早 8 小时)。"""
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone().strftime("%Y-%m-%d %H:%M")

# 券向问法分流(2026-09-22 实弹):「我的优惠券」「我使用过的优惠券」此前与
# 活动查询共用同一模板 —— 券包被活动列表淹没,已核销券完全不出现。命中券向
# 时改为聚焦券包应答;正则收窄避免「怎么使用优惠券」「优惠券可以用吗」这类
# 活动咨询误入核销查询,「核销规则」这类规则咨询也不入(核销须带 已/经/被
# 前缀或 过/的/记录/了 后缀)。
_USED_COUPON_RE = re.compile(
    r"(使用过|已使用|用过|用掉)[^。]{0,6}券"
    r"|券[^。]{0,6}(使用过|已使用|用过|已核销)"
    r"|((已|经|被)核销|核销(过|的|记录|了))"
)
_MY_COUPON_RE = re.compile(r"(我的|我领|已领|领到|名下)[^。]{0,6}券|券包")
# 优惠荐品问法(2026-09-22 实弹):「推荐优惠最大的商品」曾被导购域按销量
# 推荐答非所问 —— 命中荐品问法时按在售商品的立减额排序荐品
_RECOMMEND_RE = re.compile(r"(推荐|哪款|哪个|什么商品|值得买|力度最大|优惠最大|最划算|便宜)")


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
        "version": "1.1.0",
    }

    async def execute(self, context: SkillContext) -> SkillResult:
        ctx = await order_domain.OrderDomainService.get_thread_session_context(context.thread_id)
        user_id = context.user_id or ctx.get("userId") or ""

        question = context.input or ""
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
                # 全量带 status(claimed+used):核销态必须可答(2026-09-22 券向问法)
                my_coupons = (
                    await conn.execute(
                        text(
                            "SELECT p.name, p.discount_value, uc.status, uc.used_order_id, uc.used_at "
                            "FROM user_coupons uc "
                            "JOIN promotions p ON p.id = uc.promotion_id "
                            "WHERE uc.user_id = :u AND p.promo_type = 'coupon' "
                            "ORDER BY uc.status ASC, uc.claimed_at DESC"
                        ).bindparams(u=user_id)
                    )
                ).mappings().all()
                # 优惠荐品(2026-09-22):荐品问法按在售商品立减额排序
                recommendation = None
                if _RECOMMEND_RE.search(question):
                    recommendation = await self._render_deal_recommendation(conn)
        except Exception as err:
            return SkillResult(success=True, output=f"优惠数据暂时查询不到({err})", next_action="finish")

        if recommendation is not None:
            return SkillResult(success=True, output=recommendation, next_action="finish")

        used_only = bool(_USED_COUPON_RE.search(question))
        coupon_centric = used_only or bool(_MY_COUPON_RE.search(question))
        claimed = [c for c in my_coupons if c["status"] == "claimed"]
        used = [c for c in my_coupons if c["status"] != "claimed"]

        if coupon_centric:
            return SkillResult(
                success=True,
                output=self._render_coupon_wallet(claimed, used, used_only=used_only),
                next_action="finish",
            )

        lines = []
        if promos:
            lines.append("🎁 在售优惠活动：")
            for p in promos:
                lines.append(f"• {p['name']}（{_promo_rule_line(p)}）")
        else:
            lines.append("当前没有进行中的优惠活动。")
        if claimed:
            lines.append("")
            lines.append("🎫 我的优惠券（下单自动抵扣）：")
            for cpn in claimed:
                lines.append(f"• ¥{float(cpn['discount_value']):.0f} 券 · {cpn['name']}")
        lines.append("")
        lines.append("下单时系统会自动应用最优优惠，无需手动操作。")
        return SkillResult(success=True, output="\n".join(lines), next_action="finish")

    def _render_coupon_wallet(self, claimed: list, used: list, used_only: bool) -> str:
        """券向应答:核销查询只回已用券;券包查询可用+已用分段,诚实空。"""

        def _used_note(cpn: dict) -> str:
            if cpn["used_at"]:
                when = _fmt_local(cpn["used_at"])
                order = f"订单 {cpn['used_order_id']}" if cpn["used_order_id"] else ""
                return f"已使用（{when}{' · ' if order else ''}{order}）"
            return "已使用"

        lines = []
        if used_only:
            if used:
                lines.append("🎫 我使用过的优惠券：")
                for cpn in used:
                    lines.append(f"• ¥{float(cpn['discount_value']):.0f} 券 · {cpn['name']} {_used_note(cpn)}")
            else:
                lines.append("您还没有使用过优惠券。领券后在购物车结算时可自选抵扣。")
            lines.append("")
            lines.append("活动优惠与优惠券可叠加：活动先减，优惠券按活动后余额抵扣。")
            return "\n".join(lines)

        if claimed or used:
            lines.append("🎫 我的优惠券：")
            for cpn in claimed:
                lines.append(f"• ¥{float(cpn['discount_value']):.0f} 券 · {cpn['name']}（可用，购物车结算时可自选）")
            for cpn in used:
                lines.append(f"• ¥{float(cpn['discount_value']):.0f} 券 · {cpn['name']} {_used_note(cpn)}")
        else:
            lines.append("您还没有领取过优惠券，可在商品页领券后到购物车结算时使用。")
        lines.append("")
        lines.append("活动优惠与优惠券可叠加：活动先减，优惠券按活动后余额抵扣。")
        return "\n".join(lines)

    async def _render_deal_recommendation(self, conn) -> str:
        """优惠荐品(2026-09-22):在售商品逐一取最优商品活动(排除券型,
        券是用户资产不属商品让利),按立减额降序 Top 3;无优惠诚实空。"""
        from ..analytics.promotion_engine import best_for_amount

        products = (
            await conn.execute(
                text(
                    "SELECT p.spu_code, p.title, MIN(s.price) AS price "
                    "FROM merchant_spus p JOIN merchant_skus s ON s.spu_id = p.id "
                    "WHERE p.status = 'ON_SALE' AND s.price IS NOT NULL "
                    "GROUP BY p.spu_code, p.title"
                )
            )
        ).mappings().all()
        deals = []
        for row in products:
            price = float(row["price"])
            best = await best_for_amount(conn, price, {str(row["spu_code"])}, exclude_coupon=True)
            if best and best["discount"] > 0:
                deals.append(
                    {
                        "title": row["title"],
                        "price": price,
                        "discount": best["discount"],
                        "name": best["name"],
                        "promo_price": round(price - best["discount"], 2),
                    }
                )
        if not deals:
            return "当前没有进行中的商品优惠，暂时没有优惠推荐。"
        deals.sort(key=lambda d: d["discount"], reverse=True)
        lines = ["🎁 优惠力度最大的商品："]
        for d in deals[:3]:
            lines.append(
                f"• {d['title']} ¥{d['price']:.0f} → ¥{d['promo_price']:.0f}"
                f"（{d['name']}，立减 ¥{d['discount']:.0f}）"
            )
        lines.append("")
        lines.append("领券后可与活动叠加：活动先减，优惠券按余额抵扣。")
        return "\n".join(lines)
