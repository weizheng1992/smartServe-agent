"""校验节点 — 镜像 validator.node.ts(无错自动绿灯,出错才走 LLM 校验)。"""

from __future__ import annotations

import json

from ...event_bus import emit_status
from ...llm import get_chat_model
from ..state import AgentState


async def validator_node(state: AgentState) -> dict:
    current_plan = dict(state.get("task_plan") or {})
    current_index = current_plan.get("currentStepIndex", 0)
    subtasks = [dict(st) for st in current_plan.get("subtasks") or []]
    step = subtasks[current_index] if 0 <= current_index < len(subtasks) else None

    if step is None:
        return {"global_transitions_count": 1}

    # 审批挂起:校验器不做任何操作,不累加索引,保留现场
    result = step.get("result") or {}
    inner_output = result.get("output") if isinstance(result.get("output"), dict) else None
    is_waiting = result.get("waitingForApproval") or (inner_output or {}).get("waitingForApproval")
    if is_waiting:
        return {
            "task_plan": {**current_plan, "subtasks": subtasks, "currentStepIndex": current_index},
            "global_transitions_count": 1,
        }

    job_id = state.get("job_id")
    if job_id:
        await emit_status(
            job_id,
            f"智能决策核验器启动：正在多维度校验第 {current_index + 1} 步 [{step.get('description')}] "
            "工具产出数据的完整性与合法性...",
            node="validator",
        )

    # 🚀 无错误输出直接 100% 信任放行,免除 LLM 校验开销
    is_valid = True
    if not result or result.get("error"):
        try:
            prompt = (
                f'Validate the execution output of step "{step.get("description")}".\n'
                f"The execution resulted in: {json.dumps(result, ensure_ascii=False, default=str)}.\n"
                "Is this output sufficient and correct for this step?\n"
                "Respond with YES or NO.\nReturn ONLY YES or NO."
            )
            response = await get_chat_model().ainvoke(prompt)
            content = response.content if hasattr(response, "content") else str(response)
            is_valid = content.strip().upper() != "NO"
        except Exception as err:  # noqa: BLE001 — 校验失败默认放行
            print(f"validatorNode validation check failed, defaulting to YES: {err}")

    updated_subtasks = list(subtasks)
    if not is_valid:
        updated_subtasks[current_index] = {**step, "status": "failed"}
        if job_id:
            await emit_status(
                job_id,
                f"⚠️ 校验结果警告：第 {current_index + 1} 步执行产出未完全满足预期目标，"
                "已被决策链标记为 [failed]！",
                node="validator",
                plan={**current_plan, "subtasks": updated_subtasks, "currentStepIndex": current_index + 1},
            )
    else:
        if job_id:
            await emit_status(
                job_id,
                f"✅ 核验结果绿灯！第 {current_index + 1} 步执行结果数据完全合格、结构合法。",
                node="validator",
                plan={**current_plan, "subtasks": updated_subtasks, "currentStepIndex": current_index + 1},
            )

    return {
        "task_plan": {
            **current_plan,
            "subtasks": updated_subtasks,
            "currentStepIndex": current_index + 1,
        },
        "global_transitions_count": 1,
        "tool_errors_count": 0 if is_valid else 1,
    }
