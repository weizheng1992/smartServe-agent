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
from ..memory import ShortMemory, TaskMemory  # noqa: F401 (测试 patch 面)
from ..onboarding import build_entry_cards, resolve_onboarding_config  # noqa: F401 (测试 patch 面)
from ..skills import is_action_query  # noqa: F401 (测试 patch 面)
from ..skills.contract import SkillContext
from ..tenant import sanitize_tenant_response, tenant_of_state
from ..vision import analyze_images  # noqa: F401 (测试 patch 面)
from .consult_fast_path import (  # noqa: F401 (测试 patch 面)
    is_consult_query,
    is_consult_shaped_marker,
    run_consult_direct_answer,
)
from .exemplar_service import search_relevant_exemplars  # noqa: F401 (测试 patch 面)
from .intent_registry import (
    CONSULT_SIDE_INTENTS,
    EXPLICIT_ORDER_ID_RE,
    INTENT_REGISTRY,
    MONEY_ACTION_VETO_RE,
    OPERATIONAL_ACTION_RE,  # noqa: F401 (测试 patch 面)
    ORDER_KEYWORDS_RE,  # noqa: F401 (测试 patch 面 / embedding_anchor 经 ctx.ns 读取)
    REFUND_KEYWORDS_RE,  # noqa: F401 (测试 patch 面)
    UNSANITIZED_TAGS_RE,  # noqa: F401 (测试 patch 面)
)
from .product_disambiguator import build_select_card, disambiguate_product
from .semantic_cache import SemanticVectorCache, strip_punctuation_for_greeting
from .slot_extractor import (
    PHONE_SHAPE,
    AgentIntentType,
    SlotExtractor,  # noqa: F401 (测试 patch 面)
    parse_chinese_address,
)
from .structured_classifier import classify  # noqa: F401 (测试 patch 面)

# 数字指纹(2026-09-14 语义重复拦截收紧):门牌/单号/数量等槽位数字是动作
# 的身份的一部分 —— 两句语义相似但数字串不同,是「换了个请求」不是「重复
# 提问」(实弹:「新增地址…1211室」vs「…1402室」仅差门牌,旧确认重放顶掉
# 了新保存)。
_DIGIT_RUN_RE = re.compile(r"\d+")


def _digit_fingerprint(text: str | None) -> list[str]:
    """纯函数(测试缝):输入的数字串序列,作语义去重的槽位指纹。"""
    return _DIGIT_RUN_RE.findall(text or "")
# 退款动词族单一事实源(intent_registry.REFUND_VERB_RE,2026-09-13 收口)+
# 破损词(damage assessment 专用,不入 slot 规则表 —— 「坏了」不是退款动词)
MULTI_INTENT_CANDIDATE_RE = re.compile(
    r"(?:另外|同时|并|顺便|还有|然后|接着|以及|随后|其次|再(?=[查看买退加来试问改推结]))"
)
# 多意图不打断一期(2026-09-12):复合候选形的缺槽反问收窄与资金动作否决。
# 「然后」「并」裸词补入 —— 旧正则只有「然后再」「并且」,「退了订单9081，
# 然后推荐跑步鞋」「建地址…，并下单…」都漏判成单意图(A1/A6 实弹病灶)。
# 资金否决 = 退款动词族 + 换货(换货刻意不入族,见 intent_registry 注)
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
# 「建」单字入列(nightly 2026-09-14 实报回归:「建地址 张三…」曾整句漏检出,
# 词表只有「创建/新建」双字形)。
_ADDRESS_CREATE_PAYLOAD_RE = re.compile(
    r"(?:创建|新建|添加|新增|保存|增加|加|建)[^。,，\n]{0,8}地址[是为:：]?\s*(.*)$", re.DOTALL
)
# 复合句 payload 截断(nightly 2026-09-14):「创建地址…望京路1号，然后下单」
# 曾把「然后下单」整段吞进 fullAddress 落库 —— payload 在连接词处截断,
# 下半句属于下一个意图。
_ADDRESS_PAYLOAD_TRUNCATE_RE = re.compile(
    r"[，,。;；]?\s*(?:然后|接着|并|并且|顺便|另外|还有|以及|再(?=[查看看买退加来试问改推结]))"
)
# 姓名前缀剥除(nightly 2026-09-14):「收件人李四」曾整段 4 字尾匹配成
# 「件人李四」落库 —— 称谓前缀在姓名头部,先剥再抽(锚 ^,可迭代吃连用前缀)。
_NAME_PREFIX_RE = re.compile(r"^(?:收件人|收货人|联系人|收件|姓名|叫|我是)[:：]?\s*")
_ADDRESS_BOOK_LIST_RE = re.compile(
    r"(?:查看|看看|查一下|有哪些|列一下)(?:我的)?(?:收货地址|地址簿|地址列表)"
    r"|我的(?:收货)?地址(?:簿|列表)?(?:有哪些|是什么)?$"
    r"|^(?:地址列表|收货地址列表|地址簿列表)$"
)
# 设默认形(2026-09-15 S8):「刚才那个地址改成默认/设为默认地址」
_ADDRESS_SET_DEFAULT_RE = re.compile(
    r"(?:改成|设为|设置为|变成|设)[^。,，\n]{0,4}默认(?:地址)?|(?:默认地址)[^。,，\n]{0,4}(?:改成|设为|设置为)"
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
    if _ADDRESS_SET_DEFAULT_RE.search(text):
        return {
            "mode": "set_default",
            "entities": {"addressAction": "set_default"},
            "missingSlots": [],
        }
    # 删除形(2026-09-15 N4 能力补齐):「把我的地址全部删掉」
    if (
        re.search(r"(?:删除|删掉|移除|清空)[^。,，\n]{0,8}(?:我的)?(?:全部)?(?:收货地址|地址簿|地址)", text)
        or re.search(r"(?:收货地址|地址簿|地址)[^。,，\n]{0,8}(?:删除|删掉|移除|清空)", text)
    ):
        return {
            "mode": "delete",
            "entities": {"addressAction": "delete"},
            "missingSlots": [],
        }
    payload_match = _ADDRESS_CREATE_PAYLOAD_RE.search(text)
    if not payload_match:
        return None
    entities: dict = {"addressAction": "save"}
    payload = (payload_match.group(1) or "").strip()
    payload = _ADDRESS_PAYLOAD_TRUNCATE_RE.split(payload)[0].strip()
    phone_match = _PHONE_RE.search(payload)
    if phone_match:
        entities["receiverPhone"] = phone_match.group(1)
        before = payload[: phone_match.start()].strip(" ,，:：-—")
        while True:
            stripped = _NAME_PREFIX_RE.sub("", before).strip()
            if stripped == before:
                break
            before = stripped
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
    @staticmethod
    async def process(state: dict) -> dict:
        """意图判定管线驱动循环(admin-readiness 架构审视候选①)。

        判定顺序即 STAGES 列表顺序 —— 此前这一最重要的架构事实只存在于
        998 行函数的行序里;现每个阶段是 stages/ 包的独立深模块,行为逐字
        搬移,任一阶段 terminal 即返回终局。
        """
        thread_id = state.get("thread_id", "")
        input_text = (state.get("input") or "").strip()

        # 仲裁留痕(intent-arbitration 01):逐层累积判定提议,终局决策单点
        # 落库时作为 candidates 快照 —— 谁关闭了会话、谁压过了谁,自此可查。
        proposals: list[dict] = []

        input_embedding = state.get("input_embedding") or []
        if input_text and input_embedding:
            SemanticVectorCache.inject_input_embedding(input_text, input_embedding)

        history_msgs = await ShortMemory(thread_id).get_messages()

        from .stages import (
            ConfirmationResumeStage,
            ConsultFastTrackStage,
            DuplicateInterceptStage,
            EmbeddingAnchorStage,
            LlmRefineStage,
            RuleWhitelistStage,
            SlotFusionStage,
            SystemResumeStage,
            VisionParseStage,
        )
        from .stages.context import StageContext

        ctx = StageContext(
            state=state,
            thread_id=thread_id,
            input_text=input_text,
            clean_input=strip_punctuation_for_greeting(input_text),
            tenant_id=tenant_of_state(state),
            history_msgs=history_msgs,
            engine=IntentTriageEngine,
            damage_assessment=state.get("damage_assessment"),
            input_embedding=input_embedding,
            proposals=proposals,
        )

        stages = [
            ConfirmationResumeStage,
            SystemResumeStage,
            VisionParseStage,
            RuleWhitelistStage,
            DuplicateInterceptStage,
            ConsultFastTrackStage,
            SlotFusionStage,
            EmbeddingAnchorStage,
            LlmRefineStage,
        ]
        for stage in stages:
            verdict = await stage.judge(ctx)
            if verdict.terminal:
                return verdict.result

        # 所有阶段均未终局(理论不可达:Step 3 兜底必终局)——诚实兜底
        fallback_intents = [{"intent": "general_query", "confidence": 0.5}]
        return _triage_terminal_result(fallback_intents, input_text, history_msgs, ctx.damage_assessment)

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
        # 类型化契约适配器 A(triage 快轨,2026-09-15 架构深化②):线上
        # state → SkillContext 只在此处翻译一次。
        context = SkillContext(
            thread_id=thread_id,
            tenant_id=tenant_id,
            user_id=state.get("user_id"),
            input=input_text,
            slots=slots,
            image_urls=state.get("image_urls"),
            guide_context=state.get("guide_context") or {},
            cart_context=state.get("cart_context") or {},
            order_context=state.get("order_context"),
            damage_assessment=damage_assessment,
            short_memory=history_msgs,
        )
        try:
            matching_skill = SkillRegistry.find_matching_skill(context)
        except Exception as match_err:
            # 技能注册/匹配崩溃(如并行迁移期契约断裂)等同「无技能可用」,
            # fast-track 让位返回 None,严禁让异常冒泡炸掉整个槽位层裁决
            print(f"[Triage] SkillRegistry 匹配失败,fast-track 让位: {match_err}")
            return None
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
        if skill_result.success and skill_result.next_action == "finish":
            if skill_result.cards:
                state["cards"] = (state.get("cards") or []) + skill_result.cards
            for extra_ctx, state_key in (
                (skill_result.guide_context, "guide_context"),
                (skill_result.cart_context, "cart_context"),
                (skill_result.order_context, "order_context"),
            ):
                if extra_ctx:
                    state[state_key] = {**(state.get(state_key) or {}), **extra_ctx}
            # 技能可携带恢复计划(HITL 挂起形):随 bypass 透传,防止 run_agent
            # 回合收口以 bypass 空计划覆盖挂起步骤(高价值改址审批恢复依赖它)
            bypass = await IntentTriageEngine.handle_immediate_bypass(
                state,
                f"skill_fast_track_{matching_skill.metadata['id']}",
                skill_result.output,
                intents,
                "skill_fast_track",
                task_spec["confidence"],
                damage_assessment,
                cards=skill_result.cards,
                candidates=[
                    *(proposals or []),
                    _proposal("skill_fast_track", matching_skill.metadata["id"], task_spec["confidence"]),
                ],
                task_plan=skill_result.task_plan,
            )
            return {
                **bypass,
                "cards": state.get("cards"),
                "guide_context": state.get("guide_context"),
                "cart_context": state.get("cart_context"),
            }
        return None
