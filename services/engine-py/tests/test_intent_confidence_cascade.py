"""置信度级联回归(P0,2026-09-23):LLM 精判置信低于路由阈值时澄清反问,
取代静默深规划(实弹:低置信滑进 GMV 排行、按销量推荐答非所问)。

三轴:①纯谓词路由/澄清判定(动作域豁免、按意图覆盖阈值);②澄清文案
(候选意图编号选项 + 转人工指引,无候选诚实致歉);③LlmRefineStage 接线
(低置信 terminal 澄清、高置信照常出终局;classify 经 _engine_ns 模块缝打桩)。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from engine_py.triage.intent_registry import (
    INTENT_CLARIFY_LABELS,
    INTENT_CONFIDENCE_ROUTE,
    INTENT_ROUTE_THRESHOLD_OVERRIDES,
)
from engine_py.triage.intent_triage_engine import (
    build_confidence_clarify_message,
    resolve_confidence_action,
)


class TestResolveConfidenceAction:
    def test_above_threshold_routes(self):
        assert resolve_confidence_action(0.9, "shopping_guide") == "route"
        assert resolve_confidence_action(INTENT_CONFIDENCE_ROUTE, "promotion_query") == "route"

    def test_below_threshold_clarifies(self):
        assert resolve_confidence_action(0.49, "shopping_guide") == "clarify"
        assert resolve_confidence_action(0.1, "consult") == "clarify"

    def test_action_domain_intents_never_clarified(self):
        """动作域(cart/order_service)豁免:误澄清动作请求比误答资讯伤害大。"""
        assert resolve_confidence_action(0.05, "cart_manage") == "route"
        assert resolve_confidence_action(0.05, "refund") == "route"
        assert resolve_confidence_action(0.05, "order_query") == "route"
        assert resolve_confidence_action(0.05, "metric_query") == "route"

    def test_per_intent_override(self, monkeypatch):
        monkeypatch.setitem(INTENT_ROUTE_THRESHOLD_OVERRIDES, "promotion_query", 0.7)
        assert resolve_confidence_action(0.6, "promotion_query") == "clarify"
        assert resolve_confidence_action(0.7, "promotion_query") == "route"
        # 其他档位不受影响
        assert resolve_confidence_action(0.6, "shopping_guide") == "route"


class TestClarifyMessage:
    def test_lists_candidate_options_with_human_hint(self):
        parsed = [
            {"intent": "shopping_guide", "confidence": 0.4},
            {"intent": "metric_query", "confidence": 0.3},
        ]
        msg = build_confidence_clarify_message(parsed)
        assert INTENT_CLARIFY_LABELS["shopping_guide"] in msg
        assert INTENT_CLARIFY_LABELS["metric_query"] in msg
        assert "转人工" in msg

    def test_dedupes_and_caps_options(self):
        parsed = [{"intent": "shopping_guide", "confidence": 0.4}] * 6
        msg = build_confidence_clarify_message(parsed)
        assert msg.count("商品推荐/导购") == 1

    def test_generic_fallback_without_known_candidates(self):
        parsed = [{"intent": "general_query", "confidence": 0.4}]
        msg = build_confidence_clarify_message(parsed)
        assert "换个说法" in msg and "转人工" in msg


# ---------------------------------------------------------------------------
# LlmRefineStage 接线:classify 经 _engine_ns 模块缝打桩(密封,零真实 LLM/DB)
# ---------------------------------------------------------------------------

@dataclass
class _FakeNode:
    intent: str
    confidence: float
    type: str = "primary"
    entities: dict = field(default_factory=dict)
    missingSlots: list = field(default_factory=list)
    condition: Any = None


@dataclass
class _FakeStructured:
    intents: list
    isOutOfScope: bool = False
    clarificationMessage: str | None = None


class _FakeEngine:
    """handle_immediate_bypass/log_intent_to_db 打桩:捕获调用即返哨兵。

    注意:_engine_ns(ctx) 返回 ctx.engine.__module__ 的模块命名空间 ——
    FakeEngine 定义在本测试模块,故 classify 桩也必须挂在本模块全局。"""

    def __init__(self):
        self.bypass_calls: list[dict] = []
        self.log_calls: list[dict] = []

    async def handle_immediate_bypass(self, state, method, reply, intents, layer, confidence, damage=None, **kw):
        self.bypass_calls.append({"method": method, "reply": reply, "intents": intents})
        return {"bypassed": True, "output": reply}

    async def log_intent_to_db(self, thread_id, input_text, intents, method, confidence, **kw):
        self.log_calls.append({"method": method, "confidence": confidence})

    def _vision_disambig_due(self, *a, **kw):
        return False


# classify 桩挂本模块全局(_engine_ns 按 ctx.engine.__module__ 查符号)
_structured_holder: dict = {}


async def classify(*args, **kwargs):
    return _structured_holder["value"]


class _FakeNS:
    async def search_relevant_exemplars(self, *a, **kw):
        return []

    @staticmethod
    def format_exemplars_for_prompt(x):
        return ""

    async def run_consult_direct_answer(self, *a, **kw):
        return None


def _make_ctx(engine, input_text="随便说说"):
    from engine_py.triage.stages.context import StageContext

    return StageContext(
        state={"input": input_text},
        thread_id="t1",
        input_text=input_text,
        clean_input=input_text,
        tenant_id="aurora",
        history_msgs=[],
        engine=engine,
        damage_assessment=None,
        proposals=[],
    )


class TestLlmRefineCascadeWiring:
    def test_low_confidence_bypasses_to_clarification(self):
        from engine_py.triage.stages import LlmRefineStage

        _structured_holder["value"] = _FakeStructured(
            intents=[_FakeNode(intent="shopping_guide", confidence=0.4)]
        )
        engine = _FakeEngine()
        verdict = asyncio.run(LlmRefineStage.judge(_make_ctx(engine, "帮我搞一下那个东西")))
        assert verdict.terminal is True
        assert len(engine.bypass_calls) == 1, "低置信必须走澄清旁路"
        call = engine.bypass_calls[0]
        assert call["method"] == "confidence_clarify"
        assert "商品推荐/导购" in call["reply"]
        assert "转人工" in call["reply"]
        assert engine.log_calls, "澄清前必须留痕 intent_logs"

    def test_high_confidence_routes_as_before(self):
        from engine_py.triage.stages import LlmRefineStage

        _structured_holder["value"] = _FakeStructured(
            intents=[_FakeNode(intent="promotion_query", confidence=0.92)]
        )
        engine = _FakeEngine()
        verdict = asyncio.run(LlmRefineStage.judge(_make_ctx(engine, "有什么优惠活动")))
        assert verdict.terminal is True
        assert engine.bypass_calls == [], "高置信严禁澄清"
        result = verdict.result
        assert result["intents"][0]["intent"] == "promotion_query"
