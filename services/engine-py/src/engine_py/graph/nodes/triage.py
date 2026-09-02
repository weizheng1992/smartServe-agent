"""意图分流节点 — 镜像 packages/engine/src/graph/nodes/triage/(7 个文件)。

TODO(Phase 1b) 按依赖顺序移植:
- ruleMatchers.ts:规则前置匹配(零 LLM 快路径)
- structuredClassifier.ts:结构化意图分类(LLM,对齐 eval/prompts/classify_prompt.txt)
- semanticCache.ts:语义去重旁路(余弦相似度 ≥ 0.98 直接命中缓存)
- slotExtractor.ts:槽位抽取;低置信度写入 low_confidence_logs 并触发反问
- exemplarHarvestingService.ts / exemplarService.ts:榜样收割与沉淀
"""

from __future__ import annotations

from ..state import AgentState
from ...event_bus import emit


async def triage_node(state: AgentState) -> dict:
    job_id = state.get("job_id", "")
    await emit(job_id, "thought", {"jobId": job_id, "step": "正在识别用户意图..."})

    # 骨架:最小可运行输出,保证图可走通;分类逻辑 Phase 1b 移植后替换
    return {"intents": [], "bypass_step": True}
