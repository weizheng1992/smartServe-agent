"""校验节点 — 镜像 packages/engine/src/graph/nodes/validator.node.ts(114 LOC)。

TODO(Phase 1b) 移植:
- 子任务执行结果校验(通过 / 重试 / 回溯到 planner)
- rejected_by_admin 认知回溯标记(配合 replanned_after_rejection)
- tool_errors 计数与 tool 事件透传
"""

from __future__ import annotations

from ..state import AgentState
from ...event_bus import emit


async def validator_node(state: AgentState) -> dict:
    job_id = state.get("job_id", "")
    await emit(job_id, "thought", {"jobId": job_id, "step": "正在校验执行结果..."})

    # 骨架:不否决任何结果,交由 route_after_validator 依计数路由
    return {}
