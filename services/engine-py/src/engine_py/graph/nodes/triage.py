"""意图分流节点 — 镜像 triage.node.ts(薄包装,逻辑全在 IntentTriageEngine)。"""

from __future__ import annotations

from ...triage import IntentTriageEngine
from ..state import AgentState


async def triage_node(state: AgentState) -> dict:
    return await IntentTriageEngine.process(dict(state))
