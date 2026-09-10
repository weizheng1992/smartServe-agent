"""候选池写入入口 — 信号源定义、先验表与入池函数。

入池失败必须静默降级(print 错误上下文)且绝不阻断业务动作本身:
标差是旁路,不是主链路(观测性规范第 2/3 条)。
"""

from __future__ import annotations

from sqlalchemy import select

from ..db import BadcaseCandidate, get_session

SOURCE_HUMAN_TAKEOVER = "human_takeover"
SOURCE_PERSONA_FACT_DELETED = "persona_fact_deleted"
SOURCE_APPROVAL_REJECTED = "approval_rejected"
SOURCE_THUMBS_DOWN = "thumbs_down"  # v3.1 契约修订后接入
SOURCE_CIRCUIT_BREAKER = "circuit_breaker"  # 单独立案聚合,不直接转 case
SOURCE_INTENT_CONFLICT = "intent_conflict"  # intent-arbitration 02:跨意图族判定冲突
SOURCE_CLAIM_MISMATCH = "claim_mismatch"  # intent-arbitration 02:终稿宣称与审批落库不符

# 信号源默认先验:不同来源的可信度不同
SOURCE_PRIORS: dict[str, str] = {
    SOURCE_HUMAN_TAKEOVER: "neutral",
    SOURCE_PERSONA_FACT_DELETED: "suspected_defect",  # 记忆管道写入错误事实的明确信号
    SOURCE_APPROVAL_REJECTED: "expected_behavior",  # HITL 设计行为,除非 triage 勾选"审批判错"
    SOURCE_THUMBS_DOWN: "neutral",
    SOURCE_CIRCUIT_BREAKER: "suspected_defect",
    # 冲突可能是快轨合法压制非 LLM 层(设计行为),人审定性;宣称无据则几乎必是缺陷
    SOURCE_INTENT_CONFLICT: "neutral",
    SOURCE_CLAIM_MISMATCH: "suspected_defect",
}


async def record_badcase_signal(
    signal_source: str,
    conversation_ref: str,
    business_id: str,
    suggested_class: str | None = None,
    note: str | None = None,
    *,
    dedupe: bool = False,
) -> str | None:
    """写入一条候选池记录(事件驱动实时入池)。

    ``dedupe=True``:同 (signal_source, conversation_ref) 已有 candidate 在池则
    跳过(熔断 OPEN 窗口内同一会话多次回合只入池一次,对齐 gatekeeper 转人工
    挂点"重复呼叫不重复入池"的结构性去重语义)。

    Returns: 新记录 ID;dedupe 命中返回既有记录 ID;失败时返回 None(仅 print,不上抛)。
    """
    prior = suggested_class or SOURCE_PRIORS.get(signal_source, "neutral")
    try:
        async with get_session() as session:
            if dedupe:
                existing = (
                    await session.execute(
                        select(BadcaseCandidate.id)
                        .where(
                            BadcaseCandidate.signal_source == signal_source,
                            BadcaseCandidate.conversation_ref == conversation_ref,
                            BadcaseCandidate.status == "candidate",
                        )
                        .limit(1)
                    )
                ).scalar_one_or_none()
                if existing is not None:
                    return str(existing)
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
