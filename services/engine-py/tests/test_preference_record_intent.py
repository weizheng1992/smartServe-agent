"""preference_record 意图 + recordUserPreference 对话写路(persona-hardening 12)。

实弹(persona-hardening 10 回放,2026-09-30):顾客明说「帮我记一下我的偏好:买包
只买黑色的」,planner 规划了记录子任务,但 recordUserPreference 不在任何
IntentSpec.allowed_tools → align_plan_to_intents 必剪(gateway 日志 pruned 2),
tool_record 落库 0 行,finish 即兴假宣称「已为您成功记录偏好 ✅」。
修复取 address_manage 先例:规则层产出意图(零分类器 prompt 变更)+ 判定前置
直通 + Step3 复合注入 + planner 确定性快轨;finish 防假成功闸扩面(严禁无
工具执行背书宣称已记录);执行器快路径消费检测器抽取的 statedPreference。
"""

from __future__ import annotations

import asyncio

import pytest

from engine_py.graph.nodes import planner as planner_mod
from engine_py.graph.nodes.executor_fast_path import try_match_executor_fast_path
from engine_py.graph.nodes.step_execution_engine import _base_executor_tools
from engine_py.graph.plan_alignment import align_plan_to_intents
from engine_py.triage import intent_triage_engine as triage_mod
from engine_py.triage.intent_registry import (
    INTENT_REGISTRY,
    AgentIntentType,
    all_intent_labels,
    terminal_intents,
)
from engine_py.triage.intent_triage_engine import (
    IntentTriageEngine,
    _inject_preference_record,
    detect_preference_record,
)

PREFERENCE_RECORD = AgentIntentType.PREFERENCE_RECORD
M2_SENTENCE = "帮我记一下我的偏好:买包只买黑色的"

# ── 注册表登记(address_manage 先例:规则层产出,零分类器 prompt 变更)────────


class TestRegistry:
    def test_preference_record_registered(self):
        assert PREFERENCE_RECORD in all_intent_labels()
        assert PREFERENCE_RECORD in terminal_intents()
        spec = INTENT_REGISTRY[PREFERENCE_RECORD]
        assert spec.prompt_category is None, "规则层产出意图不得进分类器 10 类目"
        assert spec.lifecycle == "active"
        assert spec.allowed_tools == ("recordUserPreference",), (
            "写路死根因就是白名单缺注册 —— 本意图的 allowed_tools 必须携带工具真名"
        )
        assert spec.consumers, "active 档位必须盘点消费方"

    def test_tool_in_executor_dispatch_whitelist(self):
        """派发层白名单在册是快路径可达的前提(缺陷 = 意图层缺注册,两层漂移)。"""
        assert "recordUserPreference" in _base_executor_tools


# ── 检测器(纯函数)────────────────────────────────────────────────────────


class TestDetectPreferenceRecord:
    def test_m2_live_sentence_hit_with_stated_value(self):
        detected = detect_preference_record(M2_SENTENCE)
        assert detected is not None
        assert detected["entities"]["statedPreference"] == "买包只买黑色的"
        assert detected["entities"]["preferenceType"] == "color"

    def test_verb_before_object_shapes(self):
        for text in ("记住我喜欢黑色", "帮我记录一下用户的偏好", "帮我记一下,我喜欢黑色"):
            assert detect_preference_record(text) is not None, text

    def test_object_before_verb_shape(self):
        detected = detect_preference_record("把买包只买黑色这个偏好保存一下")
        assert detected is not None

    def test_size_type_inferred(self):
        detected = detect_preference_record("帮我记一下我的偏好:上衣穿L码")
        assert detected is not None
        assert detected["entities"]["preferenceType"] == "size"

    def test_negation_vetoes(self):
        for text in ("不用记我的偏好", "别记了我的偏好,谢谢"):
            assert detect_preference_record(text) is None, text

    def test_statement_without_record_verb_misses(self):
        """陈述形(「我不喜欢黑色」)归审计 Agent 被动抽取,本意图只收显式请求。"""
        for text in ("我不喜欢黑色", "推荐黑色的背包", "你的偏好设置在哪里", "我好像忘了我的喜好"):
            assert detect_preference_record(text) is None, text

    def test_guide_compound_not_hijacked_by_detector_alone(self):
        """「结合我的喜好帮我推荐」是导购不是记录 —— 检测器必须让位。"""
        assert detect_preference_record("我下周要去徒步,结合我的喜好帮我推荐一款背包") is None


# ── Step3 复合注入(纯函数缝)─────────────────────────────────────────────


class TestInjectPreferenceRecord:
    def test_compound_injects_primary_and_drops_general_query(self):
        parsed = [
            {"intent": "general_query", "confidence": 0.9, "type": "primary", "entities": {}, "missingSlots": []},
            {"intent": "shopping_guide", "confidence": 0.85, "type": "secondary", "entities": {}, "missingSlots": []},
        ]
        result = _inject_preference_record(parsed, "记住我的喜好,再推荐一款背包")
        assert [p["intent"] for p in result] == ["preference_record", "shopping_guide"]
        assert result[0]["type"] == "primary"

    def test_noop_without_record_form(self):
        parsed = [{"intent": "shopping_guide", "confidence": 0.9, "type": "primary", "entities": {}, "missingSlots": []}]
        assert _inject_preference_record(parsed, "推荐几款跑步鞋") == parsed


# ── 判定前置直通 + Step3 接线(Step 3 桩法,先例 test_address_manage_intent)──


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
        "thread_id": "thread_preference_record_test",
        "user_id": "u_preference_record",
        "input": input_text,
        "image_urls": [],
        "input_embedding": [1.0, 0.0, 0.0],
        "business_config": {"businessId": "ecommerce"},
    }


def _run_process(monkeypatch: pytest.MonkeyPatch, input_text: str, classify_result=None, log_calls: list | None = None) -> dict:
    async def _fake_embed(text: str) -> list[float]:
        return [1.0, 0.0, 0.0]

    async def _fake_anchors() -> dict:
        orth = [0.0, 1.0, 0.0]
        return {"order_status": [orth], "refund": [orth], "out_of_scope": [orth]}

    async def _fake_log(*args, **kwargs):
        if log_calls is not None:
            log_calls.append({"args": args, "kwargs": kwargs})

    async def _fake_classify(input_for_prompt, **kwargs):
        if classify_result is None:
            raise AssertionError("规则前置直通后不得再进结构化分类器")
        return classify_result

    async def _fake_consult(state, history_msgs):
        return None

    monkeypatch.setattr(triage_mod, "ShortMemory", _FakeShortMemory)
    monkeypatch.setattr(triage_mod, "TaskMemory", _FakeTaskMemory)
    monkeypatch.setattr(triage_mod, "classify", _fake_classify)
    monkeypatch.setattr(triage_mod, "run_consult_direct_answer", _fake_consult)
    monkeypatch.setattr(triage_mod, "search_relevant_exemplars", _fake_exemplars)
    monkeypatch.setattr(IntentTriageEngine, "log_intent_to_db", _fake_log)
    monkeypatch.setattr(triage_mod.SemanticVectorCache, "_tenant_cache", {})
    monkeypatch.setattr(triage_mod.SemanticVectorCache, "get_embedding_with_cache", _fake_embed)
    monkeypatch.setattr(triage_mod.SemanticVectorCache, "get_anchor_vectors", _fake_anchors)
    return asyncio.run(triage_mod.IntentTriageEngine.process(_state(input_text)))


class TestPrecheckTerminal:
    def test_pure_record_terminates_at_precheck_without_llm(self, monkeypatch):
        """M2 实弹句:纯记录偏好直通 preference_record 终局,零结构化调用 ——
        不再落导购深规划让对齐闸剪光记录子任务。"""
        log_calls: list = []
        result = _run_process(monkeypatch, M2_SENTENCE, classify_result=None, log_calls=log_calls)
        assert result["intents"][0]["intent"] == "preference_record"
        assert result["intents"][0]["entities"]["statedPreference"] == "买包只买黑色的"
        assert "output" not in result, "直通终局进 planner 编排,不是反问旁路"
        assert log_calls[0]["kwargs"].get("arbitration_reason") == "preference_record_precheck"


# ── planner 快轨 ─────────────────────────────────────────────────────────


class _FakeShortMemoryPlanner:
    def __init__(self, thread_id: str) -> None:
        pass

    async def get_messages(self) -> list:
        return []


class TestPlannerFastTrack:
    def _plan(self, monkeypatch: pytest.MonkeyPatch, intents: list[dict], input_text: str = M2_SENTENCE) -> dict:
        monkeypatch.setattr(planner_mod, "ShortMemory", _FakeShortMemoryPlanner)

        def _no_llm(*args, **kwargs):
            raise AssertionError("preference_record 快轨不得消耗 LLM")

        monkeypatch.setattr(planner_mod, "planner_llm", _no_llm)
        state = {"intents": intents, "input": input_text, "short_memory": []}
        return asyncio.run(planner_mod.planner_node(state))

    def test_single_preference_record_plans_record_tool(self, monkeypatch):
        result = self._plan(
            monkeypatch,
            [
                {
                    "intent": "preference_record",
                    "confidence": 0.9,
                    "type": "primary",
                    "entities": {"statedPreference": "买包只买黑色的", "preferenceType": "color"},
                }
            ],
        )
        subtasks = result["task_plan"]["subtasks"]
        assert len(subtasks) == 1
        assert "recordUserPreference" in subtasks[0]["description"]
        assert "买包只买黑色的" in subtasks[0]["description"], "检测器抽取的明示偏好必须进子任务描述"

    def test_fast_track_desc_matches_executor_fast_path(self, monkeypatch):
        """端到端缝:快轨子任务描述必须被执行器确定性快路径直配成真工具调用
        (写路死教训:计划到不了工具 = 一切归零)。"""
        result = self._plan(
            monkeypatch,
            [
                {
                    "intent": "preference_record",
                    "confidence": 0.9,
                    "type": "primary",
                    "entities": {"statedPreference": "买包只买黑色的", "preferenceType": "color"},
                }
            ],
        )
        desc = result["task_plan"]["subtasks"][0]["description"]
        matched = try_match_executor_fast_path(desc, M2_SENTENCE, list(_base_executor_tools))
        assert matched is not None
        assert matched["toolName"] == "recordUserPreference"
        assert matched["args"]["preferenceValue"] == "买包只买黑色的"
        assert matched["args"]["preferenceType"] == "color"


# ── 对齐闸:白名单注册后记录子任务存活 ───────────────────────────────────


def _plan(*descriptions: str) -> dict:
    return {
        "goal": "test",
        "subtasks": [
            {"id": f"s{i}", "description": d, "status": "pending"} for i, d in enumerate(descriptions)
        ],
        "currentStepIndex": 0,
    }


class TestPlanAlignment:
    def test_record_step_survives_under_preference_record(self):
        plan = _plan(
            "Call recordUserPreference to record the customer's stated preference. Stated preference: 买包只买黑色的.",
            "Call searchProducts to search backpacks",
        )
        aligned, pruned = align_plan_to_intents(
            [{"intent": "preference_record", "confidence": 0.9}], plan, M2_SENTENCE
        )
        assert [s["id"] for s in aligned["subtasks"]] == ["s0", "s1"] or len(pruned) == 1
        assert aligned["subtasks"][0]["description"].startswith("Call recordUserPreference")

    def test_shopping_guide_alone_still_prunes_record_step(self):
        """白名单纪律:导购档位不得静默获得写工具 —— 复合形必须由注入器带上
        preference_record 才放行写路。"""
        plan = _plan("Call recordUserPreference to save preference")
        aligned, pruned = align_plan_to_intents(
            [{"intent": "shopping_guide", "confidence": 0.9}], plan, M2_SENTENCE
        )
        # 写步骤必剪;全剪后对齐闸的 step_aligned_fallback 兜底(plan_alignment
        # 既有行为)不夹带 recordUserPreference,写路不放行。
        assert pruned == ["Call recordUserPreference to save preference"]
        assert all(
            "recorduserpreference" not in str(st.get("description", "")).lower()
            for st in aligned["subtasks"]
        )


# ── 执行器快路径:statedPreference 消费 + 旧形状回归 ─────────────────────


class TestExecutorFastPathPreference:
    def test_stated_preference_in_description_wins_over_whole_input(self):
        desc = (
            "Call recordUserPreference to record the customer's stated preference. "
            "Customer said: 帮我记一下我的偏好:买包只买黑色的. Stated preference: 买包只买黑色的."
        )
        result = try_match_executor_fast_path(desc, M2_SENTENCE, ["recordUserPreference"])
        assert result == {
            "toolName": "recordUserPreference",
            "args": {"preferenceType": "color", "preferenceValue": "买包只买黑色的"},
        }

    def test_legacy_shape_falls_back_to_user_input(self):
        result = try_match_executor_fast_path(
            "The customer mentioned a preference to remember",
            "帮我记一下我的偏好:上衣穿L码",
            ["recordUserPreference"],
        )
        assert result is not None
        assert result["args"]["preferenceType"] == "size"
        assert result["args"]["preferenceValue"] == "帮我记一下我的偏好:上衣穿L码"

    def test_gate_requires_dispatch_whitelist(self):
        result = try_match_executor_fast_path("record the preference", "偏好黑色", [])
        assert result is None, "派发白名单不在册时快路径不得直配"


# ── finish 防假成功闸扩面 ────────────────────────────────────────────────


class TestFinishHonestyGate:
    def _capture_prompt(self, monkeypatch: pytest.MonkeyPatch) -> str:
        import engine_py.graph.nodes.finish as finish_mod

        captured: dict = {}

        class _Resp:
            content = "好的。"

        class _StubChat:
            async def ainvoke(self, prompt: str):
                captured["prompt"] = prompt
                return _Resp()

        monkeypatch.setattr(finish_mod, "get_chat_model", lambda: _StubChat())
        state = {
            "input": M2_SENTENCE,
            "business_config": {"businessId": "ecommerce"},
            "intents": [],
            "task_plan": {"subtasks": []},
            "short_memory": [{"role": "user", "content": M2_SENTENCE}],
            "global_transitions_count": 0,
            "tool_errors_count": 0,
        }
        asyncio.run(finish_mod.finish_node(state))
        assert "prompt" in captured
        return captured["prompt"]

    def test_prompt_carries_no_claim_without_tool_result_rule(self, monkeypatch):
        prompt = self._capture_prompt(monkeypatch)
        assert "recordUserPreference" in prompt
        assert "MUST NOT claim" in prompt, "防假成功闸必须落进终稿 CRITICAL RULES"


if __name__ == "__main__":
    pytest.main([__file__])
