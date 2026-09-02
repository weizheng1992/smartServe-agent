"""任务规划节点 — 镜像 planner.node.ts(470 LOC)。

本文件当前为过渡实现:先承担「驳回步骤重规划受理标记」(TS 版在 validator
路由函数里做的状态标记,Python 图路由不可变更状态,移到本节点等价完成),
LLM 规划逻辑随 Phase 1b planner 批次替换。

TODO(Phase 1b) 移植:
- LLM 规划(prompt 对齐 eval/prompts/planner_prompt.txt,expectedTools 契约
  由 promptfoo planner 基线钉死)
- 步骤 dependencies 依赖数组声明(供 executor 并行调度)
- 多意图子任务拆分与合并
"""

from __future__ import annotations

from ...event_bus import emit_status
from ..state import AgentState


def _mark_rejected_subtasks_replanned(plan: dict) -> dict | None:
    """把 failed + rejectedByAdmin 且未受理的子任务标记为 replanned,防止无限回溯循环。"""
    subtasks = [dict(st) for st in plan.get("subtasks") or []]
    changed = False
    for st in subtasks:
        result = st.get("result") or {}
        if st.get("status") == "failed" and result.get("rejectedByAdmin") and not result.get("replanned"):
            result["replanned"] = True
            st["result"] = result
            changed = True
    return {**plan, "subtasks": subtasks} if changed else None


async def planner_node(state: AgentState) -> dict:
    job_id = state.get("job_id")
    if job_id:
        await emit_status(job_id, "正在规划任务执行方案...", node="planner")

    plan = state.get("task_plan") or {}
    replanned = _mark_rejected_subtasks_replanned(plan)
    if replanned is not None:
        return {"task_plan": replanned}

    # TODO(Phase 1b): LLM 任务规划(空规划时 validator 将按「步数耗尽」路由 finish)
    return {}
