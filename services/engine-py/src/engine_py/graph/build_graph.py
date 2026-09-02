"""build_graph — 六节点 DAG,拓扑逐边对齐 packages/engine/src/graph/buildGraph.ts。

::

    START → triage
    triage    →(条件) planner | finish    # 无意图 / 仅寒暄 / bypass_step → finish
    planner   → merge → executor → validator
    validator →(条件) executor | planner | finish
    finish    → END

validator 路由(与 TS 条件边同序判定):
1. 熔断:global_transitions ≥ 10 或 tool_errors ≥ 3 → finish
2. HITL 挂起:waiting_for_approval → finish(经 approval outbox 确定性恢复)
3. 子任务耗尽:next_index ≥ len(subtasks) 或 ≥ 10 → finish
4. 认知回溯:rejected_by_admin 且尚未重规划 → planner
5. 其余 → executor(继续执行下一子任务)
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from .nodes import executor_node, finish_node, merge_node, planner_node, triage_node, validator_node
from .state import AgentState

CIRCUIT_BREAKER_TRANSITIONS = 10
CIRCUIT_BREAKER_TOOL_ERRORS = 3
MAX_SUBTASKS = 10


def route_after_triage(state: AgentState) -> str:
    intents = state.get("intents") or []
    bypass = bool(state.get("bypass_step")) or bool(state.get("general_query_only"))
    if not intents or bypass:
        return "finish"
    return "planner"


def route_after_validator(state: AgentState) -> str:
    if state.get("global_transitions", 0) >= CIRCUIT_BREAKER_TRANSITIONS:
        return "finish"
    if state.get("tool_errors", 0) >= CIRCUIT_BREAKER_TOOL_ERRORS:
        return "finish"
    if state.get("waiting_for_approval"):
        return "finish"
    subtasks = state.get("subtasks") or []
    if state.get("next_index", 0) >= len(subtasks) or state.get("next_index", 0) >= MAX_SUBTASKS:
        return "finish"
    if state.get("rejected_by_admin") and not state.get("replanned_after_rejection"):
        return "planner"
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
