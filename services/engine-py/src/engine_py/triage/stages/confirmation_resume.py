"""✅ 澄清确认轮动作恢复 — Stage 1(原 process 开头段,逐字搬移)。

上一轮技能留下 pending_action(如 set_default_address 待确认)且本轮是
肯定确认时,直接恢复执行该动作 —— LLM 确认轮会丢上下文参数,硬编码恢复才稳。
(2026-09-15 S8/S3/S7 同族)
"""

from __future__ import annotations

import re

from .context import StageContext, StageVerdict

_CONFIRM_RE = re.compile(r"^(?:是的?|对|确认|没错|好的?|ok|OK)[,，。!！?？～～]?\s*$")


async def judge(ctx: StageContext) -> StageVerdict:
    if not _CONFIRM_RE.match(ctx.input_text.strip()):
        return StageVerdict.passthrough()

    task_state = ctx.state.get("task_plan") or {}
    pending_action = task_state.get("pendingAction") if isinstance(task_state, dict) else None
    if not (isinstance(pending_action, dict) and pending_action.get("tool")):
        return StageVerdict.passthrough()

    action_tool = str(pending_action["tool"])
    action_args = pending_action.get("args") or {}
    intents = [
        {
            "intent": "address_manage",
            "confidence": 1.0,
            "type": "primary",
            "entities": {"addressAction": action_tool, **(action_args or {})},
        }
    ]
    if ctx.state.get("job_id"):
        from ...event_bus import emit_status

        await emit_status(
            ctx.state["job_id"],
            "✅ 检测到确认回复，正在恢复上一轮待执行的操作...",
            node="triage",
        )
    return StageVerdict.terminal(ctx, intents, state=ctx.state)
