"""run_agent — TS 侧 runAgent()(packages/engine/src/graph/buildGraph.ts)的 Python 入口。

TODO(Phase 1b) — runAgent 隐性行为移植清单(影子等价性的关键,缺一即不等价):
1. 零 LLM 欢迎语快路径(硬编码 greeting 直接 finish)
2. 租户配置热加载(business_configs 表;fallback 阈值:nike $150 / adidas $120 / 默认 $100)
3. 单 embedding 注入 + 三路并取(LongMemory / EpisodicMemory / ContextualRAG,
   TS 侧为 Promise.allSettled 并发,任意失败不阻断)
4. session_metrics 遥测写入
5. LangSmith feedback POST 回传
6. CardSynthesizer 卡片合成
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from .event_bus import emit
from .graph import build_graph
from .graph.state import AgentState, to_ts_dict


class AgentJobInput(BaseModel):
    """作业输入 — 字段与 WorkflowOrchestrator.dispatchJob 的载荷对齐。"""

    job_id: str = Field(alias="jobId")
    thread_id: str = Field(alias="threadId")
    user_id: str = Field(default="CUST-8801", alias="userId")
    business_id: str = Field(default="ecommerce", alias="businessId")
    message: str
    image_urls: list[str] = Field(default_factory=list, alias="imageUrls")

    model_config = {"populate_by_name": True}


async def run_agent(job: AgentJobInput) -> dict:
    """执行一次完整 Agent 决策流水线,返回 camelCase 化的终态(影子 diff 格式)。"""
    initial: AgentState = {
        "job_id": job.job_id,
        "thread_id": job.thread_id,
        "user_id": job.user_id,
        "business_id": job.business_id,
        "message": job.message,
        "image_urls": job.image_urls,
        "global_transitions": 0,
        "tool_errors": 0,
        "next_index": 0,
        "tokens": 0,
    }

    # TODO(Phase 1b):此处按上述清单插入欢迎语快路径与三路记忆并取
    graph = build_graph()
    final_state = await graph.ainvoke(initial)

    if final_state.get("error"):
        await emit(job.job_id, "error", {"jobId": job.job_id, "message": final_state["error"]})

    return to_ts_dict(final_state)
