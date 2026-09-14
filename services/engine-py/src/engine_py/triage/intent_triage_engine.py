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
from ..onboarding import build_entry_cards, resolve_onboarding_config
from ..skills import is_action_query
from ..tenant import sanitize_tenant_response, tenant_of_state
from ..vision import analyze_images
from . import rule_matchers
from .consult_fast_path import (
    ROUTE_TO_ACTION_MARKER,
    is_consult_query,
    is_consult_shaped_marker,
    run_consult_direct_answer,
)
from .exemplar_service import format_exemplars_for_prompt, search_relevant_exemplars
from .intent_registry import (
    CONSULT_SIDE_INTENTS,
    EXPLICIT_ORDER_ID_RE,
    INTENT_REGISTRY,
    REFUND_VERB_RE,
)
from .product_disambiguator import AFTER_SALE_INTENTS, build_select_card, disambiguate_product
from .semantic_cache import SemanticVectorCache, cosine_similarity, strip_punctuation_for_greeting
from .slot_extractor import (
    ORDER_ID_RE,
    PHONE_SHAPE,
    AgentIntentType,
    SlotExtractor,
    parse_chinese_address,
)
from .structured_classifier import classify

OPERATIONAL_ACTION_RE = re.compile(
    r"(?:订单|物流|快递|发货|退款|退货|买|购物车|加购|商品|推荐|款|件|排查|查|ord|track|refund|cart|order)",
    re.IGNORECASE,
)
UNSANITIZED_TAGS_RE = re.compile(r"\[(?:ECOMMERCE|BRAND|STORE|MERCHANT|SHOP|ADIDAS|NIKE)\]", re.IGNORECASE)
ORDER_KEYWORDS_RE = re.compile(r"订单|发货|物流|查单|买的|快递|到哪|运单|面单", re.IGNORECASE)
# 退款动词族单一事实源(intent_registry.REFUND_VERB_RE,2026-09-13 收口)+
# 破损词(damage assessment 专用,不入 slot 规则表 —— 「坏了」不是退款动词)
REFUND_KEYWORDS_RE = re.compile(REFUND_VERB_RE.pattern + r"|破损|坏了|碎了|瑕疵", re.IGNORECASE)
MULTI_INTENT_CANDIDATE_RE = re.compile(
    r"(?:另外|同时|并|顺便|还有|然后|接着|以及|随后|其次|再(?=[查看买退加来试问改推结]))"
)
# 多意图不打断一期(2026-09-12):复合候选形的缺槽反问收窄与资金动作否决。
# 「然后」「并」裸词补入 —— 旧正则只有「然后再」「并且」,「退了订单9081，
# 然后推荐跑步鞋」「建地址…，并下单…」都漏判成单意图(A1/A6 实弹病灶)。
# 资金否决 = 退款动词族 + 换货(换货刻意不入族,见 intent_registry 注)
MONEY_ACTION_VETO_RE = re.compile(REFUND_VERB_RE.pattern + r"|换货", re.IGNORECASE)
# 资金动作意图集(让位判定的参照):规则层单意图终局若非本集而输入命中
# 资金词族,即视为「资金半被规则层漏检」,连终局一起让位 Step2/3 精判。
_MONEY_ACTION_INTENTS = frozenset({AgentIntentType.REFUND, AgentIntentType.ORDER_RETURN})
# 技能元数据 category 常量(售后域):资金否决只针对非售后域技能
_AFTER_SALE_SKILL_CATEGORY = "after_sale"


def _money_action_vetoed(input_text: str | None) -> bool:
    """纯谓词(测试缝):资金动作词族命中 —— 命中时导购/购物车等非售后快轨
    必须让位,动作请求绝不静默吞。"""
    return bool(input_text) and bool(MONEY_ACTION_VETO_RE.search(input_text))
# ADR-0003:经营口径排行(利润词 × 排行词共现)规则前置 —— 实弹三连拒的
# 根因是 LLM 分类层把「利润」判成后台经营数据拒答;排行是店长在客服台的
# 合法诉求,确定性直通 metric_query(planner→executor queryProductRanking)。
PROFIT_RANKING_RE = re.compile(
    r"^(?=.*(?:毛利|利润|毛利率|赚钱|挣钱|赚多少))(?=.*(?:排行|排名|top|热销|畅销|最高|前\s*\d)).+",
    re.IGNORECASE | re.DOTALL,
)


def is_profit_ranking_query(text: str | None) -> bool:
    """纯谓词(测试缝):利润词与排行词共现判定。"""
    return bool(text) and bool(PROFIT_RANKING_RE.search(text))


def _is_multi_intent_candidate(input_text: str | None) -> bool:
    """纯谓词(测试缝):复合候选形 —— 连接词命中或 查/物流/状态 × 退/改/换
    共现。复合形不做规则层缺槽反问与单意图快轨,交结构化精判与 planner 编排
    (多意图不打断一期,2026-09-12;自 inline 判定提纯,判定式逐字保持)。"""
    if not input_text:
        return False
    return bool(MULTI_INTENT_CANDIDATE_RE.search(input_text)) or (
        ("查" in input_text or "物流" in input_text or "状态" in input_text)
        and ("退" in input_text or "改" in input_text or "换" in input_text)
    )


def _should_clarify_first(parsed: list[dict]) -> bool:
    """纯谓词(测试缝):结构化层缺槽反问收窄 —— 仅 primary 缺槽且无「非咨询
    族且槽位齐备」的营救意图时才反问。secondary 缺槽不陪葬(A1:建地址+下单
    被改单地址的缺单号反问整轮劫持);营救意图存在时放行 planner 先办能办的
    (尽力而为规则),咨询族(CONSULT_SIDE_INTENTS)与缺槽意图不算营救。"""
    if not parsed:
        return False
    if not parsed[0].get("missingSlots"):
        return False
    for secondary in parsed[1:]:
        if secondary.get("intent") not in CONSULT_SIDE_INTENTS and not secondary.get("missingSlots"):
            return False
    return True


# 地址簿规则前置(多意图一期,2026-09-12):创建形/查询形两检测器 + 中文
# 地址解析(解析器在 slot_extractor)。判定 1.6 与 Step3 注入器共用。
_ADDRESS_CREATE_PAYLOAD_RE = re.compile(
    r"(?:创建|新建|添加|新增|保存|增加|加)[^。,，\n]{0,8}地址[是为:：]?\s*(.*)$", re.DOTALL
)
_ADDRESS_BOOK_LIST_RE = re.compile(
    r"(?:查看|看看|查一下|有哪些|列一下)(?:我的)?(?:收货地址|地址簿|地址列表)"
    r"|我的(?:收货)?地址(?:簿|列表)?(?:有哪些|是什么)?$"
    r"|^(?:地址列表|收货地址列表|地址簿列表)$"
)
_PHONE_RE = re.compile(rf"(?<!\d)({PHONE_SHAPE})(?!\d)")
_CHINESE_NAME_RE = re.compile(r"([\u4e00-\u9fa5]{2,4})\s*$")
_ADDRESS_SAVE_REQUIRED = ("receiverName", "receiverPhone", "province", "city", "district", "detailAddress")


def _address_manage_intent_entry(detected: dict) -> dict:
    """address_manage 终局条目单点构造(判定 1.6 直通与 Step3 注入器共用)。"""
    return {
        "intent": AgentIntentType.ADDRESS_MANAGE,
        "confidence": 0.9,
        "type": "primary",
        "entities": dict(detected["entities"]),
        "missingSlots": list(detected["missingSlots"]),
    }


def detect_address_manage(text: str | None) -> dict | None:
    """纯函数(测试缝):地址簿管理意图检出。

    返回 None=非地址簿诉求;{"mode": "save"|"list", "entities": {...},
    "missingSlots": [...]}。显式 ORD- 单号在场一律让位订单域(改单地址语境,
    即便句中出现「新创建的地址」字样);创建形 payload(收件人/电话/地址)
    缺件以 missingSlots 表达,严禁瞎猜落库。
    """
    if not text:
        return None
    if EXPLICIT_ORDER_ID_RE.search(text):
        return None
    if _ADDRESS_BOOK_LIST_RE.search(text):
        return {"mode": "list", "entities": {"addressAction": "list"}, "missingSlots": []}
    payload_match = _ADDRESS_CREATE_PAYLOAD_RE.search(text)
    if not payload_match:
        return None
    entities: dict = {"addressAction": "save"}
    payload = (payload_match.group(1) or "").strip()
    phone_match = _PHONE_RE.search(payload)
    if phone_match:
        entities["receiverPhone"] = phone_match.group(1)
        before = payload[: phone_match.start()].strip(" ,，:：-—")
        name_match = _CHINESE_NAME_RE.search(before)
        if name_match:
            entities["receiverName"] = name_match.group(1)
        after = payload[phone_match.end():].strip(" ,，:：-—")
        if after:
            entities["fullAddress"] = after
            parsed_addr = parse_chinese_address(after)
            if parsed_addr:
                entities.update(parsed_addr)
    missing = [key for key in _ADDRESS_SAVE_REQUIRED if not entities.get(key)]
    return {"mode": "save", "entities": entities, "missingSlots": missing}


def _inject_address_manage(parsed: list[dict], input_text: str) -> list[dict]:
    """Step3 复合注入(纯函数,测试缝):复合候选形(建地址+下单等)不进
    判定 1.6 直通,由本注入器把 address_manage 提为 primary —— 结构化分类器
    词表没有地址簿档位,只会产出 general_query(丢弃,兜底族不落 planner)
    与真实动作意图(保序降为 secondary)。"""
    detected = detect_address_manage(input_text)
    if detected is None:
        return parsed
    entry = _address_manage_intent_entry(detected)
    rest = [
        {**item, "type": "secondary"}
        for item in parsed
        if item.get("intent") != AgentIntentType.GENERAL_QUERY
    ]
    return [entry, *rest]

# 文本侧域角色线索(工单04 2026-09-11):措辞维度的回退 —— 正则与判定次序
# 逐字节保持旧实现,仅提为模块常量。文本线索优先于意图档位:措辞含加购动词
# 时即使档位是 chat/refund 也回 cart 域(用户嘴上在说购物车)
_CART_TEXT_HINT_RE = re.compile(
    r"(?:加购|购物车|结算|去结算|买它|加入购物车|移出购物车|清空购物车|删除第|改成\s*\d+|修改为\s*\d+)",
    re.IGNORECASE,
)
_SHOPPING_TEXT_HINT_RE = re.compile(
    r"(?:推荐|买什么|挑一款|选一款|好看|款式|选鞋|选衣服|哪款好)", re.IGNORECASE
)


def resolve_domain_role(intents: list[dict], input_text: str | None = None) -> str:
    primary_intent = ""
    for item in intents:
        if item.get("type") == "primary":
            primary_intent = item.get("intent", "")
            break
    if not primary_intent and intents:
        primary_intent = intents[0].get("intent", "")

    text = input_text or ""
    # 文本线索优先(购物车措辞最先判、次导购措辞 —— 与旧实现次序一致)
    if primary_intent == AgentIntentType.CART_MANAGE or _CART_TEXT_HINT_RE.search(text):
        return "cart"
    if primary_intent == AgentIntentType.SHOPPING_GUIDE or _SHOPPING_TEXT_HINT_RE.search(text):
        return "shopping_guide"
    # 意图档位 → 注册表 domain_role(工单04:映射上表,此处只查表;cart/
    # shopping_guide 两档在上面文本分支已返回,注册表值兜底同判)
    spec = INTENT_REGISTRY.get(primary_intent)
    if spec is not None:
        return spec.domain_role
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


def _triage_terminal_result(
    intents: list[dict],
    input_text: str,
    history_msgs: list[dict],
    damage_assessment: dict | None,
    *,
    role: str | None = None,
    state: dict | None = None,
    with_order_context: bool = False,
) -> dict:
    """成功路径(非 bypass)终局返回形状收口(工单03 2026-09-11):此前 9 处
    逐字重复。role 显式覆盖咨询回落路径的 chitchat 字面量;with_order_context
    逐站点保持键存在性 —— 是否透传单号上下文是各判定的语义差异,不在收口内
    拉齐。"""
    result = {
        "intents": intents,
        "active_domain_role": role if role is not None else resolve_domain_role(intents, input_text),
        "short_memory": history_msgs,
        "damage_assessment": damage_assessment,
        "global_transitions_count": -1,
        "tool_errors_count": -1,
    }
    if with_order_context and state is not None:
        result["order_context"] = state.get("order_context")
    return result


def _demote_consult_keep_actions(parsed: list[dict]) -> list[dict]:
    """consult 主导终局的降级(工单06 2026-09-11,本批唯一行为变更)。

    Step3 分类器判 consult 主导后,否决/RAG 空弱两条路径需要降级离场:
    - 咨询侧条目(intent ∈ CONSULT_SIDE_INTENTS)降级 general_query;
    - 动作形条目保留 —— 首个动作形提升为 primary,原 primary 降 secondary
      (intent-arbitration 故事3:带动作意图的请求绝不因一条资讯回复了事;
      故事5:混排拆开各走各路,planner 对多意图自然编排);
    - 纯 consult 输入无动作可保 → 输出与旧整体降级逐字同形(回归安全)。
    """
    result = [{**p} for p in parsed]
    for entry in result:
        if entry.get("intent") in CONSULT_SIDE_INTENTS:
            entry["intent"] = AgentIntentType.GENERAL_QUERY
    first_action = next(
        (i for i, p in enumerate(result) if p["intent"] not in CONSULT_SIDE_INTENTS), None
    )
    if first_action is None:
        return result
    if first_action == 0:
        return result
    promoted = result.pop(first_action)
    promoted["type"] = "primary"
    result[0]["type"] = "secondary"
    return [promoted, *result]


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
            print(f"[Triage] 意图日志落库失败,已跳过不阻断会话 (threadId={thread_id}): {err}")

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
            print(f"[Triage] 低置信日志落库失败,已跳过 (threadId={thread_id}): {err}")

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
        task_plan: dict | None = None,
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

        bypass_plan = task_plan or {
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
        """消歧无候选/都不像/多候选三态的 bypass 收口(Step 1.6 与意图浮现点共用,
        2026-09-09;no_match 出口 2026-09-14 坏例探测补 —— 无关图逼选是体验伤,
        见 product_disambiguator.CONFIDENCE_NO_MATCH 注释)。"""
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
        if disambig.get("status") == "no_match":
            return await IntentTriageEngine.handle_immediate_bypass(
                state,
                "image_product_no_match",
                "未在您近期的订单中找到与图片相符的商品。麻烦告诉我具体是哪件商品、出了什么问题,"
                "或直接提供订单编号,我来为您处理。",
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
            return _triage_terminal_result(intents, input_text, history_msgs, state.get("damage_assessment"))

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
                print(f"[Triage] 多模态视觉解析失败,降级启发式兜底 (threadId={thread_id}): {vision_err}")

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
            return _triage_terminal_result(intents, input_text, history_msgs, damage_assessment)

        # 🛡️ 重复提问拦截器
        try:
            user_msgs = [m for m in history_msgs if m.get("role") == "user"]
            assistant_msgs = [m for m in history_msgs if m.get("role") == "assistant"]
            is_operational_action = bool(OPERATIONAL_ACTION_RE.search(input_text))
            # 带图轮次不做文本去重(2026-09-10 误退事故):拦截器只比文本,
            # 「坏了」+破损图重发会先于 Step 0.5 图证(OCR 单号/破损定责)被消费
            # 就把会话关成上一轮答复的重放 —— 事故线程重放了修复前(pre-OCR消费)
            # 的旧消歧卡,引导用户挑本店真单对外店单 ORD-77777 误起退款审批。
            # 图证即新证据,与 is_operational_action 同为去重豁免闸。
            carries_image_evidence = bool(state.get("image_urls"))

            if (
                not is_operational_action
                and not carries_image_evidence
                and len(user_msgs) >= 2
                and assistant_msgs
            ):
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
            print(f"[Triage] 重复提问拦截器异常,已跳过去重检查 (threadId={thread_id}): {sh_err}")

        # 🛡️ Step 1: 规则白名单
        clean_input = strip_punctuation_for_greeting(input_text)
        tenant_id = tenant_of_state(state)

        if rule_matchers.is_greeting(clean_input):
            # 同源改造(new-user-onboarding D):罐头回复消费租户 onboarding_config
            # (与建线程欢迎行/引擎极速旁路同一份),入口卡一并下发;零 LLM 与
            # 仲裁留痕口径不变(rule_greeting 路由键、candidates 记录)。
            onboarding = await resolve_onboarding_config(tenant_id)
            return await IntentTriageEngine.handle_immediate_bypass(
                state,
                "rule_greeting",
                onboarding["welcomeText"],
                [{"intent": "general_query", "confidence": 1.0}],
                "rule",
                1.0,
                cards=build_entry_cards(onboarding),
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
                if consult_answer == ROUTE_TO_ACTION_MARKER:
                    # 🧭 仲裁员否决(intent-arbitration 05,2026-09-10):正则快轨
                    # 不再独自关会话 —— 直答调用复核为动作形请求,fallthrough 完整
                    # 管线(Step 1.5 起照常裁决,用户拿到动作管道结果而非资讯回复)。
                    # 改判进终局行 candidates:consult_gate 提议 consult,
                    # consult_arbiter 否决(intent 记 None —— 该层只判定「非咨询」,
                    # 不认领具体动作意图,终局由后续层裁决);不另写日志行,
                    # 终局单点落库(01)不变。
                    proposals.append(_proposal("consult_gate", "consult"))
                    proposals.append(_proposal("consult_arbiter", None))
                else:
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
            else:
                # RAG 空弱/直答失败:回落 general_query 零规划旁路(finish 终稿)
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
                return _triage_terminal_result(
                    consult_intents, input_text, history_msgs, damage_assessment, role="chitchat"
                )

        # 🛡️ Step 1.5: 意图与槽位完整性拦截
        # 资金让位标记(多意图一期):规则层见资金词族但判成非资金意图时,判定 3
        # 关键词分支同样让位 —— 否则「推荐卫衣，帮我把上一单退掉」在 Step2 被
        # 吞成单退款,导购半静默丢失(与 766 处 money_action_veto_yield 同源)。
        money_action_yielded = False
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
                return _triage_terminal_result(
                    multi_intents, input_text, history_msgs, damage_assessment,
                    state=state, with_order_context=True,
                )

            # extract_all 恒非空(detected≤1 时返回 [extract(...)]、≥2 时逐规则
            # 列表,且 ≥2 已在上分支返回),此处直接取首元素(工单02 死分支清理)
            task_spec = all_specs[0]

            # 单号信任边界(2026-09-10 误退事故第二层):slots.orderId 可能来自通用
            # extract_order_id 的历史反向回填 —— 历史最后提及的单号(旧消歧卡里的
            # 本店真单)只是续聊启发,不是用户本轮确认。它一旦进入 order_context,
            # refund 类判定(Step 2 判定 3 fused 的 confirmed 通道)与视觉消歧闸
            # (order_id_resolved)都会被短路:图内外店单 OCR 失效的轮次直接对历史
            # 单自动退款。文本显式与 TaskMemory 已确认才是可信通道;历史回填值
            # 留在 slots 供查询类续聊(ORDER_QUERY 快轨),不冒充已确认。
            text_order_match = ORDER_ID_RE.search(input_text)
            text_channel_order_id = text_order_match.group(0) if text_order_match else None
            confirmed_channel_order_id = (existing_order_context or {}).get("targetOrderId")
            trusted_order_id = text_channel_order_id or confirmed_channel_order_id
            if trusted_order_id:
                _set_target_order_id(state, trusted_order_id)

            # 图内 OCR 单号注入(2026-09-09 事故:ORD-77777 算完即丢)——单号优先级
            # 文本 > 已确认上下文 > 图内 OCR > 历史回填;注入后重跑槽位抽取,退款
            # 严格抽取器经 orderContext.targetOrderId 取到(与消歧 matched 注入同型)
            if vision_order_id and not trusted_order_id:
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
                # 文本通道单号(slots 可能携带历史回填值,不算已解析 —— 信任边界
                # 同上,2026-09-10 误退事故第二层;谓词本体另有 OCR/上下文通道)
                order_id_resolved=text_channel_order_id,
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

            # 🧭 冲突标记留痕(intent-arbitration 07,工单07 2026-09-11 挂点前移):
            # 槽位层判动作 × 咨询形措辞(疑问词×话题词×无动作动词)→ 记
            # consult_shaped_gate 提议。挂点自「槽位完整高置信终局」前移至缺槽
            # 反问检查之前 —— 07 追溯的靶形状正是咨询形输入被缺槽反问打断,
            # 旧挂点在该路径永不点亮,冲突信号源对此失明。路由不变(只记提议
            # 不碰 intents);信号只入池不成为断言(07 口径)。
            if task_spec["intentType"] != AgentIntentType.CHAT and is_consult_shaped_marker(input_text):
                proposals.append(_proposal("consult_shaped_gate", AgentIntentType.CONSULT))

            # 多意图不打断(2026-09-12):复合候选形先行判定 —— 缺槽反问与单
            # 意图快轨都不得劫持复合轮,交结构化精判与 planner 编排。
            is_multi_intent_candidate = _is_multi_intent_candidate(input_text)

            # 高风险/多参数意图缺失必填槽位 → 即时追问,阻断死循环自旋。
            # 复合候选形除外(A3:「查订单把没发货的退了」被规则层「请提供
            # 订单编号」劫持,先查单再挑的合法流永远走不到 planner)。
            if (
                task_spec["missingSlots"]
                and task_spec["clarificationMessage"]
                and not is_multi_intent_candidate
            ):
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

            # 参数齐备且非复合多意图 → 高置信度放行进入 DAG 调度
            if (
                not is_multi_intent_candidate
                and task_spec["intentType"] != "chat"
                and not task_spec["missingSlots"]
                and task_spec["confidence"] >= 0.8
            ):
                # 🚦 资金否决让位(多意图一期,2026-09-12,评审缺陷②):规则层只
                # 检出导购/购物车单意图(资金词族不在其规则 pattern 里,如「退掉」)
                # 时,连单意图终局一起让位 Step2/3 精判并留痕 —— 否则「推荐几款
                # 卫衣，帮我把上一单退掉」照样以 single_complete 吞掉退款半。
                if (
                    _money_action_vetoed(input_text)
                    and task_spec["intentType"] not in _MONEY_ACTION_INTENTS
                ):
                    yield_intents = [
                        {
                            "intent": task_spec["intentType"],
                            "confidence": task_spec["confidence"],
                            "type": "primary",
                            "taskSpec": task_spec,
                        }
                    ]
                    await IntentTriageEngine.log_intent_to_db(
                        thread_id,
                        input_text,
                        yield_intents,
                        "rule",
                        task_spec["confidence"],
                        candidates=list(proposals),
                        arbitration_reason="money_action_veto_yield",
                    )
                    money_action_yielded = True
                else:
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

                    return _triage_terminal_result(intents, input_text, history_msgs, damage_assessment)
        except Exception as slot_err:
            print(f"[Triage] 槽位澄清阶段异常,已跳过槽位层裁决 (threadId={thread_id}): {slot_err}")

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
                print(f"[Triage] 动作形输入跳过回复缓存读取 (tenantId={cache_tenant}): {input_text[:50]}")
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
                return _triage_terminal_result(
                    intents, input_text, history_msgs, damage_assessment,
                    state=state, with_order_context=True,
                )

            # 判定 1.5(ADR-0003):经营口径排行规则前置 —— 确定性直通
            # metric_query,严禁 LLM 分类层把「利润」当后台数据拒答。
            if is_profit_ranking_query(input_text):
                intents = [{"intent": "metric_query", "confidence": 0.97, "type": "primary"}]
                await IntentTriageEngine.log_intent_to_db(
                    thread_id,
                    input_text,
                    intents,
                    "rule",
                    intents[0]["confidence"],
                    candidates=[_proposal("rule", "metric_query", 0.97)],
                    arbitration_reason="profit_ranking_precheck",
                )
                return _triage_terminal_result(
                    intents, input_text, history_msgs, damage_assessment,
                    state=state,
                )

            # 判定 1.6(多意图一期,2026-09-12):地址簿规则前置 —— 词表缺口曾使
            # 「创建地址」落 general_query 让 planner 编造假改派流程(A11 实弹:
            # 幻觉「已发货联系快递员改派、转寄费自理」)。纯建/查地址(非复合)
            # 确定性直通 address_manage,零结构化调用;复合形让位 Step3 注入器。
            if not _is_multi_intent_candidate(input_text):
                detected_addr = detect_address_manage(input_text)
                if detected_addr is not None and (
                    detected_addr["mode"] == "list" or not detected_addr["missingSlots"]
                ):
                    addr_intents = [_address_manage_intent_entry(detected_addr)]
                    await IntentTriageEngine.log_intent_to_db(
                        thread_id,
                        input_text,
                        addr_intents,
                        "rule",
                        0.9,
                        candidates=[
                            *proposals,
                            _proposal("rule", AgentIntentType.ADDRESS_MANAGE, 0.9),
                        ],
                        arbitration_reason="address_manage_precheck",
                    )
                    return _triage_terminal_result(
                        addr_intents, input_text, history_msgs, damage_assessment,
                        state=state,
                    )

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
                await IntentTriageEngine.log_intent_to_db(
                    thread_id,
                    input_text,
                    intents,
                    "embedding",
                    intents[0]["confidence"],
                    candidates=[*proposals, _proposal("embedding", "order_status", score_order)],
                    arbitration_reason="embedding_order_status",
                )
                return _triage_terminal_result(
                    intents, input_text, history_msgs, damage_assessment,
                    state=state, with_order_context=True,
                )

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
                and not money_action_yielded
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
                return _triage_terminal_result(
                    intents, input_text, history_msgs, damage_assessment,
                    state=state, with_order_context=True,
                )

            # 判定 4: 超出业务范畴拦截 —— 锚点层降为提议者(intent-arbitration 06,
            # 2026-09-10)。旧路径 29 条锚句余弦 × 硬阈值判 oos 即直接关会话,零
            # LLM 确认:「买个东西怎么买」(购买流程咨询,oos 锚句相似 1.000)被
            # 误吞成零计划兜底,而结构化精判判 shopping_guide。现仅记提议后
            # fallthrough Step 3:LLM 确认出范畴 → llm_out_of_scope 收尾(行为
            # 不变,该路径 +1 调用可接受);改判 → 咨询直答/动作管线照常裁决。
            # 真 oos(天气/写代码)的确认调用经 01 的 node 归因计入延迟统计,
            # p50 咨询路径不含本路径,红线不破。
            if score_oos >= 0.86 and score_oos - max(score_order, score_refund) >= 0.06:
                proposals.append(_proposal("embedding", "out_of_scope", score_oos))
                if state.get("job_id"):
                    await emit_status(
                        state["job_id"],
                        "🔎 锚点初判为业务范畴外,正在交由大模型复核确认...",
                        node="triage",
                    )
        except Exception as embed_err:
            print(f"[Triage] 嵌入锚点分类异常,已跳过 Step 2 锚点判定 (threadId={thread_id}): {embed_err}")

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
                print(
                    f"[Triage] 租户样本召回失败,降级空样本 "
                    f"(threadId={thread_id}/tenantId={active_tenant_id}): {ex_err}"
                )

            structured_res = await classify(
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
                return await IntentTriageEngine.handle_immediate_bypass(
                    state,
                    "llm_out_of_scope",
                    reply,
                    [{"intent": "general_query", "confidence": 0.9}],
                    "structured_llm",
                    0.9,
                    candidates=[
                        *proposals,
                        _proposal("structured_llm", "out_of_scope", 0.9),
                    ],
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
                    if item.intent in _MONEY_ACTION_INTENTS and "orderId" not in (item.missingSlots or []):
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

            # 缺槽反问收窄(多意图不打断一期,2026-09-12):仅 primary 缺槽且
            # 无营救意图时反问;secondary 缺槽(A1:改单地址缺单号)不劫持
            # primary 齐备的复合轮,放行 planner 先办能办的、结尾一次性追问。
            if (
                _should_clarify_first(parsed)
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
                    if consult_answer == ROUTE_TO_ACTION_MARKER:
                        # 🧭 仲裁员否决(05):分类器判 consult × 仲裁员判动作形。
                        # 不再 fallthrough 深规划(consult 落 planner 会失控深规划),
                        # 降级离场;降级保留动作形条目并提升首个动作为 primary
                        # (工单06 2026-09-11)—— 否决只否「资讯直答」,不否动作,
                        # 带动作意图的请求绝不因一条资讯回复了事(故事3/5),
                        # 提升后非单 general_query 自然进 planner 编排。
                        # 否决进 candidates 留痕,终局行可溯改判来源。
                        proposals.append(_proposal("consult_arbiter", None))
                        parsed = _demote_consult_keep_actions(parsed)
                    else:
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
                else:
                    # RAG 空弱:同款降级离场(工单06:保留动作形并提升 primary;
                    # 纯 consult 输入输出与旧整体降级同形)
                    parsed = _demote_consult_keep_actions(parsed)

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

            return _triage_terminal_result(
                parsed, input_text, history_msgs, damage_assessment,
                state=state, with_order_context=True,
            )
        except CircuitBreakerOpenError:
            # 上游 LLM 熔断非节点级可恢复:上抛 run_agent 走 job 级降级(兜底 intent 仅面向分类输出类失败)
            raise
        except Exception as err:
            print(f"[Triage] Step 3 结构化精判失败,降级兜底意图 (threadId={thread_id}): {err}")
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
            return _triage_terminal_result(fallback_intents, input_text, history_msgs, damage_assessment)

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

        # 🚦 资金动作一票否决(多意图不打断一期,2026-09-12):输入含退款/退货
        # 词族而命中的技能非售后域时,拒绝快轨 —— 否则「退了订单X，然后推荐Y」
        # 被导购 fallback 正则整句吞掉,资金动作静默丢失(实弹矩阵 A6)。
        # 返回 None 落回 embedding 锚点/结构化精判,那里有 refund 锚点与判定 3。
        if _money_action_vetoed(input_text) and (
            matching_skill.metadata.get("category") != _AFTER_SALE_SKILL_CATEGORY
        ):
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
            # 技能可携带恢复计划(HITL 挂起形):随 bypass 透传,防止 run_agent
            # 回合收口以 bypass 空计划覆盖挂起步骤(高价值改址审批恢复依赖它)
            bypass = await IntentTriageEngine.handle_immediate_bypass(
                state,
                f"skill_fast_track_{matching_skill.metadata['id']}",
                skill_result["output"],
                intents,
                "skill_fast_track",
                task_spec["confidence"],
                damage_assessment,
                cards=skill_result.get("cards"),
                candidates=[
                    *(proposals or []),
                    _proposal("skill_fast_track", matching_skill.metadata["id"], task_spec["confidence"]),
                ],
                task_plan=skill_result.get("taskPlan"),
            )
            return {
                **bypass,
                "cards": state.get("cards"),
                "guide_context": state.get("guide_context"),
                "cart_context": state.get("cart_context"),
            }
        return None
