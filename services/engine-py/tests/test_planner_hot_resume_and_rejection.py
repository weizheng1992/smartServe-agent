"""planner HITL 恢复契约(HOT-RESUME 计划保全 + 管理员驳回回溯)。

夜审 2026-10-02 测试缺口③④(planner.py 两大恢复分支此前零覆盖):
- HOT-RESUME(Plan-Preservation Bypass):审批已决议(approved/cancelled/
  resolved_by_human)→ 100% 复用历史计划对象、跳过大模型规划、零 LLM;
  审批未决议(waiting)不得旁路;
- 驳回回溯(Cognitive State Backtracking):System: 恢复语 + 最新工单
  rejected → 当前步标 failed/rejectedByAdmin + 驳回原因入步结果,注入
  [CRITICAL ADVISORY] 重规划上下文,且快轨被禁(必须走 LLM 深规划)。

全程打桩 approval 查询与 get_chat_model,零 DB / 零 LLM。
"""

from __future__ import annotations

import asyncio
from contextlib import contextmanager

from engine_py.graph.nodes.planner import planner_node


@contextmanager
def _fake_planner_llm(content: str | None = None):
    """打桩 planner.get_chat_model,返回 prompt 收集列表供零 LLM 断言。"""
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


def _state(**kwargs) -> dict:
    base = {"intents": [], "input": "", "short_memory": [{"role": "user", "content": "你好"}]}
    base.update(kwargs)
    return base


def _plan_with_waiting_step(approval_id: str) -> dict:
    return {
        "goal": "退款 ORD-1",
        "currentStepIndex": 0,
        "subtasks": [
            {
                "id": "s1",
                "description": "Call processRefund for order ORD-1",
                "status": "pending",
                "result": {"waitingForApproval": True, "approvalId": approval_id},
            }
        ],
    }


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


# ---------- HOT-RESUME:决议即 100% 复用历史计划 ----------


def test_hot_resume_approved_reuses_prior_plan_zero_llm(monkeypatch):
    _patch_approval(monkeypatch, {"id": "a1", "status": "approved", "actionPayload": {}})
    prior_plan = _plan_with_waiting_step("a1")
    with _fake_planner_llm("must not be called") as calls:
        result = asyncio.run(
            planner_node(
                _state(
                    intents=[{"intent": "refund"}],
                    input="System: Human approval granted. Please execute the requested action.",
                    task_plan=prior_plan,
                    thread_id="t-hot-resume",
                )
            )
        )
    assert result["task_plan"] is prior_plan, "HOT-RESUME 必须原对象复用历史计划"
    assert result["global_transitions_count"] == 1
    assert calls == [], "决议旁路不得消耗 LLM"


def test_hot_resume_cancelled_and_human_resolved(monkeypatch):
    """cancel / resolved_by_human 同闸复用(决议三态闭集)。"""
    for status in ("cancelled", "resolved_by_human"):
        _patch_approval(monkeypatch, {"id": "a1", "status": status, "actionPayload": {}})
        prior_plan = _plan_with_waiting_step("a1")
        with _fake_planner_llm("must not be called") as calls:
            result = asyncio.run(
                planner_node(
                    _state(
                        intents=[{"intent": "refund"}],
                        input="System: Human approval cancelled by the user.",
                        task_plan=prior_plan,
                        thread_id="t-hot-resume",
                    )
                )
            )
        assert result["task_plan"] is prior_plan and calls == [], status


def test_hot_resume_not_fired_when_approval_still_waiting(monkeypatch):
    """未决议(waiting)不得旁路 —— 否则挂起工单被静默跳过执行。"""
    _patch_approval(monkeypatch, {"id": "a1", "status": "waiting", "actionPayload": {}})
    prior_plan = _plan_with_waiting_step("a1")
    with _fake_planner_llm(None) as calls:  # 脏输出 → per-intent 兜底计划,形状不在此断言
        result = asyncio.run(
            planner_node(
                _state(
                    intents=[{"intent": "refund"}],
                    input="继续",
                    task_plan=prior_plan,
                    thread_id="t-hot-resume",
                )
            )
        )
    assert len(calls) == 1, "未决议必须走深规划"
    assert result["task_plan"] is not prior_plan


# ---------- 驳回回溯:rejected → 标步 + ADVISORY 重规划 ----------


def test_rejection_backtracks_step_and_injects_advisory(monkeypatch):
    reason = "单笔超限,需人工复核"
    _patch_approval(monkeypatch, {"id": "a1", "status": "rejected", "actionPayload": {"rejectionReason": reason}})
    prior_plan = _plan_with_waiting_step("a1")
    with _fake_planner_llm(None) as calls:
        asyncio.run(
            planner_node(
                _state(
                    intents=[{"intent": "refund"}],
                    input="System: Human approval rejected. Reason: 单笔超限. Please replan alternative path.",
                    task_plan=prior_plan,
                    thread_id="t-reject",
                )
            )
        )
    step = prior_plan["subtasks"][0]
    assert step["status"] == "failed", "驳回必须把当前步标 failed"
    assert step["result"]["rejectedByAdmin"] is True
    assert step["result"]["rejectionReason"] == reason
    assert len(calls) == 1, "驳回上下文禁用快轨,必须深规划"
    assert "REJECTED by the Administrator" in calls[0]
    assert reason in calls[0], "驳回原因必须进入重规划提示词"


def test_rejected_approval_without_system_resume_no_backtrack(monkeypatch):
    """非 System: 恢复语(普通新问句)不触发回溯改步。"""
    reason = "单笔超限"
    _patch_approval(monkeypatch, {"id": "a1", "status": "rejected", "actionPayload": {"rejectionReason": reason}})
    prior_plan = _plan_with_waiting_step("a1")
    with _fake_planner_llm(None) as calls:
        asyncio.run(
            planner_node(
                _state(
                    intents=[{"intent": "refund"}],
                    input="帮我退款 ORD-1",
                    task_plan=prior_plan,
                    thread_id="t-reject",
                )
            )
        )
    step = prior_plan["subtasks"][0]
    assert "rejectedByAdmin" not in (step.get("result") or {})
    assert calls == [], "无驳回上下文时等待中的步可走快轨/旁路,不强制深规划"
