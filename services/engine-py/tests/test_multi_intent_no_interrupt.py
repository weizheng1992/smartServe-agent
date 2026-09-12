"""多意图不打断一期(2026-09-12 spec: .scratch/multi-intent-no-interrupt/spec.md)。

11 探针实弹矩阵(.scratch/address-order-bug/matrix_results.json)钉死三类失败:
①secondary 缺槽反问劫持全场(A1/A3:「建地址+下单」被一句「请提供订单号」
整轮打断);②资金动作被导购快轨静默吞(A6:「退了订单9081,然后推荐跑步鞋」
整句进了导购技能,退款连被考虑的机会都没有);③裸数字单号正则把手机号当
订单号。本套按缝钉死:缺槽短路收窄(规则层+结构化层同口径)、资金动作一票
否决、手机号防污染。
"""

from __future__ import annotations

import asyncio

import pytest

from engine_py.triage import intent_triage_engine as triage_mod
from engine_py.triage.intent_triage_engine import (
    MULTI_INTENT_CANDIDATE_RE,
    IntentTriageEngine,
    _is_multi_intent_candidate,
    _should_clarify_first,
)
from engine_py.triage.semantic_cache import SemanticVectorCache
from engine_py.triage.slot_extractor import ORDER_ID_RE, extract_order_id
from engine_py.triage.structured_classifier import IntentNode, StructuredTriageOutput

# ── ①手机号防污染:裸数字单号分支排除手机形态 ──────────────────────────────


class TestOrderIdPhoneExclusion:
    def test_phone_number_is_not_order_id(self):
        assert extract_order_id("收件人张伟 手机13800138000 北京市海淀区") is None
        assert ORDER_ID_RE.search("13800138000") is None

    def test_non_phone_bare_digits_still_extracted(self):
        """宽松裸数字通道的既有语义保留:非手机形态的 8+ 位数字仍认单号。"""
        assert extract_order_id("订单 12345678") == "12345678"

    def test_prefixed_ids_unaffected(self):
        assert extract_order_id("ORD-12345 到哪了") == "ORD-12345"
        assert extract_order_id("AURORA-ORD-2026-9083 的物流") == "AURORA-ORD-2026-9083"


# ── ②资金动作一票否决导购/购物车快轨 ───────────────────────────────────────


class TestMoneyActionVeto:
    def test_veto_regex_hits_money_actions(self):
        from engine_py.triage.intent_triage_engine import MONEY_ACTION_VETO_RE, _money_action_vetoed

        for text in (
            "退了订单AURORA-ORD-2026-9083，然后推荐几款跑步鞋",
            "我想退款",
            "这个我要退货",
            "退还押金",
            "帮我换货",
            "申请售后",
            "把9081退掉",
        ):
            assert MONEY_ACTION_VETO_RE.search(text), text
            assert _money_action_vetoed(text), text

    def test_veto_regex_spells_without_money_actions(self):
        from engine_py.triage.intent_triage_engine import MONEY_ACTION_VETO_RE, _money_action_vetoed

        for text in (
            "推荐几款跑步鞋",
            "推荐不容易掉色的卫衣",
            "看看有什么背包",
            "加入购物车",
            None,
        ):
            assert not MONEY_ACTION_VETO_RE.search(text or ""), text
            assert not _money_action_vetoed(text), text

    def _run_fast_track(self, monkeypatch: pytest.MonkeyPatch, input_text: str, skill_category: str):
        """桩 SkillRegistry(函数内延迟导入,须打真身)返回指定类目的假技能。"""

        class _FakeSkill:
            metadata = {"id": "skill_fake", "category": skill_category}

            async def execute(self, context: dict) -> dict:
                return {"success": True, "nextAction": "finish", "output": "假技能回复"}

        from engine_py.skills import SkillRegistry

        monkeypatch.setattr(
            SkillRegistry, "find_matching_skill", classmethod(lambda cls, ctx: _FakeSkill())
        )

        async def _fake_log(*args, **kwargs):
            return None

        monkeypatch.setattr(IntentTriageEngine, "log_intent_to_db", _fake_log)

        class _FakeTaskMemory:
            def __init__(self, thread_id: str) -> None:
                pass

            async def save_task_state(self, state: dict) -> None:
                return None

        monkeypatch.setattr(triage_mod, "TaskMemory", _FakeTaskMemory)

        state = {"thread_id": "t_veto", "input": input_text}
        task_spec = {"intentType": "shopping_guide", "confidence": 0.95, "slots": {}}
        return asyncio.run(
            IntentTriageEngine._try_skill_fast_track(
                state, "t_veto", "ecommerce", task_spec, [], None,
                [{"intent": "shopping_guide", "confidence": 0.95}], [],
            )
        )

    def test_guide_skill_vetoed_when_money_action_present(self, monkeypatch):
        """「退了订单…然后推荐」:导购技能(pre_sale)不得劫持整轮 → 返回 None
        落回 embedding 锚点/结构化精判(资金动作被正视)。"""
        result = self._run_fast_track(
            monkeypatch, "退了订单AURORA-ORD-2026-9083，然后推荐几款跑步鞋", "pre_sale"
        )
        assert result is None

    def test_guide_skill_still_runs_for_pure_shopping(self, monkeypatch):
        """纯导购输入(无资金动作词)不受伤:快轨照常直达闭环。"""
        result = self._run_fast_track(monkeypatch, "推荐几款跑步鞋", "pre_sale")
        assert result is not None
        assert "假技能回复" in (result.get("output") or "")

    def test_after_sale_skill_never_vetoed(self, monkeypatch):
        """售后域技能(category=after_sale)与资金动作同族,永不否决。"""
        result = self._run_fast_track(monkeypatch, "我想退款", "after_sale")
        assert result is not None


# ── ③缺槽短路收窄 ─────────────────────────────────────────────────────────


class TestClarifyGatePredicate:
    def test_primary_missing_with_consult_secondary_asks(self):
        """primary 缺槽 × 咨询族 secondary:没有可营救动作 → 反问(A8 形)。"""
        parsed = [
            {"intent": "order_return", "confidence": 0.9, "type": "primary", "missingSlots": ["orderId"]},
            {"intent": "consult", "confidence": 0.7, "type": "secondary", "missingSlots": []},
        ]
        assert _should_clarify_first(parsed) is True

    def test_primary_missing_alone_asks(self):
        parsed = [{"intent": "refund", "confidence": 0.9, "type": "primary", "missingSlots": ["orderId"]}]
        assert _should_clarify_first(parsed) is True

    def test_primary_complete_secondary_missing_does_not_ask(self):
        """A1 形:primary(cart_manage)齐备,secondary(改单地址)缺单号 →
        放行 planner,整轮不再被反问劫持。"""
        parsed = [
            {"intent": "cart_manage", "confidence": 0.95, "type": "primary", "missingSlots": []},
            {"intent": "order_modify_address", "confidence": 0.9, "type": "secondary", "missingSlots": ["orderId"]},
        ]
        assert _should_clarify_first(parsed) is False

    def test_primary_missing_but_actionable_secondary_rescues(self):
        """primary 缺槽但 secondary 是槽位齐备的动作意图 → 先办能办的。"""
        parsed = [
            {"intent": "refund", "confidence": 0.9, "type": "primary", "missingSlots": ["orderId"]},
            {"intent": "shopping_guide", "confidence": 0.85, "type": "secondary", "missingSlots": []},
        ]
        assert _should_clarify_first(parsed) is False

    def test_empty_parsed_does_not_ask(self):
        assert _should_clarify_first([]) is False


class TestMultiIntentCandidate:
    def test_bare_ranhou_is_candidate(self):
        """A6 病灶:「然后推荐」——旧正则只有「然后再」,裸「然后」漏判。"""
        assert MULTI_INTENT_CANDIDATE_RE.search("退了订单9081，然后推荐几款跑步鞋")
        assert _is_multi_intent_candidate("退了订单9081，然后推荐几款跑步鞋")

    def test_existing_markers_unchanged(self):
        assert _is_multi_intent_candidate("推荐背包，顺便查一下我的订单")
        assert _is_multi_intent_candidate("加购这个，并修改地址")

    def test_query_and_action_cooccurrence_is_candidate(self):
        """A3 病灶第二支:查/物流/状态 × 退/改/换 共现。"""
        assert _is_multi_intent_candidate("查一下我最近的订单，然后把还没发货的那件退了")

    def test_plain_single_intent_not_candidate(self):
        assert not _is_multi_intent_candidate("查一下我的订单")
        assert not _is_multi_intent_candidate("推荐跑步鞋")


# ── ③接线:规则层/结构化层短路收窄(Step 3 桩法,先例 test_step3_consult_demote)──


async def _fake_exemplars(*args, **kwargs) -> list:
    return []


class _FakeShortMemory:
    def __init__(self, thread_id: str) -> None:
        pass

    async def get_messages(self) -> list:
        return []


class _FakeTaskMemory:
    def __init__(self, thread_id: str) -> None:
        pass

    async def get_task_state(self) -> dict | None:
        return None

    async def save_task_state(self, state: dict) -> None:
        return None


def _state(input_text: str) -> dict:
    return {
        "thread_id": "thread_multi_intent_test",
        "user_id": "u_multi_intent",
        "input": input_text,
        "image_urls": [],
        "input_embedding": [1.0, 0.0, 0.0],
        "business_config": {"businessId": "ecommerce"},
    }


def _run_process(monkeypatch: pytest.MonkeyPatch, input_text: str, classify_result: StructuredTriageOutput, log_calls: list) -> dict:
    """锚点向量全正交 → Step 2 三判定全不命中,直落 Step 3 的 fake classify。"""

    async def _fake_classify(input_for_prompt, **kwargs):
        return classify_result

    async def _fake_embed(text: str) -> list[float]:
        return [1.0, 0.0, 0.0]

    async def _fake_anchors() -> dict:
        orth = [0.0, 1.0, 0.0]
        return {"order_status": [orth], "refund": [orth], "out_of_scope": [orth]}

    async def _fake_log(*args, **kwargs):
        log_calls.append({"args": args, "kwargs": kwargs})

    async def _fake_consult(state, history_msgs):
        return None

    monkeypatch.setattr(triage_mod, "ShortMemory", _FakeShortMemory)
    monkeypatch.setattr(triage_mod, "TaskMemory", _FakeTaskMemory)
    monkeypatch.setattr(triage_mod, "classify", _fake_classify)
    monkeypatch.setattr(triage_mod, "run_consult_direct_answer", _fake_consult)
    monkeypatch.setattr(triage_mod, "search_relevant_exemplars", _fake_exemplars)
    monkeypatch.setattr(IntentTriageEngine, "log_intent_to_db", _fake_log)
    monkeypatch.setattr(SemanticVectorCache, "_tenant_cache", {})
    monkeypatch.setattr(SemanticVectorCache, "get_embedding_with_cache", _fake_embed)
    monkeypatch.setattr(SemanticVectorCache, "get_anchor_vectors", _fake_anchors)
    return asyncio.run(triage_mod.IntentTriageEngine.process(_state(input_text)))


class TestRuleLevelClarifySkipOnCompound:
    def test_a3_shape_reaches_structured_instead_of_rule_clarification(self, monkeypatch):
        """「查订单把没发货的退了」:复合候选形不做规则层缺槽反问,落结构化
        精判 → primary(order_query)齐备 → 放行 planner(整轮无反问)。"""
        log_calls: list = []
        result = _run_process(
            monkeypatch,
            "查一下我最近的订单，然后把还没发货的那件退了",
            StructuredTriageOutput(
                intents=[
                    IntentNode(intent="order_query", confidence=0.9, type="primary", missingSlots=[]),
                    IntentNode(intent="refund", confidence=0.85, type="secondary", missingSlots=["orderId"]),
                ],
                clarificationMessage="请提供订单编号",
            ),
            log_calls,
        )
        assert "output" not in result, "复合形不得被缺槽反问劫持整轮"
        assert [p["intent"] for p in result["intents"]] == ["order_query", "refund"]

    def test_a1_shape_secondary_missing_slot_does_not_hijack(self, monkeypatch):
        """「来点背包,并修改收货地址…」:primary 齐备 × secondary 缺单号 →
        结构化层不反问,双意图放行 planner。"""
        log_calls: list = []
        result = _run_process(
            monkeypatch,
            "来点背包，并修改收货地址到上海市浦东新区",
            StructuredTriageOutput(
                intents=[
                    IntentNode(intent="cart_manage", confidence=0.95, type="primary", missingSlots=[]),
                    IntentNode(
                        intent="order_modify_address", confidence=0.9, type="secondary",
                        missingSlots=["orderId"],
                    ),
                ],
                clarificationMessage="如果是修改已有订单的地址，请提供订单号",
            ),
            log_calls,
        )
        assert "output" not in result, "secondary 缺槽不得劫持 primary 齐备的复合轮"
        assert [p["intent"] for p in result["intents"]] == ["cart_manage", "order_modify_address"]
        # 放行时 parsed 必须携带 missingSlots 注记(planner 尽力而为规则的输入)
        assert result["intents"][1].get("missingSlots") == ["orderId"]


class TestOrderIdShapeSanitize:
    def test_bare_fragment_order_id_stripped_for_money_action(self, monkeypatch):
        """A6 实弹修复:「退了订单9081」的四位数尾缀被分类器抽成 orderId ——
        连宽松单号正则都不过的形态必须剥除并补缺槽注记,资金动作严禁以
        假单号为据直接执行(执行器曾未调工具即宣称退款成功)。"""
        log_calls: list = []
        result = _run_process(
            monkeypatch,
            "退了订单9081，然后推荐几款跑步鞋",
            StructuredTriageOutput(
                intents=[
                    IntentNode(
                        intent="refund", confidence=0.95, type="primary",
                        entities={"orderId": "9081"}, missingSlots=[],
                    ),
                    IntentNode(
                        intent="shopping_guide", confidence=0.95, type="secondary",
                        entities={"productName": "跑步鞋"}, missingSlots=[],
                    ),
                ]
            ),
            log_calls,
        )
        first = result["intents"][0]
        assert first["entities"].get("orderId") is None, "不合格形态的单号必须剥除"
        assert "orderId" in (first.get("missingSlots") or []), "剥除后必须补缺槽注记"
        assert "output" not in result, "剥除后放行 planner(先办导购+追问退哪单)"
        assert result["intents"][1]["intent"] == "shopping_guide"

    def test_valid_shape_order_id_survives(self, monkeypatch):
        """规范形态单号(ORD-/AURORA-ORD-)不受形状校验误伤。"""
        log_calls: list = []
        result = _run_process(
            monkeypatch,
            "退了订单AURORA-ORD-2026-9083，然后推荐几款跑步鞋",
            StructuredTriageOutput(
                intents=[
                    IntentNode(
                        intent="refund", confidence=0.95, type="primary",
                        entities={"orderId": "AURORA-ORD-2026-9083"}, missingSlots=[],
                    ),
                    IntentNode(intent="shopping_guide", confidence=0.9, type="secondary", missingSlots=[]),
                ]
            ),
            log_calls,
        )
        assert result["intents"][0]["entities"].get("orderId") == "AURORA-ORD-2026-9083"


class TestMoneyActionYieldWiring:
    def test_connector_less_money_and_guide_yields_to_structured(self, monkeypatch):
        """评审缺陷②:无连接词的「导购+资金」句(「推荐几款卫衣，帮我把上一单
        退掉」)规则层只检出导购单意图 —— 资金否决必须连单意图终局一起让位
        Step2/3 精判并留痕,否则退款半照样被 slot_extractor_single_complete 吞掉。"""

        class _FakeSkill:
            metadata = {"id": "skill_shopping_guide", "category": "pre_sale"}

            async def execute(self, context: dict) -> dict:
                return {"success": True, "nextAction": "finish", "output": "假导购回复"}

        from engine_py.skills import SkillRegistry

        monkeypatch.setattr(
            SkillRegistry, "find_matching_skill", classmethod(lambda cls, ctx: _FakeSkill())
        )
        log_calls: list = []
        result = _run_process(
            monkeypatch,
            "推荐几款卫衣，帮我把上一单退掉",
            StructuredTriageOutput(
                intents=[
                    IntentNode(intent="shopping_guide", confidence=0.9, type="primary", missingSlots=[]),
                    IntentNode(intent="refund", confidence=0.85, type="secondary", missingSlots=["orderId"]),
                ],
            ),
            log_calls,
        )
        reasons = [lc["kwargs"].get("arbitration_reason") for lc in log_calls]
        assert "money_action_veto_yield" in reasons, "资金否决让位必须留痕"
        assert "假导购回复" not in str(result.get("output")), "资金动作在场不得单导购终局"
        assert [p["intent"] for p in result["intents"]] == ["shopping_guide", "refund"]


class TestStructuredClarifyStillAsksWhenPrimaryMissing:
    def test_a8_shape_primary_missing_with_consult_asks(self, monkeypatch):
        """「我想退货,顺便看看退货政策」:primary(退款)缺单号 × 咨询族
        secondary → 仍反问(资金动作纪律不回归),且反问来自结构化层。"""
        log_calls: list = []
        structured_msg = "请问您需要为哪笔订单申请退款/退货？请提供您的【订单编号】。"
        result = _run_process(
            monkeypatch,
            "我想退货，顺便看看退货政策",
            StructuredTriageOutput(
                intents=[
                    IntentNode(intent="order_return", confidence=0.9, type="primary", missingSlots=["orderId"]),
                    IntentNode(intent="consult", confidence=0.7, type="secondary", missingSlots=[]),
                ],
                clarificationMessage=structured_msg,
            ),
            log_calls,
        )
        assert result.get("output") == structured_msg
        assert log_calls[0]["kwargs"].get("arbitration_reason") == "slot_clarification_structured"


if __name__ == "__main__":
    pytest.main([__file__])
