"""Step3 consult 降级保留动作形(triage-review-remediation 工单06,2026-09-11)。

旧降级把 parsed 全量改写 general_query —— 混排输入(咨询主 + 动作次)的动作
secondary 一并被吞,动作请求以一条资讯回复了事,违反 intent-arbitration
故事3(带动作意图的请求绝不收到一条资讯回复就了事)/故事5(混排拆开各走
各路)。本套钉死:

1. 降级函数:纯 consult 输出与旧整体降级同形;混排保留动作形并提升首个
   动作为 primary;
2. 接线:仲裁员否决与 RAG 空弱两条路径,refund 类动作 secondary 存活且
   提升为 primary(planner 仅对单 general_query 零规划,提升后自然编排);
3. 留痕:否决路径 candidates 含 consult_arbiter 提议。

测试输入「顺便问下尺码怎么选」的层行为(实测钉死):咨询闸因「顺便」闭合、
槽位层判 chat(不终局)、Step 3 由 fake classify 接管精判。
"""

from __future__ import annotations

import asyncio

import pytest

from engine_py.triage import intent_triage_engine as triage_mod
from engine_py.triage.consult_fast_path import ROUTE_TO_ACTION_MARKER
from engine_py.triage.intent_triage_engine import _demote_consult_keep_actions
from engine_py.triage.semantic_cache import SemanticVectorCache
from engine_py.triage.structured_classifier import IntentNode, StructuredTriageOutput

# ── 降级函数单测(纯函数,无 IO)──────────────────────────────────────────


class TestDemoteFunction:
    def test_pure_consult_keeps_legacy_shape(self):
        """纯 consult 输入:与旧整体降级逐字同形(intent 全降 general_query,
        type 原样保留),回归安全。"""
        parsed = [
            {"intent": "consult", "confidence": 0.92, "type": "primary", "entities": {}},
            {"intent": "out_of_scope", "confidence": 0.6, "type": "secondary", "entities": {}},
        ]
        result = _demote_consult_keep_actions(parsed)
        assert [p["intent"] for p in result] == ["general_query", "general_query"]
        assert [p["type"] for p in result] == ["primary", "secondary"]
        assert [p["confidence"] for p in result] == [0.92, 0.6]

    def test_mixed_promotes_first_action_to_primary(self):
        """混排(咨询主 + 退款次):refund 保留并提升 primary,咨询降
        general_query 转 secondary —— 动作不再被资讯回复吞掉。"""
        parsed = [
            {"intent": "consult", "confidence": 0.92, "type": "primary", "entities": {}},
            {"intent": "refund", "confidence": 0.85, "type": "secondary", "entities": {}},
        ]
        result = _demote_consult_keep_actions(parsed)
        assert [p["intent"] for p in result] == ["refund", "general_query"]
        assert [p["type"] for p in result] == ["primary", "secondary"]
        assert result[0]["confidence"] == 0.85

    def test_input_list_not_mutated(self):
        parsed = [{"intent": "consult", "confidence": 0.9, "type": "primary"}]
        _demote_consult_keep_actions(parsed)
        assert parsed[0]["intent"] == "consult", "降级不得原地改写调用方列表"


# ── Step3 接线测试(fake classify / fake 直答,正交锚点令 Step 2 全跳过)──


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


def _state() -> dict:
    return {
        "thread_id": "thread_step3_demote_test",
        "user_id": "u_step3_demote",
        "input": "顺便问下尺码怎么选",  # 实测:咨询闸闭合(顺便)、槽位层判 chat
        "image_urls": [],
        "input_embedding": [1.0, 0.0, 0.0],
        "business_config": {"businessId": "ecommerce"},
    }


class TestStep3DemoteWiring:
    def _run_process(
        self,
        monkeypatch: pytest.MonkeyPatch,
        classify_result: StructuredTriageOutput,
        consult_answer,
        log_calls: list,
    ) -> dict:
        """锚点向量全部正交([1,0,0]×[0,1,0]=0)→ Step 2 三判定全不命中,
        直落 Step 3;consult_answer 为 None 模拟 RAG 空弱,哨兵模拟仲裁否决。"""

        async def _fake_classify(input_text, **kwargs):
            return classify_result

        async def _fake_consult(state, history_msgs):
            return consult_answer

        async def _fake_embed(text: str) -> list[float]:
            return [1.0, 0.0, 0.0]

        async def _fake_anchors() -> dict:
            orth = [0.0, 1.0, 0.0]
            return {"order_status": [orth], "refund": [orth], "out_of_scope": [orth]}

        async def _fake_log(*args, **kwargs):
            log_calls.append({"args": args, "kwargs": kwargs})

        monkeypatch.setattr(triage_mod, "ShortMemory", _FakeShortMemory)
        monkeypatch.setattr(triage_mod, "TaskMemory", _FakeTaskMemory)
        monkeypatch.setattr(triage_mod, "classify", _fake_classify)
        monkeypatch.setattr(triage_mod, "run_consult_direct_answer", _fake_consult)
        monkeypatch.setattr(triage_mod, "search_relevant_exemplars", _fake_exemplars)
        monkeypatch.setattr(triage_mod.IntentTriageEngine, "log_intent_to_db", _fake_log)
        monkeypatch.setattr(SemanticVectorCache, "_tenant_cache", {})
        monkeypatch.setattr(SemanticVectorCache, "get_embedding_with_cache", _fake_embed)
        monkeypatch.setattr(SemanticVectorCache, "get_anchor_vectors", _fake_anchors)
        return asyncio.run(triage_mod.IntentTriageEngine.process(_state()))

    def test_veto_keeps_action_secondary_promoted_to_primary(self, monkeypatch):
        """仲裁员否决 × 混排(咨询主+退款次):refund 存活且提升 primary,
        咨询降 general_query;否决只否「资讯直答」,不否动作(故事3/5)。"""
        log_calls: list = []
        result = self._run_process(
            monkeypatch,
            StructuredTriageOutput(
                intents=[
                    IntentNode(intent="consult", confidence=0.92, type="primary"),
                    IntentNode(intent="refund", confidence=0.85, type="secondary"),
                ]
            ),
            (ROUTE_TO_ACTION_MARKER, [], 0.0),
            log_calls,
        )
        assert [p["intent"] for p in result["intents"]] == ["refund", "general_query"]
        assert result["intents"][0]["type"] == "primary", "首个动作形必须是 primary"
        # 提升后非单 general_query → planner 编排;域角色随动作意图取 order_service
        assert result["active_domain_role"] == "order_service"
        assert "output" not in result, "降级离场是终局返回,不得以资讯回复关会话"
        candidates = log_calls[0]["kwargs"]["candidates"]
        assert ("consult_arbiter", None) in [(c["layer"], c["intent"]) for c in candidates]

    def test_rag_empty_keeps_action_secondary_promoted_to_primary(self, monkeypatch):
        """RAG 空弱 × 混排:同款降级,动作形同样存活提升。"""
        log_calls: list = []
        result = self._run_process(
            monkeypatch,
            StructuredTriageOutput(
                intents=[
                    IntentNode(intent="consult", confidence=0.9, type="primary"),
                    IntentNode(intent="refund", confidence=0.8, type="secondary"),
                ]
            ),
            None,  # RAG 空弱/直答失败
            log_calls,
        )
        assert [p["intent"] for p in result["intents"]] == ["refund", "general_query"]
        assert result["active_domain_role"] == "order_service"

    def test_pure_consult_veto_matches_legacy_demotion(self, monkeypatch):
        """纯 consult 输入的否决:维持既有整体降级形状(全 general_query、
        域角色 chitchat)—— 工单06 不改纯咨询路径行为。"""
        log_calls: list = []
        result = self._run_process(
            monkeypatch,
            StructuredTriageOutput(
                intents=[
                    IntentNode(intent="consult", confidence=0.92, type="primary"),
                    IntentNode(intent="general_query", confidence=0.6, type="secondary"),
                ]
            ),
            (ROUTE_TO_ACTION_MARKER, [], 0.0),
            log_calls,
        )
        assert [p["intent"] for p in result["intents"]] == ["general_query", "general_query"]
        assert [p["type"] for p in result["intents"]] == ["primary", "secondary"]
        assert result["active_domain_role"] == "chitchat"


if __name__ == "__main__":
    pytest.main([__file__])
