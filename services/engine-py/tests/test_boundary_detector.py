"""任务边界判定器(docs/multi-turn-task-state.md P1-1,2026-10-24 grilling D2)。

判定本体在 triage LLM 结构化输出(boundary 字段,与意图分类同源零额外调用);
本套测消费侧两条决策链的纯逻辑与 planner 缝:
- resolve_boundary_action:低置信 → 澄清(fail 方向=澄清,严禁默认重规划);
- planner Boundary-Preserve:高置信 modify → 保留既有计划零 LLM;四道门禁
  (System 轮/驳回上下文/审批挂起步/计划不在场)逐一钉死。

全程打桩,零 DB / 零 LLM。
"""

from __future__ import annotations

import asyncio
from contextlib import contextmanager

import pytest

from engine_py.graph.nodes.planner import planner_node
from engine_py.triage.intent_triage_engine import resolve_boundary_action

# ── 桩夹具(tests 非包,从 test_planner_hot_resume_and_rejection 本地复制)──


@contextmanager
def _fake_planner_llm(content: str | None = None):
    from engine_py.graph.nodes import planner as pl

    calls: list[str] = []

    class _Bound:
        async def ainvoke(self, prompt: str):
            calls.append(prompt)
            return type("Resp", (), {"content": content})()

    class _Model:
        def bind(self, **_kwargs) -> _Bound:
            return _Bound()

    original = pl.get_chat_model
    pl.get_chat_model = lambda: _Model()
    try:
        yield calls
    finally:
        pl.get_chat_model = original


def _patch_approval(monkeypatch, by_id_result, *, forbid_thread_lookup: bool = True):
    from engine_py.graph.nodes import planner as pl

    async def _by_id(approval_id):
        if isinstance(by_id_result, Exception):
            raise by_id_result
        return by_id_result

    async def _by_thread(thread_id):
        if forbid_thread_lookup:
            raise AssertionError("有 approvalId 时不得走线程级兜底查询")
        return by_id_result

    monkeypatch.setattr(pl, "find_approval_by_id", _by_id)
    monkeypatch.setattr(pl, "find_latest_approval_by_thread_id", _by_thread)


def _state(**kwargs) -> dict:
    base = {"intents": [], "input": "", "short_memory": [{"role": "user", "content": "你好"}]}
    base.update(kwargs)
    return base


def _b(decision: str = "modify", confidence: float = 0.9) -> dict:
    return {"decision": decision, "confidence": confidence, "rationale": "仅改日期", "entitiesChanged": ["date"]}


class TestResolveBoundaryAction:
    def test_low_confidence_clarifies(self):
        assert resolve_boundary_action(_b(confidence=0.4), history_turns=4, enabled=True, threshold=0.6) == "clarify"

    def test_confident_passes_both_directions(self):
        for decision in ("modify", "new"):
            b = _b(decision=decision, confidence=0.9)
            assert resolve_boundary_action(b, history_turns=4, enabled=True, threshold=0.6) == "pass"

    def test_abstain_none_passes(self):
        assert resolve_boundary_action(None, history_turns=4, enabled=True, threshold=0.6) == "pass"

    def test_no_prior_turns_never_clarifies(self):
        """无前文=无前任务:prompt 要求省略,模型违约也不澄清首问(防御)。"""
        assert resolve_boundary_action(_b(confidence=0.1), history_turns=0, enabled=True, threshold=0.6) == "pass"

    def test_disabled_passes(self):
        assert resolve_boundary_action(_b(confidence=0.1), history_turns=4, enabled=False, threshold=0.6) == "pass"

    def test_bad_confidence_passes(self):
        assert resolve_boundary_action(_b(confidence="高"), history_turns=4, enabled=True, threshold=0.6) == "pass"


class TestBoundaryEvalScoring:
    """评测跑分器纯函数(docs §4.3):评分口径即验收口径,钉死防漂移。"""

    def test_loader_skips_blank_and_bad_lines(self, tmp_path):
        from engine_py.evals.run_boundary_eval import load_boundary_cases

        p = tmp_path / "cases.jsonl"
        p.write_text(
            '{"input": "改周四", "expect": "modify"}\n\n不是json\n'
            '{"input": "查物流", "expect": "new"}\n',
            encoding="utf-8",
        )
        cases = load_boundary_cases(p)
        assert [c["expect"] for c in cases] == ["modify", "new"]

    def test_score_modify_hit_and_miss(self):
        from engine_py.evals.run_boundary_eval import score_boundary_case

        case = {"expect": "modify"}
        ok, _ = score_boundary_case(case, {"decision": "modify", "confidence": 0.9}, 0.6)
        assert ok
        ok, _ = score_boundary_case(case, {"decision": "new", "confidence": 0.9}, 0.6)
        assert not ok
        ok, _ = score_boundary_case(case, {"decision": "modify", "confidence": 0.3}, 0.6)
        assert not ok, "低置信 modify 下游会澄清,不算命中"
        ok, _ = score_boundary_case(case, None, 0.6)
        assert not ok

    def test_score_clarify_low_conf_or_abstain(self):
        from engine_py.evals.run_boundary_eval import score_boundary_case

        case = {"expect": "clarify"}
        ok, _ = score_boundary_case(case, {"decision": "modify", "confidence": 0.3}, 0.6)
        assert ok
        ok, _ = score_boundary_case(case, None, 0.6)
        assert not ok, "弃权=运行时不澄清,评分与被测行为一致,严禁放水(code-review 裁定)"
        ok, _ = score_boundary_case(case, {"decision": "new", "confidence": 0.9}, 0.6)
        assert not ok, "模糊例给了高置信 = 误判"

    def test_route_key_boundary_clarify_maps_to_clarify(self):
        """boundary_clarify 靠 clarif 子串落 clarify 桶 —— 改名即静默漂到
        bypass_other 使健康度指标失真,此测试钉死映射(code-review 裁定)。"""
        from engine_py.triage.intent_triage_engine import turn_path_for_route

        assert turn_path_for_route("boundary_clarify") == "clarify"

    def test_format_history_shape(self):
        from engine_py.evals.run_boundary_eval import format_history

        text = format_history(
            [{"role": "user", "content": "订酒店"}, {"role": "assistant", "content": "已列出"}]
        )
        assert "User: 订酒店" in text and "Assistant: 已列出" in text


def _plan_in_progress() -> dict:
    """进行中计划:首步已完成,当前步普通 pending(无审批旗标)。"""
    return {
        "goal": "上海行程",
        "currentStepIndex": 1,
        "subtasks": [
            {"id": "s1", "description": "查周三高铁", "status": "completed"},
            {"id": "s2", "description": "订周三酒店", "status": "pending"},
        ],
    }


class TestPlannerBoundaryPreserve:
    def test_boundary_modify_preserves_plan_zero_llm(self, monkeypatch):
        _patch_approval(monkeypatch, None, forbid_thread_lookup=False)
        prior_plan = _plan_in_progress()
        with _fake_planner_llm("must not be called") as calls:
            result = asyncio.run(
                planner_node(
                    _state(
                        intents=[{"intent": "cart_manage", "confidence": 0.9}],
                        input="不是周三,改周四",
                        task_plan=prior_plan,
                        boundary=_b(),
                        thread_id="t-boundary",
                    )
                )
            )
        assert result["task_plan"] is prior_plan, "Boundary-Preserve 必须原对象复用既有计划"
        assert result["global_transitions_count"] == 1
        assert calls == [], "modify 保留分支不得消耗 LLM"

    def test_boundary_new_keeps_replanning(self, monkeypatch):
        """new = 现状重规划(裁决 D2 不改 new 分支行为)。意图用 refund(无
        快轨命中),general_query 会撞极简旁路测不到深规划。"""
        _patch_approval(monkeypatch, None, forbid_thread_lookup=False)
        prior_plan = _plan_in_progress()
        with _fake_planner_llm(None) as calls:
            result = asyncio.run(
                planner_node(
                    _state(
                        intents=[{"intent": "refund", "confidence": 0.9}],
                        input="这个月信用卡花了多少",
                        task_plan=prior_plan,
                        boundary=_b(decision="new"),
                        thread_id="t-boundary-new",
                    )
                )
            )
        assert len(calls) == 1, "new 分支必须走深规划"
        assert result["task_plan"] is not prior_plan

    def test_boundary_low_confidence_no_preserve(self, monkeypatch):
        _patch_approval(monkeypatch, None, forbid_thread_lookup=False)
        prior_plan = _plan_in_progress()
        with _fake_planner_llm(None) as calls:
            asyncio.run(
                planner_node(
                    _state(
                        intents=[{"intent": "cart_manage", "confidence": 0.9}],
                        input="顺便帮我看看别的",
                        task_plan=prior_plan,
                        boundary=_b(confidence=0.3),
                        thread_id="t-boundary-low",
                    )
                )
            )
        assert len(calls) == 1, "低置信不保留(澄清在 triage 层发生,planner 只认高置信)"

    def test_boundary_inert_without_prior_plan(self, monkeypatch):
        """计划不在场 → 门禁放行深规划(接线票落地前 modify 天然 inert)。"""
        _patch_approval(monkeypatch, None, forbid_thread_lookup=False)
        with _fake_planner_llm(None) as calls:
            asyncio.run(
                planner_node(
                    _state(
                        intents=[{"intent": "cart_manage", "confidence": 0.9}],
                        input="不是周三,改周四",
                        boundary=_b(),
                        thread_id="t-boundary-empty",
                    )
                )
            )
        assert len(calls) == 1

    def test_system_resume_not_hijacked(self, monkeypatch):
        """System: 恢复轮不受边界判定支配(HITL 保存/驳回回溯自有语义)。"""
        _patch_approval(monkeypatch, {"id": "a1", "status": "waiting", "actionPayload": {}})
        prior_plan = _plan_in_progress()
        with _fake_planner_llm(None) as calls:
            asyncio.run(
                planner_node(
                    _state(
                        intents=[{"intent": "refund", "confidence": 0.9}],
                        input="System: Resume after approval wait.",
                        task_plan=prior_plan,
                        boundary=_b(),
                        thread_id="t-boundary-sys",
                    )
                )
            )
        assert len(calls) == 1, "System 轮严禁被 Boundary-Preserve 抢道"

    def test_waiting_approval_step_not_hijacked(self, monkeypatch):
        """当前步挂审批 → 审批通道轮自有决议语义,Boundary-Preserve 不抢。"""
        _patch_approval(monkeypatch, {"id": "a1", "status": "waiting", "actionPayload": {}})
        prior_plan = _plan_in_progress()
        prior_plan["subtasks"][1]["result"] = {"waitingForApproval": True, "approvalId": "a1"}
        with _fake_planner_llm(None) as calls:
            asyncio.run(
                planner_node(
                    _state(
                        intents=[{"intent": "refund", "confidence": 0.9}],
                        input="改一下金额",
                        task_plan=prior_plan,
                        boundary=_b(),
                        thread_id="t-boundary-waiting",
                    )
                )
            )
        assert len(calls) == 1, "审批挂起步严禁被 Boundary-Preserve 跳过"

    def test_threshold_from_settings(self, monkeypatch):
        """阈值读 settings(AI_BOUNDARY_CONFIDENCE_THRESHOLD 可配);冻结
        dataclass 用 object.__setattr__ 打点并复原。"""
        from engine_py.graph.nodes import planner as pl

        real = pl.settings.boundary_confidence_threshold
        object.__setattr__(pl.settings, "boundary_confidence_threshold", 0.95)
        try:
            _patch_approval(monkeypatch, None, forbid_thread_lookup=False)
            prior_plan = _plan_in_progress()
            with _fake_planner_llm(None) as calls:
                asyncio.run(
                    planner_node(
                        _state(
                            intents=[{"intent": "cart_manage", "confidence": 0.9}],
                            input="不是周三,改周四",
                            task_plan=prior_plan,
                            boundary=_b(confidence=0.9),
                            thread_id="t-boundary-thr",
                        )
                    )
                )
            assert len(calls) == 1, "阈值调高后 0.9 不再够格保留"
        finally:
            object.__setattr__(pl.settings, "boundary_confidence_threshold", real)


if __name__ == "__main__":
    pytest.main([__file__])
