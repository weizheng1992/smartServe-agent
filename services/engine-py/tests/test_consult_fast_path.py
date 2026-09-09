"""咨询类直答快轨(2026-09-09)—— 政策/尺码/时效类「问知识」输入单次调用直答。

此前咨询无独立意图档位:「退货政策是什么」按措辞随机误落 —— Step 1.5
ORDER_RETURN 规则(含「退货」即动作形)反问订单号,或 Step 2 判定 3 关键词
快车道(退货字样 × 无订单字样)误判 refund 动作意图进 planner 深度规划。
本套钉死:
1. is_consult_query 三重否定闸(订单号/动作形/带图)+ 话题×疑问判定;
2. run_consult_direct_answer 编排:RAG 过线直答、缓存先查后回填、
   空弱/失败回落 None、熔断穿透;
3. triage Step 1.4 接线:直答命中旁路输出,空弱回落 general_query
   零规划(不再被误判动作形反问订单号)。
"""

from __future__ import annotations

import asyncio

import pytest

from engine_py.llm import CircuitBreakerOpenError
from engine_py.triage import consult_fast_path as cfp
from engine_py.triage import intent_triage_engine as triage_mod
from engine_py.triage.consult_fast_path import (
    RAG_DIRECT_MIN_SIMILARITY,
    is_consult_query,
    run_consult_direct_answer,
)
from engine_py.triage.semantic_cache import SemanticVectorCache


class TestIsConsultQuery:
    @pytest.mark.parametrize(
        "text",
        [
            "退货政策是什么",
            "你们的退货政策",  # 省略式裸话题(≤12 字)
            "退货政策",  # 裸名词短语
            "尺码怎么选",
            "退款多久到账",
            "7天无理由退货是真的吗",
            "怎么退货",
            "发票怎么开",
            "你们包邮吗",
            "这件衣服怎么洗",
            "你们支持哪些支付方式",
        ],
    )
    def test_consult_questions_match(self, text: str):
        assert is_consult_query(text), f"咨询形输入应命中: {text}"

    @pytest.mark.parametrize(
        "text",
        [
            "帮我退款",  # 动作形
            "我要退货",
            "帮我申请退款",
            "退货 ORD-98712",  # 显式订单号
            "查一下ORD-98712到哪了",
            "查一下我的订单",  # 订单/查 动作域
            "发货了吗",  # 问的是「我那单」,订单状态域
            "帮我把地址改成北京",
            "把第1件加入购物车",
            "转人工",
            "顺便问下退货政策再帮我查下订单",  # 复合意图
            "你好",  # 无咨询话题
            "今天天气怎么样",  # 话题不在店铺知识域
        ],
    )
    def test_action_or_offtopic_do_not_match(self, text: str):
        assert not is_consult_query(text), f"非咨询输入不得命中: {text}"

    def test_image_gate_lives_in_is_consult_query_itself(self):
        """带图闸在 is_consult_query 本体(2026-09-09 评审修复):咨询形措辞 × 带图
        → False。旧行为是快轨内部拒答后由 Step 1.4 回落 general_query 截胡,
        绕过视觉定责消歧与图内 OCR 单号消费;现带图输入根本不入快轨。"""
        assert is_consult_query("这鞋坏了怎么退货"), "同措辞无图仍应命中快轨"
        assert not is_consult_query("这鞋坏了怎么退货", has_image=True), "带图售后走视觉定责管道"
        assert not is_consult_query("退货政策是什么", has_image=True)


def _consult_state(similarity: float = 0.72) -> dict:
    return {
        "thread_id": "thread_consult_test",
        "user_id": "u_consult",
        "input": "退货政策是什么",
        "image_urls": [],
        "input_embedding": [1.0, 0.0, 0.0],
        "business_config": {"businessId": "ecommerce"},
        "rag_documents": [
            {
                "chunkText": "自签收之日起 7 天无理由退换货,吊牌完整。",
                "contextualSummary": "退货政策切片",
                "similarity": similarity,
            }
        ],
    }


class TestRunConsultDirectAnswer:
    def _patch(self, monkeypatch: pytest.MonkeyPatch, answer=None, answer_exc: Exception | None = None):
        calls: dict = {}

        async def _fake_answer(input_text, rag_documents, history_msgs, brand_name):
            calls["answer_args"] = (input_text, brand_name)
            if answer_exc:
                raise answer_exc
            return answer or "答:支持 7 天无理由退换货。"

        def _fake_cache_add(business_id, query, reply, vector):
            calls["cache_add"] = (business_id, query, reply[:12])

        monkeypatch.setattr(cfp, "answer_consult_from_rag", _fake_answer)
        monkeypatch.setattr(cfp, "add_query_to_semantic_cache", _fake_cache_add)
        monkeypatch.setattr(cfp, "get_merchant_display_name", lambda tenant: "智选电商")
        monkeypatch.setattr(SemanticVectorCache, "_tenant_cache", {})
        return calls

    def test_strong_rag_single_call_answer_and_cache_writeback(self, monkeypatch):
        calls = self._patch(monkeypatch)
        hit = asyncio.run(run_consult_direct_answer(_consult_state(), []))
        assert hit is not None
        answer, intents, _confidence = hit
        assert "7 天无理由" in answer
        assert intents[0]["intent"] == "consult"
        # 单次直答 + 回填缓存(同题下次秒回)
        assert calls["answer_args"][0] == "退货政策是什么"
        assert calls["cache_add"][0] == "ecommerce"
        assert calls["cache_add"][1] == "退货政策是什么"

    def test_weak_rag_returns_none_without_llm_call(self, monkeypatch):
        calls = self._patch(monkeypatch)
        hit = asyncio.run(run_consult_direct_answer(_consult_state(similarity=0.45), []))
        assert hit is None
        assert "answer_args" not in calls, "RAG 不过线不得发起直答调用"
        assert 0.45 < RAG_DIRECT_MIN_SIMILARITY <= 0.72

    def test_empty_rag_returns_none(self, monkeypatch):
        self._patch(monkeypatch)
        state = _consult_state()
        state["rag_documents"] = []
        assert asyncio.run(run_consult_direct_answer(state, [])) is None

    def test_image_input_returns_none(self, monkeypatch):
        self._patch(monkeypatch)
        state = _consult_state()
        state["image_urls"] = ["/api/uploads/x.png"]
        assert asyncio.run(run_consult_direct_answer(state, [])) is None, "带图售后走视觉定责管道"

    def test_answer_failure_falls_back_to_none(self, monkeypatch):
        self._patch(monkeypatch, answer_exc=RuntimeError("bigmodel 5xx"))
        assert asyncio.run(run_consult_direct_answer(_consult_state(), [])) is None

    def test_circuit_breaker_propagates(self, monkeypatch):
        self._patch(
            monkeypatch,
            answer_exc=CircuitBreakerOpenError({"state": "OPEN", "failures": 3, "nextAttemptInMs": 30000}),
        )
        with pytest.raises(CircuitBreakerOpenError):
            asyncio.run(run_consult_direct_answer(_consult_state(), []))

    def test_semantic_cache_hit_skips_llm_call(self, monkeypatch):
        calls = self._patch(monkeypatch)
        monkeypatch.setattr(
            SemanticVectorCache,
            "_tenant_cache",
            {"ecommerce": [{"query": "退货政策是啥", "reply": "缓存答案:7 天无理由。", "vector": [1.0, 0.0, 0.0]}]},
        )
        hit = asyncio.run(run_consult_direct_answer(_consult_state(), []))
        assert hit is not None
        assert hit[0] == "缓存答案:7 天无理由。"
        assert hit[1][0]["intent"] == "general_query", "缓存复放口径与 Step 2 super_semantic_cache 一致"
        assert "answer_args" not in calls, "缓存命中不得再发起 LLM 调用"


async def _fake_exemplars(*args, **kwargs) -> list:
    return []


async def _noop_log(*args, **kwargs) -> None:
    return None


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


class TestTriageWiring:
    """Step 1.4 接线:process() 层验证直答旁路与空弱回落(误路由修复)。"""

    def _run_process(self, monkeypatch: pytest.MonkeyPatch, direct_hit) -> dict:
        async def _fake_direct(state, history_msgs):
            return direct_hit

        async def _fake_embed(text: str) -> list[float]:
            return [0.0, 0.0, 1.0]

        async def _fake_anchors() -> dict:
            orth = [1.0, 0.0, 0.0]
            return {"order_status": [orth], "refund": [orth], "out_of_scope": [orth]}

        monkeypatch.setattr(triage_mod, "ShortMemory", _FakeShortMemory)
        monkeypatch.setattr(triage_mod, "TaskMemory", _FakeTaskMemory)
        monkeypatch.setattr(triage_mod, "run_consult_direct_answer", _fake_direct)
        monkeypatch.setattr(triage_mod, "search_relevant_exemplars", _fake_exemplars)
        monkeypatch.setattr(triage_mod.IntentTriageEngine, "log_intent_to_db", _noop_log)
        monkeypatch.setattr(SemanticVectorCache, "_tenant_cache", {})
        monkeypatch.setattr(SemanticVectorCache, "get_embedding_with_cache", _fake_embed)
        monkeypatch.setattr(SemanticVectorCache, "get_anchor_vectors", _fake_anchors)

        state = _consult_state()
        return asyncio.run(triage_mod.IntentTriageEngine.process(state))

    def test_consult_direct_hit_bypasses_to_output(self, monkeypatch):
        result = self._run_process(
            monkeypatch,
            ("答:支持 7 天无理由退换货,吊牌需完整。", [{"intent": "consult", "confidence": 0.95, "type": "primary"}], 0.95),
        )
        assert result["intents"][0]["intent"] == "consult"
        assert "7 天无理由" in result["output"]
        assert result["task_plan"]["subtasks"][0]["id"] == "bypass_step"

    def test_consult_without_rag_falls_to_general_query_not_refund_action(self, monkeypatch):
        """修复钉子:RAG 空弱时必须落 general_query 零规划旁路 —— 旧行为是
        Step 1.5/Step 2 把「退货政策」误判 refund/order_return 动作形(反问
        订单号或进 planner 深度规划)。"""
        result = self._run_process(monkeypatch, None)
        assert result["intents"][0]["intent"] == "general_query"
        assert "output" not in result, "空弱回落不应产出旁路回复(交 finish 终稿)"
        assert "订单编号" not in str(result), "不得误判动作形反问订单号"


if __name__ == "__main__":
    pytest.main([__file__])
