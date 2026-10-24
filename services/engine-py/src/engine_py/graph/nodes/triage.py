"""意图分流节点 — 镜像 triage.node.ts(薄包装,逻辑全在 IntentTriageEngine)。"""

from __future__ import annotations

from ...llm import bind_llm_call_node
from ...triage import IntentTriageEngine
from ..state import AgentState


async def triage_node(state: AgentState) -> dict:
    # 节点内直调(分类器/咨询直答)无 langgraph_node 元数据,ContextVar 兜底归因
    bind_llm_call_node("triage")
    result = await IntentTriageEngine.process(dict(state))
    # 轮路径(docs/ai-usage-panel.md P0-1):旁路出口自带 turn_path;非旁路
    # 主链(planner→executor→finish)由本节点单点默认 —— process 的唯一
    # 生产调用点在此,收口最窄。
    result.setdefault("turn_path", "deep_path")
    return result
