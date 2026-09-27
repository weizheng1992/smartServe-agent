"""词族之家 parity + 册外词扫描 lint(Gen-3 域A,spec §5/§1)。

三层钉(intent_registry §1.7):
1. **byte**:迁移时各消费面的派生串与冻结旧字面逐字节相等 —— 零行为变化
   的主验收;本文件顶部 FROZEN_* 即迁移快照,改词面先改册、再有意改快照。
2. **fixture**:刻意重排/重组的面(纯字面交替 reordering 对 .search() 真值
   中性)在「词族全量 + 复合句 + 反例」语料上与旧字面真值等价。
3. **lint**:非家族之家模块里 re.compile 字面常量中,裸交替成员若等于在册
   词条即红 —— 新词面必须先入册(或显式 # intent-exception(reason) 声明)。

pytest 退出阶段挂死(Py3.14)与本文件无关:纯 AST/正则,不碰事件循环。
"""

from __future__ import annotations

import ast
import os
import re

from engine_py.badcase import intent_signals
from engine_py.graph import plan_alignment
from engine_py.graph.nodes import executor_fast_path, planner
from engine_py.skills import fallback_dispatcher, guide_skills, order_skills, promotion_skill
from engine_py.skills.cart import resolver
from engine_py.skills.cart import skill as cart_skill
from engine_py.tools_registry import mall_domain
from engine_py.triage import intent_registry as R
from engine_py.triage import intent_triage_engine, slot_extractor

# ---------------------------------------------------------------------------
# 1. byte parity:派生串 == 冻结旧字面(迁移快照,逐字节)
# ---------------------------------------------------------------------------

FROZEN_GUIDE_FALLBACK = (
    r"(?:推荐|买什么|挑一款|选一款|好看|款式|选鞋|选衣服|哪款好|跑步鞋|卫衣|夹克|热门|爆款|热销|热卖|畅销|上新|新品|卖得好|卖的好"
    r"|最便宜|便宜点|最贵|性价比|哪个好|怎么选|有什么区别|买哪种|该用什么|需要准备什么"
    r"|背什么|用哪种|什么包)"
)

BYTE_CASES: list[tuple[str, str, str]] = [
    # (说明, 新派生 pattern, 冻结旧字面)
    ("resolver._ADD_RE", resolver._ADD_RE.pattern, r"(?:加购物车|加入购物车|放进购物车|放入购物车|加购)"),
    (
        "resolver._VIEW_ONLY_RE",
        resolver._VIEW_ONLY_RE.pattern,
        r"(?:查看购物车|看下购物车|购物车总价|看购物车|购物车里|购物车有什么|多少钱|算下总价|结算|去买单|去结算)",
    ),
    (
        "resolver._CHECKOUT_RE",
        resolver._CHECKOUT_RE.pattern,
        r"(?:结算下单|去结算|提交订单|付款|[^\s]下单|^下单|(?:然后|再|接着|帮忙|帮我|给我)结算)",
    ),
    (
        "resolver._CHECKOUT_ADDR_RE",
        resolver._CHECKOUT_ADDR_RE.pattern,
        r"(?:寄到|送到|地址为|地址是|邮寄到)\s*([^,，。!！?？\n]+)",
    ),
    (
        "resolver._BEST_SELLER_RE",
        resolver._BEST_SELLER_RE.pattern,
        r"(?:销量最好|销量最佳|卖得最好|最好卖|卖得好|畅销|热卖|热销|爆款)",
    ),
    (
        "plan_alignment.CHECKOUT_TRIGGER_RE(与 resolver 同字面孪生)",
        plan_alignment.CHECKOUT_TRIGGER_RE.pattern,
        resolver._CHECKOUT_RE.pattern,
    ),
    (
        "executor._CHECKOUT_ACTION_RE",
        executor_fast_path._CHECKOUT_ACTION_RE.pattern,
        r"下单|去结算|提交订单|付款|去买单",
    ),
    (
        "executor._INPUT_ADDRESS_RE",
        executor_fast_path._INPUT_ADDRESS_RE.pattern,
        r"(?:改成|改到|送至|送去|寄到|地址为|地址是)\s*([^,，!！?？\n]+)",
    ),
    (
        "executor._STATED_ADDRESS_RE",
        executor_fast_path._STATED_ADDRESS_RE.pattern,
        r"(?:shipping to|地址是|寄到|送到|邮寄到)\s*([^,，。\n]+)",
    ),
    (
        "planner._GENERAL_ORDER_LIST_RE",
        planner._GENERAL_ORDER_LIST_RE.pattern,
        (
            r"查询.*订单|查订单|我的订单|订单列表|名下.*订单|支持退货.*订单|支持退款.*订单|可退.*订单|哪些.*订单|订单|我问订单"
            r"|看看我买了啥|买了啥|买过啥|我买的东西|历史购买记录"
        ),
    ),
    (
        "planner._METRIC_HINT_RE",
        planner._METRIC_HINT_RE.pattern,
        r"(?:gmv|销售额|销量|毛利|利润|赚钱|挣钱|赚多少|滞销|卖得好|卖的好)",
    ),
    (
        "planner._SHOPPING_HINT_RE",
        planner._SHOPPING_HINT_RE.pattern,
        r"(?:推荐|买什么|挑一款|选一款|哪款好)",
    ),
    # planner_node 函数局部面(无法按模块属性钉):经同一族投影表达式钉死
    # —— 冻结串一旦与投影漂移即红,族序/取词下标被动过就会现形。
    (
        "planner_node 局部 _CHECKOUT_HINT_RE(族投影)",
        R._grp(*R._pick(R.CHECKOUT_FAMILY, 7, 6, 5)),
        r"(?:结算|下单|买单)",
    ),
    (
        "planner_node 局部 _STATED_ADDR_RE(族投影)",
        R._grp(*R._pick(R.ADDRESS_VERB_FAMILY, 12, 5, 10, 13)) + r"\s*([^,，。]+)",
        r"(?:地址是|寄到|送到|邮寄到)\s*([^,，。]+)",
    ),
    (
        "slot.ADDRESS_KEYWORDS_RE",
        slot_extractor.ADDRESS_KEYWORDS_RE.pattern,
        r"(?:改成|改到|送至|送往|送去|寄到|寄往|改派到|改派|改送|新地址[是为:：]?|地址[是为:：])\s*([^,，!！?？\n]+)",
    ),
    (
        "slot.PROMOTION 负向豁免",
        slot_extractor.INTENT_DETECTION_RULES[0].negative_pattern.pattern,
        r"(?:下单|去结算|结算|付款|提交订单|加入购物车|放进购物车|加购)",
    ),
    (
        "slot.SHOPPING_GUIDE 负向豁免",
        slot_extractor.INTENT_DETECTION_RULES[2].negative_pattern.pattern,
        r"^(?!.*(?:都要|全要|一起买)).*(?:加购物车|加入购物车|放进购物车|加购|移出购物车|清空购物车)",
    ),
    (
        "slot.ORDER_RETURN(退款动词族注册表正则)",
        slot_extractor.INTENT_DETECTION_RULES[5].pattern.pattern,
        R.REFUND_VERB_RE.pattern,
    ),
    (
        "slot.ORDER_QUERY",
        slot_extractor.INTENT_DETECTION_RULES[6].pattern.pattern,
        r"(?:查.*物流|物流到哪|物流信息|快递单号|快递到哪|发货了吗|包裹到哪|查快递|寄到哪|送至哪|到了没|查一下.*订单|查订单状态|查询.*订单|物流查询|查下订单|查订单|我的订单|名下.*订单|全部订单|查单|运单|面单)",
    ),
    (
        "slot.ORDER_MODIFY_ADDRESS 动词串",
        slot_extractor.INTENT_DETECTION_RULES[3].pattern.pattern,
        r"(?:(?:修改|更改|变更|换|改|更新).*?(?:收货)?(?:地址|位置|地方)|(?:收货)?(?:地址|位置|地方).*?(?:修改|更改|变更|换|改|错|变)|(?:改到|改成|送至|送往|改派到|改派|改送)\s*[^?？哪里哪儿\n]+)",
    ),
    (
        "slot.ORDER_MODIFY_ADDRESS 负向豁免",
        slot_extractor.INTENT_DETECTION_RULES[3].negative_pattern.pattern,
        (
            r"(?:寄到|送至|送往|寄往|送去)\s*(?:哪里|哪儿|哪了|何处|\?|？)"
            r"|改成默认|设为默认|设置为默认|变成默认|设默认"
        ),
    ),
    (
        "slot.ORDER_QUERY 负向豁免",
        slot_extractor.INTENT_DETECTION_RULES[6].negative_pattern.pattern,
        r"(?:寄到|送至|送往|寄往|送去)\s*(?:哪里|哪儿|哪了|何处|\?|？)",
    ),
    (
        "slot.METRIC_QUERY",
        slot_extractor.INTENT_DETECTION_RULES[7].pattern.pattern,
        r"(?:销售额|销量|出货量|毛利|利润率|gmv|滞销|排行|最卖钱|最赚钱)",
    ),
    (
        "slot._GENERAL_LIST_POSITIVE_RE",
        slot_extractor._GENERAL_LIST_POSITIVE_RE.pattern,
        r"(?:我的订单|全部订单|名下.*订单|所有订单|历史订单|查订单|查询.*订单|查下订单|订单列表|看看我买了啥|我有哪些订单|历史购买记录|查下我买的东西)",
    ),
    ("guide._FALLBACK_RE", guide_skills.ShoppingGuideSkill._FALLBACK_RE.pattern, FROZEN_GUIDE_FALLBACK),
    (
        "guide._CLOTHING_ANCHOR_RE",
        guide_skills.ShoppingGuideSkill._CLOTHING_ANCHOR_RE.pattern,
        r"衣服|服装|衣着|上衣|外套|裤子|衬衫|夹克|羽绒服|T恤|裤|鞋|靴|衫|帽|袜",
    ),
    (
        "guide._ABSENCE_ANCHOR_RE",
        guide_skills.ShoppingGuideSkill._ABSENCE_ANCHOR_RE.pattern,
        r"衣服|服装|衣着|上衣|外套|裤子|衬衫|夹克|羽绒服|T恤|裤|鞋|靴|衫|帽|袜|配饰|背包|书包|装备|帐篷|睡袋|垫|包",
    ),
    (
        "order_skills.OrderRefundSkill._FALLBACK_RE",
        order_skills.OrderRefundSkill._FALLBACK_RE.pattern,
        r"(?:退款|退货|退钱|退单|不想要了|破损|瑕疵)",
    ),
    (
        "fallback_dispatcher._ORDER_QUERY_HINT",
        fallback_dispatcher._ORDER_QUERY_HINT.pattern,
        r"查|物流|到哪|状态|发货",
    ),
    (
        "engine.PROFIT_RANKING_RE",
        intent_triage_engine.PROFIT_RANKING_RE.pattern,
        r"^(?=.*(?:毛利|利润|毛利率|赚钱|挣钱|赚多少))(?=.*(?:排行|排名|top|热销|畅销|最高|前\s*\d)).+",
    ),
    (
        "engine._CART_TEXT_HINT_RE",
        intent_triage_engine._CART_TEXT_HINT_RE.pattern,
        r"(?:加购|购物车|结算|去结算|买它|加入购物车|移出购物车|清空购物车|删除第|改成\s*\d+|修改为\s*\d+)",
    ),
    (
        "engine._SHOPPING_TEXT_HINT_RE",
        intent_triage_engine._SHOPPING_TEXT_HINT_RE.pattern,
        r"(?:推荐|买什么|挑一款|选一款|好看|款式|选鞋|选衣服|哪款好)",
    ),
    (
        "engine._PROMO_DEAL_HINT_RE",
        intent_triage_engine._PROMO_DEAL_HINT_RE.pattern,
        (
            r"(?:优惠|折扣|划算|满减|券)[^。]{0,8}(?:推荐|哪款|哪个|力度)"
            r"|(?:推荐|哪款|哪个)[^。]{0,8}(?:优惠|折扣|划算|满减)"
        ),
    ),
    (
        "engine._ORDER_TOPIC_NOUN_RE",
        intent_triage_engine._ORDER_TOPIC_NOUN_RE.pattern,
        r"(订单|物流|退款|退货|换货|发货|快递|运单|包裹|购物车|收货|地址|发票|售后|签收|账单)",
    ),
    (
        "engine._ACTION_OPERATION_RE",
        intent_triage_engine._ACTION_OPERATION_RE.pattern,
        r"(申请|提交|支付|付款|下单|购买|修改|变更|取消|删除|催单|催发货|改寄|查(?:询|一下|看))",
    ),
    (
        "engine._REFORMAT_DELIVERY_RE",
        intent_triage_engine._REFORMAT_DELIVERY_RE.pattern,
        r"(显示|展示|呈现|列(?:出|个|一下)|罗列|输出|整理|排(?:成|个|一下)|给|来|做|弄|换成|改成)",
    ),
    (
        "intent_signals._CLAIM_PATTERNS[0]",
        intent_signals._CLAIM_PATTERNS[0].pattern,
        r"(已|已经).{0,6}(发起|提交|办理|完成|成功|执行|通过).{0,6}(退款|退货|审批|工单|申请)",
    ),
    (
        "intent_signals._CLAIM_PATTERNS[1]",
        intent_signals._CLAIM_PATTERNS[1].pattern,
        r"(退款|退货|审批|工单|申请).{0,4}(已|已经).{0,2}(成功|完成|通过|受理|提交)",
    ),
    (
        "intent_signals._CLAIM_PATTERNS[2]",
        intent_signals._CLAIM_PATTERNS[2].pattern,
        r"已为您.{0,12}(退款|退货|发起退款|提交)",
    ),
    (
        "promotion_skill._RECOMMEND_RE",
        promotion_skill._RECOMMEND_RE.pattern,
        (
            r"(推荐|哪款|哪个|什么商品|值得买|力度最大|优惠最大|最划算|便宜"
            r"|叠加[^。]{0,4}减|减得?最[多高狠]|立减)"
        ),
    ),
    (
        "cart_skill._CAN_HANDLE_RE(头段即 ADD_TO_CART_RE 原样拼入;余段 fixture 钉)",
        cart_skill._CAN_HANDLE_RE.pattern.split("|购物车|")[0],
        r"(?:加购物车|加入购物车|放进购物车|放入购物车|加购)",
    ),
]


def test_byte_parity_family_faces() -> None:
    """逐字节断言:派生串与冻结旧字面完全相等。"""
    mismatches = [
        f"{name}\n  new={new!r}\n  old={old!r}"
        for name, new, old in BYTE_CASES
        if new != old
    ]
    assert not mismatches, "byte parity 破面:\n" + "\n".join(mismatches)


def test_byte_parity_regex_flags_unchanged() -> None:
    """编译 flags 也是契约:IGNORECASE/DOTALL 历史形保持。"""
    assert plan_alignment.CHECKOUT_TRIGGER_RE.flags & re.IGNORECASE
    assert resolver._CHECKOUT_RE.flags & re.IGNORECASE == 0  # 本地编译不带 IGNORECASE
    assert planner._METRIC_HINT_RE.flags & re.IGNORECASE
    assert planner._GENERAL_ORDER_LIST_RE.flags & re.IGNORECASE
    assert intent_triage_engine.PROFIT_RANKING_RE.flags & (re.IGNORECASE | re.DOTALL)
    assert slot_extractor.INTENT_DETECTION_RULES[2].pattern.flags & re.IGNORECASE


# ---------------------------------------------------------------------------
# 2. fixture parity:重排/重组面在语料上与旧字面 .search() 真值等价
# ---------------------------------------------------------------------------

ADD_SENTENCES = [
    "把第2件加入购物车", "帮我加购一件卫衣", "加购", "加购物车", "放进购物车",
    "放入购物车", "加入购物车", "不要加购", "我要加购跑步鞋", "把推荐的第一款放进购物车",
]
GUIDE_SENTENCES = [
    "推荐一款跑步鞋", "买什么好", "挑一款", "选一款", "好看的衣服", "款式怎么样",
    "选鞋", "选衣服", "哪款好", "跑步鞋有什么推荐", "卫衣", "夹克", "热门商品",
    "爆款", "热销", "热卖", "畅销书", "上新了", "新品", "卖得好", "卖的好",
    "最便宜的背包", "便宜点", "最贵的是什么", "性价比", "哪个好", "怎么选",
    "有什么区别", "买哪种", "该用什么", "需要准备什么", "背什么", "用哪种", "什么包",
    "推荐X，都要了",
]
GUIDE_NEGATIVES = ["退货政策是什么", "查订单", "把第二件加入购物车", "你好"]
CHECKOUT_SENTENCES = [
    "下单", "去结算", "提交订单", "付款", "去买单", "买单", "结算", "结算下单",
    "帮我结算", "然后结算", "这件下单", "我要付款",
]
CHECKOUT_NEGATIVES = ["还没下单", "先不付款", "货到付款", "查看购物车"]
ADDRESS_SENTENCES = [
    "改成北京市朝阳区", "改到上海", "送至广州市", "送往深圳", "送去杭州",
    "寄到南京", "寄往成都", "改派到武汉", "改派", "改送", "送到长沙",
    "地址为重庆市", "地址是西安市", "邮寄到青岛", "新地址：济南市",
    "帮我改成默认地址", "我的收货地址是福州市",
]
ADDRESS_NEGATIVES = ["地址在哪里", "退货", "推荐一款鞋"]
BEST_SELLER_SENTENCES = [
    "销量最好的裤子放购物车", "销量最佳", "卖得最好", "最好卖的商品",
    "卖得好", "畅销", "热卖", "热销", "爆款", "给我看看销量最好的鞋",
]
BEST_SELLER_NEGATIVES = ["退货政策", "结算", "查订单"]
METRIC_SENTENCES = [
    "gmv多少", "销售额", "销量排行", "毛利", "利润", "赚钱吗", "挣钱", "赚多少",
    "滞销品", "卖得好吗", "卖的好", "毛利率", "利润率", "出货量", "最卖钱", "最赚钱",
    "最赚钱的商品毛利排行", "销量排行前5",
]
METRIC_NEGATIVES = ["推荐卫衣", "退货政策", "加购一件"]
ORDER_LIST_SENTENCES = [
    "我的订单", "名下订单", "查订单", "查询我的订单", "订单列表",
    "看看我买了啥", "历史购买记录", "全部订单", "历史订单", "查下订单",
    "我有哪些订单", "支持退货的订单", "哪些订单可以退", "买了啥", "我买的东西",
]
ORDER_LIST_NEGATIVES = ["推荐一款鞋", "退了这单", "改成3件"]

FIXTURE_CASES: list[tuple[str, str, re.Pattern[str], list[str]]] = [
    # (说明, 冻结旧字面, 新编译 RE, 语料(真值必须一致;反例都应不命中))
    (
        "executor._ADD_ACTION_RE(词序重排)",
        r"加入购物车|放进购物车|放入购物车|加购物车|加购",
        executor_fast_path._ADD_ACTION_RE,
        ADD_SENTENCES + CHECKOUT_NEGATIVES,
    ),
    (
        "resolver._VIEW_EXCLUDE_RE(族头化)",
        r"(?:加购物车|加入购物车|放进购物车|放入购物车|加购|买第|要第|改成|修改|删除|移除|删掉)",
        resolver._VIEW_EXCLUDE_RE,
        ADD_SENTENCES + ["买第2件", "要第3件", "改成3", "修改数量", "删除第1件", "移除", "删掉吧"]
        + ADDRESS_NEGATIVES,
    ),
    (
        "resolver._SEARCH_INTENT_RE(榜词族后置)",
        r"(?:推荐|询|问|看看|看看有|找|挑|评价|口碑|热销|爆款|有什么|销量最好|销量最佳|卖得最好|最好卖|卖得好|畅销|热卖)",
        resolver._SEARCH_INTENT_RE,
        ["推荐一款鞋", "问问客服", "看看有货吗", "找一下", "挑一件", "评价怎么样", "口碑好",
         "有什么", "热销", "爆款", "销量最好", "销量最佳", "卖得最好", "最好卖", "卖得好",
         "畅销", "热卖"]
        + ["结算下单", "改地址到北京"],
    ),
    (
        "cart_skill._CAN_HANDLE_RE(族头化+旧序整理)",
        (
            r"(?:加购物车|加入购物车|放进购物车|加购|购物车|结算|买第|件加入|款加入|放入购物车|"
            r"第[0-9一二三四五六七八九十两几][件款个双]|要第|删除|移除|删掉|清空|改成\s*\d+|修改为\s*\d+|数量设为\s*\d+)"
        ),
        cart_skill._CAN_HANDLE_RE,
        ADD_SENTENCES + CHECKOUT_SENTENCES[:1] + ["买第2件", "件加入", "款加入",
                                                  "第2件", "第二件", "要第2件", "删除", "移除",
                                                  "删掉", "清空购物车", "改成3", "修改为4", "数量设为2"]
        + ["退货政策", "查订单"],
    ),
    (
        "slot.CART_MANAGE(族头化+放入购物车归位+买第去重)",
        r"(?:加购物车|加入购物车|放进购物车|加购|购物车|结算|去结算|去买单|下单|查看购物车|清空购物车|购物车里|移出购物车|删除.*?购物车|从购物车.*?删除|买第|件加入|款加入|放入购物车|加第|买第|要第|改成\s*\d+|修改为\s*\d+|数量设为\s*\d+|第[一二三四五12345两几][件款个双].*?(?:购物车|买|要|加|删|改|去)|(?:删除|移除|删掉).*?第[一二三四五12345两几][件款个双])|^(?:把)?第\s*[一二三四五12345两几]\s*[件款个双]|都要|全要|一起买",
        slot_extractor.INTENT_DETECTION_RULES[1].pattern,
        ADD_SENTENCES + CHECKOUT_SENTENCES
        + ["查看购物车", "清空购物车", "购物车里有什么", "移出购物车", "删除购物车里的第2件",
           "从购物车删除第3件", "买第2件", "件加入", "款加入", "加第3件", "要第2件",
           "改成3", "修改为4", "数量设为2", "第2件我要删", "删除第2件", "把第2件",
           "都要", "全要", "一起买"]
        + ["退货政策", "查订单"],
    ),
    (
        "slot.SHOPPING_GUIDE(增补词留位+族投影)",
        r"(?:推荐|买什么|有什么好看|有没有|挑一款|选一款|适合.*的|找一找|推荐一款|介绍一下|哪款好|选鞋|选衣服|看商品|导购|什么牌子|款式|推荐几件|推荐几款|热门|爆款|热销|热卖|畅销|上新|新品|卖得好|卖的好)|最便宜|便宜点|最贵|性价比|哪个好|怎么选|有什么区别|买哪种|该用什么|需要准备什么|背什么|用哪种|什么包",
        slot_extractor.INTENT_DETECTION_RULES[2].pattern,
        GUIDE_SENTENCES
        + ["有什么好看", "有没有推荐", "适合夏天的", "找一找", "推荐一款", "介绍一下",
           "看商品", "导购", "什么牌子", "推荐几件", "推荐几款"]
        + GUIDE_NEGATIVES,
    ),
    (
        "engine.PROFIT_RANKING_RE(利润/榜词族投影)",
        r"^(?=.*(?:毛利|利润|毛利率|赚钱|挣钱|赚多少))(?=.*(?:排行|排名|top|热销|畅销|最高|前\s*\d)).+",
        intent_triage_engine.PROFIT_RANKING_RE,
        ["利润最高的商品排行", "毛利排名", "毛利率top5", "赚钱排行", "挣钱最多排名",
         "赚多少排一下", "最赚钱的商品热销榜", "畅销商品里毛利最高的", "利润排行前3"]
        + ["利润多少", "销量排行", "退货政策"],
    ),
]


def test_fixture_parity_reordered_faces() -> None:
    """重排面:旧字面 vs 新派生在语料上 .search() 真值逐句相等。"""
    mismatches: list[str] = []
    for name, frozen, new, corpus in FIXTURE_CASES:
        old_re = re.compile(frozen, re.IGNORECASE)
        for text in corpus:
            if bool(old_re.search(text)) != bool(new.search(text)):
                mismatches.append(f"{name}: {text!r} old={bool(old_re.search(text))} new={bool(new.search(text))}")
    assert not mismatches, "fixture parity 破面:\n" + "\n".join(mismatches)


def test_fixture_parity_add_action_strip_sub() -> None:
    """剥词面是 re.sub 语义:剥词结果必须与旧串逐字一致(短词殿后约束)。"""
    frozen = (
        r"加入购物车|放进购物车|放入购物车|加购物车|加购|购物车|帮我|给我|麻烦|我想|想要|"
        r"放到|放进|放入|装进|扔进|丢进|"
        r"下单|结账|来一[件个个只]|一[件个个只]|\d+\s*[件个个只]|加入|谢谢|最后|这个|那个|一下|买|要|加|吧|呗|哦|哈|把|"
        r"第\s*[0-9一二三四五六七八九十百千]*"
    )
    old_re = re.compile(frozen)
    samples = [
        "把第2件加入购物车", "帮我把加购一下", "我想加购卫衣", "放进购物车",
        "放入购物车", "加购跑步鞋", "把那个加入购物车", "给我加购最后一件",
        "改成M码", "曜石黑", "买单",
    ]
    diff = [
        f"{s!r}: old={old_re.sub(' ', s)!r} new={resolver._ADD_ACTION_STRIP_RE.sub(' ', s)!r}"
        for s in samples
        if old_re.sub(" ", s) != resolver._ADD_ACTION_STRIP_RE.sub(" ", s)
    ]
    assert not diff, "剥词面 sub 结果漂移:\n" + "\n".join(diff)


def test_ranking_metric_text_mapping_unchanged() -> None:
    """指标词族投影后的排行映射行为不变(利润榜变销量榜是历史事故)。"""
    from_text = planner._ranking_metric_from_text
    assert from_text("毛利率最高的商品") == "margin_rate"
    assert from_text("毛利排行") == "gross_profit"
    assert from_text("最赚钱的商品") == "gross_profit"
    assert from_text("挣钱最多的") == "gross_profit"
    assert from_text("gmv最高") == "gmv"
    assert from_text("销售额排行") == "gmv"
    assert from_text("滞销品") == "stock_risk"
    assert from_text("销量排行") == "volume"


# ---------------------------------------------------------------------------
# 3. 在册完备性:家族词条被派生面逐词匹配
# ---------------------------------------------------------------------------

def test_inventory_family_words_matched_by_derived_faces() -> None:
    """加词只许改册:派生面必须自动吞下家族全量词条。"""
    for word in R.ADD_TO_CART_FAMILY:
        assert R.ADD_TO_CART_RE.search(word), word
        assert cart_skill._CAN_HANDLE_RE.search(word), word
    for word in R.BEST_SELLER_FAMILY:
        assert R.BEST_SELLER_HINT_RE.search(word), word
        assert resolver._BEST_SELLER_RE.search(word), word
        assert planner._BEST_SELLER_RE.search(word), word
    for word in R.CLOTHING_ANCHOR_FAMILY + R.ABSENCE_EXTRA_FAMILY:
        assert guide_skills.ShoppingGuideSkill._ABSENCE_ANCHOR_RE.search(word), word
    for word in R.CLOTHING_ANCHOR_FAMILY:
        assert guide_skills.ShoppingGuideSkill._CLOTHING_ANCHOR_RE.search(word), word


def test_inventory_guide_core_covered_by_consumer_faces() -> None:
    """导购核心族:guide 兜底覆盖全族;slot 建议面覆盖其历史投影。

    slot SHOPPING_GUIDE 的历史字面就不含 4/9/10/11(好看只以「有什么好看」
    形状在场;跑步鞋/卫衣/夹克是商品锚词,guide 兜底面专管)—— 库存断言
    按 slot 真实投影下标记账,不虚构覆盖面。"""
    fallback = guide_skills.ShoppingGuideSkill._FALLBACK_RE
    slot_rule = slot_extractor.INTENT_DETECTION_RULES[2].pattern
    for idx, word in enumerate(R.GUIDE_CORE_FAMILY):
        assert fallback.search(word), f"guide._FALLBACK_RE 漏 {word}"
        if idx in {4, 9, 10, 11}:
            continue
        assert slot_rule.search(word), f"slot SHOPPING_GUIDE 漏 {word}"


# ---------------------------------------------------------------------------
# 4. 册外词扫描 lint
# ---------------------------------------------------------------------------

SRC_ROOT = os.path.join(os.path.dirname(__file__), "..", "src", "engine_py")

# 家族之家分册:词面可以住在这里(册子本体 / greeting·转人工样板 / cart 解析器)
HOME_MODULES = {
    "triage/intent_registry.py",
    "triage/rule_matchers.py",
    "skills/cart/resolver.py",
}
# 域外声明:analytics/ 是对照域(spec §0 不入裁决);semantic_routes 是
# 06 号票自治的影子资产,两者均不属客服意图词表治理面。
OUT_OF_SCOPE = ("analytics/", "triage/semantic_routes.py")
# 去重豁免词表是「命中即算操作形」的宽匹配词表,不是派生家族 —— 不参与 lint
# (单字 买/查/款/件 会把一切面误伤;该表本体已住册,消费方引 OPERATIONAL_ACTION_RE)
LINT_EXEMPT_FAMILIES = {"OPERATIONAL_ACTION_FAMILY"}

LINT_WORDS: set[str] = {
    word
    for name, family in vars(R).items()
    if name.endswith("_FAMILY") and isinstance(family, tuple) and name not in LINT_EXEMPT_FAMILIES
    for word in family
}

_MARKER = "intent-exception("


def _top_level_members(pattern: str) -> list[str]:
    """括号扁平化后按 '|' 切分:组包装的手抄词同样现形。

    去掉所有 ( ) 与非捕获组前缀 ?: —— 手抄病灶的典型形恰是
    ``(?:加购|购物车|...)`` 整组交替,只看顶层会把组内词条放走。
    字符类/量词等元字符段剥括号后必含额外字符,不会与纯词条撞形;
    反向风险(误伤)只存在于「把词条当整个交替成员包在组里」——
    那正是要抓的手抄。"""
    flat = pattern.replace("(", "").replace(")", "").replace("?:", "")
    return [seg for seg in flat.split("|") if seg]


def _pattern_constants(node: ast.expr):
    """收集 re.compile 参数里的字面常量段:字符串常量与 '+ ' 拼接链。

    刻意不进入 Call/Attribute/Subscript —— 经 _alt/_grp/_pick 或家族下标
    引用拼出的段天然在册,无需(也不应)按字面扫描。"""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        yield node.value
    elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        yield from _pattern_constants(node.left)
        yield from _pattern_constants(node.right)


def _is_re_api(call: ast.Call) -> bool:
    return (
        isinstance(call.func, ast.Attribute)
        and isinstance(call.func.value, ast.Name)
        and call.func.value.id == "re"
        and call.func.attr in {"compile", "search", "match", "fullmatch", "sub", "finditer", "split"}
    )


def _scan_file(rel: str, source: str) -> list[tuple[int, str]]:
    lines = source.splitlines()
    flagged: list[tuple[int, str]] = []
    for node in ast.walk(ast.parse(source)):
        if not (isinstance(node, ast.Call) and _is_re_api(node)):
            continue
        marker_window = "\n".join(lines[max(0, node.lineno - 3): node.lineno])
        if _MARKER in marker_window:
            continue
        if not node.args:
            continue
        for const in _pattern_constants(node.args[0]):
            for member in _top_level_members(const):
                if member in LINT_WORDS:
                    flagged.append((node.lineno, member))
    return flagged


def test_no_registered_word_used_bare_outside_home() -> None:
    """册外词扫描:非家族之家模块不得手抄在册词条为裸交替成员。"""
    violations: list[str] = []
    root = os.path.abspath(SRC_ROOT)
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d != "__pycache__"]
        for fn in filenames:
            if not fn.endswith(".py"):
                continue
            path = os.path.join(dirpath, fn)
            rel = os.path.relpath(path, root).replace(os.sep, "/")
            if any(rel.startswith(prefix) or rel == prefix.rstrip("/") for prefix in OUT_OF_SCOPE):
                continue
            if rel in HOME_MODULES:
                continue
            with open(path, encoding="utf-8") as fh:
                source = fh.read()
            for lineno, word in _scan_file(rel, source):
                violations.append(f"{rel}:{lineno} 裸交替成员「{word}」在册 —— 先入册再引用,或加 # intent-exception(reason)")
    assert not violations, "册外手抄词条:\n" + "\n".join(violations)


def test_lint_catches_new_handcopy() -> None:
    """lint 自检:构造一个册外手抄面必须被抓获(防 lint 失效成摆设)。"""
    assert _scan_file("fake.py", "X = re.compile(r'(?:推荐|买什么)')") == [(1, "推荐"), (1, "买什么")]
    assert _scan_file("fake.py", "X = re.compile(r'(?:加购|购物车)')") == [(1, "加购")]
    # 家族引用拼接与豁免标记不算违规
    assert _scan_file("fake.py", "X = re.compile(R.ADD_TO_CART_RE.pattern + '|买第')") == []
    assert _scan_file("fake.py", "# intent-exception(test)\nX = re.compile(r'(?:加购)')") == []


def test_lint_mall_domain_price_face_is_declared() -> None:
    """mall_domain 价格极值面:声明留本地(改写管道 + 反向 import 成环)。"""
    assert mall_domain.MallDomainService._PRICE_SUPERLATIVE_RE.pattern == (
        r"(?:最便宜|最贵|性价比高|性价比|便宜点|便宜)"
    )
