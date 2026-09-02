"""计划合并节点 — 镜像 packages/engine/src/graph/nodes/merge.node.ts(18 LOC,轻量)。

将 planner 产出的任务规划展开为待执行子任务序列。
"""

from __future__ import annotations

from ..state import AgentState


async def merge_node(state: AgentState) -> dict:
    return {"subtasks": list(state.get("task_plan") or [])}
