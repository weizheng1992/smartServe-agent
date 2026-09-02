"""任务规划节点 — 镜像 packages/engine/src/graph/nodes/planner.node.ts(470 LOC)。

TODO(Phase 1b) 移植:
- LLM 规划(prompt 对齐 eval/prompts/planner_prompt.txt,expectedTools 契约
  由 promptfoo planner 基线钉死)
- 步骤 dependencies 依赖数组声明(供 executor 并行调度)
- 多意图子任务拆分与合并
"""

from __future__ import annotations

from ..state import AgentState
from ...event_bus import emit


async def planner_node(state: AgentState) -> dict:
    job_id = state.get("job_id", "")
    await emit(job_id, "thought", {"jobId": job_id, "step": "正在规划任务执行方案..."})

    # 骨架:空规划;validator 将按「子任务耗尽」路由到 finish
    return {"task_plan": [], "next_index": 0}
