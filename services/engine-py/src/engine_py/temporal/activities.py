"""Temporal Activities — 镜像 temporal/activities.ts(runAgentStateNode 节点分发)。"""

from __future__ import annotations

from sqlalchemy import select

from ..cards import CardSynthesizer
from ..db import Thread, get_session
from ..graph.nodes import executor_node, finish_node, merge_node, planner_node, triage_node, validator_node
from ..graph.state import AgentState, to_ts_dict
from ..memory import EpisodicMemory, LongMemory, ShortMemory, TaskMemory
from ..tenant import get_merchant_display_name

_NODE_HANDLERS = {
    "triage": triage_node,
    "planner": planner_node,
    "merge": merge_node,
    "executor": executor_node,
    "validator": validator_node,
    "finish": finish_node,
}


async def run_agent_state_node(node_name: str, ts_state: dict) -> dict:
    """以 TS camelCase 状态在指定节点上推进一步(进出均为 TS 状态格式)。"""
    state: AgentState = dict(ts_state)  # type: ignore[assignment]
    business_id = str(
        (state.get("businessConfig") or {}).get("businessId") or state.get("businessId") or "ecommerce"
    )

    if state.get("threadId") and (business_id == "ecommerce" or not business_id):
        try:
            async with get_session() as session:
                row = (
                    await session.execute(select(Thread).where(Thread.id == state["threadId"]).limit(1))
                ).scalar_one_or_none()
                if row and row.business_id:
                    business_id = row.business_id
        except Exception as err:
            print(f"[Temporal Activities] Failed to resolve thread businessId: {err}")

    if not state.get("longMemoryFacts") or not state.get("episodicEvents"):
        long_memory = LongMemory(state.get("userId", ""), business_id)
        episodic_memory = EpisodicMemory(state.get("userId", ""), business_id)
        long_facts, episodic_events = await __import__("asyncio").gather(
            long_memory.search_relevant_facts(state.get("input", "")),
            episodic_memory.retrieve_events(state.get("input", "")),
        )
        state["longMemoryFacts"] = long_facts
        state["episodicEvents"] = episodic_events

    if not state.get("businessConfig") or not (state.get("businessConfig") or {}).get("systemPrompt"):
        default_limit = 150 if business_id == "nike" else 120 if business_id == "adidas" else 100
        brand_name = get_merchant_display_name(business_id)
        state["businessConfig"] = {
            "businessId": business_id,
            "systemPrompt": (
                f"You are an advanced, professional AI Customer Support Agent representing {brand_name}. "
                "Help users resolve order, shipping, and refund queries."
            ),
            "intents": {
                "order_status": {"description": "Track or check order delivery status."},
                "refund": {"description": "Process or request refunds."},
                "general_query": {"description": "General customer questions."},
            },
            "tools": ["getOrderStatus", "processRefund", "takeScreenshot", "listUserOrders"],
            "executionMode": "plan-and-execute",
            "confidenceThresholds": {"high": 0.85, "mid": 0.6},
            "refundAutoApprovalLimit": default_limit,
            **(state.get("businessConfig") or {}),
        }

    # 将 TS 状态转 Python 状态键推进节点
    from ..graph.state import AgentState as _AS  # noqa: F401 — 类型提示

    py_state: dict = _ts_to_py_state(state)
    handler = _NODE_HANDLERS.get(node_name)
    if handler is None:
        raise ValueError(f"Unknown node: {node_name}")
    updates = await handler(py_state)  # type: ignore[arg-type]
    py_state.update({k: v for k, v in updates.items()})

    if node_name == "finish":
        synthesized_cards = CardSynthesizer.synthesize_cards(
            {
                "taskPlan": py_state.get("task_plan"),
                "intents": py_state.get("intents"),
                "damageAssessment": py_state.get("damage_assessment"),
            }
        )
        final_cards = py_state.get("cards") or synthesized_cards
        py_state["cards"] = final_cards

        if py_state.get("output"):
            short_memory = ShortMemory(state.get("threadId", ""))
            episodic_memory = EpisodicMemory(state.get("userId", ""), business_id)
            long_memory = LongMemory(state.get("userId", ""), business_id)
            await short_memory.add_message("user", state.get("input", ""))
            await short_memory.add_message("assistant", py_state["output"], final_cards)
            await __import__("asyncio").gather(
                episodic_memory.add_event(
                    f"Handled conversation thread: {state.get('threadId')}. "
                    f"Output summary: {py_state['output'][:80]}",
                    5,
                ),
                long_memory.extract_and_store_fact(py_state["output"], state.get("input", "")),
            )
        if py_state.get("task_plan"):
            await TaskMemory(state.get("threadId", "")).save_task_state(py_state["task_plan"])

    return _py_to_ts_state(py_state)


_TS_TO_PY = {
    "threadId": "thread_id",
    "userId": "user_id",
    "jobId": "job_id",
    "imageUrls": "image_urls",
    "damageAssessment": "damage_assessment",
    "inputEmbedding": "input_embedding",
    "activeDomainRole": "active_domain_role",
    "guideContext": "guide_context",
    "cartContext": "cart_context",
    "orderContext": "order_context",
    "taskPlan": "task_plan",
    "shortMemory": "short_memory",
    "longMemoryFacts": "long_memory_facts",
    "episodicEvents": "episodic_events",
    "ragDocuments": "rag_documents",
    "businessConfig": "business_config",
    "loopCount": "loop_count",
    "globalTransitionsCount": "global_transitions_count",
    "toolErrorsCount": "tool_errors_count",
}


def _ts_to_py_state(ts_state: dict) -> dict:
    return {_TS_TO_PY.get(k, k): v for k, v in ts_state.items()}


def _py_to_ts_state(py_state: dict) -> dict:
    return to_ts_dict(py_state)
