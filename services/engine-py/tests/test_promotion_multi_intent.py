"""多意图候选判定测试(优惠对话接入后的复合场景;纯谓词离线可测)。

多意图不打断一期(2026-09-12):复合候选形交结构化精判与 planner 编排。
优惠词面加入后,「查订单 顺便看优惠券」这类复合问句必须走多意图候选路径,
不得被单意图规则快轨劫持。
"""

from __future__ import annotations

import pytest

from engine_py.triage.intent_triage_engine import _is_multi_intent_candidate


class TestMultiIntentWithPromotion:
    @pytest.mark.parametrize("text", [
        "查一下订单9081 顺便看看有什么优惠券",
        "我的订单发货了吗 然后推荐点优惠活动",
        "退了这单 还有优惠券吗",
    ])
    def test_compound_promotion_questions_are_candidates(self, text):
        assert _is_multi_intent_candidate(text) is True, f"复合问句应命中多意图候选: {text}"

    @pytest.mark.parametrize("text", [
        "有什么优惠活动",
        "我的优惠券有哪些",
    ])
    def test_single_promotion_question_not_candidate(self, text):
        """单一优惠询问不算复合(单意图直达技能查询)。"""
        assert _is_multi_intent_candidate(text) is False
