"""计划合并节点 — 镜像 merge.node.ts(轻量透平,保留子任务原序)。"""

from __future__ import annotations

from ..state import AgentState


async def merge_node(state: AgentState) -> dict:
    current_plan = state.get("task_plan") or {}
    return {"task_plan": {**current_plan, "subtasks": list(current_plan.get("subtasks") or [])}}
