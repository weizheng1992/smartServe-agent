"""🛡️ Step 2 Embedding 锚点判定 — Stage(原 process 段,逐字搬移)。

语义缓存读闸(动作形输入防投毒)→ 锚点余弦打分 → 单号融合(文本>上下文>
OCR)→ 判定 1 复合直达 / 1.5 经营排行前置 / 1.6 地址簿前置 / 2 订单查询 /
3 退款直达 / 4 超范畴提议(fallthrough Step 3 确认)。异常诚实跳过锚点层。
"""

from __future__ import annotations

import asyncio

from ...tenant import tenant_of_state
from ..intent_triage_engine import (
    ORDER_KEYWORDS_RE,
    REFUND_KEYWORDS_RE,
    _address_manage_intent_entry,
    _is_multi_intent_candidate,
    _proposal,
)
from ..semantic_cache import cosine_similarity
from ..slot_extractor import ORDER_ID_RE, AgentIntentType
from .context import StageContext, StageVerdict


async def judge(ctx: StageContext) -> StageVerdict:
    state, input_text, thread_id, tenant_id = ctx.state, ctx.input_text, ctx.thread_id, ctx.tenant_id
    score_order = 0.0
    score_refund = 0.0
    score_oos = 0.0

    try:
        user_vector, anchors = await asyncio.gather(
            ctx.ns.SemanticVectorCache.get_embedding_with_cache(input_text),
            ctx.ns.SemanticVectorCache.get_anchor_vectors(),
        )

        # 🛡️ 读闸(防缓存投毒,2026-09-04 幻觉加购 bug 加固):动作形输入(任一
        # 技能声明可处理)不得命中回复缓存 —— 即使缓存已被历史投毒,动作也必须
        # 落到下方锚点判定 / Step 3 精判的真实执行管道。
        cache_tenant = tenant_of_state(state)
        if ctx.ns.is_action_query(input_text, cache_tenant):
            print(f"[Triage] 动作形输入跳过回复缓存读取 (tenantId={cache_tenant}): {input_text[:50]}")
        else:
            cache_hit = ctx.ns.SemanticVectorCache.find_best_semantic_match(cache_tenant, user_vector, 0.96)
            if cache_hit:
                return StageVerdict(
                    terminal=True,
                    result=await ctx.engine.handle_immediate_bypass(
                        state,
                        "super_semantic_cache",
                        cache_hit["match"]["reply"],
                        [{"intent": "general_query", "confidence": cache_hit["similarity"]}],
                        "semantic_cache",
                        cache_hit["similarity"],
                        candidates=[
                            *ctx.proposals,
                            _proposal("semantic_cache", "general_query", cache_hit["similarity"]),
                        ],
                    ),
                )

        for v in anchors["order_status"]:
            score_order = max(score_order, cosine_similarity(user_vector, v))
        for v in anchors["refund"]:
            score_refund = max(score_refund, cosine_similarity(user_vector, v))
        for v in anchors["out_of_scope"]:
            score_oos = max(score_oos, cosine_similarity(user_vector, v))

        matched_order_id_match = ORDER_ID_RE.search(input_text)
        matched_order_id = matched_order_id_match.group(0) if matched_order_id_match else None
        # 单号融合优先级:文本显式 > 已确认上下文 > 图内 OCR(2026-09-09),
        # 判定 1/2/3 同一融合口径,一次算定共用
        confirmed_order_id = (state.get("order_context") or {}).get("targetOrderId")
        fused_order_id = matched_order_id or confirmed_order_id or ctx.vision_order_id
        has_order_keywords = bool(ORDER_KEYWORDS_RE.search(input_text))
        has_refund_keywords = bool(REFUND_KEYWORDS_RE.search(input_text)) or bool(ctx.damage_assessment)

        # 判定 1: 复合意图直达
        if (
            score_order >= 0.85
            and score_refund >= 0.85
            and abs(score_order - score_refund) < 0.15
            and has_order_keywords
            and has_refund_keywords
        ):
            intents = [
                {
                    "intent": "order_status",
                    "confidence": score_order,
                    "type": "primary",
                    **({"entities": {"orderId": fused_order_id}} if fused_order_id else {}),
                },
                {
                    "intent": "refund",
                    "confidence": score_refund,
                    "type": "secondary",
                    **({"entities": {"orderId": fused_order_id}} if fused_order_id else {}),
                },
            ]
            await ctx.engine.log_intent_to_db(
                thread_id,
                input_text,
                intents,
                "embedding",
                intents[0]["confidence"],
                candidates=[
                    *ctx.proposals,
                    _proposal("embedding", "order_status", score_order),
                    _proposal("embedding", "refund", score_refund),
                ],
                arbitration_reason="embedding_composite",
            )
            return StageVerdict(terminal=True, result=await _terminal_with_order_context(ctx, intents))

        # 判定 1.5(ADR-0003):经营口径排行规则前置 —— 确定性直通
        # metric_query,严禁 LLM 分类层把「利润」当后台数据拒答。
        from ..intent_triage_engine import is_profit_ranking_query

        if is_profit_ranking_query(input_text):
            intents = [{"intent": "metric_query", "confidence": 0.97, "type": "primary"}]
            await ctx.engine.log_intent_to_db(
                thread_id,
                input_text,
                intents,
                "rule",
                intents[0]["confidence"],
                candidates=[_proposal("rule", "metric_query", 0.97)],
                arbitration_reason="profit_ranking_precheck",
            )
            return StageVerdict(terminal=True, result=await _terminal(ctx, intents))

        # 判定 1.6(多意图一期,2026-09-12):地址簿规则前置 —— 词表缺口曾使
        # 「创建地址」落 general_query 让 planner 编造假改派流程(A11 实弹:
        # 幻觉「已发货联系快递员改派、转寄费自理」)。纯建/查地址(非复合)
        # 确定性直通 address_manage,零结构化调用;复合形让位 Step3 注入器。
        from ..intent_triage_engine import detect_address_manage

        if not _is_multi_intent_candidate(input_text):
            detected_addr = detect_address_manage(input_text)
            if detected_addr is not None and (
                detected_addr["mode"] == "list" or not detected_addr["missingSlots"]
            ):
                addr_intents = [_address_manage_intent_entry(detected_addr)]
                await ctx.engine.log_intent_to_db(
                    thread_id,
                    input_text,
                    addr_intents,
                    "rule",
                    0.9,
                    candidates=[
                        *ctx.proposals,
                        _proposal("rule", AgentIntentType.ADDRESS_MANAGE, 0.9),
                    ],
                    arbitration_reason="address_manage_precheck",
                )
                return StageVerdict(terminal=True, result=await _terminal(ctx, addr_intents))

        # 判定 2: 物流/订单状态查询直达
        # 多意图不打断(2026-09-12):关键词分支对复合候选形让位(同判定 3 注)
        if (score_order >= 0.88 and score_order - score_oos >= 0.08) or (
            has_order_keywords
            and not has_refund_keywords
            and not _is_multi_intent_candidate(input_text)
        ):
            intents = [
                {
                    "intent": "order_status",
                    "confidence": max(score_order, 0.95),
                    "type": "primary",
                    **({"entities": {"orderId": fused_order_id}} if fused_order_id else {}),
                }
            ]
            await ctx.engine.log_intent_to_db(
                thread_id,
                input_text,
                intents,
                "embedding",
                intents[0]["confidence"],
                candidates=[*ctx.proposals, _proposal("embedding", "order_status", score_order)],
                arbitration_reason="embedding_order_status",
            )
            return StageVerdict(terminal=True, result=await _terminal_with_order_context(ctx, intents))

        # 判定 3: 明确退款执行意图直达
        # 多意图不打断(2026-09-12):关键词分支是单意图时代产物 —— 复合候选
        # 形下「查订单把没发货的退了」的查单词独走终端吞掉退款半(A3 实弹),
        # 让位结构化精判; embedding 高分分支(≥0.88)不受闸,主语义明确时照常直达。
        # money_action_yielded 同闸:规则层已判「资金词在场但意图是导购/购物车」,
        # 此处若独走退款终端,复合句的另一半又被吞(词表扩容后的连带面)。
        if (score_refund >= 0.88 and score_refund - score_oos >= 0.08) or (
            has_refund_keywords
            and not has_order_keywords
            and not _is_multi_intent_candidate(input_text)
            and not ctx.flags.get("money_action_yielded")
        ):
            refund_order_id = fused_order_id
            # 📷 意图浮现点消歧(2026-09-09):模糊损坏词(「坏了」)的售后意图
            # 由 damage_assessment 在此浮现,SlotExtractor 阶段还是 chat —— Step 1.6
            # 闸门因此永不触发。此处带图缺单号必须同样过消歧,否则为本场景
            # 造的商品选择卡对典型措辞失效,退回 planner 深规划自由发挥。
            if ctx.engine._vision_disambig_due(
                state,
                ctx.vision_analysis,
                after_sale=True,  # 判定3 分支本身即售后关键词成立
                order_id_resolved=refund_order_id,  # 融合单号(文本/上下文/OCR)非空即有主
            ):
                disambig = await ctx.engine._run_vision_disambig(state, ctx.vision_analysis, tenant_id)
                if disambig["status"] == "matched":
                    refund_order_id = disambig["orderId"]
                else:
                    return StageVerdict(
                        terminal=True,
                        result=await ctx.engine._vision_disambig_bypass(
                            state,
                            "refund",
                            max(score_refund, 0.95),
                            ctx.damage_assessment,
                            disambig,
                            candidates=[
                                *ctx.proposals,
                                _proposal("embedding", "refund", score_refund),
                            ],
                        ),
                    )
            intents = [
                {
                    "intent": "refund",
                    "confidence": max(score_refund, 0.95),
                    "type": "primary",
                    **({"entities": {"orderId": refund_order_id}} if refund_order_id else {}),
                }
            ]
            await ctx.engine.log_intent_to_db(
                thread_id,
                input_text,
                intents,
                "embedding",
                intents[0]["confidence"],
                candidates=[*ctx.proposals, _proposal("embedding", "refund", score_refund)],
                arbitration_reason="embedding_refund",
            )
            return StageVerdict(terminal=True, result=await _terminal_with_order_context(ctx, intents))

        # 判定 4: 超出业务范畴拦截 —— 锚点层降为提议者(intent-arbitration 06,
        # 2026-09-10)。旧路径 29 条锚句余弦 × 硬阈值判 oos 即直接关会话,零
        # LLM 确认:「买个东西怎么买」(购买流程咨询,oos 锚句相似 1.000)被
        # 误吞成零计划兜底,而结构化精判判 shopping_guide。现仅记提议后
        # fallthrough Step 3:LLM 确认出范畴 → llm_out_of_scope 收尾(行为
        # 不变,该路径 +1 调用可接受);改判 → 咨询直答/动作管线照常裁决。
        # 真 oos(天气/写代码)的确认调用经 01 的 node 归因计入延迟统计,
        # p50 咨询路径不含本路径,红线不破。
        if score_oos >= 0.86 and score_oos - max(score_order, score_refund) >= 0.06:
            ctx.proposals.append(_proposal("embedding", "out_of_scope", score_oos))
            if state.get("job_id"):
                from ...event_bus import emit_status

                await emit_status(
                    state["job_id"],
                    "🔎 锚点初判为业务范畴外,正在交由大模型复核确认...",
                    node="triage",
                )
    except Exception as embed_err:
        print(f"[Triage] 嵌入锚点分类异常,已跳过 Step 2 锚点判定 (threadId={thread_id}): {embed_err}")

    return StageVerdict.passthrough()


async def _terminal(ctx: StageContext, intents: list[dict]) -> dict:
    from ..intent_triage_engine import _triage_terminal_result

    return _triage_terminal_result(intents, ctx.input_text, ctx.history_msgs, ctx.damage_assessment, state=ctx.state)


async def _terminal_with_order_context(ctx: StageContext, intents: list[dict]) -> dict:
    from ..intent_triage_engine import _triage_terminal_result

    return _triage_terminal_result(
        intents,
        ctx.input_text,
        ctx.history_msgs,
        ctx.damage_assessment,
        state=ctx.state,
        with_order_context=True,
    )
