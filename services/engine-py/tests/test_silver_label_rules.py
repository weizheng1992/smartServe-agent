"""P2 通道③复判纯函数回归(2026-09-23):pick_silver_label 的贴标签纪律
—— 恰好一条规则高置信命中才贴;多规则歧义/零命中/低置信一律 None,
严禁给歧义句硬贴(那是通道①②的领地)。"""

from __future__ import annotations

import pytest

from engine_py.triage.slot_extractor import SlotExtractor


class TestPickSilverLabel:
    def test_single_rule_high_confidence_labels(self):
        assert SlotExtractor.pick_silver_label("有什么优惠活动") == "promotion_query"
        assert SlotExtractor.pick_silver_label("加入购物车") == "cart_manage"

    def test_multi_rule_ambiguity_returns_none(self):
        """优惠+推荐同句双中曾是 21:22 误路由现场 —— 歧义句禁止硬贴。"""
        assert SlotExtractor.pick_silver_label("推荐优惠最大的商品") is None

    def test_zero_hit_returns_none(self):
        assert SlotExtractor.pick_silver_label("帮我搞一下那个东西啊") is None

    @pytest.mark.parametrize("phrase", ["有什么优惠活动", "推荐几款连衣裙", "退货政策是什么"])
    def test_known_phrases_are_deterministic(self, phrase):
        """同句复判必须确定(同输入同标签,跑两遍防抖)。"""
        first = SlotExtractor.pick_silver_label(phrase)
        second = SlotExtractor.pick_silver_label(phrase)
        assert first == second
