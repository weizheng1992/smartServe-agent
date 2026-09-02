"""任务规划节点 — 镜像 planner.node.ts(470 LOC,全量移植)。

极速直达通道(Fast-Path)优先于 LLM 规划:general_query 旁路、热恢复计划复用、
驳回认知回溯、人工转接直达、复合诉求组装、泛查单直达、订单号关联多意图组装。
"""

from __future__ import annotations

import json
import re

from ...approvals import find_approval_by_id, find_latest_approval_by_thread_id
from ...event_bus import emit_status
from ...llm import get_chat_model
from ...memory import ShortMemory
from ...tenant import get_merchant_display_name
from ..state import AgentState, build_history_context
from .utils import extract_order_id

_EXPLICIT_ORDER_ID_RE = re.compile(r"(?:[A-Za-z0-9]+-)*ORD-[A-Za-z0-9_-]+", re.IGNORECASE)
_GENERAL_ORDER_LIST_RE = re.compile(
    r"查询.*订单|查订单|我的订单|订单列表|名下.*订单|支持退货.*订单|支持退款.*订单|可退.*订单|哪些.*订单|订单|我问订单",
    re.IGNORECASE,
)


async def planner_node(state: AgentState) -> dict:
    intents = state.get("intents") or []
    input_text = state.get("input", "")
    job_id = state.get("job_id")

    # 🧠 general_query 极简旁路:Null 步骤瞬间穿透到 Finish
    if len(intents) == 1 and intents[0].get("intent") == "general_query":
        direct_plan = {
            "goal": "Bypass planner loop and respond to general query directly",
            "subtasks": [
                {"id": "respond_general", "description": "Present general query response to user", "status": "pending"}
            ],
            "currentStepIndex": 0,
        }
        if job_id:
            await emit_status(
                job_id,
                "检测到日常问询或欢迎语诉求，系统已完美启用【极速直达旁路】，无需进入复杂的工具规划与自旋校验环...",
                node="planner",
                plan=direct_plan,
            )
        return {"task_plan": direct_plan, "global_transitions_count": 1}

    if job_id:
        await emit_status(
            job_id, "正在根据分类意图，由大模型动态生成高精准子步骤执行规划...", node="planner"
        )

    prior_plan = state.get("task_plan") or {}
    prior_subtasks = prior_plan.get("subtasks") or []

    # 🛡️ Plan-Preservation Bypass(HOT-RESUME):审批已决议则 100% 复用历史计划
    if prior_subtasks:
        current_step_index = prior_plan.get("currentStepIndex", 0)
        current_step = (
            prior_subtasks[current_step_index] if 0 <= current_step_index < len(prior_subtasks) else None
        )
        if current_step and (
            (current_step.get("result") or {}).get("waitingForApproval") or current_step.get("status") == "pending"
        ):
            try:
                approval_id = (current_step.get("result") or {}).get("approvalId")
                latest_approval = (
                    await find_approval_by_id(approval_id)
                    if approval_id
                    else await find_latest_approval_by_thread_id(state.get("thread_id", ""))
                )
                if latest_approval and latest_approval["status"] in (
                    "approved",
                    "cancelled",
                    "resolved_by_human",
                ):
                    status_label = (
                        "核准"
                        if latest_approval["status"] == "approved"
                        else "人工接管办结"
                        if latest_approval["status"] == "resolved_by_human"
                        else "取消"
                    )
                    if job_id:
                        await emit_status(
                            job_id,
                            f"🔄 恢复计划：检测到历史执行工单已人工审核决议为 [{status_label}]，"
                            "跳过大模型规划，100% 物理复用历史步骤并精确恢复执行流！",
                            node="planner",
                            plan=prior_plan,
                        )
                    return {"task_plan": prior_plan, "global_transitions_count": 1}
            except Exception as db_err:  # noqa: BLE001
                print(f"[Planner Bypass] Failed to check approval status for bypass: {db_err}")

    # 🧠 Cognitive State Backtracking:管理员驳回 → failed/rejectedByAdmin 标记 + 重规划上下文
    rejection_context = ""
    is_system_resume = isinstance(input_text, str) and input_text.startswith("System:")
    if is_system_resume and prior_subtasks:
        current_step_index = prior_plan.get("currentStepIndex", 0)
        step = prior_subtasks[current_step_index] if 0 <= current_step_index < len(prior_subtasks) else None
        step_approval_id = (step.get("result") or {}).get("approvalId") if step else None

        latest_approval = None
        try:
            latest_approval = (
                await find_approval_by_id(step_approval_id)
                if step_approval_id
                else await find_latest_approval_by_thread_id(state.get("thread_id", ""))
            )
        except Exception as db_err:  # noqa: BLE001
            print(f"[Planner Rejection Check] Failed to check latest approval for backtracking: {db_err}")

        if latest_approval and latest_approval["status"] == "rejected":
            if step and (
                (step.get("result") or {}).get("waitingForApproval")
                or step.get("status") in ("pending", "executing")
            ):
                rejection_reason = (
                    latest_approval["actionPayload"].get("rejectionReason")
                    or latest_approval.get("reason")
                    or "No reason provided"
                )
                prior_subtasks[current_step_index] = {
                    **step,
                    "status": "failed",
                    "result": {
                        **(step.get("result") or {}),
                        "rejectedByAdmin": True,
                        "rejectionReason": rejection_reason,
                    },
                }
                prior_plan = {**prior_plan, "subtasks": prior_subtasks}

        rejected_step = next(
            (st for st in prior_subtasks if st.get("status") == "failed" and (st.get("result") or {}).get("rejectedByAdmin")),
            None,
        )
        if rejected_step:
            rejection_reason = (rejected_step.get("result") or {}).get("rejectionReason") or "No reason provided"
            rejection_context = (
                f'\n\n[CRITICAL ADVISORY]: A previous step "{rejected_step.get("description")}" was '
                f'REJECTED by the Administrator.\nRejection feedback/reason: "{rejection_reason}".\n'
                "Please replan and output an alternative approach that respects this rejection. Do NOT suggest "
                "the same rejected action. If a smaller refund was suggested, adjust the amount. If the user "
                "request cannot be fulfilled, generate a step to explain the reason politely to the user."
            )

    # 📦 SaaS Contextual RAG 注入
    rag_context = ""
    rag_documents = state.get("rag_documents") or []
    if rag_documents:
        formatted_docs = "\n".join(
            f'[Store Policy Rule {idx + 1}] (Context Summary: {doc.get("contextualSummary") or "N/A"}): '
            f'"{doc.get("chunkText")}"'
            for idx, doc in enumerate(rag_documents)
        )
        rag_context = (
            f"\n\n[RELEVANT BUSINESS POLICIES & KNOWLEDGE BASE]:\n{formatted_docs}\n"
            "Strictly adhere to these store policies while making the plan. If a policy specifies return "
            "timelines, tag conditions, or shipping methods, make sure any proposed subtasks or user "
            "communication steps strictly follow these rules."
        )

    tenant_id = str((state.get("business_config") or {}).get("businessId") or "ecommerce").lower()
    brand_name = get_merchant_display_name(tenant_id)
    default_system_prompt = (
        f"You are an advanced, professional AI Customer Support Agent representing {brand_name}. "
        "Help users resolve order, shipping, and refund queries."
    )
    business_system_prompt = (state.get("business_config") or {}).get("systemPrompt")
    system_prompt = (
        business_system_prompt
        if business_system_prompt and brand_name in business_system_prompt
        else default_system_prompt
    )
    tenant_context = (
        f"\n\n[MULTI-TENANT ISOLATION BOUNDARY]:\n"
        f"You are an AI Customer Support Agent representing: {brand_name} (Merchant identifier: {tenant_id}).\n"
        f"- Always plan subtasks and customer responses representing {brand_name}.\n"
        f"- You must strictly align your plan with {brand_name}'s store policies and system tools.\n"
        f'- In all user-facing subtasks, refer to the store strictly by its real brand name "{brand_name}".\n'
        "- If the customer explicitly asks to query or operate on unrelated external brands/stores, plan to "
        f"politely refuse and clarify that you only support {brand_name}."
    )

    # 🚀 会话上下文记忆注入
    short_memory = state.get("short_memory") or []
    if not short_memory:
        short_memory = await ShortMemory(state.get("thread_id", "")).get_messages()
    history_context = ""
    if short_memory:
        formatted_history = build_history_context(short_memory)
        if formatted_history:
            history_context = (
                f"\n\n[CONVERSATION HISTORY (PAST TURNS)]:\n{formatted_history}\n\n"
                "[CRITICAL DIRECTIVE]: Carefully read the conversation history above. If the customer is "
                "requesting a refund or action in their current input, and they have already provided a "
                "specific order ID in previous turns (or you have already queried it successfully), you MUST "
                "extract and use that order ID to formulate your subtasks (e.g. processRefund with orderId: "
                "ORD-98712). DO NOT plan to ask the customer for the order ID again if it was already "
                "mentioned or established in the history!"
            )

    # ⚡ 极速直达通道(Fast-Path,零 LLM 开销)
    if not rejection_context and intents:
        single_intent = intents[0].get("intent")

        if single_intent == "human_escalation":
            fast_plan = {
                "goal": "Escalate conversation to human support operator",
                "subtasks": [
                    {
                        "id": "step_fast_human_escalation",
                        "description": "Trigger human escalation and create pending approval ticket for customer support operator",
                        "status": "pending",
                    }
                ],
                "currentStepIndex": 0,
            }
            if job_id:
                await emit_status(
                    job_id,
                    "⚡ 极速介入直达：检测到人工客服与熔断诉求，已物理生成人工转接步骤并推入执行链！",
                    node="planner",
                    plan=fast_plan,
                )
            return {"task_plan": fast_plan, "short_memory": short_memory, "global_transitions_count": 1}

        has_shopping_guide = any(i.get("intent") == "shopping_guide" for i in intents)
        has_cart_manage = any(i.get("intent") == "cart_manage" for i in intents)
        has_order_list = any(i.get("intent") in ("order_status", "order_query") for i in intents)

        if (has_shopping_guide or has_cart_manage) and has_order_list and len(intents) >= 2:
            fast_subtasks = []
            if has_cart_manage:
                fast_subtasks.append(
                    {"id": "step_fast_cart_0", "description": f"Execute CartSkill for input: {input_text}", "status": "pending"}
                )
            else:
                fast_subtasks.append(
                    {"id": "step_fast_guide_0", "description": f"Execute ShoppingGuideSkill for input: {input_text}", "status": "pending"}
                )
            fast_subtasks.append(
                {"id": "step_fast_list_orders_1", "description": "Call listUserOrders to fetch recent orders", "status": "pending"}
            )
            fast_plan = {
                "goal": "Execute composite shopping and order query subtasks",
                "subtasks": fast_subtasks,
                "currentStepIndex": 0,
            }
            if job_id:
                await emit_status(
                    job_id,
                    f"⚡ 极速规划直达：识别到复合诉求，已智能组装 {len(fast_subtasks)} 项子任务流并投入执行引擎！",
                    node="planner",
                    plan=fast_plan,
                )
            return {"task_plan": fast_plan, "short_memory": short_memory, "global_transitions_count": 1}

        is_explicit_order_id = bool(_EXPLICIT_ORDER_ID_RE.search(input_text))
        is_general_order_list_query = (
            single_intent in ("order_status", "order_query")
            and bool(_GENERAL_ORDER_LIST_RE.search(input_text))
            and not is_explicit_order_id
        )

        if is_general_order_list_query and len(intents) == 1:
            fast_plan = {
                "goal": "List recent orders for customer",
                "subtasks": [
                    {"id": "step_fast_list_orders", "description": "Call listUserOrders to fetch recent orders", "status": "pending"}
                ],
                "currentStepIndex": 0,
            }
            if job_id:
                await emit_status(
                    job_id,
                    "⚡ 极速规划直达：检测到客户订单列表查询诉求，秒级调度 listUserOrders 工具进行物理查单！",
                    node="planner",
                    plan=fast_plan,
                )
            return {"task_plan": fast_plan, "short_memory": short_memory, "global_transitions_count": 1}

        entity_order_id = next(
            (i.get("entities", {}).get("orderId") for i in intents if i.get("entities", {}).get("orderId")), None
        )
        extracted_order_id = entity_order_id or extract_order_id(input_text, None, short_memory)

        if extracted_order_id:
            action_intents = [
                i
                for i in intents
                if i.get("intent")
                in ("order_status", "refund", "order_modify_address", "order_query", "order_return")
            ]

            if action_intents:
                fast_subtasks = []
                for idx, item in enumerate(action_intents):
                    suffix = f"_{idx}" if len(action_intents) > 1 else ""
                    intent = item["intent"]
                    condition = item.get("condition")
                    if intent in ("order_status", "order_query"):
                        fast_subtasks.append(
                            {
                                "id": f"step_fast_status{suffix}",
                                "description": f"Call getOrderStatus for order {extracted_order_id}",
                                "status": "pending",
                                **({"condition": condition} if condition else {}),
                            }
                        )
                    elif intent in ("refund", "order_return"):
                        fast_subtasks.append(
                            {
                                "id": f"step_fast_refund{suffix}",
                                "description": f"Call processRefund for order {extracted_order_id}",
                                "status": "pending",
                                **({"condition": condition} if condition else {}),
                            }
                        )
                    elif intent == "order_modify_address":
                        task_spec = item.get("taskSpec") or {}
                        target_address = (task_spec.get("slots") or {}).get("newAddress") or "客户指定新地址"
                        fast_subtasks.append(
                            {
                                "id": f"step_fast_change_address{suffix}",
                                "description": f"Call changeShippingAddress for order {extracted_order_id} with new address {target_address}",
                                "status": "pending",
                                **({"condition": condition} if condition else {}),
                            }
                        )

                has_conditional_step = any(st.get("condition") for st in fast_subtasks)
                has_status_query = any("step_fast_status" in st["id"] for st in fast_subtasks)
                if has_conditional_step and not has_status_query:
                    fast_subtasks.insert(
                        0,
                        {
                            "id": "step_fast_status_pre",
                            "description": f"Call getOrderStatus for order {extracted_order_id}",
                            "status": "pending",
                        },
                    )

                if fast_subtasks:
                    first_intent = action_intents[0]["intent"]
                    if first_intent in ("order_status", "order_query"):
                        goal_action = "Query status"
                    elif first_intent in ("refund", "order_return"):
                        goal_action = "Process refund"
                    elif first_intent == "order_modify_address":
                        goal_action = "Change shipping address"
                    else:
                        goal_action = first_intent

                    fast_plan = {
                        "goal": (
                            f"{goal_action} for order {extracted_order_id}"
                            if len(fast_subtasks) == 1
                            else f"Execute multiple subtasks for order {extracted_order_id}"
                        ),
                        "subtasks": fast_subtasks,
                        "currentStepIndex": 0,
                    }
                    if job_id:
                        await emit_status(
                            job_id,
                            f"⚡ 极速规划直达：关联订单号 [{extracted_order_id}]，快速生成 "
                            f"{len(fast_subtasks)} 项多意图执行步骤，绕过大模型规划消耗！",
                            node="planner",
                            plan=fast_plan,
                        )
                    return {
                        "task_plan": fast_plan,
                        "short_memory": short_memory,
                        "global_transitions_count": 1,
                    }

    # 🧠 LLM 深度规划
    prompt = (
        f'System Instruction Context: "{system_prompt}"{tenant_context}\n'
        f"Based on the intents: {json.dumps(intents, ensure_ascii=False, default=str)} and input: "
        f'"{input_text}", generate a sequence of structured steps (a plan) to satisfy the request.'
        f"{rejection_context}{rag_context}{history_context}\n\n"
        "[CRITICAL MULTI-TURN MEMORY & RETRIEVAL DIRECTIVES]:\n"
        "1. Carefully inspect the [CONVERSATION HISTORY (PAST TURNS)] above. If the customer has already "
        'mentioned a specific Order ID (e.g., "ORD-98712") in previous turns, or if an Order ID was '
        "successfully checked earlier, you MUST assume the customer's current request (for refund, status "
        "query, or returns) is regarding that EXACT Order ID!\n"
        '2. If the customer asks "我还有其他订单吗" (Do I have other orders?), "查询我名下的订单" (Query '
        'orders under my name), "我可以退货的订单有哪些" (Which orders can I return?), or wants to list '
        'their order history / eligible return orders, you MUST plan a step to call the "listUserOrders" '
        "tool to fetch their recent order list.\n"
        '3. If an Order ID (like "ORD-98712") is present in the history, bypass any placeholder check '
        "steps, and directly plan a concrete step to execute the requested action. For example: \"Call the "
        "processRefund tool with orderId 'ORD-98712' to initiate the return/refund in our systems.\"\n"
        '4. If NO Order ID exists anywhere in the conversation history, and they are asking for an order '
        'operation (refund, tracking), you should plan a step to call "listUserOrders" first to dynamically '
        "find their recent orders, or ask the customer to provide their Order ID if listUserOrders is "
        "unavailable or returns nothing.\n"
        '5. DO NOT plan a step to call "processRefund" when the customer is merely asking which orders are '
        'eligible for return! Only plan "processRefund" when the customer specifies a concrete order to be '
        "refunded.\n\n"
        "Return a JSON object with:\n"
        '- "goal": overall goal description\n'
        '- "subtasks": array of objects with keys "id" (unique string), "description" (what to do, e.g., '
        "call tool getOrderStatus, or ask user for confirmation).\n"
        "Return ONLY the raw JSON object. Do not include markdown or backticks."
    )

    try:
        response = await get_chat_model().ainvoke(prompt)
        content = response.content if hasattr(response, "content") else str(response)
        try:
            clean_response = content.strip()
            clean_response = re.sub(r"^```json\s*", "", clean_response)
            clean_response = re.sub(r"```$", "", clean_response).strip()
            plan = json.loads(clean_response)
        except Exception:  # noqa: BLE001 — JSON 解析失败回退逐意图步骤
            plan = {
                "goal": "Address customer request",
                "subtasks": [
                    {"id": f"step_{idx}", "description": f"Handle {it.get('intent')} process", "status": "pending"}
                    for idx, it in enumerate(intents)
                ],
            }

        task_plan = {
            "goal": plan.get("goal") or "Handle customer request",
            "subtasks": [
                {"id": sub.get("id"), "description": sub.get("description"), "status": "pending"}
                for sub in (plan.get("subtasks") or [])
            ],
            "currentStepIndex": 0,
        }

        if job_id:
            await emit_status(
                job_id,
                f"子步骤物理规划成功！目标：{task_plan['goal']}，拆解为 {len(task_plan['subtasks'])} 个子任务。",
                node="planner",
                plan=task_plan,
            )
        return {"task_plan": task_plan, "short_memory": short_memory, "global_transitions_count": 1}
    except Exception as err:  # noqa: BLE001 — LLM 失败回退单步计划
        print(f"plannerNode failed, falling back to default single-step plan: {err}")
        return {
            "task_plan": {
                "goal": "Answer customer queries",
                "subtasks": [
                    {"id": "step_fallback", "description": "Address request in fallback mode", "status": "pending"}
                ],
                "currentStepIndex": 0,
            },
            "global_transitions_count": 1,
        }
