"""🛣️ Step 1.4 咨询类直答快轨 — Stage(原 process 段,逐字搬移)。

政策/尺码/物流时效等「问知识」型输入在此闭环(此前咨询按措辞随机误落三处,
57-114s 回复大头的根源)。复用 run_agent 预取的 RAG 切片单次调用直答;RAG
空弱/直答失败回落 general_query 零规划旁路;仲裁员否决动作形请求时 fallthrough
完整管线。带图闸在 is_consult_query 本体。
"""

from __future__ import annotations

from ..consult_fast_path import (
    ROUTE_TO_ACTION_MARKER,
)
from ..intent_registry import AgentIntentType
from ..intent_triage_engine import _proposal
from .context import StageContext, StageVerdict


async def judge(ctx: StageContext) -> StageVerdict:
    state = ctx.state
    if not ctx.ns.is_consult_query(ctx.input_text, has_image=bool(state.get("image_urls"))):
        return StageVerdict.passthrough()

    consult_hit = await ctx.ns.run_consult_direct_answer(state, ctx.history_msgs)
    if consult_hit is not None:
        consult_answer, consult_intents, consult_confidence = consult_hit
        if consult_answer == ROUTE_TO_ACTION_MARKER:
            # 🧭 仲裁员否决(intent-arbitration 05,2026-09-10):正则快轨
            # 不再独自关会话 —— 直答调用复核为动作形请求,fallthrough 完整
            # 管线(Step 1.5 起照常裁决,用户拿到动作管道结果而非资讯回复)。
            # 改判进终局行 candidates:consult_gate 提议 consult,
            # consult_arbiter 否决(intent 记 None —— 该层只判定「非咨询」,
            # 不认领具体动作意图,终局由后续层裁决);不另写日志行,
            # 终局单点落库(01)不变。
            ctx.proposals.append(_proposal("consult_gate", "consult"))
            ctx.proposals.append(_proposal("consult_arbiter", None))
            return StageVerdict.passthrough()

        return StageVerdict(
            terminal=True,
            result=await ctx.engine.handle_immediate_bypass(
                state,
                "rag_consult_direct",
                consult_answer,
                consult_intents,
                "rag_direct",
                consult_confidence,
                ctx.damage_assessment,
                candidates=[_proposal("consult_gate", "consult")],
            ),
        )

    # RAG 空弱/直答失败:回落 general_query 零规划旁路(finish 终稿)
    consult_intents = [{"intent": AgentIntentType.GENERAL_QUERY, "confidence": 0.9, "type": "primary"}]
    await ctx.engine.log_intent_to_db(
        ctx.thread_id,
        ctx.input_text,
        consult_intents,
        "consult_no_rag",
        0.9,
        candidates=[_proposal("consult_gate", "consult")],
        arbitration_reason="consult_no_rag",
    )
    from ..intent_triage_engine import _triage_terminal_result

    return StageVerdict(
        terminal=True,
        result=_triage_terminal_result(
            consult_intents, ctx.input_text, ctx.history_msgs, ctx.damage_assessment, role="chitchat"
        ),
    )
