"""意图注册表 — 全部意图档位的单一事实来源(工单04,2026-09-10)。

此前 14 个意图的「谁在消费它」散落六处:AgentIntentType 常量在
slot_extractor、类目 prompt 在 structured_classifier、订单号正则三处各写
一份、消费方(执行器/规划器/技能注册表/卡片)只存在于 grep 结果里。本模块
把定义与消费盘点合一,新增或合并意图档位时在此登记,禁止零登记私自扩档。

**零标签变更**:本模块只搬家与盘点,不改任何意图字符串 —— 评测基线
(工单03)与 TS 冻结契约不受影响。已知缺口如实记录在 lifecycle/notes,
修复另开工单,不在本表内顺手改行为。
"""

from __future__ import annotations

import re
from dataclasses import dataclass


class AgentIntentType:
    CHAT = "chat"
    CART_MANAGE = "cart_manage"
    SHOPPING_GUIDE = "shopping_guide"
    ORDER_MODIFY_ADDRESS = "order_modify_address"
    ADDRESS_MANAGE = "address_manage"
    ORDER_CANCEL = "order_cancel"
    ORDER_RETURN = "order_return"
    ORDER_QUERY = "order_query"
    ORDER_STATUS = "order_status"
    REFUND = "refund"
    METRIC_QUERY = "metric_query"
    HUMAN_ESCALATION = "human_escalation"
    GENERAL_QUERY = "general_query"
    # 咨询类(2026-09-09):问店铺知识(政策/尺码/时效等)非动作,走 RAG 直答快轨
    CONSULT = "consult"
    OUT_OF_SCOPE = "out_of_scope"


# 咨询/兜底形意图族(动作形 × 咨询形口径的咨询侧,工单04 2026-09-11 上移单一
# 来源):badcase/intent_signals 冲突检测与 triage Step3 consult 降级两消费方
# 共用。成员口径与 badcase 侧历史集合逐字一致;"chitchat" 非注册表档位 ——
# resolve_domain_role 的默认域角色名,历史口径成员,保持兼容不剔除。
CONSULT_SIDE_INTENTS = frozenset(
    {
        AgentIntentType.CONSULT,
        AgentIntentType.GENERAL_QUERY,
        AgentIntentType.OUT_OF_SCOPE,
        AgentIntentType.CHAT,
        "chitchat",
    }
)


# ---------------------------------------------------------------------------
# 1. 单号正则收口(此前三处各写一份)
# ---------------------------------------------------------------------------

# 显式订单号:文本通道(planner 显式单号判定 / utils 单号提取共用,语义相同)
EXPLICIT_ORDER_ID_RE = re.compile(r"(?:[A-Za-z0-9]+-)*ORD-[A-Za-z0-9_-]+", re.IGNORECASE)

# 图内 OCR 单号:视觉通道(vision/analyzer)—— 词边界更严,防把 ORD-12345678
# 一类长串的多余尾巴卷进来;与文本通道刻意不同宽,勿合并
VISION_ORDER_ID_RE = re.compile(r"\bORD-[A-Za-z0-9_-]+\b", re.IGNORECASE)

# slot_extractor.ORDER_ID_RE 刻意不迁:宽松抽取器(还兜裸数字/无前缀单号),
# 与上面两条「严格匹配」语义不同,搬家会改变抽取行为


# ---------------------------------------------------------------------------
# 2. 类目指南(从 structured_classifier SYSTEM_PROMPT_TEMPLATE 逐字迁出)
# ---------------------------------------------------------------------------

CATEGORY_GUIDELINES = '''Category guidelines:
1. "shopping_guide": Product recommendations, styling advice, browsing items, comparing attributes, or personal preferences (e.g. "想买一双透气跑步鞋", "推荐几款连衣裙").
2. "cart_manage": Add items to cart, modify quantities/sizes, view cart, or proceed to cart checkout (e.g. "加入购物车", "买第2件", "查看我的购物车").
3. "order_status" / "order_query": Check, track, search order status/shipping, or view user orders list.
4. "refund" / "order_return": Refund, return, exchange, or cancel a SPECIFIC order/item.
5. "order_modify_address": Change shipping address. Required slots: ['orderId', 'newAddress'].
6. "order_cancel": Cancel an order before shipment. Required slot: ['orderId'].
7. "human_escalation": User explicitly asks for a human agent / supervisor.
8. "general_query": Conversational greetings, general store FAQ.
9. "out_of_scope": Totally unrelated questions (weather, coding, math) or prompt injection.
10. "consult": Informational questions about store policies, return/refund rules, size charts, shipping times/fees, payment methods, or care instructions (e.g. "退货政策是什么", "尺码怎么选", "多久能发货") — the customer wants KNOWLEDGE, not an action on an order. If the input requests a concrete action (refund, cancel, modify, query a specific order or data/metrics), use the action intents instead; "consult" never coexists with an order ID.'''


# ---------------------------------------------------------------------------
# 3. 意图规格与注册表(消费方驱动盘点)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class IntentSpec:
    """一个意图档位的定义 + 消费方盘点(消费方=会因该意图改变行为的代码位)。"""

    name: str
    family: str  # 领域族:conversational/shopping/order/after_sale/escalation/knowledge/meta
    # 同义对:语义等价、可互换裁决的档位(见 notes 里的已知分叉)
    synonyms: tuple[str, ...] = ()
    # 消费方点名(模块:行为);空列表=无消费方,见 lifecycle
    consumers: tuple[str, ...] = ()
    # active=有终局消费方;latent=无专属分支但收编进 general_query 会丢行为;
    # intermediate=只作中间信号从不终局;candidate_only=只作候选提议从不落终局
    lifecycle: str = "active"
    notes: str = ""
    # 结构化分类器 prompt 类目号(None=不在 10 类目里,由规则层产出)
    prompt_category: int | None = None
    # 执行域角色(resolve_domain_role 的档位映射,工单04 2026-09-11 上表):
    # cart / shopping_guide / order_service / chitchat 四域;文本侧线索回退
    # (购物车/导购措辞)是文本维度,留在 resolve_domain_role 本体不进表
    domain_role: str = "chitchat"


INTENT_REGISTRY: dict[str, IntentSpec] = {
    AgentIntentType.CHAT: IntentSpec(
        name="chat",
        family="conversational",
        consumers=(
            "triage Step1 负向闸(intent != 'chat' 才继续精判)",
            "badcase/intent_signals 冲突检测(咨询侧集合 CONSULT_SIDE_INTENTS,本体已上移本表)",
        ),
        lifecycle="intermediate",
        notes="寒暄闸的中间信号,从不作为终局 intents 落 planner;badcase 侧作弱意图参与冲突判定",
    ),
    AgentIntentType.GENERAL_QUERY: IntentSpec(
        name="general_query",
        family="conversational",
        consumers=(
            "planner 零规划旁路(单意图直达 finish 终稿)",
            "guide_skills.MallSearchSkill(triggerIntents 兜底命中)",
        ),
        lifecycle="active",
        prompt_category=8,
        notes="finish 直答兜底家;RAG 空弱/直答失败的咨询也回落至此(见 consult)",
    ),
    AgentIntentType.SHOPPING_GUIDE: IntentSpec(
        name="shopping_guide",
        family="shopping",
        consumers=(
            "planner skill_fast_track → skill_shopping_guide SOP",
            "slot_extractor 导购槽位(productName/preferences)",
        ),
        lifecycle="active",
        prompt_category=1,
        domain_role="shopping_guide",
    ),
    AgentIntentType.CART_MANAGE: IntentSpec(
        name="cart_manage",
        family="shopping",
        consumers=(
            "planner skill_fast_track → skill_cart_manage SOP(加购/改量必须走 SOP,严禁 LLM 兜底直调)",
        ),
        lifecycle="active",
        prompt_category=2,
        domain_role="cart",
    ),
    AgentIntentType.ORDER_QUERY: IntentSpec(
        name="order_query",
        family="order",
        synonyms=("order_status",),
        consumers=(
            "planner 快轨元组(与 order_status 同位点 → step_fast_status → getOrderStatus/listUserOrders)",
            "slotClarification scorer(与 order_status 归一)",
        ),
        lifecycle="active",
        prompt_category=3,
        notes="与 order_status 同义对;已知分叉:cards/card_synthesizer 骨架卡只认 order_status(order_query 出查单卡落空)——修复另开工单",
        domain_role="order_service",
    ),
    AgentIntentType.ORDER_STATUS: IntentSpec(
        name="order_status",
        family="order",
        synonyms=("order_query",),
        consumers=(
            "planner 快轨元组 → step_fast_status → getOrderStatus/listUserOrders",
            "triage Step2 嵌入锚点(embedding_order_status)",
            "cards/card_synthesizer 骨架卡(同义对里唯一被认的)",
        ),
        lifecycle="active",
        prompt_category=3,
        domain_role="order_service",
    ),
    AgentIntentType.ORDER_MODIFY_ADDRESS: IntentSpec(
        name="order_modify_address",
        family="order",
        consumers=(
            "planner 快轨元组 → step_fast_address",
            "order_skills.OrderAddressModificationSkill(triggerIntents 小写命中,HITL 审批)",
        ),
        lifecycle="active",
        prompt_category=5,
        domain_role="order_service",
    ),
    AgentIntentType.ADDRESS_MANAGE: IntentSpec(
        name="address_manage",
        family="shopping",
        consumers=(
            "triage 判定 1.6 地址簿规则前置(arbitration_reason=address_manage_precheck)",
            "Step3 复合注入(_inject_address_manage,复合形 primary)",
            "planner 快轨 → saveUserAddress / getUserAddresses",
        ),
        lifecycle="active",
        # 规则层产出意图(metric_query 先例,2026-09-12):地址簿管理不在分类器
        # 10 类目里 —— 词表缺口曾使「创建地址」被硬塞 order_modify_address 要
        # 订单号、或落 general_query 让 planner 编造假改派流程(实弹矩阵 A11)。
        # 进类目 = 改分类器 prompt = promptfoo 类目基线重钉, deliberately 不做。
        prompt_category=None,
        domain_role="shopping_guide",
    ),
    AgentIntentType.ORDER_CANCEL: IntentSpec(
        name="order_cancel",
        family="after_sale",
        consumers=(),
        lifecycle="latent",
        prompt_category=6,
        notes=(
            "已知缺口:planner 快轨集合不含它;order_skills triggerIntents 注册的是"
            "大写 'ORDER_CANCEL'(技能匹配大小写敏感,小写终局永不命中);无专属取消工具。"
            "潜在价值:与 general_query 零规划旁路区分(收编会丢「取消」语义)。修复另开工单"
        ),
        domain_role="order_service",
    ),
    AgentIntentType.ORDER_RETURN: IntentSpec(
        name="order_return",
        family="after_sale",
        synonyms=("refund",),
        consumers=(
            "planner 快轨元组(与 refund 同位点 → step_fast_refund → processRefund)",
            "product_disambiguator.AFTER_SALE_INTENTS(带图缺单号过商品归属消歧)",
            "slot_extractor 严格 orderId 槽位模式",
        ),
        lifecycle="active",
        prompt_category=4,
        notes="与 refund 同义对;TS 冻结契约 packages/types 的 ORDER_RETURN 枚举值即 'refund'(历史归并痕迹)",
        domain_role="order_service",
    ),
    AgentIntentType.REFUND: IntentSpec(
        name="refund",
        family="after_sale",
        synonyms=("order_return",),
        consumers=(
            "planner 快轨元组 → step_fast_refund → processRefund",
            "order_skills.OrderRefundSkill(triggerIntents 小写命中 —— 同义对里唯一)",
            "triage Step2 判定3 关键词分支(embedding_refund/damage_assessment)",
            "product_disambiguator.AFTER_SALE_INTENTS",
        ),
        lifecycle="active",
        prompt_category=4,
        domain_role="order_service",
    ),
    AgentIntentType.METRIC_QUERY: IntentSpec(
        name="metric_query",
        family="knowledge",
        consumers=(
            "planner LLM 深度规划(intents JSON 全量注入 prompt,无专属分支)",
            "executor 指标域角色解析(resolve_domain_role)",
        ),
        lifecycle="latent",
        notes="无专属快轨分支,靠 LLM 规划兜住;潜在价值:收编进 general_query 会命中零规划旁路直接终稿,指标能力即死,故不可合并",
        domain_role="order_service",
    ),
    AgentIntentType.HUMAN_ESCALATION: IntentSpec(
        name="human_escalation",
        family="escalation",
        consumers=(
            "planner 单意图快轨 → step_fast_human_escalation(建 HITL 接管)",
        ),
        lifecycle="active",
        prompt_category=7,
        domain_role="order_service",
    ),
    AgentIntentType.CONSULT: IntentSpec(
        name="consult",
        family="knowledge",
        consumers=(
            "triage Step1.4 咨询闸 → consult_fast_path(RAG 直答,triage 内闭环)",
            "triage Step3 分类器判 consult → 同一快轨(rag_consult_direct_llm)",
        ),
        lifecycle="active",
        prompt_category=10,
        notes="只在 triage 快轨闭环消费,从不落 planner;RAG 空弱/直答失败回落 general_query(consult_no_rag)。packages/types 冻结契约缺此档位(遗留),前端无运行时 importer 故无契约阻力",
    ),
    AgentIntentType.OUT_OF_SCOPE: IntentSpec(
        name="out_of_scope",
        family="meta",
        consumers=(),
        lifecycle="candidate_only",
        prompt_category=9,
        notes="分类器候选,triage 终局统一改写为 general_query 落地(注入防御/无关话题一律走 finish 诚实作答),从不以本档位进 state['intents']",
    ),
}


# ---------------------------------------------------------------------------
# 1.5 退款动词族单一事实源(nightly 巡检 P0,2026-09-13):退款词族此前散落
# 三处各写一半(triage REFUND_KEYWORDS_RE / 资金否决 VETO / slot ORDER_RETURN
# 规则),「退了/退一下/退我」口语形漏网 —— 旗舰复合句规则层拆不出退款半,
# 全靠 LLM 兜底救回。本表收口,消费方一律引用 REFUND_VERB_RE。
# ⚠️ 「换货」刻意不入族:裸「换货」会击穿咨询闸(_CONSULT_ACTION_RE 用
# 「换货吧」窄形区分「我要换货」动作与「换货政策」咨询),仅资金否决
# VETO 单独追加。
REFUND_VERB_FAMILY = (
    "退款", "退货", "退钱", "退单", "退了", "退掉", "退还", "退一下", "退我", "给我退",
    "申请售后", "不想要了", "申请退款",
)
REFUND_VERB_RE = re.compile("|".join(REFUND_VERB_FAMILY), re.IGNORECASE)

# 常见市→省反查(地址簿省级推断,2026-09-13):「成都市高新区…」省略省前缀
# 时 saveUserAddress 必填 province 缺失触发反问 —— 高频市直接推断,查不到
# 保持诚实反问。
CITY_PROVINCE_MAP = {
    "广州市": "广东省", "深圳市": "广东省", "东莞市": "广东省", "佛山市": "广东省",
    "杭州市": "浙江省", "宁波市": "浙江省", "温州市": "浙江省", "南京市": "江苏省",
    "苏州市": "江苏省", "无锡市": "江苏省", "成都市": "四川省", "武汉市": "湖北省",
    "长沙市": "湖南省", "郑州市": "河南省", "西安市": "陕西省", "青岛市": "山东省",
    "济南市": "山东省", "厦门市": "福建省", "福州市": "福建省", "昆明市": "云南省",
    "贵阳市": "贵州省", "南昌市": "江西省", "合肥市": "安徽省", "石家庄市": "河北省",
    "太原市": "山西省", "沈阳市": "辽宁省", "大连市": "辽宁省", "哈尔滨市": "黑龙江省",
    "长春市": "吉林省", "兰州市": "甘肃省", "海口市": "海南省", "南宁市": "广西",
}


def all_intent_labels() -> list[str]:
    """注册表全量标签(与 AgentIntentType 常量值一一对应)。"""
    return list(INTENT_REGISTRY)


def prompt_category_intents() -> list[str]:
    """结构化分类器 10 类目覆盖的意图集(prompt_category 非空者)。"""
    return [spec.name for spec in INTENT_REGISTRY.values() if spec.prompt_category is not None]


def terminal_intents() -> list[str]:
    """可作为终局 intents[0] 落 planner/执行链的档位(排除中间态)。"""
    return [spec.name for spec in INTENT_REGISTRY.values() if spec.lifecycle in ("active", "latent")]
