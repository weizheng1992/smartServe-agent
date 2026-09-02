"""build_graph — 六节点 DAG,路由判定逐边对齐 packages/engine/src/graph/buildGraph.ts。

::

    START → triage
    triage    →(条件) planner | finish
    planner   → merge → executor → validator
    validator →(条件) executor | planner | finish
    finish    → END

triage 路由:无意图 / 唯一意图为 general_query / output 已置(旁路直达)/
taskPlan.subtasks[0].id === 'bypass_step' → finish。

validator 路由(与 TS 同序判定):
1. 熔断:globalTransitionsCount ≥ 10 或 toolErrorsCount ≥ 3 → finish
2. 任一子任务 waitingForApproval → finish(HITL 安全挂起)
3. 任一子任务 failed + rejectedByAdmin 且未 replanned → planner(认知回溯;
   replanned 标记由 planner 节点完成 —— Python 图路由不可变更状态)
4. currentStepIndex ≥ len(subtasks) 或 ≥ 10 → finish
5. 其余 → executor
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from .nodes import executor_node, finish_node, merge_node, planner_node, triage_node, validator_node
from .state import AgentState

CIRCUIT_BREAKER_TRANSITIONS = 10
CIRCUIT_BREAKER_TOOL_ERRORS = 3
MAX_PLAN_STEPS = 10


def route_after_triage(state: AgentState) -> str:
    intents = state.get("intents") or []
    if not intents:
        return "finish"
    if len(intents) == 1 and intents[0].get("intent") == "general_query":
        return "finish"
    subtasks = (state.get("task_plan") or {}).get("subtasks") or []
    if state.get("output") or (subtasks and subtasks[0].get("id") == "bypass_step"):
        return "finish"
    return "planner"


def route_after_validator(state: AgentState) -> str:
    subtasks = (state.get("task_plan") or {}).get("subtasks") or []
    next_index = (state.get("task_plan") or {}).get("currentStepIndex", 0)

    if (state.get("global_transitions_count") or 0) >= CIRCUIT_BREAKER_TRANSITIONS:
        return "finish"
    if (state.get("tool_errors_count") or 0) >= CIRCUIT_BREAKER_TOOL_ERRORS:
        return "finish"
    if any((st.get("result") or {}).get("waitingForApproval") for st in subtasks):
        return "finish"
    if any(
        st.get("status") == "failed"
        and (st.get("result") or {}).get("rejectedByAdmin")
        and not (st.get("result") or {}).get("replanned")
        for st in subtasks
    ):
        return "planner"
    if next_index >= len(subtasks) or next_index >= MAX_PLAN_STEPS:
        return "finish"
    return "executor"


def build_graph():
    graph = StateGraph(AgentState)

    graph.add_node("triage", triage_node)
    graph.add_node("planner", planner_node)
    graph.add_node("merge", merge_node)
    graph.add_node("executor", executor_node)
    graph.add_node("validator", validator_node)
    graph.add_node("finish", finish_node)

    graph.add_edge(START, "triage")
    graph.add_conditional_edges("triage", route_after_triage, {"planner": "planner", "finish": "finish"})
    graph.add_edge("planner", "merge")
    graph.add_edge("merge", "executor")
    graph.add_edge("executor", "validator")
    graph.add_conditional_edges(
        "validator",
        route_after_validator,
        {"executor": "executor", "planner": "planner", "finish": "finish"},
    )
    graph.add_edge("finish", END)

    return graph.compile()
