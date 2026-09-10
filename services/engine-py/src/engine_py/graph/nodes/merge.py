"""计划合并节点 — 镜像 merge.node.ts(轻量透平,保留子任务原序)。"""

from __future__ import annotations

from ...llm import bind_llm_call_node
from ..state import AgentState


async def merge_node(state: AgentState) -> dict:
    bind_llm_call_node("merge")  # 无 LLM 调用,防前一节点归因串味
    current_plan = state.get("task_plan") or {}
    return {"task_plan": {**current_plan, "subtasks": list(current_plan.get("subtasks") or [])}}
