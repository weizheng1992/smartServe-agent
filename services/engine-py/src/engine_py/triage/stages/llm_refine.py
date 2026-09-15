"""🛡️ Step 3 大模型结构化联合精判 — Stage(原 process 段,逐字搬移)。

租户示例召回 → 结构化分类 → oos 确认收尾 → 单号形态校验与地址簿注入 →
意图浮现点消歧(Step 3)→ 缺槽反问收窄 → consult 直答/降级 → 终局落库。
LLM 熔断上抛走 job 级降级;其他异常兜底 general_query。
"""

from __future__ import annotations

from ...llm import CircuitBreakerOpenError
from ...tenant import tenant_of_state
from ..intent_registry import AgentIntentType
from ..product_disambiguator import AFTER_SALE_INTENTS
from ..slot_extractor import ORDER_ID_RE
from .context import StageContext, StageVerdict


def _engine_ns(ctx: StageContext):
    """协作符号经引擎**模块**命名空间运行时读取 —— 测试对 triage 模块的
    monkeypatch(triage_mod.classify 等存量 patch)借此对全管线生效;
    注意返回模块而非 IntentTriageEngine 类(类上没有这些符号)。"""
    import sys

    return sys.modules[ctx.engine.__module__]


def _route_marker():
    from ..consult_fast_path import ROUTE_TO_ACTION_MARKER

    return ROUTE_TO_ACTION_MARKER


def _money_action_intents():
    from ..intent_triage_engine import _MONEY_ACTION_INTENTS

    return _MONEY_ACTION_INTENTS


def _demote_consult_keep_actions(parsed):
    from ..intent_triage_engine import _demote_consult_keep_actions as f

    return f(parsed)


def _inject_address_manage(parsed, input_text):
    from ..intent_triage_engine import _inject_address_manage as f

    return f(parsed, input_text)


def _proposal(layer, intent, confidence=None):
    from ..intent_triage_engine import _proposal as f

    return f(layer, intent, confidence)


def _set_target_order_id(state, order_id):
    from ..intent_triage_engine import _set_target_order_id as f

    f(state, order_id)


def _should_clarify_first(parsed):
    from ..intent_triage_engine import _should_clarify_first as f

    return f(parsed)



async def judge(ctx: StageContext) -> StageVerdict:
    state, input_text, thread_id = ctx.state, ctx.input_text, ctx.thread_id
    # 🛡️ Step 3: 大模型结构化联合精判
    context_msgs = ctx.history_msgs[:-1]
    recent_history = "\n".join(
        f"{'User' if m.get('role') == 'user' else 'Assistant'}: {m.get('content')}"
        for m in context_msgs[-4:]
    )

    try:
        active_tenant_id = tenant_of_state(state)

        exemplars_prompt = ""
        try:
            matched_exemplars = await _engine_ns(ctx).search_relevant_exemplars(
                active_tenant_id, input_text, state.get("input_embedding") or [], 3
            )
            if matched_exemplars:
                exemplars_prompt = ctx.ns.format_exemplars_for_prompt(matched_exemplars)
        except Exception as ex_err:
            print(
                f"[Triage] 租户样本召回失败,降级空样本 "
                f"(threadId={thread_id}/tenantId={active_tenant_id}): {ex_err}"
            )

        structured_res = await _engine_ns(ctx).classify(
            input_text,
            recent_history_text=recent_history,
            exemplars_prompt=exemplars_prompt,
        )

        fallback_match = ORDER_ID_RE.search(input_text)
        fallback_order_id = fallback_match.group(0) if fallback_match else None

        # 分类器提议(Step 3 各决策点共用的 candidates 尾元素)
        llm_first = structured_res.intents[0] if structured_res.intents else None
        llm_proposal = _proposal(
            "structured_llm",
            llm_first.intent if llm_first else None,
            (llm_first.confidence if llm_first else None) or 0.9,
        )

        is_oos = structured_res.isOutOfScope or any(
            item.intent == "out_of_scope" for item in structured_res.intents
        )
        if is_oos:
            # 锚点 oos 提议的 LLM 确认终点(06):真 oos 在此收尾,candidates
            # 呈现 embedding→structured_llm 的确认链;改判则不进本分支,
            # 走下方 consult 直答 / 动作管线。宣称 out_of_scope × 落库
            # general_query:坏例池「宣称与落库不符」信号源同口径。
            reply = (
                "您好！我是您的高级智能电商客服助理，主要负责协助处理导购、购物车、订单物流及退款相关业务。"
                "您刚才提到的问题超出了我的服务范围（属于外部或高风险意图）。"
                "请问有什么具体的电商业务需要我协助吗？"
            )
            return StageVerdict(
                terminal=True,
                result=await ctx.engine.handle_immediate_bypass(
                    state,
                    "llm_out_of_scope",
                    reply,
                    [{"intent": "general_query", "confidence": 0.9}],
                    "structured_llm",
                    0.9,
                    candidates=[
                        *ctx.proposals,
                        _proposal("structured_llm", "out_of_scope", 0.9),
                    ],
                ),
            )

        parsed: list[dict] = []
        for idx, item in enumerate(structured_res.intents):
            entities = dict(item.entities or {})
            # 单号形态校验(多意图一期,2026-09-12):分类器自由抽取的
            # orderId 连宽松单号正则都不过时(「退了订单9081」的尾缀被抽成
            # 单号,A6 实弹:执行器未调工具即宣称退款成功)必须剥除并补缺槽
            # 注记 —— 资金/订单动作严禁以假单号为据执行;规范化单号
            # (ORD-/AURORA-ORD-)不受影响,正则 fallback 通道本就合法。
            raw_order_id = entities.get("orderId")
            if raw_order_id and not ORDER_ID_RE.search(str(raw_order_id)):
                entities.pop("orderId", None)
                if item.intent in _money_action_intents() and "orderId" not in (item.missingSlots or []):
                    item.missingSlots = list(item.missingSlots or []) + ["orderId"]
            primary_order_id = entities.get("orderId") or fallback_order_id
            if primary_order_id:
                entities["orderId"] = primary_order_id
            parsed.append(
                {
                    "intent": item.intent,
                    "confidence": item.confidence or 0.9,
                    "type": item.type or ("primary" if idx == 0 else "secondary"),
                    "entities": entities,
                    # 多意图不打断(2026-09-12):缺槽注记随行 —— 缺槽反问
                    # 收窄谓词与 planner「尽力而为」规则都以它为输入
                    "missingSlots": list(item.missingSlots or []),
                    **({"condition": item.condition.model_dump()} if item.condition else {}),
                }
            )

        primary_order_id = next(
            (p["entities"]["orderId"] for p in parsed if p["entities"].get("orderId")), None
        )
        if primary_order_id:
            _set_target_order_id(state, primary_order_id)

        # 地址簿复合注入(多意图一期,2026-09-12):分类器词表无地址簿档位,
        # 建地址形(可复合下单/导购)在此提为 primary,A1「建地址+下单寄新
        # 地址」由此双意图进 planner。
        parsed = _inject_address_manage(parsed, input_text)

        # 📷 意图浮现点消歧 · Step 3(2026-09-09):分类器判出售后意图、带图
        # 且全链无单号(文本/OCR/上下文)时同样过商品消歧 —— 与判定 3 同理,
        # 售后意图可能到精判才浮现。matched 注入 parsed 实体与订单上下文并
        # 令下方澄清分支让位(结构化输出的 missingSlots 是注入前的陈旧快照);
        # ambiguous/no_orders 走商品选择卡旁路。
        vision_disambig_matched = False
        has_after_sale = any(p["intent"] in AFTER_SALE_INTENTS for p in parsed)
        after_sale_missing_order = any(
            p["intent"] in AFTER_SALE_INTENTS and not p["entities"].get("orderId")
            for p in parsed
        )
        if ctx.engine._vision_disambig_due(
            state,
            ctx.vision_analysis,
            after_sale=has_after_sale and after_sale_missing_order,
            order_id_resolved=None,  # 缺单号已由 after_sale_missing_order 表达(per-intent entities)
        ):
            disambig = await ctx.engine._run_vision_disambig(
                state, ctx.vision_analysis, active_tenant_id
            )
            if disambig["status"] == "matched":
                vision_disambig_matched = True
                for p in parsed:
                    if p["intent"] in AFTER_SALE_INTENTS:
                        p["entities"]["orderId"] = disambig["orderId"]
            else:
                return StageVerdict(
                    terminal=True,
                    result=await ctx.engine._vision_disambig_bypass(
                        state,
                        parsed[0]["intent"] if parsed else "refund",
                        parsed[0]["confidence"] if parsed else 0.9,
                        ctx.damage_assessment,
                        disambig,
                        candidates=[*ctx.proposals, llm_proposal],
                    ),
                )

        # 缺槽反问收窄(多意图不打断一期,2026-09-12):仅 primary 缺槽且
        # 无营救意图时反问;secondary 缺槽(A1:改单地址缺单号)不劫持
        # primary 齐备的复合轮,放行 planner 先办能办的、结尾一次性追问。
        if (
            _should_clarify_first(parsed)
            and structured_res.clarificationMessage
            and not vision_disambig_matched
        ):
            return StageVerdict(
                terminal=True,
                result=await ctx.engine.handle_immediate_bypass(
                    state,
                    "slot_clarification_structured",
                    structured_res.clarificationMessage,
                    parsed,
                    "structured_llm",
                    parsed[0]["confidence"] if parsed else 0.9,
                    ctx.damage_assessment,
                    candidates=[*ctx.proposals, llm_proposal],
                ),
            )

        # 🛣️ 分类器判 consult(规则层漏网的咨询措辞)× RAG 非空 → 直答快轨;
        # RAG 空弱降级 general_query,免得 planner 对未知咨询意图深度规划失控
        if parsed and parsed[0].get("intent") == AgentIntentType.CONSULT:
            consult_hit = await _engine_ns(ctx).run_consult_direct_answer(state, ctx.history_msgs)
            if consult_hit is not None:
                consult_answer, _, consult_confidence = consult_hit
                if consult_answer == _route_marker():
                    # 🧭 仲裁员否决(05):分类器判 consult × 仲裁员判动作形。
                    # 不再 fallthrough 深规划(consult 落 planner 会失控深规划),
                    # 降级离场;降级保留动作形条目并提升首个动作为 primary
                    # (工单06 2026-09-11)—— 否决只否「资讯直答」,不否动作,
                    # 带动作意图的请求绝不因一条资讯回复了事(故事3/5),
                    # 提升后非单 general_query 自然进 planner 编排。
                    # 否决进 candidates 留痕,终局行可溯改判来源。
                    ctx.proposals.append(_proposal("consult_arbiter", None))
                    parsed = _demote_consult_keep_actions(parsed)
                else:
                    return StageVerdict(
                        terminal=True,
                        result=await ctx.engine.handle_immediate_bypass(
                            state,
                            "rag_consult_direct_llm",
                            consult_answer,
                            parsed,
                            "rag_direct",
                            consult_confidence,
                            ctx.damage_assessment,
                            candidates=[*ctx.proposals, llm_proposal],
                        ),
                    )
            else:
                # RAG 空弱:同款降级离场(工单06:保留动作形并提升 primary;
                # 纯 consult 输入输出与旧整体降级同形)
                parsed = _demote_consult_keep_actions(parsed)

        confidence = parsed[0]["confidence"] if parsed else 0.85
        await ctx.engine.log_intent_to_db(
            thread_id,
            input_text,
            parsed,
            "structured_llm",
            confidence,
            candidates=[*ctx.proposals, llm_proposal],
            arbitration_reason="structured_llm_terminal",
        )

        if state.get("job_id"):
            from ...event_bus import emit_status

            await emit_status(
                state["job_id"],
                "用户意图识别成功！检测到核心意图: "
                + ", ".join(p["intent"] for p in parsed)
                + " (置信度: "
                + ", ".join(f"{p['confidence']:.2f}" for p in parsed)
                + ")",
                node="triage",
            )

        from ..intent_triage_engine import _triage_terminal_result

        return StageVerdict(
            terminal=True,
            result=_triage_terminal_result(
                parsed, input_text, ctx.history_msgs, ctx.damage_assessment,
                state=state, with_order_context=True,
            ),
        )
    except CircuitBreakerOpenError:
        # 上游 LLM 熔断非节点级可恢复:上抛 run_agent 走 job 级降级(兜底 intent 仅面向分类输出类失败)
        raise
    except Exception as err:
        print(f"[Triage] Step 3 结构化精判失败,降级兜底意图 (threadId={thread_id}): {err}")
        fallback_intents = [{"intent": "general_query", "confidence": 0.5}]
        await ctx.engine.log_intent_to_db(
            thread_id,
            input_text,
            fallback_intents,
            "structured_llm_fallback",
            0.5,
            candidates=list(ctx.proposals),
            arbitration_reason="structured_llm_exception_fallback",
        )
        from ..intent_triage_engine import _triage_terminal_result

        return StageVerdict(
            terminal=True,
            result=_triage_terminal_result(fallback_intents, input_text, ctx.history_msgs, ctx.damage_assessment),
        )
