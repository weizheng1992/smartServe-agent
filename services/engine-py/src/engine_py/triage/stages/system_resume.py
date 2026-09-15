"""🛡️ 人工恢复/系统提问解挂判定 — Stage 2(原 process 段,逐字搬移)。

输入以 "System:" 开头 = 主管人工决议(审批核准/驳回)后的恢复指令:
按挂起任务里是否有退款子任务快速解挂,拉起后续处理步骤。
"""

from __future__ import annotations

from .context import StageContext, StageVerdict


async def judge(ctx: StageContext) -> StageVerdict:
    if not ctx.input_text.startswith("System:"):
        return StageVerdict.passthrough()

    task_plan = ctx.state.get("task_plan") or {}
    subtasks = task_plan.get("subtasks") or []
    has_refund_task = any(
        "refund" in (st.get("description") or "").lower()
        or (st.get("result") or {}).get("approvalId")
        for st in subtasks
    )
    intent = "refund" if has_refund_task else "order_status"
    intents = [{"intent": intent, "confidence": 1.0}]
    if ctx.state.get("job_id"):
        from ...event_bus import emit_status

        await emit_status(
            ctx.state["job_id"],
            "🔄 恢复执行流：检测到主管人工决议，正在快速解挂并拉起后续处理步骤...",
            node="triage",
        )
    return StageVerdict.terminal(ctx, intents, damage_assessment=ctx.state.get("damage_assessment"))
