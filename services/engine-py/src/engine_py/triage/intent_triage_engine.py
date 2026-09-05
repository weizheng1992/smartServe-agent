"""多层级意图分流引擎 — 镜像 triage/intentTriageEngine.ts(913 LOC)。

分流层级:多模态感知(TODO)→ 规则前置 → 语义重复拦截 → Embedding 向量评估
→ 大模型结构化联合精判。所有旁路统一经 handle_immediate_bypass 收口。
"""

from __future__ import annotations

import asyncio
import re
from typing import Any

from ..db import IntentLog, LowConfidenceLog, get_session
from ..event_bus import emit_job_result, emit_status
from ..memory import ShortMemory, TaskMemory
from ..skills import is_action_query
from ..tenant import get_merchant_display_name, sanitize_tenant_response
from . import rule_matchers
from .exemplar_service import format_exemplars_for_prompt, search_relevant_exemplars
from .semantic_cache import SemanticVectorCache, cosine_similarity, strip_punctuation_for_greeting
from .slot_extractor import ORDER_ID_RE, SlotExtractor
from .structured_classifier import classify

OPERATIONAL_ACTION_RE = re.compile(
    r"(?:订单|物流|快递|发货|退款|退货|买|购物车|加购|商品|推荐|款|件|排查|查|ord|track|refund|cart|order)",
    re.IGNORECASE,
)
UNSANITIZED_TAGS_RE = re.compile(r"\[(?:ECOMMERCE|BRAND|STORE|MERCHANT|SHOP|ADIDAS|NIKE)\]", re.IGNORECASE)
ORDER_KEYWORDS_RE = re.compile(r"订单|发货|物流|查单|买的|快递|到哪|运单|面单", re.IGNORECASE)
REFUND_KEYWORDS_RE = re.compile(r"退款|退货|退钱|退单|退款申请|退货流程|破损|坏了|碎了|瑕疵", re.IGNORECASE)
MULTI_INTENT_CANDIDATE_RE = re.compile(r"(?:另外|同时|并且|顺便|还有|然后再|接着|以及)")


def resolve_domain_role(intents: list[dict], input_text: str | None = None) -> str:
    primary_intent = ""
    for item in intents:
        if item.get("type") == "primary":
            primary_intent = item.get("intent", "")
            break
    if not primary_intent and intents:
        primary_intent = intents[0].get("intent", "")

    if primary_intent == "cart_manage" or re.search(
        r"(?:加购|购物车|结算|去结算|买它|加入购物车|移出购物车|清空购物车|删除第|改成\s*\d+|修改为\s*\d+)",
        input_text or "",
        re.IGNORECASE,
    ):
        return "cart"
    if primary_intent == "shopping_guide" or re.search(
        r"(?:推荐|买什么|挑一款|选一款|好看|款式|选鞋|选衣服|哪款好)", input_text or "", re.IGNORECASE
    ):
        return "shopping_guide"
    if primary_intent in (
        "order_status",
        "refund",
        "order_modify_address",
        "order_cancel",
        "order_query",
        "order_return",
        "human_escalation",
        "metric_query",
    ):
        return "order_service"
    return "chitchat"


def _tenant_of(state: dict) -> str:
    business_config = state.get("business_config") or {}
    return str(
        business_config.get("businessId") or state.get("business_id") or "ecommerce"
    ).lower()


class IntentTriageEngine:
    @staticmethod
    async def log_intent_to_db(
        thread_id: str, input_text: str, intents: list[dict], method: str, confidence: float
    ) -> None:
        try:
            async with get_session() as session:
                session.add(
                    IntentLog(
                        thread_id=thread_id,
                        input_text=input_text,
                        predicted_intents=intents,
                        method=method,
                        confidence=confidence,
                    )
                )
                await session.commit()
            if confidence < 0.65:
                await IntentTriageEngine.log_low_confidence_to_db(thread_id, input_text, intents)
        except Exception as err:
            print(f"[Triage Logging Exception] Bypassed log persistence: {err}")

    @staticmethod
    async def log_low_confidence_to_db(thread_id: str, input_text: str, candidates: Any) -> None:
        try:
            async with get_session() as session:
                session.add(
                    LowConfidenceLog(
                        thread_id=thread_id,
                        input_text=input_text,
                        candidates=candidates,
                        reviewed=False,
                    )
                )
                await session.commit()
        except Exception as err:
            print(f"[Low Confidence Logging Exception] Bypassed log persistence: {err}")

    @staticmethod
    async def handle_immediate_bypass(
        state: dict,
        route_key: str,
        reply_text: str,
        intents: list[dict],
        method: str,
        confidence: float,
        damage_assessment: dict | None = None,
        cards: list | None = None,
    ) -> dict:
        tenant_id = _tenant_of(state)
        sanitized_reply = sanitize_tenant_response(reply_text, tenant_id)
        effective_cards = cards if cards is not None else (state.get("cards") or [])

        await IntentTriageEngine.log_intent_to_db(
            state.get("thread_id", ""),
            state.get("input", ""),
            intents if intents else [{"intent": "general_query", "confidence": confidence}],
            method,
            confidence,
        )

        bypass_plan = {
            "goal": "Address quick bypass query",
            "subtasks": [
                {
                    "id": "bypass_step",
                    "description": f"Handle immediate bypass shortcut [{route_key}]",
                    "status": "completed",
                    "result": {"message": "Bypassed successfully"},
                }
            ],
            "currentStepIndex": 1,
        }

        job_id = state.get("job_id")
        if job_id:
            if "greeting" in route_key:
                friendly_msg = "极速通道：已秒级识别您所发送的日常打招呼，为您载入高画质欢迎界面..."
            elif "out_of_scope" in route_key:
                friendly_msg = "业务范围提示：识别到该咨询超出了当前电商客服的处理范畴，已为您生成智能指引..."
            else:
                friendly_msg = "快速通道：检测到系统白名单指令，正在为您高速吐出专属答复..."
            await emit_status(job_id, friendly_msg, node="triage", plan=bypass_plan)
            await asyncio.sleep(0.1)
            await emit_job_result(job_id, sanitized_reply, bypass_plan, effective_cards)

        final_intents = intents if intents else [{"intent": "general_query", "confidence": confidence}]
        return {
            "intents": final_intents,
            "active_domain_role": resolve_domain_role(final_intents, state.get("input")),
            "output": sanitized_reply,
            "task_plan": bypass_plan,
            "cards": effective_cards,
            "damage_assessment": damage_assessment,
            "global_transitions_count": -1,
            "tool_errors_count": -1,
        }

    @staticmethod
    async def process(state: dict) -> dict:
        thread_id = state.get("thread_id", "")
        input_text = (state.get("input") or "").strip()

        input_embedding = state.get("input_embedding") or []
        if input_text and input_embedding:
            SemanticVectorCache.inject_input_embedding(input_text, input_embedding)

        short_memory = ShortMemory(thread_id)
        history_msgs = await short_memory.get_messages()

        # 🛡️ 人工恢复/系统提问解挂判定
        if input_text.startswith("System:"):
            task_plan = state.get("task_plan") or {}
            subtasks = task_plan.get("subtasks") or []
            has_refund_task = any(
                "refund" in (st.get("description") or "").lower()
                or (st.get("result") or {}).get("approvalId")
                for st in subtasks
            )
            intent = "refund" if has_refund_task else "order_status"
            intents = [{"intent": intent, "confidence": 1.0}]
            if state.get("job_id"):
                await emit_status(
                    state["job_id"],
                    "🔄 恢复执行流：检测到主管人工决议，正在快速解挂并拉起后续处理步骤...",
                    node="triage",
                )
            return {
                "intents": intents,
                "active_domain_role": resolve_domain_role(intents, input_text),
                "short_memory": history_msgs,
                "damage_assessment": state.get("damage_assessment"),
                "global_transitions_count": -1,
                "tool_errors_count": -1,
            }

        if state.get("job_id"):
            await emit_status(
                state["job_id"],
                "正在进行多渠道意图分层检验（层级：多模态感知 -> 规则前置 -> 语义重复拦截 -> "
                "Embedding向量评估 -> 大模型多意图精判）...",
                node="triage",
            )

        # 📷 Step 0.5: 多模态视觉解析
        # TODO(Phase 1b): 移植 vision/visionAnalyzerService.ts(OCR 面单/破损定责,
        # 1500ms Promise.race 容灾)。当前带图输入仅记录告警,不阻断分流。
        damage_assessment = state.get("damage_assessment")
        if state.get("image_urls"):
            print("[Triage Multimodal Vision] TODO(Phase 1b): visionAnalyzerService 尚未移植,跳过图像解析")

        # 🛡️ Step 0: 输入格式预过滤
        if not input_text and not state.get("image_urls"):
            reply = "您好！看起来您发送了一条空消息。请问有什么我可以帮您的？"
            return await IntentTriageEngine.handle_immediate_bypass(state, "rule_empty", reply, [], "rule", 1.0)

        if rule_matchers.is_symbol_only(input_text):
            reply = "您好！如果您有关于订单、物流或退款方面的疑问，可以直接向我提问，我将为您竭诚服务。"
            return await IntentTriageEngine.handle_immediate_bypass(state, "rule_symbols", reply, [], "rule", 1.0)

        if len(input_text) > 1000:
            reply = "您好！您发送的内容过长，系统暂时无法解析。请问您有具体的订单或退款问题需要我协助吗？"
            return await IntentTriageEngine.handle_immediate_bypass(
                state, "rule_length_limit", reply, [], "rule", 1.0
            )

        if rule_matchers.is_human_escalation_requested(input_text):
            intents = [{"intent": "human_escalation", "confidence": 1.0}]
            return {
                "intents": intents,
                "active_domain_role": resolve_domain_role(intents, input_text),
                "short_memory": history_msgs,
                "damage_assessment": damage_assessment,
                "global_transitions_count": -1,
                "tool_errors_count": -1,
            }

        # 🛡️ 重复提问拦截器
        try:
            user_msgs = [m for m in history_msgs if m.get("role") == "user"]
            assistant_msgs = [m for m in history_msgs if m.get("role") == "assistant"]
            is_operational_action = bool(OPERATIONAL_ACTION_RE.search(input_text))

            if not is_operational_action and len(user_msgs) >= 2 and assistant_msgs:
                last_user_msg = user_msgs[-2]
                last_assistant_msg = assistant_msgs[-1]

                is_exactly_same = input_text.strip() == last_user_msg["content"].strip()

                is_semantically_same = False
                if (
                    not is_exactly_same
                    and len(input_text.strip()) > 3
                    and len(last_user_msg["content"].strip()) > 3
                ):
                    current_vec, last_vec = await asyncio.gather(
                        SemanticVectorCache.get_embedding_with_cache(input_text),
                        SemanticVectorCache.get_embedding_with_cache(last_user_msg["content"]),
                    )
                    sim = cosine_similarity(current_vec, last_vec)
                    if sim >= 0.98:
                        is_semantically_same = True

                is_last_response_failed = rule_matchers.is_failed_response(last_assistant_msg["content"])
                has_unsanitized_tags = bool(UNSANITIZED_TAGS_RE.search(last_assistant_msg["content"]))

                if (is_exactly_same or is_semantically_same) and not is_last_response_failed and not has_unsanitized_tags:
                    prefix_msg = (
                        "您好！检测到您发送了与刚才相同的咨询。这是刚才为您查询的最新进度：\n\n"
                        if is_exactly_same
                        else "您好！检测到您提问了相似的问题。这是刚才为您查询的最新进度：\n\n"
                    )
                    reply = f"{prefix_msg}{last_assistant_msg['content']}"
                    final_intents = [{"intent": "general_query", "confidence": 1.0}]
                    return await IntentTriageEngine.handle_immediate_bypass(
                        state,
                        "duplicate_bypass",
                        reply,
                        final_intents,
                        "rule",
                        1.0,
                        None,
                        last_assistant_msg.get("cards"),
                    )
        except Exception as sh_err:
            print(f"[Triage Duplicate Shield Exception] Bypassed duplicate check: {sh_err}")

        # 🛡️ Step 1: 规则白名单
        clean_input = strip_punctuation_for_greeting(input_text)
        tenant_id = _tenant_of(state)
        brand_name = get_merchant_display_name(tenant_id)

        if rule_matchers.is_greeting(clean_input):
            reply = (
                f"您好！我是 {brand_name} 的智能客服助理。✨\n\n"
                "我能为您提供以下高效率的自动化业务操作：\n"
                '1. **订单物流查询**：例如 *"帮我查一下 ORD-98712 的发货状态"*\n'
                '2. **快捷退款办理**：例如 *"帮我申请退款"*\n'
                '3. **网页看板快照**：例如 *"帮我截取系统首页进行界面圆角核验"*\n\n'
                "请告诉我您需要处理的业务，我将直接为您调起系统底层工具为您搞定！"
            )
            return await IntentTriageEngine.handle_immediate_bypass(
                state, "rule_greeting", reply, [{"intent": "general_query", "confidence": 1.0}], "rule", 1.0
            )

        if rule_matchers.is_exit_command(clean_input):
            reply = (
                "好的，很高兴为您服务！如果您后续还有任何关于订单状态或退款方面的需要，"
                "欢迎随时联系我。祝您生活愉快，再见！👋"
            )
            return await IntentTriageEngine.handle_immediate_bypass(
                state, "rule_exit_conversation", reply, [{"intent": "general_query", "confidence": 1.0}], "rule", 1.0
            )

        # 🛡️ Step 1.5: 意图与槽位完整性拦截
        try:
            task_memory = TaskMemory(thread_id)
            existing_task_state = await task_memory.get_task_state() or {}
            active_intent = existing_task_state.get("activeIntent")
            existing_slots = existing_task_state.get("slots") or {}
            existing_order_context = existing_task_state.get("orderContext") or state.get("order_context")

            context = {
                "orderContext": existing_order_context,
                "shortMemory": state.get("short_memory"),
                "historyMsgs": history_msgs,
            }

            all_specs = SlotExtractor.extract_all(input_text, active_intent, existing_slots, context)

            if len(all_specs) >= 2:
                multi_intents: list[dict] = []
                for idx, spec in enumerate(all_specs):
                    entry: dict[str, Any] = {
                        "intent": spec["intentType"],
                        "confidence": spec["confidence"],
                        "type": "primary" if idx == 0 else "secondary",
                        "taskSpec": spec,
                    }
                    if spec["slots"].get("orderId"):
                        entry["entities"] = {"orderId": str(spec["slots"]["orderId"])}
                    multi_intents.append(entry)

                primary_order_id = next(
                    (s["slots"]["orderId"] for s in all_specs if s["slots"].get("orderId")), None
                )
                if primary_order_id:
                    state["order_context"] = {
                        **(state.get("order_context") or {}),
                        "targetOrderId": str(primary_order_id),
                    }

                await IntentTriageEngine.log_intent_to_db(
                    thread_id, input_text, multi_intents, "slot_extractor_multi", 0.95
                )
                return {
                    "intents": multi_intents,
                    "active_domain_role": resolve_domain_role(multi_intents, input_text),
                    "short_memory": history_msgs,
                    "damage_assessment": damage_assessment,
                    "order_context": state.get("order_context"),
                    "global_transitions_count": -1,
                    "tool_errors_count": -1,
                }

            task_spec = all_specs[0] if all_specs else SlotExtractor.extract(
                input_text, active_intent, existing_slots, context
            )

            if task_spec["slots"].get("orderId"):
                state["order_context"] = {
                    **(state.get("order_context") or {}),
                    "targetOrderId": str(task_spec["slots"]["orderId"]),
                }

            # 高风险/多参数意图缺失必填槽位 → 即时追问,阻断死循环自旋
            if task_spec["missingSlots"] and task_spec["clarificationMessage"]:
                await task_memory.save_task_state(
                    {
                        "goal": f"Fulfill {task_spec['intentType']}",
                        "subtasks": [],
                        "currentStepIndex": 0,
                        "activeIntent": task_spec["intentType"],
                        "slots": task_spec["slots"],
                        "orderContext": state.get("order_context"),
                        "guideContext": state.get("guide_context"),
                        "cartContext": state.get("cart_context"),
                    }
                )
                return await IntentTriageEngine.handle_immediate_bypass(
                    state,
                    "slot_clarification_fastpath",
                    task_spec["clarificationMessage"],
                    [
                        {
                            "intent": task_spec["intentType"],
                            "confidence": task_spec["confidence"],
                            "taskSpec": task_spec,
                        }
                    ],
                    "slot_extractor",
                    task_spec["confidence"],
                    damage_assessment,
                )

            is_multi_intent_candidate = bool(MULTI_INTENT_CANDIDATE_RE.search(input_text)) or (
                ("查" in input_text or "物流" in input_text or "状态" in input_text)
                and ("退" in input_text or "改" in input_text or "换" in input_text)
            )

            # 参数齐备且非复合多意图 → 高置信度放行进入 DAG 调度
            if (
                not is_multi_intent_candidate
                and task_spec["intentType"] != "chat"
                and not task_spec["missingSlots"]
                and task_spec["confidence"] >= 0.8
            ):
                intents = [
                    {
                        "intent": task_spec["intentType"],
                        "confidence": task_spec["confidence"],
                        "taskSpec": task_spec,
                    }
                ]
                await IntentTriageEngine.log_intent_to_db(
                    thread_id, input_text, intents, "slot_extractor", task_spec["confidence"]
                )
                await task_memory.save_task_state(
                    {
                        "goal": f"Completed {task_spec['intentType']}",
                        "subtasks": [],
                        "currentStepIndex": 0,
                        "activeIntent": None,
                        "slots": task_spec["slots"],
                        "orderContext": state.get("order_context"),
                        "guideContext": state.get("guide_context"),
                        "cartContext": state.get("cart_context"),
                    }
                )

                # 🎯 Skill Fast-Track 直达极速执行(skills 包落地后自动激活)
                fast_track = await IntentTriageEngine._try_skill_fast_track(
                    state, thread_id, tenant_id, task_spec, history_msgs, damage_assessment, intents
                )
                if fast_track is not None:
                    return fast_track

                return {
                    "intents": intents,
                    "active_domain_role": resolve_domain_role(intents, input_text),
                    "short_memory": history_msgs,
                    "damage_assessment": damage_assessment,
                    "global_transitions_count": -1,
                    "tool_errors_count": -1,
                }
        except Exception as slot_err:
            print(f"[Triage Slot-Clarification Exception]: {slot_err}")

        # 🛡️ Step 2: Embedding 快速语义分类
        score_order = 0.0
        score_refund = 0.0
        score_oos = 0.0

        try:
            user_vector, anchors = await asyncio.gather(
                SemanticVectorCache.get_embedding_with_cache(input_text),
                SemanticVectorCache.get_anchor_vectors(),
            )

            # 🛡️ 读闸(防缓存投毒,2026-09-04 幻觉加购 bug 加固):动作形输入(任一
            # 技能声明可处理)不得命中回复缓存 —— 即使缓存已被历史投毒,动作也必须
            # 落到下方锚点判定 / Step 3 精判的真实执行管道。
            cache_tenant = _tenant_of(state)
            if is_action_query(input_text, cache_tenant):
                print(f"[Triage Semantic Cache] Action-shaped input skips reply cache: {input_text[:50]}")
            else:
                cache_hit = SemanticVectorCache.find_best_semantic_match(cache_tenant, user_vector, 0.96)
                if cache_hit:
                    return await IntentTriageEngine.handle_immediate_bypass(
                        state,
                        "super_semantic_cache",
                        cache_hit["match"]["reply"],
                        [{"intent": "general_query", "confidence": cache_hit["similarity"]}],
                        "semantic_cache",
                        cache_hit["similarity"],
                    )

            for v in anchors["order_status"]:
                score_order = max(score_order, cosine_similarity(user_vector, v))
            for v in anchors["refund"]:
                score_refund = max(score_refund, cosine_similarity(user_vector, v))
            for v in anchors["out_of_scope"]:
                score_oos = max(score_oos, cosine_similarity(user_vector, v))

            matched_order_id_match = ORDER_ID_RE.search(input_text)
            matched_order_id = matched_order_id_match.group(0) if matched_order_id_match else None
            has_order_keywords = bool(ORDER_KEYWORDS_RE.search(input_text))
            has_refund_keywords = bool(REFUND_KEYWORDS_RE.search(input_text)) or bool(damage_assessment)

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
                        **({"entities": {"orderId": matched_order_id}} if matched_order_id else {}),
                    },
                    {
                        "intent": "refund",
                        "confidence": score_refund,
                        "type": "secondary",
                        **({"entities": {"orderId": matched_order_id}} if matched_order_id else {}),
                    },
                ]
                await IntentTriageEngine.log_intent_to_db(
                    thread_id, input_text, intents, "embedding", intents[0]["confidence"]
                )
                return {
                    "intents": intents,
                    "active_domain_role": resolve_domain_role(intents, input_text),
                    "short_memory": history_msgs,
                    "damage_assessment": damage_assessment,
                    "global_transitions_count": -1,
                    "tool_errors_count": -1,
                }

            # 判定 2: 物流/订单状态查询直达
            if (score_order >= 0.88 and score_order - score_oos >= 0.08) or (
                has_order_keywords and not has_refund_keywords
            ):
                intents = [
                    {
                        "intent": "order_status",
                        "confidence": max(score_order, 0.95),
                        "type": "primary",
                        **({"entities": {"orderId": matched_order_id}} if matched_order_id else {}),
                    }
                ]
                await IntentTriageEngine.log_intent_to_db(
                    thread_id, input_text, intents, "embedding", intents[0]["confidence"]
                )
                return {
                    "intents": intents,
                    "active_domain_role": resolve_domain_role(intents, input_text),
                    "short_memory": history_msgs,
                    "damage_assessment": damage_assessment,
                    "global_transitions_count": -1,
                    "tool_errors_count": -1,
                }

            # 判定 3: 明确退款执行意图直达
            if (score_refund >= 0.88 and score_refund - score_oos >= 0.08) or (
                has_refund_keywords and not has_order_keywords
            ):
                intents = [
                    {
                        "intent": "refund",
                        "confidence": max(score_refund, 0.95),
                        "type": "primary",
                        **({"entities": {"orderId": matched_order_id}} if matched_order_id else {}),
                    }
                ]
                await IntentTriageEngine.log_intent_to_db(
                    thread_id, input_text, intents, "embedding", intents[0]["confidence"]
                )
                return {
                    "intents": intents,
                    "active_domain_role": resolve_domain_role(intents, input_text),
                    "short_memory": history_msgs,
                    "damage_assessment": damage_assessment,
                    "global_transitions_count": -1,
                    "tool_errors_count": -1,
                }

            # 判定 4: 超出业务范畴拦截
            if score_oos >= 0.86 and score_oos - max(score_order, score_refund) >= 0.06:
                reply = (
                    "您好！我是您的高级智能电商客服助理，主要负责协助处理订单、物流及退款相关业务。"
                    "您刚才提到的问题超出了我的服务范围（属于日常咨询/外部问题）。"
                    "请问有什么具体的电商订单问题需要我协助吗？"
                )
                return await IntentTriageEngine.handle_immediate_bypass(
                    state,
                    "embedding_out_of_scope",
                    reply,
                    [{"intent": "general_query", "confidence": score_oos}],
                    "embedding",
                    score_oos,
                )
        except Exception as embed_err:
            print(f"[Triage Embedding Step 2 Exception] Bypassing Embedding Classifier: {embed_err}")

        # 🛡️ Step 3: 大模型结构化联合精判
        context_msgs = history_msgs[:-1]
        recent_history = "\n".join(
            f"{'User' if m.get('role') == 'user' else 'Assistant'}: {m.get('content')}"
            for m in context_msgs[-4:]
        )

        try:
            active_tenant_id = _tenant_of(state)

            exemplars_prompt = ""
            try:
                matched_exemplars = await search_relevant_exemplars(
                    active_tenant_id, input_text, state.get("input_embedding") or [], 3
                )
                if matched_exemplars:
                    exemplars_prompt = format_exemplars_for_prompt(matched_exemplars)
            except Exception as ex_err:
                print(f"[Triage Exemplars Retrieval Exception]: {ex_err}")

            structured_res = await classify(
                input_text,
                recent_history_text=recent_history,
                job_id=state.get("job_id"),
                thread_id=state.get("thread_id"),
                exemplars_prompt=exemplars_prompt,
            )

            fallback_match = ORDER_ID_RE.search(input_text)
            fallback_order_id = fallback_match.group(0) if fallback_match else None

            is_oos = structured_res.isOutOfScope or any(
                item.intent == "out_of_scope" for item in structured_res.intents
            )
            if is_oos:
                reply = (
                    "您好！我是您的高级智能电商客服助理，主要负责协助处理导购、购物车、订单物流及退款相关业务。"
                    "您刚才提到的问题超出了我的服务范围（属于外部或高风险意图）。"
                    "请问有什么具体的电商业务需要我协助吗？"
                )
                return await IntentTriageEngine.handle_immediate_bypass(
                    state,
                    "llm_out_of_scope",
                    reply,
                    [{"intent": "general_query", "confidence": 0.9}],
                    "structured_llm",
                    0.9,
                )

            parsed: list[dict] = []
            for idx, item in enumerate(structured_res.intents):
                entities = dict(item.entities or {})
                primary_order_id = entities.get("orderId") or fallback_order_id
                if primary_order_id:
                    entities["orderId"] = primary_order_id
                parsed.append(
                    {
                        "intent": item.intent,
                        "confidence": item.confidence or 0.9,
                        "type": item.type or ("primary" if idx == 0 else "secondary"),
                        "entities": entities,
                        **({"condition": item.condition.model_dump()} if item.condition else {}),
                    }
                )

            primary_order_id = next(
                (p["entities"]["orderId"] for p in parsed if p["entities"].get("orderId")), None
            )
            if primary_order_id:
                state["order_context"] = {
                    **(state.get("order_context") or {}),
                    "targetOrderId": str(primary_order_id),
                }

            first_missing = next(
                (i for i in structured_res.intents if i.missingSlots), None
            )
            if first_missing is not None and structured_res.clarificationMessage:
                return await IntentTriageEngine.handle_immediate_bypass(
                    state,
                    "slot_clarification_structured",
                    structured_res.clarificationMessage,
                    parsed,
                    "structured_llm",
                    parsed[0]["confidence"] if parsed else 0.9,
                    damage_assessment,
                )

            confidence = parsed[0]["confidence"] if parsed else 0.85
            await IntentTriageEngine.log_intent_to_db(thread_id, input_text, parsed, "structured_llm", confidence)

            if state.get("job_id"):
                await emit_status(
                    state["job_id"],
                    "用户意图识别成功！检测到核心意图: "
                    + ", ".join(p["intent"] for p in parsed)
                    + " (置信度: "
                    + ", ".join(f"{p['confidence']:.2f}" for p in parsed)
                    + ")",
                    node="triage",
                )

            return {
                "intents": parsed,
                "active_domain_role": resolve_domain_role(parsed, input_text),
                "short_memory": history_msgs,
                "damage_assessment": damage_assessment,
                "order_context": state.get("order_context"),
                "global_transitions_count": -1,
                "tool_errors_count": -1,
            }
        except Exception as err:
            print(f"IntentTriageEngine Step 3 structured classifier failed: {err}")
            fallback_intents = [{"intent": "general_query", "confidence": 0.5}]
            await IntentTriageEngine.log_intent_to_db(
                thread_id, input_text, fallback_intents, "structured_llm_fallback", 0.5
            )
            return {
                "intents": fallback_intents,
                "active_domain_role": resolve_domain_role(fallback_intents, input_text),
                "short_memory": history_msgs,
                "damage_assessment": damage_assessment,
                "global_transitions_count": -1,
                "tool_errors_count": -1,
            }

    @staticmethod
    async def _try_skill_fast_track(
        state: dict,
        thread_id: str,
        tenant_id: str,
        task_spec: dict,
        history_msgs: list[dict],
        damage_assessment: dict | None,
        intents: list[dict],
    ) -> dict | None:
        """🎯 Skill Fast-Track:命中专属技能则 Triage 阶段直达闭环履约。

        skills 包尚未移植(Phase 1b)时返回 None,走正常 DAG 调度路径,
        行为等价于「无匹配 Skill」的 TS 分支。
        """
        try:
            from ..skills import SkillRegistry
        except ImportError:
            return None

        input_text = state.get("input", "")
        slots = {**task_spec["slots"], "activeIntent": task_spec["intentType"]}
        context = {
            "threadId": thread_id,
            "tenantId": tenant_id,
            "userId": state.get("user_id"),
            "input": input_text,
            "slots": slots,
            "imageUrls": state.get("image_urls"),
            "extra": {
                "damageAssessment": damage_assessment,
                "guideContext": state.get("guide_context"),
                "cartContext": state.get("cart_context"),
                "orderContext": state.get("order_context"),
                "shortMemory": history_msgs,
            },
        }
        matching_skill = SkillRegistry.find_matching_skill(context)
        if matching_skill is None:
            return None

        skill_result = await matching_skill.execute(context)
        if skill_result.get("success") and skill_result.get("nextAction") == "finish":
            if skill_result.get("cards"):
                state["cards"] = (state.get("cards") or []) + skill_result["cards"]
            for ctx_key in ("guideContext", "cartContext", "orderContext"):
                extra_ctx = (skill_result.get("extra") or {}).get(ctx_key)
                if extra_ctx:
                    state_key = {"guideContext": "guide_context", "cartContext": "cart_context", "orderContext": "order_context"}[ctx_key]
                    state[state_key] = {**(state.get(state_key) or {}), **extra_ctx}
            bypass = await IntentTriageEngine.handle_immediate_bypass(
                state,
                f"skill_fast_track_{matching_skill.metadata['id']}",
                skill_result["output"],
                intents,
                "skill_fast_track",
                task_spec["confidence"],
                damage_assessment,
            )
            return {
                **bypass,
                "cards": state.get("cards"),
                "guide_context": state.get("guide_context"),
                "cart_context": state.get("cart_context"),
            }
        return None
