"""收尾节点 — 镜像 finish.node.ts(熔断道歉文案/审批转接文案/旁路透传/RAG 注入/LLM 终稿)。

TODO(Phase 1b):CardSynthesizer 卡片合成、session_metrics 埋点、LangSmith 回传。
"""

from __future__ import annotations

import json

from ...llm import get_chat_model
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
        except Exception as err:  # noqa: BLE001
            print(f"[FinishNode] Failed to resolve thread tenantId: {err}")
    return tenant_id


async def finish_node(state: AgentState) -> dict:
    short_memory = state.get("short_memory") or []
    tenant_id = await _resolve_tenant_id(dict(state))
    brand_name = get_merchant_display_name(tenant_id)

    global_transitions = state.get("global_transitions_count") or 0
    tool_errors = state.get("tool_errors_count") or 0
    plan = state.get("task_plan") or {"subtasks": []}
    subtasks = plan.get("subtasks") or []

    # 🛡️ 图级硬熔断:直接返回高保真道歉文案,免除 LLM 调用
    if global_transitions >= 10 or tool_errors >= 3:
        apology = (
            f"您好！我是 {brand_name} 的智能客服助手。由于当前系统网络出现短暂波动，或者底层接口响应延迟，"
            "为了保障您的账户、资金安全，我们已经**自动为您【熔断并终止】了本次自动决策流程**。✨\n\n"
            "我们非常重视您的体验，请您完全放心：\n"
            "1. **资金双写安全保障**：所有高危敏感动作（如退款）均处于完全锁定状态，"
            "绝对不会发生多扣款、重复退款 or 数据混淆。\n"
            "2. **已为您自动转接至特级高级客服**：我已将您此前的全部沟通记录、已规划步骤以及遇到的异常参数"
            "**自动加密转交到我们的一线资深人工客服主管**。\n\n"
            "人工主管专员将在 **1 分钟内直接在本会话中为您接管服务并妥善解决**，请您稍等。"
            "给您带来的不便我们深感抱歉，感谢您的宝贵耐心！👋"
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
            escalation_reply = (
                f"您好！我是 {brand_name} 的智能客服助手。已为您**成功触发人工客服接入流程**。✨\n\n"
                "我们已锁定了当前会话，并将您的提问、已知订单数据与完整历史沟通记录"
                "**加密推送到资深人工客服主管接管队列**。\n\n"
                "人工主管专员将在 **1 分钟内直接在本会话中为您接管服务并回应**，请您稍等。"
                "如您有更多细节补充，也可以直接在此留言！👋"
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
        f"{json.dumps(subtasks, ensure_ascii=False, default=str)}{rag_context}{history_context}"
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
        f"represent {brand_name}."
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
            except Exception as cache_err:  # noqa: BLE001
                print(f"[Finish Cache] Failed to cache general query: {cache_err}")

        return {"output": sanitized_content.strip(), "short_memory": short_memory}
    except Exception as err:  # noqa: BLE001
        print(f"finishNode failed, using fallback summary: {err}")
        fallback_details = json.dumps(
            [st.get("result") for st in subtasks], ensure_ascii=False, default=str
        )
        return {
            "output": f"您好！您的请求已由 {brand_name} 客服系统处理。执行详情：{fallback_details}",
            "short_memory": short_memory,
        }
