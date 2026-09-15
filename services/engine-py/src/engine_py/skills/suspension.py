"""HITL 挂起缝 — 工单创建、挂起计划立即落库、响应组装的唯一实现。

wayfinder 004 不变量:审批工单对前端轮询可见的瞬间,恢复计划必须已在
TaskMemory —— 秒级核签派发的恢复任务若读到空计划,挂起操作静默丢失
(2026-09-12 实弹:approve 成功而地址未变)。该不变量的实现此前散在两处
(step 执行引擎一处;改址技能高价值分支的一份是 return 之后的永不可达死
代码),技能快轨路径的落库实际靠 run_agent 回合收口事后兜底,竞态窗口
真实存在。本模块把三件事收进一条缝:开工单 → 挂起瞬间落库 → 组响应。
"""

from __future__ import annotations

from .contract import SkillResult


async def persist_suspended_plan(thread_id: str | None, plan: dict) -> bool:
    """挂起计划立即落 TaskMemory(挂起瞬间 ≠ 运行收口时刻);返回是否落库。

    空 thread_id 会命中 TaskMemory("") 的共享键,污染其他会话的任务记忆,
    拒写。落库失败不阻断挂起响应(工单已可见,恢复语义由收口兜底)。"""
    if not thread_id:
        print("[Suspension] 挂起计划落库跳过:thread_id 为空,拒绝写入共享键")
        return False
    try:
        from ..memory.task_memory import TaskMemory

        await TaskMemory(thread_id).save_task_state(plan)
        return True
    except Exception as err:
        print(f"[Suspension] 挂起计划落库失败 thread={thread_id}: {err}")
        return False


async def suspend_for_approval(
    *,
    thread_id: str | None,
    user_id: str | None,
    skill_id: str,
    action_type: str,
    action_payload: dict,
    step_id: str,
    step_description: str,
    plan_goal: str,
    order_context: dict,
    output_template: str,
) -> SkillResult:
    """高价值操作 HITL 三合一:创建审批工单 → 挂起计划瞬间落库 → 组响应。

    output_template 中的 {approval_id} 以工单号填充。task_plan 随结果带回,
    防 run_agent 收口以空计划覆盖挂起(审批 resume 由此恢复)。
    """
    from ..approvals.gatekeeper import ApprovalPolicyEngine

    ticket = await ApprovalPolicyEngine.create_pending_approval_ticket(
        {
            "threadId": thread_id or "",
            "userId": user_id,
            "actionType": action_type,
            "actionPayload": {"args": action_payload},
            "jobId": None,
            "stepToRun": {"id": step_id, "description": step_description},
            "currentPlan": {"subtasks": [{}]},
            "currentIndex": 0,
        }
    )
    approval_id = ticket.get("approvalId")

    awaiting_plan = {
        "goal": plan_goal,
        "subtasks": [
            {
                "id": step_id,
                "description": step_description,
                "status": "pending",
                "result": {"waitingForApproval": True, "approvalId": approval_id},
            }
        ],
        "currentStepIndex": 0,
    }
    # 挂起即落库:审批可见性与恢复计划入库必须同一时刻成立,严禁只随结果
    # 带回等收口落库 —— 秒级核签的 resume 会在收口前启动
    await persist_suspended_plan(thread_id, awaiting_plan)

    return SkillResult(
        skill_id=skill_id,
        output=output_template.format(approval_id=approval_id),
        task_plan=awaiting_plan,
        order_context=order_context,
    )
