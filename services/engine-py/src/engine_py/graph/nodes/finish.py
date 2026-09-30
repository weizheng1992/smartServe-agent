"""收尾节点 — 镜像 finish.node.ts(熔断道歉文案/审批转接文案/旁路透传/RAG 注入/LLM 终稿)。

TODO(Phase 1b):CardSynthesizer 卡片合成、session_metrics 埋点、LangSmith 回传。
"""

from __future__ import annotations

import json

from ...llm import CircuitBreakerOpenError, bind_llm_call_node, get_chat_model
from ...memory import ShortMemory
from ...skills import is_action_query
from ...tenant import get_merchant_display_name, sanitize_tenant_response
from ...triage import add_query_to_semantic_cache
from ..state import AgentState, build_history_context

# 注:finish 节点只更新 state,不直接发布事件;终态事件由 run_agent 收口发布。


async def _resolve_tenant_id(state: dict) -> str:
    tenant_id = str(
        (state.get("business_config") or {}).get("businessId") or state.get("business_id") or "ecommerce"
    ).lower()
    if state.get("thread_id") and (tenant_id == "ecommerce" or not tenant_id):
        try:
            from sqlalchemy import select

            from ...db import Thread, get_session

            async with get_session() as session:
                row = (
                    await session.execute(select(Thread).where(Thread.id == state["thread_id"]).limit(1))
                ).scalar_one_or_none()
                if row and row.business_id:
                    tenant_id = row.business_id.lower()
        except Exception as err:
            print(f"[FinishNode] Failed to resolve thread tenantId: {err}")
    return tenant_id


async def finish_node(state: AgentState) -> dict:
    bind_llm_call_node("finish")
    short_memory = state.get("short_memory") or []
    tenant_id = await _resolve_tenant_id(dict(state))
    brand_name = get_merchant_display_name(tenant_id)

    global_transitions = state.get("global_transitions_count") or 0
    tool_errors = state.get("tool_errors_count") or 0
    plan = state.get("task_plan") or {"subtasks": []}
    subtasks = plan.get("subtasks") or []

    # 🛡️ 图级硬熔断:直接返回高保真道歉文案,免除 LLM 调用。
    # 诚实纪律(2026-09-27 事故):旧文案谎称「已自动转接人工客服,1 分钟内接管」,
    # 但熔断路径没有任何转接动作(assigned_operator_id 不变、无接管房间通知),
    # 顾客按承诺等人工永远等不到。现改为如实指引 —— 「转人工」是规则层真实
    # 意图(rule_matchers),回复即真触发人工接管。阈值经 build_graph 单源;
    # 函数内延迟导入(build_graph ⇄ nodes 模块环)。
    from ..build_graph import CIRCUIT_BREAKER_TOOL_ERRORS, CIRCUIT_BREAKER_TRANSITIONS

    if global_transitions >= CIRCUIT_BREAKER_TRANSITIONS or tool_errors >= CIRCUIT_BREAKER_TOOL_ERRORS:
        apology = (
            f"您好！我是 {brand_name} 的智能客服助手。由于系统繁忙，本次自动服务已中止，"
            "您的资金与订单安全不受任何影响。\n\n"
            "如需人工帮助，请直接回复「**转人工**」，人工客服将尽快在本会话中为您服务；"
            "您也可以稍后重试刚才的请求。给您带来不便，我们深表歉意！🙏"
        )
        return {"output": sanitize_tenant_response(apology, tenant_id), "short_memory": short_memory}

    # 🛡️ 人工转接挂起直达文案
    approval_step = next((st for st in subtasks if (st.get("result") or {}).get("waitingForApproval")), None)
    if approval_step:
        result = approval_step.get("result") or {}
        is_human_escalation = result.get("actionType") == "human_escalation" or "human_escalation" in (
            approval_step.get("description") or ""
        ).lower()
        if is_human_escalation:
            # 诚实化(2026-09-29 实弹):旧文案承诺「加密推送到主管接管队列 /
            # 1 分钟内接管」而系统并无队列与时效保证 —— 过度承诺即投诉源。
            # 现实语义:工单已建 + 接管活态翻「呼叫中」,坐席认领后消息经桥
            # 实时送达;无人认领由排队超时回落 AI(诚实告知,可再次呼叫)。
            escalation_reply = (
                f"您好！我是 {brand_name} 的智能客服助手，已为您呼叫人工客服。📞\n\n"
                "人工客服将尽快在本会话接入并回复您；接入前您也可以继续留言补充问题。"
            )
            return {"output": sanitize_tenant_response(escalation_reply, tenant_id), "short_memory": short_memory}

    # 🛡️ 前置旁路直达响应透传
    if state.get("output") and not approval_step and global_transitions <= 0:
        return {
            "output": sanitize_tenant_response(state["output"], tenant_id),
            "short_memory": short_memory,
        }

    input_text = state.get("input", "")

    # 📦 Contextual RAG 租户隔离知识注入
    rag_context = ""
    rag_documents = state.get("rag_documents") or []
    if rag_documents:
        formatted_docs = "\n".join(
            f'[Store Policy Rule {idx + 1}] (Context Summary: {doc.get("contextualSummary") or "N/A"}): '
            f'"{doc.get("chunkText")}"'
            for idx, doc in enumerate(rag_documents)
        )
        rag_context = (
            f"\n\n[RELEVANT STORE POLICIES & KNOWLEDGE BASE]:\n{formatted_docs}\n"
            "If relevant, explain these policies politely to the customer in Chinese to justify why certain "
            "actions (like returns or shipping constraints) can or cannot be taken, and strictly ground your "
            "explanation on these rules."
        )

    # 🧠 画像/情境记忆注入(persona-hardening 03 裁决:终稿单点 + 防复读闸)
    # bug#2 教训制度化:画像参与措辞 ≠ 参与检索 —— 块指令明写「未参与当轮
    # 过滤时严禁宣称已按偏好过滤」。空召回零渲染零 token。
    # 上限与召回侧同源(画像 Top-5 / 情境 Top-3):召回调大 limit 时须同步。
    profile_limit, events_limit, text_cap = 5, 3, 80

    def _memory_lines(items: list, text_key: str, limit: int, tag=None) -> list[str]:
        lines: list[str] = []
        for item in items[:limit]:
            text = str(item.get(text_key) or "").strip() if isinstance(item, dict) else str(item or "").strip()
            if not text:
                continue
            if len(text) > text_cap:
                text = text[:text_cap] + "…"
            prefix = f"[{tag(item)}] " if tag else ""
            # 编号只给实际渲染行,空文本行跳号
            lines.append(f"{len(lines) + 1}. {prefix}{text}")
        return lines

    def _scope_tag(fact) -> str:
        # 缺失 scope 兜底 global 与系统语义同向:召回侧 `row.scope or "global"`
        # 已归并,DB 默认即 global;可见性闸在召回 _tenant_visible,渲染侧
        # 不构成 tenant 事实误标全局的泄漏面。
        return fact.get("scope") if isinstance(fact, dict) and fact.get("scope") in ("global", "tenant") else "global"

    persona_context = ""
    persona_lines = _memory_lines(state.get("long_memory_facts") or [], "fact", profile_limit, tag=_scope_tag)
    if persona_lines:
        persona_context = (
            "\n\n[USER PROFILE MEMORY]:\n" + "\n".join(persona_lines) + "\n"
            "These are the customer's approved profile facts. Reference them ONLY when relevant to the "
            "current question (e.g. size conversion, recommendation phrasing, continuity of past topics). "
            "They were NOT applied to filter or search products in this turn — you MUST NOT claim that "
            "recommendations were filtered, selected, or combined based on these preferences unless such "
            "filtering actually happened in this turn's retrieval (the current tool results show it)."
        )

    episodic_context = ""
    event_lines = _memory_lines(state.get("episodic_events") or [], "event", events_limit)
    if event_lines:
        episodic_context = (
            "\n\n[MEMORY OF PAST EVENTS]:\n" + "\n".join(event_lines) + "\n"
            "These are the customer's past business events with this store; mention them only when "
            "relevant for conversational continuity."
        )

    default_system_prompt = (
        f"You are an advanced, professional AI Customer Support Agent representing {brand_name}. "
        "Help users resolve order, shipping, and refund queries."
    )
    business_system_prompt = (state.get("business_config") or {}).get("systemPrompt")
    system_prompt = (
        business_system_prompt if business_system_prompt and brand_name in business_system_prompt else default_system_prompt
    )

    tenant_context = (
        f"\n\n[MULTI-TENANT ISOLATION BOUNDARY]:\n"
        f"You are an AI Customer Support Agent representing: {brand_name} (Merchant identifier: {tenant_id}).\n"
        f"- Always address yourself naturally and politely as the customer service assistant for {brand_name}.\n"
        f"- You must strictly align your replies, recommendations, and decisions with {brand_name}'s store "
        "policies and real system tool results.\n"
        f'- In all user-facing sentences, refer to the store strictly by its real brand name "{brand_name}". '
        'Never output raw placeholder IDs like "[ECOMMERCE]" or "[BRAND]".\n'
        '- If the tool "listUserOrders" returns orders in "orders", summarize the found '
        f"{brand_name} orders with their Order IDs, statuses, and amounts.\n"
        '- If the tool "listUserOrders" returns an empty list or no orders found, politely inform the customer '
        f"in Chinese that no order records were found under their account in {brand_name}, and invite them to "
        "provide an order number or check their login account.\n"
        "- If the customer explicitly asks to query or operate on unrelated external brands/stores that you do "
        f"not represent, politely explain that you are the dedicated customer assistant for {brand_name} and "
        f"only handle {brand_name} orders and services."
    )

    if not short_memory:
        short_memory = await ShortMemory(state.get("thread_id", "")).get_messages()
    history_context = ""
    if short_memory:
        formatted_history = build_history_context(short_memory)
        if formatted_history:
            history_context = f"\n\n[CONVERSATION HISTORY (PAST TURNS)]:\n{formatted_history}"

    prompt = (
        f'System Instruction Context: "{system_prompt}"{tenant_context}\n'
        "Formulate a clean, professional, and helpful customer support message in Chinese.\n"
        f'Customer Question: "{input_text}"\n'
        "The plan execution details (the ultimate truth from physical database) are: "
        f"{json.dumps(subtasks, ensure_ascii=False, default=str)}{rag_context}{persona_context}{episodic_context}{history_context}"
        "Locally discussed details might also reside in the conversation history above.\n\n"
        "CRITICAL RULES (最高行为准则 - 严禁幻觉与跨租户泄露):\n"
        '1. If the customer is asking about what was just discussed, what actions were just performed in '
        'previous turns, or meta-questions about the conversation history (e.g., "刚退款的是哪笔订单?", '
        '"我们刚刚查了什么?"), you MUST answer based on the [CONVERSATION HISTORY (PAST TURNS)] above.\n'
        "2. Otherwise, for any new queries regarding order status or refunds that executed tools in the "
        "current turn, you must answer 100% based on the REAL tools results in the current subtasks list.\n"
        '3. If any tool returned an error or was blocked by policy (e.g. "Address modification blocked: '
        'Order ... is currently [SHIPPED]", "Order not found", or "Failed to process"), you MUST honestly '
        "and politely inform the customer in Chinese that the operation cannot be completed (for example: "
        "the parcel has already been shipped/dispatched, so the shipping address cannot be modified "
        "directly, and recommend contacting the courier or rejecting on delivery). Under NO circumstances "
        "should you state that the address was successfully changed when the tool returned an error!\n"
        "4. If the tool executed successfully and returned the order details (status, carrier, etc.), you "
        "summarize them accurately.\n"
        '5. If the executed tool was "listUserOrders" and returned an array of orders in "orders", provide '
        "a concise summary greeting (e.g. stating the number of orders found) and politely guide the "
        "customer to choose an order from the interactive order cards below or reply with the order ID to "
        "proceed with logistics tracking or refunds. DO NOT redundantly list out full itemized markdown "
        f"details for every single order when interactive cards are already attached.\n"
        f"6. Keep the output professional, polite, and fully in Chinese. Refer to the store strictly as {brand_name}.\n"
        "7. Under NO circumstances should you hallucinate or fabricate information about other brands. If "
        "the customer explicitly asks to query an external brand/store, politely reply that you only "
        f"represent {brand_name}.\n"
        "8. BUDGET HONESTY (预算转述纪律, 2026-09-27): The tool/skill output is the ONLY source for price "
        "totals. NEVER claim 「总价不超过X」「合计在预算内」 unless the tool result explicitly states that "
        "conclusion; if the tool output shows a total exceeding the customer's stated budget, you MUST "
        "faithfully relay the overage — claiming budget compliance when the items sum over budget is a lie."
    )

    try:
        response = await get_chat_model().ainvoke(prompt)
        raw_content = response.content if hasattr(response, "content") else str(response)
        sanitized_content = sanitize_tenant_response(raw_content, tenant_id)

        # 🚀 general_query 结果回填语义缓存
        # 🛡️ 写闸(防缓存投毒,2026-09-04 幻觉加购 bug 加固):技能可处理的"动作形"
        # 输入禁止回填 —— 走到 LLM 终稿分支的 general_query 回复没有任何工具执行
        # 结果背书,一旦写入,后续相似请求将以 ≥0.96 相似度永久命中缓存、绕过
        # 真实技能执行(正是"已成功加购"幻觉扩散的机制)。
        intents = state.get("intents") or []
        is_only_general = len(intents) == 1 and intents[0].get("intent") == "general_query"
        input_embedding = state.get("input_embedding") or []
        if (
            is_only_general
            and state.get("input")
            and len(input_embedding) > 0
            and not is_action_query(state["input"], tenant_id)
        ):
            try:
                add_query_to_semantic_cache(tenant_id, state["input"], sanitized_content.strip(), input_embedding)
            except Exception as cache_err:
                print(f"[Finish Cache] Failed to cache general query: {cache_err}")

        return {"output": sanitized_content.strip(), "short_memory": short_memory}
    except CircuitBreakerOpenError:
        # 上游 LLM 熔断非节点级可恢复:上抛 run_agent 走 job 级降级道歉
        # + session_metrics 落 llm_circuit_breaker(兜底仅面向解析/输出类失败)
        raise
    except Exception as err:
        print(f"finishNode failed, using fallback summary: {err}")
        # 确定性兜底分发器(2026-09-19「兜底什么回答什么」):LLM 终稿失败时,
        # 词面可路由的问题(优惠/券/订单状态)仍由数据技能/真实查询回答;
        # 无能力命中才保留罐头。数据诚实铁律:只答真实查到的。
        try:
            from engine_py.skills.fallback_dispatcher import deterministic_fallback_answer

            fallback_output = await deterministic_fallback_answer(
                state.get("input") or state.get("input_text") or "",
                state.get("thread_id"),
                state.get("userId") or state.get("user_id") or "",
                state.get("businessId") or "aurora",
            )
        except Exception as fb_err:
            print(f"[Finish] 确定性兜底失败: {fb_err}")
            fallback_output = None
        if fallback_output:
            return {"output": fallback_output, "short_memory": short_memory}
        fallback_details = json.dumps(
            [st.get("result") for st in subtasks], ensure_ascii=False, default=str
        )
        return {
            "output": f"您好！您的请求已由 {brand_name} 客服系统处理。执行详情：{fallback_details}",
            "short_memory": short_memory,
        }
