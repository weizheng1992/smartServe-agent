"""执行节点 — 镜像 executor.node.ts(薄包装,逻辑全在 StepExecutionEngine)。"""

from __future__ import annotations

from ...llm import bind_llm_call_node
from ..state import AgentState
from .step_execution_engine import execute_step


async def executor_node(state: AgentState) -> dict:
    bind_llm_call_node("executor")
    result = await execute_step(dict(state))
    update: dict = {
        "task_plan": result["taskPlan"],
        "global_transitions_count": result["globalTransitionsCount"],
    }
    if "shortMemory" in result:
        update["short_memory"] = result["shortMemory"]
    if "toolErrorsCount" in result:
        update["tool_errors_count"] = result["toolErrorsCount"]
    return update
