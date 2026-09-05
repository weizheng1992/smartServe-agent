"""候选池写入入口 — 信号源定义、先验表与入池函数。

入池失败必须静默降级(print 错误上下文)且绝不阻断业务动作本身:
标差是旁路,不是主链路(观测性规范第 2/3 条)。
"""

from __future__ import annotations

from ..db import BadcaseCandidate, get_session

SOURCE_HUMAN_TAKEOVER = "human_takeover"
SOURCE_PERSONA_FACT_DELETED = "persona_fact_deleted"
SOURCE_APPROVAL_REJECTED = "approval_rejected"
SOURCE_THUMBS_DOWN = "thumbs_down"  # v3.1 契约修订后接入
SOURCE_CIRCUIT_BREAKER = "circuit_breaker"  # 单独立案聚合,不直接转 case

# 信号源默认先验:不同来源的可信度不同
SOURCE_PRIORS: dict[str, str] = {
    SOURCE_HUMAN_TAKEOVER: "neutral",
    SOURCE_PERSONA_FACT_DELETED: "suspected_defect",  # 记忆管道写入错误事实的明确信号
    SOURCE_APPROVAL_REJECTED: "expected_behavior",  # HITL 设计行为,除非 triage 勾选"审批判错"
    SOURCE_THUMBS_DOWN: "neutral",
    SOURCE_CIRCUIT_BREAKER: "suspected_defect",
}


async def record_badcase_signal(
    signal_source: str,
    conversation_ref: str,
    business_id: str,
    suggested_class: str | None = None,
    note: str | None = None,
) -> str | None:
    """写入一条候选池记录(事件驱动实时入池)。

    Returns: 新记录 ID;失败时返回 None(仅 print,不上抛)。
    """
    prior = suggested_class or SOURCE_PRIORS.get(signal_source, "neutral")
    try:
        async with get_session() as session:
            row = BadcaseCandidate(
                signal_source=signal_source,
                conversation_ref=conversation_ref,
                business_id=business_id or "ecommerce",
                suggested_class=prior,
                status="candidate",
                note=note,
            )
            session.add(row)
            await session.commit()
            print(
                f"[BadcasePool] 信号入池: source={signal_source} tenant={business_id} "
                f"ref={conversation_ref} class={prior}"
            )
            return str(row.id)
    except Exception as err:
        print(f"[BadcasePool] Failed to record badcase signal ({signal_source}/{conversation_ref}): {err}")
        return None
