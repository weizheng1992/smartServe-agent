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
    # 候选上下文上行(2026-09-12):技能 extra 或 searchProducts 工具结果刷新的
    # guideContext 必须回写图状态,否则 run_agent 收口把上一轮 stale 候选原样
    # 存回 TaskMemory,下一轮加购序数解析到旧候选(幻影 Nike 入车症状)。
    if result.get("guideContext") is not None:
        update["guide_context"] = result["guideContext"]
    return update
