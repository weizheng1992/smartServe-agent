"""收尾节点 — 镜像 finish.node.ts(211 LOC)+ cards/cardSynthesizer.ts。

TODO(Phase 1b) 移植:
- CardSynthesizer 富卡片合成(order_status / product 等卡片家族)
- session_metrics 遥测写入
- LangSmith feedback 回传
"""

from __future__ import annotations

from ..state import AgentState
from ...event_bus import emit


async def finish_node(state: AgentState) -> dict:
    job_id = state.get("job_id", "")
    output = state.get("output") or "智能客服已为您处理完毕。"
    cards = state.get("cards") or []

    # emit() 会按 TS 语义在 cards 非空时先发 cards 事件再发 result
    await emit(job_id, "result", {"jobId": job_id, "output": output, "cards": cards})
    return {"output": output, "tokens": state.get("tokens", 0)}
