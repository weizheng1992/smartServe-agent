"""skills/routing 路由深模块契约(2026-10-07 收口后,五处缝的行为在同一
interface 上各钉一组)。

此前路由知识散落五处(triage 快轨 / is_action_query 缓存闸 / fallback 自拼
正则 / step_engine 服装守卫摸私有正则),一处补词其余四处仍缺 —— 实弹
A11/c21。本册钉死:收集口后各缝行为不变 + 词表单点可测(fake 技能直喂,
不动注册中心)。
"""

from __future__ import annotations

import re

from engine_py.skills import routing
from engine_py.skills.base_skill import BaseSkill
from engine_py.skills.contract import SkillContext, SkillResult


def _skill(skill_id: str, triggers: list[str], *, category: str | None = None, keywords: list[str] | None = None):
    """最小 fake 技能:triggerIntents 精确命中 + 可选 can_handle 词面。"""

    class _S(BaseSkill):
        metadata = {
            "id": skill_id,
            "name": skill_id,
            "triggerIntents": triggers,
            **({"category": category} if category else {}),
        }

        def can_handle(self, context: SkillContext) -> bool:
            text = (context.input or "").lower()
            return any(k in text for k in (keywords or []))

        async def execute(self, context: SkillContext) -> SkillResult:
            return SkillResult(output=skill_id)

    return _S()


_GUIDE = _skill("skill_shopping_guide", ["shopping_guide"], keywords=["推荐"])
_AFTER_SALE = _skill("skill_order_refund", ["refund", "order_return"], category="after_sale", keywords=["退款"])
_CART = _skill("skill_cart_manage", ["cart_manage"], keywords=["加购", "购物车"])


class TestMatchSkill:
    def test_decided_intent_beats_keyword_fallback(self):
        """已决意图优先:「推荐优惠最大的商品」判 promotion_query 时,导购的
        「推荐」词面严禁截胡(A 实弹 2026-09-22)。"""
        promo = _skill("skill_promotion_query", ["promotion_query"], keywords=["推荐"])
        ctx = SkillContext(input="推荐优惠最大的商品", slots={"activeIntent": "promotion_query"})
        assert routing.match_skill([_GUIDE, promo], ctx) is promo

    def test_keyword_fallback_for_undecided_input(self):
        ctx = SkillContext(input="帮我加购一件外套", slots={})
        assert routing.match_skill([_GUIDE, _CART], ctx) is _CART

    def test_no_match_returns_none(self):
        assert routing.match_skill([_GUIDE, _CART], SkillContext(input="今天天气如何", slots={})) is None


class TestIsActionShaped:
    def test_action_shaped_true_and_false(self):
        assert routing.is_action_shaped([_GUIDE, _CART], "加购一件冲锋衣") is True
        assert routing.is_action_shaped([_GUIDE, _CART], "今天天气如何") is False

    def test_fail_closed_on_matcher_crash(self, monkeypatch):
        """嗅探自身炸按动作处理:宁可缓存失效,不可放行投毒。"""
        def _boom(skills, context):
            raise RuntimeError("boom")

        monkeypatch.setattr(routing, "match_skill", _boom)
        assert routing.is_action_shaped([_GUIDE], "随便什么") is True


class TestMoneyActionVeto:
    def test_money_word_vetoes_non_aftersale(self):
        assert routing.is_money_action_vetoed("退了订单X,然后推荐Y", "shopping") is True

    def test_after_sale_category_never_vetoed(self):
        assert routing.is_money_action_vetoed("退了订单X", "after_sale") is False

    def test_plain_text_never_vetoed(self):
        assert routing.is_money_action_vetoed("推荐一款背包", "shopping") is False


class TestRerouteTool:
    def test_outfit_shape_reroutes_to_guide(self):
        """搭配语义守卫:searchProducts + 搭配形态 → 导购技能(实弹「只有装备/
        只有衣服」双族缺失)。"""
        assert routing.reroute_tool("searchProducts", "去户外搭配一套衣服和装备") == "skill_shopping_guide"

    def test_plain_product_query_stays(self):
        assert routing.reroute_tool("searchProducts", "查一下极光背包的库存") == "searchProducts"

    def test_other_tools_untouched(self):
        assert routing.reroute_tool("processRefund", "搭配一套衣服") == "processRefund"


class TestRouteFallback:
    def test_promo_wording(self):
        assert routing.route_fallback("有什么优惠活动") == (True, "", False)

    def test_explicit_order_id(self):
        _promo, order_id, wants_order = routing.route_fallback("订单AURORA-ORD-2026-9081到哪了")
        assert order_id == "AURORA-ORD-2026-9081" and wants_order

    def test_order_words_need_order_literal(self):
        promo, order_id, wants_order = routing.route_fallback("查一下物流状态发货了没")
        assert promo is False and order_id == "" and wants_order is False


class TestGuidePublicRegexes:
    """服装守卫判据转公开正则(原 step_engine 伸手摸私有属性,2026-10-07 收口)——
    公开名即 routing.reroute_tool 与技能内补脚共用的单一事实源。"""

    def test_outfit_and_anchor_regexes_are_public(self):
        from engine_py.skills.guide_skills import ShoppingGuideSkill

        assert isinstance(ShoppingGuideSkill.OUTFIT_RE, re.Pattern)
        assert isinstance(ShoppingGuideSkill.CLOTHING_ANCHOR_RE, re.Pattern)
        assert ShoppingGuideSkill.OUTFIT_RE.search("搭配一套露营装备")
        assert ShoppingGuideSkill.CLOTHING_ANCHOR_RE.search("衣服")
