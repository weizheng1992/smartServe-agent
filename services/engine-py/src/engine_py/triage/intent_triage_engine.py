"""多层级意图分流引擎 — 镜像 triage/intentTriageEngine.ts(913 LOC)。

分流层级:多模态感知(vision,2026-09-08 wayfinder multimodal 003 移植)→ 规则前置
→ 语义重复拦截 → Embedding 向量评估 → 大模型结构化联合精判。所有旁路统一经
handle_immediate_bypass 收口。
"""

from __future__ import annotations

import asyncio
import re
from typing import Any

from ..badcase.intent_signals import record_intent_conflict_if_any
from ..db import IntentLog, LowConfidenceLog, get_session
from ..event_bus import emit_job_result, emit_status
from ..llm import CircuitBreakerOpenError
from ..memory import ShortMemory, TaskMemory
from ..skills import is_action_query
from ..tenant import get_merchant_display_name, sanitize_tenant_response, tenant_of_state
from ..vision import analyze_images
from . import rule_matchers
from .consult_fast_path import is_consult_query, run_consult_direct_answer
from .exemplar_service import format_exemplars_for_prompt, search_relevant_exemplars
from .product_disambiguator import AFTER_SALE_INTENTS, build_select_card, disambiguate_product
from .semantic_cache import SemanticVectorCache, cosine_similarity, strip_punctuation_for_greeting
from .slot_extractor import ORDER_ID_RE, AgentIntentType, SlotExtractor
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


def _set_target_order_id(state: dict, order_id: str) -> None:
    """已确认单号注入 state.order_context(文本/已确认上下文/图内 OCR/消歧
    matched 同型,2026-09-09 收口 —— 此前全文件 8 处逐字重复的合并形状)。"""
    state["order_context"] = {**(state.get("order_context") or {}), "targetOrderId": str(order_id)}


async def _emit_vision_order_linked(job_id: str | None, order_id: str, product_name: str) -> None:
    """消歧 matched 的订单关联播报(三个意图浮现点共用同一文案)。"""
    if job_id:
        await emit_status(
            job_id,
            f"📷 已根据照片自动关联订单 {order_id} 的 {product_name}"
            "(如识别有误,请直接告知正确订单号)",
            node="triage",
        )


def _proposal(layer: str, intent: Any, confidence: Any = None) -> dict:
    """仲裁留痕:单层判定提议快照(intent-arbitration 01,2026-09-10)。

    candidates 列表的元素形状:``{"layer", "intent", "confidence"}``。规则闸门
    (consult_gate/rule_prefilter)无数值置信度,confidence 记 None;
    消费方(坏例池冲突信号源、冲突触发仲裁)以 layer+intent 对判定冲突。
    """
    return {
        "layer": layer,
        "intent": str(intent) if intent is not None else None,
        "confidence": round(float(confidence), 3) if confidence is not None else None,
    }


class IntentTriageEngine:
    @staticmethod
    async def log_intent_to_db(
        thread_id: str,
        input_text: str,
        intents: list[dict],
        method: str,
        confidence: float,
        candidates: list[dict] | None = None,
        arbitration_reason: str | None = None,
    ) -> None:
        """终局决策单点落库(intent-arbitration 01):candidates 承载各判定层
        提议快照,winner 取首个 primary 意图,arbitration_reason 记裁决理由
        (旁路路径默认 route_key)。对同一输入只允许一次本调用 —— 槽位层与
        skill_fast_track 曾双写两行且无仲裁记录,现 fast-track 命中时以
        bypass 内的本次写为准,槽位层不再预写。"""
        try:
            async with get_session() as session:
                session.add(
                    IntentLog(
                        thread_id=thread_id,
                        input_text=input_text,
                        predicted_intents=intents,
                        method=method,
                        confidence=confidence,
                        candidates=candidates,
                        winner=(intents[0].get("intent") if intents else None),
                        arbitration_reason=arbitration_reason,
                    )
                )
                await session.commit()
            if confidence < 0.65:
                await IntentTriageEngine.log_low_confidence_to_db(thread_id, input_text, intents)
            # 📥 分类器冲突信号入坏例池(02):候选跨意图族(动作形 × 咨询形)
            # → 候选行;入池静默降级,失败不影响意图日志已落的事实
            if candidates and len(candidates) >= 2:
                await record_intent_conflict_if_any(thread_id, candidates)
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
        candidates: list[dict] | None = None,
        arbitration_reason: str | None = None,
    ) -> dict:
        tenant_id = tenant_of_state(state)
        sanitized_reply = sanitize_tenant_response(reply_text, tenant_id)
        effective_cards = cards if cards is not None else (state.get("cards") or [])

        await IntentTriageEngine.log_intent_to_db(
            state.get("thread_id", ""),
            state.get("input", ""),
            intents if intents else [{"intent": "general_query", "confidence": confidence}],
            method,
            confidence,
            candidates=candidates,
            # 旁路的裁决理由默认即路由键(哪条快道关闭了会话)
            arbitration_reason=arbitration_reason or route_key,
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
    def _vision_disambig_due(
        state: dict,
        vision_analysis: dict | None,
        *,
        after_sale: bool,
        order_id_resolved: str | None,
    ) -> bool:
        """视觉消歧闸门谓词(三浮现点共用收口,工单04 2026-09-10)。

        带图 × 售后意图已浮现 × 全链无单号(文本通道 / 图内 OCR / 已确认
        targetOrderId 三通道皆无)→ 须过商品归属消歧。此前三站各写一套
        `and not ...` 链,漏一条即静默漏闸;单号通道判定在此唯一实现。
        售后意图如何浮现(intentType / 关键词分支 / 结构化 entities)是各站
        差异所在,由调用方算好经 after_sale 传入;order_id_resolved 传该站
        已解析到的文本通道单号(与 OCR/上下文通道在此融合判定)。
        """
        vision_order_id = str((vision_analysis or {}).get("extractedOrderId") or "").strip()
        return bool(
            after_sale
            and state.get("image_urls")
            and vision_analysis
            and not (order_id_resolved or "").strip()
            and not vision_order_id
            and not (state.get("order_context") or {}).get("targetOrderId")
        )

    @staticmethod
    async def _run_vision_disambig(state: dict, vision_analysis: dict, tenant_id: str) -> dict:
        """带图售后缺单号时的商品归属消歧核心(Step 1.6 / Step 2 判定 3 / Step 3
        三个意图浮现点共用,2026-09-09 收口):matched 时注入 targetOrderId 并播报
        订单关联;其余状态原样返回,由调用方经 _vision_disambig_bypass 收口。
        闸门条件(带图 × 售后意图 × 全链无单号)经 _vision_disambig_due 唯一实现。"""
        disambig = await disambiguate_product(vision_analysis, state.get("user_id"), tenant_id)
        if disambig["status"] == "matched":
            _set_target_order_id(state, disambig["orderId"])
            await _emit_vision_order_linked(
                state.get("job_id"), disambig["orderId"], disambig["productName"]
            )
        return disambig

    @staticmethod
    async def _vision_disambig_bypass(
        state: dict,
        intent_type: str,
        confidence: float,
        damage_assessment: dict | None,
        disambig: dict,
        candidates: list[dict] | None = None,
    ) -> dict:
        """消歧无候选/多候选两态的 bypass 收口(Step 1.6 与意图浮现点共用,2026-09-09)。"""
        if not disambig["candidates"]:
            return await IntentTriageEngine.handle_immediate_bypass(
                state,
                "image_product_no_orders",
                "未能找到您可用的订单信息。请提供订单编号,或输入「转人工」联系人工客服为您处理。",
                [{"intent": intent_type, "confidence": confidence}],
                "vision_disambig",
                0.9,
                damage_assessment,
                candidates=candidates,
            )
        return await IntentTriageEngine.handle_immediate_bypass(
            state,
            "image_product_select",
            "收到您的照片 📷 为准确定位商品,请选择破损的是哪件商品:",
            [{"intent": intent_type, "confidence": confidence}],
            "vision_disambig",
            0.9,
            damage_assessment,
            [build_select_card(disambig["candidates"])],
            candidates=candidates,
        )

    @staticmethod
    async def process(state: dict) -> dict:
        thread_id = state.get("thread_id", "")
        input_text = (state.get("input") or "").strip()

        # 仲裁留痕(intent-arbitration 01,2026-09-10):逐层累积判定提议,终局
        # 决策单点落库时作为 candidates 快照 —— 正则/槽位/锚点层降为「提议者」,
        # 谁关闭了会话、谁压过了谁,自此可查(坏例池冲突信号源共同消费)。
        proposals: list[dict] = []

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

        # 📷 Step 0.5: 多模态视觉解析(wayfinder multimodal 003,移植 visionAnalyzerService)
        damage_assessment = state.get("damage_assessment")
        vision_analysis: dict | None = None  # Step 1.6 商品归属消歧消费(摘要/物体)
        if state.get("image_urls"):
            if state.get("job_id"):
                await emit_status(
                    state["job_id"],
                    "📷 多模态感知：正在进行图像 OCR、快递面单解析与商品破损瑕疵评级...",
                    node="triage",
                )
            try:
                vision_analysis = await analyze_images(state["image_urls"], input_text)
                damage_assessment = vision_analysis.get("damageAssessment") or damage_assessment
            except Exception as vision_err:
                print(f"[Triage Multimodal Vision Exception]: {vision_err}")

        # 图内 OCR 单号(2026-09-09):消费语义与文本单号一致 —— 进实体/订单上下文,
        # 查无此单由技能归属校验诚实报错;此前算完即丢,图内明示单号对流程零贡献
        vision_order_id = str((vision_analysis or {}).get("extractedOrderId") or "").strip().upper() or None

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
        tenant_id = tenant_of_state(state)
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

        # 🛣️ Step 1.4: 咨询类直答快轨(2026-09-09)—— 政策/尺码/物流时效等
        # 「问知识」型输入在此闭环。此前咨询无独立意图档位,按措辞随机误落三处
        # (Step 1.5 退货字样误判动作形反问订单号 / Step 2 判定 3 关键词误判
        # refund 动作进 planner 深度规划 / general_query 两跳),咨询回复
        # 57-114s 的大头即源于此。此处复用 run_agent 预取的 RAG 切片单次调用
        # 直答;RAG 空弱/直答失败回落 general_query 零规划旁路(finish 终稿
        # 诚实作答),严防下游把咨询误判成动作形。带图闸在 is_consult_query
        # 本体:咨询形措辞 × 带图(「这鞋坏了怎么退货」+ 破损图)不入快轨,
        # 走 Step 1.5 起的 OCR 单号消费与视觉定责消歧管道(若在快轨内拒答再
        # 回落 general_query,会截胡消歧并令图内单号重新算完即丢)。
        if is_consult_query(input_text, has_image=bool(state.get("image_urls"))):
            consult_hit = await run_consult_direct_answer(state, history_msgs)
            if consult_hit is not None:
                consult_answer, consult_intents, consult_confidence = consult_hit
                return await IntentTriageEngine.handle_immediate_bypass(
                    state,
                    "rag_consult_direct",
                    consult_answer,
                    consult_intents,
                    "rag_direct",
                    consult_confidence,
                    damage_assessment,
                    candidates=[_proposal("consult_gate", "consult")],
                )
            consult_intents = [{"intent": AgentIntentType.GENERAL_QUERY, "confidence": 0.9, "type": "primary"}]
            await IntentTriageEngine.log_intent_to_db(
                thread_id,
                input_text,
                consult_intents,
                "consult_no_rag",
                0.9,
                candidates=[_proposal("consult_gate", "consult")],
                arbitration_reason="consult_no_rag",
            )
            return {
                "intents": consult_intents,
                "active_domain_role": "chitchat",
                "short_memory": history_msgs,
                "damage_assessment": damage_assessment,
                "global_transitions_count": -1,
                "tool_errors_count": -1,
            }

        # 🛡️ Step 1.5: 意图与槽位完整性拦截
        try:
            task_memory = TaskMemory(thread_id)
            existing_task_state = await task_memory.get_task_state() or {}
            active_intent = existing_task_state.get("activeIntent")
            existing_slots = existing_task_state.get("slots") or {}
            existing_order_context = existing_task_state.get("orderContext") or state.get("order_context")

            # 已确认订单上下文同步进 state(2026-09-09):Step 2 各判定的单号
            # 融合与返回透传都以 state.order_context 为准,不同步则已确认单号
            # 在此轮丢失(甚至被图内 OCR 单号压过)
            if (existing_order_context or {}).get("targetOrderId") and not (
                (state.get("order_context") or {}).get("targetOrderId")
            ):
                _set_target_order_id(state, existing_order_context["targetOrderId"])

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
                    _set_target_order_id(state, primary_order_id)

                await IntentTriageEngine.log_intent_to_db(
                    thread_id,
                    input_text,
                    multi_intents,
                    "slot_extractor_multi",
                    0.95,
                    candidates=[
                        _proposal("slot_extractor", s["intentType"], s["confidence"]) for s in all_specs
                    ],
                    arbitration_reason="slot_extractor_multi",
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
                _set_target_order_id(state, task_spec["slots"]["orderId"])

            # 图内 OCR 单号注入(2026-09-09 事故:ORD-77777 算完即丢)——文本单号
            # 与已确认订单上下文优先,OCR 不得覆盖;注入后重跑槽位抽取,退款严格
            # 抽取器经 orderContext.targetOrderId 取到(与消歧 matched 注入同型)
            if (
                vision_order_id
                and not task_spec["slots"].get("orderId")
                and not (existing_order_context or {}).get("targetOrderId")
            ):
                _set_target_order_id(state, vision_order_id)
                context["orderContext"] = state["order_context"]
                task_spec = SlotExtractor.extract(input_text, active_intent, existing_slots, context)

            # 槽位层提议入留痕(实体注入/消歧重抽取后取最终形态;后续各决策点
            # 的 candidates 以此为前缀,呈现「槽位判 X vs 锚点判 Y」的竞争原貌)
            proposals.append(_proposal("slot_extractor", task_spec["intentType"], task_spec["confidence"]))

            # 📷 Step 1.6: 破损图商品归属消歧(grilling 2026-09-09)——售后意图
            # 带图但缺 orderId(图内也无单号,OCR 通道失效)时,用 vision 摘要 ×
            # 近单商品行做 LLM 消歧,替代机械"请提供订单号"澄清:
            #   唯一高置信命中 → 注入 targetOrderId 并重跑槽位抽取(退款严格
            #     抽取器只认输入正则与该键,slot_extractor.py:72-82);
            #   多候选/低置信/模型失败 → 商品选择 quick_replies 卡片问用户;
            #   无候选订单 → 明示指引。消歧失败绝不炸会话,最坏多问一次。
            if IntentTriageEngine._vision_disambig_due(
                state,
                vision_analysis,
                after_sale=task_spec["intentType"] in AFTER_SALE_INTENTS,
                order_id_resolved=task_spec["slots"].get("orderId"),
            ):
                disambig = await IntentTriageEngine._run_vision_disambig(state, vision_analysis, tenant_id)
                if disambig["status"] == "matched":
                    context["orderContext"] = state["order_context"]
                    # 重跑槽位抽取:targetOrderId 已就位,本轮 slots 直接带上
                    # orderId,免二次"请提供订单号"澄清;仍取不到则走下方正常澄清兜底
                    task_spec = SlotExtractor.extract(input_text, active_intent, existing_slots, context)
                    proposals[-1] = _proposal(
                        "slot_extractor", task_spec["intentType"], task_spec["confidence"]
                    )
                else:
                    # 无候选/多候选两态收口(无候选明示指引,多候选出商品选择卡)
                    return await IntentTriageEngine._vision_disambig_bypass(
                        state,
                        task_spec["intentType"],
                        task_spec["confidence"],
                        damage_assessment,
                        disambig,
                        candidates=list(proposals),
                    )

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
                    candidates=list(proposals),
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

                # 🎯 Skill Fast-Track 直达极速执行(skills 包落地后自动激活)。
                # 终局决策单点落库(01):fast-track 命中时以 bypass 内的写为准
                # (method=skill_fast_track,candidates 含槽位+技能两提议);
                # 未命中才在下方落 slot_extractor 行 —— 修复同一输入双写。
                fast_track = await IntentTriageEngine._try_skill_fast_track(
                    state,
                    thread_id,
                    tenant_id,
                    task_spec,
                    history_msgs,
                    damage_assessment,
                    intents,
                    proposals,
                )
                if fast_track is not None:
                    return fast_track

                await IntentTriageEngine.log_intent_to_db(
                    thread_id,
                    input_text,
                    intents,
                    "slot_extractor",
                    task_spec["confidence"],
                    candidates=list(proposals),
                    arbitration_reason="slot_extractor_single_complete",
                )

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
            cache_tenant = tenant_of_state(state)
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
                        candidates=[
                            *proposals,
                            _proposal("semantic_cache", "general_query", cache_hit["similarity"]),
                        ],
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
            fused_order_id = matched_order_id or confirmed_order_id or vision_order_id
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
                        **({"entities": {"orderId": fused_order_id}} if fused_order_id else {}),
                    },
                    {
                        "intent": "refund",
                        "confidence": score_refund,
                        "type": "secondary",
                        **({"entities": {"orderId": fused_order_id}} if fused_order_id else {}),
                    },
                ]
                await IntentTriageEngine.log_intent_to_db(
                    thread_id,
                    input_text,
                    intents,
                    "embedding",
                    intents[0]["confidence"],
                    candidates=[
                        *proposals,
                        _proposal("embedding", "order_status", score_order),
                        _proposal("embedding", "refund", score_refund),
                    ],
                    arbitration_reason="embedding_composite",
                )
                return {
                    "intents": intents,
                    "active_domain_role": resolve_domain_role(intents, input_text),
                    "short_memory": history_msgs,
                    "damage_assessment": damage_assessment,
                    "order_context": state.get("order_context"),
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
                        **({"entities": {"orderId": fused_order_id}} if fused_order_id else {}),
                    }
                ]
                await IntentTriageEngine.log_intent_to_db(
                    thread_id,
                    input_text,
                    intents,
                    "embedding",
                    intents[0]["confidence"],
                    candidates=[*proposals, _proposal("embedding", "order_status", score_order)],
                    arbitration_reason="embedding_order_status",
                )
                return {
                    "intents": intents,
                    "active_domain_role": resolve_domain_role(intents, input_text),
                    "short_memory": history_msgs,
                    "damage_assessment": damage_assessment,
                    "order_context": state.get("order_context"),
                    "global_transitions_count": -1,
                    "tool_errors_count": -1,
                }

            # 判定 3: 明确退款执行意图直达
            if (score_refund >= 0.88 and score_refund - score_oos >= 0.08) or (
                has_refund_keywords and not has_order_keywords
            ):
                refund_order_id = fused_order_id
                # 📷 意图浮现点消歧(2026-09-09):模糊损坏词(「坏了」)的售后意图
                # 由 damage_assessment 在此浮现,SlotExtractor 阶段还是 chat —— Step 1.6
                # 闸门因此永不触发。此处带图缺单号必须同样过消歧,否则为本场景
                # 造的商品选择卡对典型措辞失效,退回 planner 深规划自由发挥。
                if IntentTriageEngine._vision_disambig_due(
                    state,
                    vision_analysis,
                    after_sale=True,  # 判定3 分支本身即售后关键词成立
                    order_id_resolved=refund_order_id,  # 融合单号(文本/上下文/OCR)非空即有主
                ):
                    disambig = await IntentTriageEngine._run_vision_disambig(state, vision_analysis, tenant_id)
                    if disambig["status"] == "matched":
                        refund_order_id = disambig["orderId"]
                    else:
                        return await IntentTriageEngine._vision_disambig_bypass(
                            state,
                            "refund",
                            max(score_refund, 0.95),
                            damage_assessment,
                            disambig,
                            candidates=[
                                *proposals,
                                _proposal("embedding", "refund", score_refund),
                            ],
                        )
                intents = [
                    {
                        "intent": "refund",
                        "confidence": max(score_refund, 0.95),
                        "type": "primary",
                        **({"entities": {"orderId": refund_order_id}} if refund_order_id else {}),
                    }
                ]
                await IntentTriageEngine.log_intent_to_db(
                    thread_id,
                    input_text,
                    intents,
                    "embedding",
                    intents[0]["confidence"],
                    candidates=[*proposals, _proposal("embedding", "refund", score_refund)],
                    arbitration_reason="embedding_refund",
                )
                return {
                    "intents": intents,
                    "active_domain_role": resolve_domain_role(intents, input_text),
                    "short_memory": history_msgs,
                    "damage_assessment": damage_assessment,
                    "order_context": state.get("order_context"),
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
                    candidates=[
                        *proposals,
                        # 宣称 out_of_scope × 落库 general_query:锚点层的宣称与
                        # 终局落库不符,坏例池「宣称与落库不符」信号源的靶样本
                        _proposal("embedding", "out_of_scope", score_oos),
                    ],
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
            active_tenant_id = tenant_of_state(state)

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
                    candidates=[
                        *proposals,
                        # 宣称 out_of_scope × 落库 general_query:与判定 4 同口径
                        _proposal("structured_llm", "out_of_scope", 0.9),
                    ],
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
                _set_target_order_id(state, primary_order_id)

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
            if IntentTriageEngine._vision_disambig_due(
                state,
                vision_analysis,
                after_sale=has_after_sale and after_sale_missing_order,
                order_id_resolved=None,  # 缺单号已由 after_sale_missing_order 表达(per-intent entities)
            ):
                disambig = await IntentTriageEngine._run_vision_disambig(
                    state, vision_analysis, active_tenant_id
                )
                if disambig["status"] == "matched":
                    vision_disambig_matched = True
                    for p in parsed:
                        if p["intent"] in AFTER_SALE_INTENTS:
                            p["entities"]["orderId"] = disambig["orderId"]
                else:
                    return await IntentTriageEngine._vision_disambig_bypass(
                        state,
                        parsed[0]["intent"] if parsed else "refund",
                        parsed[0]["confidence"] if parsed else 0.9,
                        damage_assessment,
                        disambig,
                        candidates=[*proposals, llm_proposal],
                    )

            first_missing = next(
                (i for i in structured_res.intents if i.missingSlots), None
            )
            if (
                first_missing is not None
                and structured_res.clarificationMessage
                and not vision_disambig_matched
            ):
                return await IntentTriageEngine.handle_immediate_bypass(
                    state,
                    "slot_clarification_structured",
                    structured_res.clarificationMessage,
                    parsed,
                    "structured_llm",
                    parsed[0]["confidence"] if parsed else 0.9,
                    damage_assessment,
                    candidates=[*proposals, llm_proposal],
                )

            # 🛣️ 分类器判 consult(规则层漏网的咨询措辞)× RAG 非空 → 直答快轨;
            # RAG 空弱降级 general_query,免得 planner 对未知咨询意图深度规划失控
            if parsed and parsed[0].get("intent") == AgentIntentType.CONSULT:
                consult_hit = await run_consult_direct_answer(state, history_msgs)
                if consult_hit is not None:
                    consult_answer, _, consult_confidence = consult_hit
                    return await IntentTriageEngine.handle_immediate_bypass(
                        state,
                        "rag_consult_direct_llm",
                        consult_answer,
                        parsed,
                        "rag_direct",
                        consult_confidence,
                        damage_assessment,
                        candidates=[*proposals, llm_proposal],
                    )
                parsed = [{**p, "intent": AgentIntentType.GENERAL_QUERY} for p in parsed]

            confidence = parsed[0]["confidence"] if parsed else 0.85
            await IntentTriageEngine.log_intent_to_db(
                thread_id,
                input_text,
                parsed,
                "structured_llm",
                confidence,
                candidates=[*proposals, llm_proposal],
                arbitration_reason="structured_llm_terminal",
            )

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
        except CircuitBreakerOpenError:
            # 上游 LLM 熔断非节点级可恢复:上抛 run_agent 走 job 级降级(兜底 intent 仅面向分类输出类失败)
            raise
        except Exception as err:
            print(f"IntentTriageEngine Step 3 structured classifier failed: {err}")
            fallback_intents = [{"intent": "general_query", "confidence": 0.5}]
            await IntentTriageEngine.log_intent_to_db(
                thread_id,
                input_text,
                fallback_intents,
                "structured_llm_fallback",
                0.5,
                candidates=list(proposals),
                arbitration_reason="structured_llm_exception_fallback",
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
        proposals: list[dict] | None = None,
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
                candidates=[
                    *(proposals or []),
                    _proposal("skill_fast_track", matching_skill.metadata["id"], task_spec["confidence"]),
                ],
            )
            return {
                **bypass,
                "cards": state.get("cards"),
                "guide_context": state.get("guide_context"),
                "cart_context": state.get("cart_context"),
            }
        return None
