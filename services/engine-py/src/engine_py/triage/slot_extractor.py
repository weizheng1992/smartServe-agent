"""实体与槽位对齐引擎 — 镜像 triage/slotExtractor.ts(正则与规则表逐条移植)。

AgentTaskSpec 的键保持 TS camelCase(intentType/slots/confidence/missingSlots/
clarificationMessage):该对象会进入事件载荷与 planner 输入,属于内部契约。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable


class AgentIntentType:
    CHAT = "chat"
    CART_MANAGE = "cart_manage"
    SHOPPING_GUIDE = "shopping_guide"
    ORDER_MODIFY_ADDRESS = "order_modify_address"
    ORDER_CANCEL = "order_cancel"
    ORDER_RETURN = "order_return"
    ORDER_QUERY = "order_query"
    ORDER_STATUS = "order_status"
    REFUND = "refund"
    METRIC_QUERY = "metric_query"
    HUMAN_ESCALATION = "human_escalation"
    GENERAL_QUERY = "general_query"
    OUT_OF_SCOPE = "out_of_scope"


# ---------------------------------------------------------------------------
# 1. 原子实体提取器
# ---------------------------------------------------------------------------
ORDER_ID_RE = re.compile(
    r"(?:[A-Za-z0-9]+[-_])*ORD(?:[-_][A-Za-z0-9]+)+|\b[A-Za-z]{2,8}[-_]?\d{4,}\b|\b\d{8,}\b",
    re.IGNORECASE,
)
ADDRESS_KEYWORDS_RE = re.compile(
    r"(?:改成|改到|送至|送往|送去|寄到|寄往|改派到|改派|改送|新地址[是为:：]?|地址[是为:：])\s*([^,，!！?？\n]+)",
    re.IGNORECASE,
)
PROVINCE_CITY_RE = re.compile(
    r"(?:北京市|上海市|天津市|重庆市|广东省|浙江省|江苏省|四川省|湖北省|山东省|河南省|河北省|陕西省|福建省|湖南省|安徽省|辽宁省|江西省|广西|海南省|贵州省|云南省|山西省|吉林省|黑龙江省|内蒙古|新疆|西藏|青海|宁夏|海淀区|朝阳区|西城区|东城区|浦东新区|黄浦区|徐汇区|静安区)[^\s,，。!！?？\n]+",
    re.IGNORECASE,
)

RETURN_REASONS_MAP: list[dict] = [
    {"reason": "wrong_size", "keywords": ["尺码", "穿不上", "大", "小"]},
    {"reason": "quality_issue", "keywords": ["质量", "坏", "破", "瑕疵"]},
    {"reason": "not_as_described", "keywords": ["不符合", "不一样", "虚假"]},
    {"reason": "no_reason_7d", "keywords": ["七天", "不喜欢", "不想要"]},
]


def extract_order_id(text: str, context: dict | None = None) -> str | None:
    match = ORDER_ID_RE.search(text)
    if match:
        return match.group(0).upper()
    order_context = (context or {}).get("orderContext") or {}
    if order_context.get("targetOrderId"):
        return str(order_context["targetOrderId"]).upper()
    msgs = (context or {}).get("shortMemory") or (context or {}).get("historyMsgs") or []
    for msg in reversed(msgs):
        content = msg if isinstance(msg, str) else (msg or {}).get("content")
        if content and isinstance(content, str):
            hist_match = ORDER_ID_RE.search(content)
            if hist_match:
                return hist_match.group(0).upper()
    return None


def extract_new_address(text: str) -> str | None:
    kw_match = ADDRESS_KEYWORDS_RE.search(text)
    if kw_match and kw_match.group(1):
        return kw_match.group(1).strip()
    prov_match = PROVINCE_CITY_RE.search(text)
    if prov_match:
        return prov_match.group(0).strip()
    return None


def extract_return_reason(text: str) -> str | None:
    for item in RETURN_REASONS_MAP:
        if any(kw in text for kw in item["keywords"]):
            return item["reason"]
    return None


# ---------------------------------------------------------------------------
# 2. 声明式意图匹配规则表
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class IntentRule:
    intent: str
    confidence: float
    pattern: re.Pattern[str]
    negative_pattern: re.Pattern[str] | None = None


INTENT_DETECTION_RULES: list[IntentRule] = [
    IntentRule(
        intent=AgentIntentType.CART_MANAGE,
        confidence=0.95,
        pattern=re.compile(
            r"(?:加购物车|加入购物车|放进购物车|加购|购物车|结算|去结算|去买单|查看购物车|清空购物车|购物车里|移出购物车|删除.*?购物车|从购物车.*?删除|买第|件加入|款加入|放入购物车|加第|买第|要第|改成\s*\d+|修改为\s*\d+|数量设为\s*\d+|第[一二三四五12345两几][件款个双].*?(?:购物车|买|要|加|删|改|去)|(?:删除|移除|删掉).*?第[一二三四五12345两几][件款个双])|^(?:把)?第\s*[一二三四五12345两几]\s*[件款个双]",
            re.IGNORECASE,
        ),
    ),
    IntentRule(
        intent=AgentIntentType.SHOPPING_GUIDE,
        confidence=0.95,
        pattern=re.compile(
            r"(?:推荐|买什么|有什么好看|有没有|挑一款|选一款|适合.*的|找一找|推荐一款|介绍一下|哪款好|选鞋|选衣服|看商品|导购|什么牌子|款式|推荐几件|推荐几款)",
            re.IGNORECASE,
        ),
        negative_pattern=re.compile(r"(?:加购物车|加入购物车|放进购物车|加购|移出购物车|清空购物车)", re.IGNORECASE),
    ),
    IntentRule(
        intent=AgentIntentType.ORDER_MODIFY_ADDRESS,
        confidence=0.95,
        pattern=re.compile(
            r"(?:(?:修改|更改|变更|换|改|更新).*?(?:收货)?(?:地址|位置|地方)|(?:收货)?(?:地址|位置|地方).*?(?:修改|更改|变更|换|改|错|变)|(?:改到|改成|送至|送往|改派到|改派|改送)\s*[^?？哪里哪儿\n]+)",
            re.IGNORECASE,
        ),
        negative_pattern=re.compile(r"(?:寄到|送至|送往|寄往|送去)\s*(?:哪里|哪儿|哪了|何处|\?|？)", re.IGNORECASE),
    ),
    IntentRule(
        intent=AgentIntentType.ORDER_CANCEL,
        confidence=0.92,
        pattern=re.compile(r"(?:取消订单|撤销订单|退订|取消.*单)", re.IGNORECASE),
    ),
    IntentRule(
        intent=AgentIntentType.ORDER_RETURN,
        confidence=0.95,
        pattern=re.compile(r"(?:退货|退款|退单|申请售后|退钱|不想要了|申请退款)", re.IGNORECASE),
    ),
    IntentRule(
        intent=AgentIntentType.ORDER_QUERY,
        confidence=0.92,
        pattern=re.compile(
            r"(?:查.*物流|物流到哪|物流信息|快递单号|快递到哪|发货了吗|包裹到哪|查快递|寄到哪|送至哪|到了没|查一下.*订单|查订单状态|查询.*订单|物流查询|查下订单|查订单|我的订单|名下.*订单|全部订单)",
            re.IGNORECASE,
        ),
        negative_pattern=re.compile(r"(?:寄到|送至|送往|寄往|送去)\s*(?:哪里|哪儿|哪了|何处|\?|？)", re.IGNORECASE),
    ),
    IntentRule(
        intent=AgentIntentType.METRIC_QUERY,
        confidence=0.96,
        pattern=re.compile(r"(?:销售额|销量|出货量|毛利|利润率|gmv|滞销|排行|最卖钱|最赚钱)", re.IGNORECASE),
    ),
]

_GENERAL_LIST_POSITIVE_RE = re.compile(
    r"(?:我的订单|全部订单|名下.*订单|所有订单|历史订单|查订单|查询.*订单|查下订单|订单列表|看看我买了啥|我有哪些订单|历史购买记录|查下我买的东西)",
    re.IGNORECASE,
)
_GENERAL_LIST_LOGISTICS_RE = re.compile(
    r"(?:查.*物流|物流到哪|物流信息|快递单号|快递到哪|发货了吗|包裹到哪|查快递)", re.IGNORECASE
)


def is_general_order_list_query(text: str) -> bool:
    return bool(_GENERAL_LIST_POSITIVE_RE.search(text)) and not bool(_GENERAL_LIST_LOGISTICS_RE.search(text))


# ---------------------------------------------------------------------------
# 3. Schema 驱动的槽位声明
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class SlotDefinition:
    name: str
    required_fn: Callable[[str], bool]
    extractor: Callable[[str, dict | None], str | None]


@dataclass(frozen=True)
class IntentSchema:
    slots: list[SlotDefinition]
    clarification_builder: Callable[[dict, list[str]], str | None] | None = None


def _modify_address_clarification(slots: dict, missing: list[str]) -> str | None:
    if "orderId" in missing and "newAddress" in missing:
        return "好的，请问您需要修改哪笔订单的收货地址？请提供您的【订单编号】（如 ORD-889901）以及【新的收货地址】。"
    if "newAddress" in missing:
        return f"已为您定位到订单 [{slots.get('orderId')}]，请问您需要将收货地址变更为哪个新的收货地址？"
    if "orderId" in missing:
        return f"收到您的新地址 [{slots.get('newAddress')}]，请问您需要修改哪笔【订单编号】的收货地址？"
    return None


INTENT_SCHEMAS: dict[str, IntentSchema] = {
    AgentIntentType.ORDER_MODIFY_ADDRESS: IntentSchema(
        slots=[
            SlotDefinition(name="orderId", required_fn=lambda _t: True, extractor=lambda t, ctx: extract_order_id(t, ctx)),
            SlotDefinition(name="newAddress", required_fn=lambda _t: True, extractor=lambda t, _ctx: extract_new_address(t)),
        ],
        clarification_builder=_modify_address_clarification,
    ),
    AgentIntentType.ORDER_RETURN: IntentSchema(
        slots=[
            SlotDefinition(name="orderId", required_fn=lambda _t: True, extractor=lambda t, ctx: extract_order_id(t, ctx)),
            SlotDefinition(name="returnReason", required_fn=lambda _t: False, extractor=lambda t, _ctx: extract_return_reason(t)),
        ],
        clarification_builder=lambda _slots, missing: (
            "请问您需要为哪笔订单申请退款/退货？请提供您的【订单编号】。" if "orderId" in missing else None
        ),
    ),
    AgentIntentType.ORDER_CANCEL: IntentSchema(
        slots=[
            SlotDefinition(name="orderId", required_fn=lambda _t: True, extractor=lambda t, ctx: extract_order_id(t, ctx)),
        ],
        clarification_builder=lambda _slots, missing: (
            "请问您需要取消哪笔订单？请提供【订单编号】。" if "orderId" in missing else None
        ),
    ),
    AgentIntentType.ORDER_QUERY: IntentSchema(
        slots=[
            SlotDefinition(
                name="orderId",
                required_fn=lambda text: not is_general_order_list_query(text),
                extractor=lambda t, ctx: extract_order_id(t, ctx),
            ),
        ],
        clarification_builder=lambda _slots, missing: (
            "请提供您需要查询的【订单编号】或【运单号】。" if "orderId" in missing else None
        ),
    ),
}

REQUIRED_SLOTS_MAP: dict[str, list[str]] = {
    AgentIntentType.ORDER_MODIFY_ADDRESS: ["orderId", "newAddress"],
    AgentIntentType.ORDER_RETURN: ["orderId"],
    AgentIntentType.ORDER_CANCEL: ["orderId"],
    AgentIntentType.ORDER_QUERY: ["orderId"],
}


# ---------------------------------------------------------------------------
# 4. SlotExtractor
# ---------------------------------------------------------------------------
class SlotExtractor:
    @staticmethod
    def extract_entities(user_input: str, context: dict | None = None) -> dict[str, Any]:
        text = user_input.strip()
        entities: dict[str, Any] = {}
        order_id = extract_order_id(text, context)
        if order_id:
            entities["orderId"] = order_id
        new_address = extract_new_address(text)
        if new_address:
            entities["newAddress"] = new_address
        return_reason = extract_return_reason(text)
        if return_reason:
            entities["returnReason"] = return_reason
        return entities

    @staticmethod
    def detect_intents(text: str) -> list[IntentRule]:
        matched: list[IntentRule] = []
        for rule in INTENT_DETECTION_RULES:
            if not rule.pattern.search(text):
                continue
            if rule.negative_pattern and rule.negative_pattern.search(text):
                continue
            matched.append(rule)
        return matched

    @staticmethod
    def extract(
        user_input: str,
        active_intent_context: str | None = None,
        existing_slots: dict | None = None,
        context: dict | None = None,
    ) -> dict:
        text = user_input.strip()

        matched_rules = SlotExtractor.detect_intents(text)
        primary_matched = matched_rules[0] if matched_rules else None

        intent_type = AgentIntentType.CHAT
        confidence = 0.9

        if active_intent_context:
            intent_type = active_intent_context
            confidence = 0.95
        elif primary_matched:
            if primary_matched.intent == AgentIntentType.ORDER_QUERY and is_general_order_list_query(text):
                intent_type = AgentIntentType.CHAT
                confidence = 0.9
            else:
                intent_type = primary_matched.intent
                confidence = primary_matched.confidence

        extracted = SlotExtractor.extract_entities(text, context)
        slots: dict[str, Any] = {**(existing_slots or {}), **extracted}

        schema = INTENT_SCHEMAS.get(intent_type)
        missing_slots: list[str] = []
        if schema:
            for slot_def in schema.slots:
                if slot_def.required_fn(text) and not slots.get(slot_def.name):
                    missing_slots.append(slot_def.name)

        clarification_message = (
            schema.clarification_builder(slots, missing_slots) if missing_slots and schema else None
        )

        return {
            "intentType": intent_type,
            "slots": slots,
            "confidence": confidence,
            "missingSlots": missing_slots,
            "clarificationMessage": clarification_message,
        }

    @staticmethod
    def extract_all(
        user_input: str,
        active_intent_context: str | None = None,
        existing_slots: dict | None = None,
        context: dict | None = None,
    ) -> list[dict]:
        text = user_input.strip()
        detected = SlotExtractor.detect_intents(text)
        if len(detected) <= 1:
            return [SlotExtractor.extract(user_input, active_intent_context, existing_slots, context)]
        return [
            SlotExtractor.extract(user_input, rule.intent, existing_slots, context) for rule in detected
        ]
