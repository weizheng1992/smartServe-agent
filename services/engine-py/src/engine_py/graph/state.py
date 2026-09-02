"""Agent 全局状态 — 镜像 packages/engine/src/graph/state.ts 的 AgentStateAnnotation。

字段名取 snake_case(Python 惯例);``to_ts_dict`` 将其映射回 TS 的 camelCase
键名,供影子双跑做逐字段 diff。
"""

from __future__ import annotations

from typing import Any, TypedDict


class AgentState(TypedDict, total=False):
    # 作业标识
    job_id: str
    thread_id: str
    user_id: str
    business_id: str
    message: str
    image_urls: list[str]

    # triage 产出
    intents: list[dict[str, Any]]
    bypass_step: bool
    general_query_only: bool

    # planner / executor 循环控制(与 buildGraph.ts 条件边一一对应)
    task_plan: list[dict[str, Any]]
    subtasks: list[dict[str, Any]]
    next_index: int
    global_transitions: int
    tool_errors: int
    waiting_for_approval: bool
    rejected_by_admin: bool
    replanned_after_rejection: bool

    # 四象限记忆 + Contextual RAG 上下文
    short_memory: list[dict[str, Any]]
    long_memory_facts: list[dict[str, Any]]
    episodic_context: list[dict[str, Any]]
    rag_context: list[dict[str, Any]]

    # 产出
    output: str
    cards: list[dict[str, Any]]
    tokens: int
    error: str | None


_CAMEL_KEY_MAP = {
    "job_id": "jobId",
    "thread_id": "threadId",
    "user_id": "userId",
    "business_id": "businessId",
    "image_urls": "imageUrls",
    "task_plan": "taskPlan",
    "next_index": "nextIndex",
    "global_transitions": "globalTransitions",
    "tool_errors": "toolErrors",
    "waiting_for_approval": "waitingForApproval",
    "rejected_by_admin": "rejectedByAdmin",
    "replanned_after_rejection": "replannedAfterRejection",
    "short_memory": "shortMemory",
    "long_memory_facts": "longMemoryFacts",
    "episodic_context": "episodicContext",
    "rag_context": "ragContext",
    "bypass_step": "bypassStep",
    "general_query_only": "generalQueryOnly",
}


def to_ts_dict(state: AgentState | dict[str, Any]) -> dict[str, Any]:
    """snake_case → TS camelCase,影子 diff 的序列化格式。"""
    return {_CAMEL_KEY_MAP.get(key, key): value for key, value in state.items()}
