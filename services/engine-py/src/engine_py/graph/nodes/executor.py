"""执行节点 — 镜像 stepExecutionEngine.ts(632 LOC)+ executorFastPath.ts(183 LOC)。

TODO(Phase 1b) 移植:
- SkillRegistry 优先调度(5 个 BaseSkill 子类:SOP 校验 / pre / execute / post
  管道与租户阈值覆写 getEffectiveConfig / getEffectiveApprovalThreshold)
- 无匹配 Skill 时回退工具注册表分发(20 个工具,ToolExecutionContext 注入租户)
- 按 dependencies 数组 Promise.allSettled 并行执行
- HITL 挂起:requiresApproval 动作写入 pending_approvals + approval_outbox_events
  同事务原子提交,置 waiting_for_approval 并发 approval_required 事件
"""

from __future__ import annotations

from ..state import AgentState
from ...event_bus import emit


async def executor_node(state: AgentState) -> dict:
    job_id = state.get("job_id", "")
    await emit(job_id, "thought", {"jobId": job_id, "step": "正在执行任务步骤..."})

    # 骨架:仅推进循环计数;真实调度逻辑 Phase 1b 移植
    return {"global_transitions": state.get("global_transitions", 0) + 1}
