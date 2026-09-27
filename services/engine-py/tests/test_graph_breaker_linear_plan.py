"""图级熔断阈值的合法计划回归(2026-09-27 事故)。

症状:aurora 实弹「把销量最好的裤子放到购物车，买2件」被 planner 拆成 5 步
(排行/加购/确认/改量/结算),全部绿执行(tool_errors=0),但转移计数按每子任务
双份累加(executor +1、validator +1,TS 基线同款),第 5 步末尾恰好到旧阈值 10
→ route/finish 双闸误判熔断,把技能层已算好的诚实回答截杀成道歉罐头。同问题
计划规模随会话历史 3→4→5 步爬升(转移 7→9→11),09-27 首次过线。

钉死契约:
- 合法线性计划(≤MAX_PLAN_STEPS 步)即使双计满额(2×10=20)也不得触发熔断;
- 熔断阈值 = 2×MAX_PLAN_STEPS+2,只拦真正失控;tool_errors ≥3 独立生效;
- 熔断道歉必须诚实:严禁谎称「已转接人工/1 分钟内接管」(熔断路径无任何
  转接动作),只可指引真实存在的「转人工」规则意图(rule_matchers)。
"""

from __future__ import annotations

import sys

import pytest

from engine_py.graph import build_graph as bg_fn  # 包层重导出 = 编译函数本身
from engine_py.graph.build_graph import (
    CIRCUIT_BREAKER_TOOL_ERRORS,
    CIRCUIT_BREAKER_TRANSITIONS,
    MAX_PLAN_STEPS,
    route_after_validator,
)
from engine_py.graph.nodes import executor as executor_mod
from engine_py.graph.nodes import finish as finish_mod
from engine_py.graph.state import AgentState

BG = sys.modules["engine_py.graph.build_graph"]


def _make_plan(n: int) -> dict:
    return {
        "goal": "Add the best-selling pants to the shopping cart and purchase two pieces",
        "subtasks": [
            {"id": f"st_{i}", "description": f"step {i}: do the cart thing", "status": "pending"}
            for i in range(1, n + 1)
        ],
        "currentStepIndex": 0,
    }


async def _triage_stub(_state):
    return {"intents": [{"intent": "cart_manage", "confidence": 0.95}]}


async def _planner_stub(_state):
    return {"task_plan": _make_plan(5)}


async def _execute_step_stub(state):
    """镜像 step_execution_engine 返回形状:恒绿结果 +1 转移;index 由 validator 推进。"""
    plan = dict(state.get("task_plan") or {})
    subtasks = [dict(st) for st in plan.get("subtasks") or []]
    idx = plan.get("currentStepIndex", 0)
    if 0 <= idx < len(subtasks):
        subtasks[idx] = {
            **subtasks[idx],
            "status": "completed",
            "result": {"output": f"step {idx + 1} ok", "success": True, "error": None},
        }
    return {
        "taskPlan": {**plan, "subtasks": subtasks, "currentStepIndex": idx},
        "globalTransitionsCount": 1,
    }


class _FakeModel:
    class _Resp:
        content = "关于「裤子」的销量排序我无法确定卖得最好的一款,店内在售 3 款裤子,请挑选。"

    async def ainvoke(self, _prompt):
        return self._Resp()


@pytest.fixture()
def stub_graph_leaves(monkeypatch):
    monkeypatch.setattr(BG, "triage_node", _triage_stub)
    monkeypatch.setattr(BG, "planner_node", _planner_stub)
    monkeypatch.setattr(executor_mod, "execute_step", _execute_step_stub)
    monkeypatch.setattr(finish_mod, "get_chat_model", lambda: _FakeModel())


def _base_state() -> AgentState:
    return {
        "input": "把销量最好的裤子放到购物车，买2件",
        "thread_id": "dbg_breaker_thread",
        "business_id": "aurora",  # 跳过 finish 的租户 DB 回查
        "global_transitions_count": 0,
        "tool_errors_count": 0,
    }


def test五步全绿计划不得触发熔断(stub_graph_leaves):
    """事故同形:5 子任务全绿线性计划(transitions 双计到 10)必须正常收尾,
    输出 finish 终稿而非熔断道歉。"""
    import asyncio

    graph = bg_fn()
    result = asyncio.run(graph.ainvoke(_base_state()))

    subtasks = (result.get("task_plan") or {}).get("subtasks") or []
    assert all(st.get("status") == "completed" for st in subtasks), "5 步应全部绿完成"
    assert (result.get("global_transitions_count") or 0) == 10, "executor+validator 双计每步 +2"
    assert (result.get("tool_errors_count") or 0) == 0
    output = str(result.get("output") or "")
    assert "熔断" not in output, "全绿计划严禁被熔断道歉截杀"
    assert "挑选" in output, "finish 终稿(LLM 罐头)应浮出"


def test阈值大于合法双计上限():
    """阈值语义:合法计划物理上限 = 2×MAX_PLAN_STEPS(全双计),熔断只拦失控。"""
    assert CIRCUIT_BREAKER_TRANSITIONS > 2 * MAX_PLAN_STEPS


def test路由失控转移仍拉闸():
    """超出合法上限的转移数仍须熔断 —— 护栏存在性钉死。"""
    state: AgentState = {
        "task_plan": {"subtasks": [{"id": "s1", "status": "pending"}], "currentStepIndex": 0},
        "global_transitions_count": CIRCUIT_BREAKER_TRANSITIONS,
        "tool_errors_count": 0,
    }
    assert route_after_validator(state) == "finish"


def test路由合法上限内放行():
    """合法双计满额(20)不构成熔断 —— 事故阈值与失控保护的分界。"""
    state: AgentState = {
        "task_plan": {
            "subtasks": [{"id": f"s{i}", "status": "pending"} for i in range(10)],
            "currentStepIndex": 0,
        },
        "global_transitions_count": 2 * MAX_PLAN_STEPS,
        "tool_errors_count": 0,
    }
    assert route_after_validator(state) == "executor"


def test路由工具错误仍拉闸():
    state: AgentState = {
        "task_plan": {"subtasks": [{"id": "s1", "status": "pending"}], "currentStepIndex": 0},
        "global_transitions_count": 0,
        "tool_errors_count": CIRCUIT_BREAKER_TOOL_ERRORS,
    }
    assert route_after_validator(state) == "finish"


def test熔断道歉诚实不含虚假转接承诺():
    """熔断文案诚实纪律:严禁「已转接/1 分钟内接管」空头承诺(实弹:顾客等人工
    永远等不到,assigned_operator_id 全程未变);只可指引真实「转人工」意图。"""
    import asyncio

    state: AgentState = {
        "input": "把销量最好的裤子放到购物车，买2件",
        "thread_id": "dbg_breaker_thread",
        "business_id": "aurora",
        "global_transitions_count": CIRCUIT_BREAKER_TRANSITIONS,
        "tool_errors_count": 0,
    }
    result = asyncio.run(finish_mod.finish_node(state))
    output = str(result.get("output") or "")
    assert "转人工" in output, "必须指引真实的转人工通道"
    assert "转接至特级" not in output
    assert "已自动转接" not in output
    assert "1 分钟内" not in output and "1分钟内" not in output
