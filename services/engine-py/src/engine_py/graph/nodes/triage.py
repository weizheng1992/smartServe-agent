"""意图分流节点 — 镜像 triage.node.ts(薄包装,逻辑全在 IntentTriageEngine)。"""

from __future__ import annotations

from ...llm import bind_llm_call_node
from ...triage import IntentTriageEngine
from ..state import AgentState


async def triage_node(state: AgentState) -> dict:
    # 节点内直调(分类器/咨询直答)无 langgraph_node 元数据,ContextVar 兜底归因
    bind_llm_call_node("triage")
    return await IntentTriageEngine.process(dict(state))
