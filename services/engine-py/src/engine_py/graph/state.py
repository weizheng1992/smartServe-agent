"""Agent 全局状态 — 逐字段镜像 packages/engine/src/graph/state.ts 的 AgentStateAnnotation。

reducer 语义与 TS 版一一对应:
- global/toolErrors 计数:更新值 -1 表示归零,否则累加(TS: y === -1 ? 0 : x + y)
- guide/cart/order context、taskPlan、businessConfig:dict 浅合并(未提供则保持)
- damageAssessment / activeDomainRole / cards / imageUrls:有值才覆盖
- history:追加

注意:task_plan / subtasks 的**内部键保持 TS camelCase**(goal/subtasks/currentStepIndex、
id/description/status/result),因为这些对象会原样进入 SSE ``status`` 事件的 plan 载荷,
属于冻结的线上契约。``to_ts_dict`` 只做顶层键的 snake→camel 映射,供影子 diff。
"""

from __future__ import annotations

from typing import Annotated, Any, TypedDict

from ..ontology_generated import DEFAULT_REFUND_AUTO_APPROVAL_LIMIT


def _counter_reducer(current: int, update: int) -> int:
    return 0 if update == -1 else current + update


def _merge_dict_reducer(current: dict, update: dict | None) -> dict:
    if update is None:
        return current
    return {**current, **update}


def _replace_if_present_reducer(current: Any, update: Any) -> Any:
    return update if update is not None else current


def _concat_reducer(current: list, update: list) -> list:
    return current + update


class AgentState(TypedDict, total=False):
    # 线程与用户标识
    thread_id: str
    user_id: str
    job_id: str

    # 当前输入与历史
    input: str
    image_urls: Annotated[list[str], _replace_if_present_reducer]
    damage_assessment: Annotated[dict | None, _replace_if_present_reducer]
    # 视觉解析完整产物(A2 证据快照,2026-10-17 视觉加固):此前只活 triage
    # StageContext 惰性组,apply_after_sale 落证据表时不可达;『有值才覆盖』——
    # 带图轮次覆盖旧值,无图轮次保留上一轮视觉产物供售后快照跨轮可用
    vision_analysis: Annotated[dict | None, _replace_if_present_reducer]
    input_embedding: list[float]
    history: Annotated[list[dict], _concat_reducer]

    # 意图分类
    intents: list[dict[str, Any]]

    # 多 Agent 领域角色与上下文总线
    active_domain_role: Annotated[str | None, _replace_if_present_reducer]
    guide_context: Annotated[dict | None, _merge_dict_reducer]
    cart_context: Annotated[dict | None, _merge_dict_reducer]
    order_context: Annotated[dict | None, _merge_dict_reducer]

    # 富卡片输出
    cards: Annotated[list[dict], _replace_if_present_reducer]

    # 任务记忆(plan 内部键保持 camelCase:goal/subtasks/currentStepIndex)
    task_plan: Annotated[dict, _merge_dict_reducer]

    # 循环启动时加载的记忆
    short_memory: list[dict]
    # 历史装配产物(2026-09-21):run_agent 预算裁剪+滚动摘要一次性生成,
    # planner/finish 直接消费;缺省时节点内回退 build_history_block 裸拼
    history_block: str
    long_memory_facts: list[Any]
    episodic_events: list[Any]
    rag_documents: list[dict]
    business_config: Annotated[dict, _merge_dict_reducer]

    # 最终产出
    output: str

    # 循环控制计数(-1 归零语义见 _counter_reducer)
    loop_count: int
    global_transitions_count: Annotated[int, _counter_reducer]
    tool_errors_count: Annotated[int, _counter_reducer]


DEFAULT_TASK_PLAN: dict = {"goal": "", "subtasks": [], "currentStepIndex": 0}

DEFAULT_BUSINESS_CONFIG: dict = {
    "businessId": "ecommerce",
    "systemPrompt": (
        "You are an advanced, professional AI Customer Support Agent specialized in E-Commerce. "
        "Help users resolve order, shipping, and refund queries."
    ),
    "intents": {
        "order_status": {"description": "Track or check order delivery status."},
        "refund": {"description": "Process or request refunds."},
        "general_query": {"description": "General customer questions."},
    },
    "tools": ["getOrderStatus", "processRefund", "listUserOrders"],
    "executionMode": "plan-and-execute",
    "confidenceThresholds": {"high": 0.85, "mid": 0.6},
    # 免签缺省单源(ADR-0015 决策 4):历史 100 与技能侧 50 分叉,统一 50
    "refundAutoApprovalLimit": DEFAULT_REFUND_AUTO_APPROVAL_LIMIT,
}

_CAMEL_KEY_MAP = {
    "thread_id": "threadId",
    "user_id": "userId",
    "job_id": "jobId",
    "image_urls": "imageUrls",
    "damage_assessment": "damageAssessment",
    "vision_analysis": "visionAnalysis",
    "input_embedding": "inputEmbedding",
    "active_domain_role": "activeDomainRole",
    "guide_context": "guideContext",
    "cart_context": "cartContext",
    "order_context": "orderContext",
    "task_plan": "taskPlan",
    "short_memory": "shortMemory",
    "long_memory_facts": "longMemoryFacts",
    "episodic_events": "episodicEvents",
    "rag_documents": "ragDocuments",
    "business_config": "businessConfig",
    "loop_count": "loopCount",
    "global_transitions_count": "globalTransitionsCount",
    "tool_errors_count": "toolErrorsCount",
}


def to_ts_dict(state: AgentState | dict[str, Any]) -> dict[str, Any]:
    """snake_case → TS camelCase,影子 diff 的序列化格式。"""
    return {_CAMEL_KEY_MAP.get(key, key): value for key, value in state.items()}

