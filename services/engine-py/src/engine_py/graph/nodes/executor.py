"""执行节点 — 镜像 stepExecutionEngine.ts(632 LOC)+ executorFastPath.ts。

当前为过渡实现:只推进循环计数与进度事件,真实调度(SkillRegistry 优先 /
工具注册表回退 / dependencies 并行 / HITL 挂起)随 Phase 1b executor 批次替换。

TODO(Phase 1b) 移植:
- SkillRegistry 优先调度(5 个 BaseSkill 子类:SOP 校验 / pre / execute / post
  管道与租户阈值覆写 getEffectiveConfig / getEffectiveApprovalThreshold)
- 无匹配 Skill 时回退工具注册表分发(20 个工具,ToolExecutionContext 注入租户)
- 按 dependencies 数组并行执行(TS 为 Promise.allSettled)
- HITL 挂起:requiresApproval 动作写入 pending_approvals + approval_outbox_events
  同事务原子提交,置 waitingForApproval 并发 approval_required 事件
"""

from __future__ import annotations

from ...event_bus import emit_status
from ..state import AgentState


async def executor_node(state: AgentState) -> dict:
    job_id = state.get("job_id")
    if job_id:
        await emit_status(job_id, "正在执行任务步骤...", node="executor")

    return {"global_transitions_count": 1}
