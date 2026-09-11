"""冲突标记留痕(intent-arbitration 07,2026-09-10)—— 「判动作 × 咨询形」残余观测。

数据定夺:01 仲裁留痕 393 行(method 分布覆盖槽位/技能/锚点/精判全部终局)
直接审计「槽位/锚点层判动作 × 咨询形措辞」0 例 —— 该残余在现有措辞分布下
不存在(p50 咨询已被 Step 1.4 快轨 + Step 3 分类器 + 06 改判三层 LLM 覆盖),
不为其硬上 LLM 仲裁调用;但单层动作终局的 candidates 无 consult 侧候选,
残余一旦出现对坏例池冲突信号源不可见 —— 故加零调用标记 is_consult_shaped_marker,
命中即记 consult_shaped_gate 提议进留痕(02 信号源同口径消费),路由不变。
"""

from __future__ import annotations

import asyncio

import pytest

from engine_py.triage import intent_triage_engine as triage_mod
from engine_py.triage.consult_fast_path import is_consult_shaped_marker
from engine_py.triage.semantic_cache import SemanticVectorCache


class TestConsultShapedMarker:
    @pytest.mark.parametrize(
        "text",
        [
            "退货流程是什么样的",
            "退款金额怎么算",
            "换货的话需要什么条件",
            "7天无理由的话怎么说",
        ],
    )
    def test_consult_shaped_matches(self, text: str):
        assert is_consult_shaped_marker(text), f"咨询形标记应命中: {text}"

    @pytest.mark.parametrize(
        "text",
        [
            "帮我申请退款",  # 动作动词
            "我要退货",  # 动作动词
            "退货 ORD-98712",  # 单号即动作指向
            "查一下物流",  # 查 动词
            "今天天气怎么样",  # 无售后/政策话题词
            "你好",  # 无话题无疑问
        ],
    )
    def test_action_or_offtopic_do_not_match(self, text: str):
        assert not is_consult_shaped_marker(text), f"非咨询形标记不得命中: {text}"


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


def _action_state() -> dict:
    # 槽位层判 refund 且带单号(完整槽位,单意图高置信终局)
    return {
        "thread_id": "thread_conflict_marker_test",
        "user_id": "u_marker",
        "input": "帮我申请退款 ORD-98712",
        "image_urls": [],
        "input_embedding": [1.0, 0.0, 0.0],
        "order_context": {"targetOrderId": "ORD-98712"},
        "business_config": {"businessId": "ecommerce"},
    }


def _clarify_state() -> dict:
    # 缺槽反问终局(工单07 观测洞靶形状):咨询闸因「顺便」闭合、槽位层判
    # order_return 缺 orderId 触发反问、咨询形标记真命中(均实测钉死)
    return {
        "thread_id": "thread_conflict_marker_clarify",
        "user_id": "u_marker_clarify",
        "input": "顺便问下退货政策是什么",
        "image_urls": [],
        "input_embedding": [1.0, 0.0, 0.0],
        "business_config": {"businessId": "ecommerce"},
    }


class TestConflictMarkerWiring:
    """接线:标记命中 → consult_shaped_gate 提议进终局留痕,路由不变。"""

    def _run_process(
        self, monkeypatch: pytest.MonkeyPatch, log_calls: list, state: dict | None = None
    ) -> dict:
        async def _fake_embed(text: str) -> list[float]:
            return [1.0, 0.0, 0.0]

        async def _fake_anchors() -> dict:
            orth = [0.0, 1.0, 0.0]
            return {"order_status": [orth], "refund": [orth], "out_of_scope": [orth]}

        async def _fake_log(*args, **kwargs):
            log_calls.append({"args": args, "kwargs": kwargs})

        async def _fake_fast_track(*args, **kwargs):
            return None  # 不触发技能真执行(观测留痕路径,技能直通另有套件)

        monkeypatch.setattr(triage_mod, "ShortMemory", _FakeShortMemory)
        monkeypatch.setattr(triage_mod, "TaskMemory", _FakeTaskMemory)
        monkeypatch.setattr(triage_mod, "search_relevant_exemplars", _fake_exemplars)
        monkeypatch.setattr(triage_mod.IntentTriageEngine, "log_intent_to_db", _fake_log)
        monkeypatch.setattr(triage_mod.IntentTriageEngine, "_try_skill_fast_track", _fake_fast_track)
        monkeypatch.setattr(SemanticVectorCache, "_tenant_cache", {})
        monkeypatch.setattr(SemanticVectorCache, "get_embedding_with_cache", _fake_embed)
        monkeypatch.setattr(SemanticVectorCache, "get_anchor_vectors", _fake_anchors)
        return asyncio.run(triage_mod.IntentTriageEngine.process(state or _action_state()))

    def test_marker_fires_records_gate_proposal_without_route_change(self, monkeypatch):
        """标记命中(模拟措辞逃逸):终局行 candidates 含 consult_shaped_gate
        提议 —— 坏例池冲突信号源可见;结果仍是动作终局(路由不变)。"""
        log_calls: list = []
        monkeypatch.setattr(triage_mod, "is_consult_shaped_marker", lambda t: True)
        result = self._run_process(monkeypatch, log_calls)
        assert result["intents"][0]["intent"] == "order_return", "标记只留痕,不改路由"
        candidates = log_calls[0]["kwargs"]["candidates"]
        layers = [(c["layer"], c["intent"]) for c in candidates]
        assert ("consult_shaped_gate", "consult") in layers
        # 02 冲突口径同源:detect_intent_conflict 对该 candidates 必须报冲突
        from engine_py.badcase.intent_signals import detect_intent_conflict

        assert detect_intent_conflict(candidates) is not None

    def test_normal_action_termination_has_no_gate_proposal(self, monkeypatch):
        """常规动作终局(措辞无咨询形):无标记提议,留痕与信号源行为不变。"""
        log_calls: list = []
        result = self._run_process(monkeypatch, log_calls)
        assert result["intents"][0]["intent"] == "order_return"
        layers = [c["layer"] for c in log_calls[0]["kwargs"]["candidates"]]
        assert "consult_shaped_gate" not in layers

    def test_marker_fires_on_clarification_terminal(self, monkeypatch):
        """工单07(挂点前移):缺槽反问终局 —— 07 追溯的历史靶落点(咨询形
        输入被槽位层反问打断)—— 的留痕也带 consult_shaped_gate 提议;真实
        标记不模拟;路由不变(照旧反问补单号)。"""
        log_calls: list = []
        result = self._run_process(monkeypatch, log_calls, _clarify_state())
        # 反问终局:bypass 输出为澄清话术,意图仍是槽位层判定的 order_return
        assert result["intents"][0]["intent"] == "order_return", "标记只留痕,不改路由"
        assert "订单编号" in str(result.get("output", "")), "缺槽反问终局形态保持"
        candidates = log_calls[0]["kwargs"]["candidates"]
        layers = [(c["layer"], c["intent"]) for c in candidates]
        assert ("consult_shaped_gate", "consult") in layers, "缺槽反问终局的留痕必须带上标记提议"
        # 02 冲突口径同源:该留痕对坏例池冲突信号源可见
        from engine_py.badcase.intent_signals import detect_intent_conflict

        assert detect_intent_conflict(candidates) is not None


if __name__ == "__main__":
    pytest.main([__file__])
