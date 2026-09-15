"""极速直达工具匹配 — 镜像 executorFastPath.ts(正则逐条移植)。"""

from __future__ import annotations

import re

from .utils import extract_order_id

_PURE_COMMUNICATION_RE = re.compile(
    r"^(present|ask|inform|explain|tell|show|display|向用户|询问|告知|说明|解释)", re.IGNORECASE
)
_COMMUNICATION_ACTION_RE = re.compile(r"(call|invoke|execute|调用|执行)", re.IGNORECASE)
_DESC_ADDRESS_RE = re.compile(r"with new address\s*([^\n]+)", re.IGNORECASE)
_INPUT_ADDRESS_RE = re.compile(r"(?:改成|改到|送至|送去|寄到|地址为|地址是)\s*([^,，!！?？\n]+)", re.IGNORECASE)
# 未发货语义(ADR-0001 Q2):快路径与 LLM 路径同语义,严禁快路径吞过滤
_UNSHIPPED_RE = re.compile(r"未发货|还没发货|尚未发货")
# saveUserAddress 六必需字段(planner 快轨子任务描述以「字段 值、」形态携带)
_SAVE_ADDR_FIELDS = ("receiverName", "receiverPhone", "province", "city", "district", "detailAddress")
# 排行指标提取(planner 快轨子任务描述形态:「rankingMetric gmv」)
_RANKING_METRIC_RE = re.compile(r"rankingMetric\s+([a-z_]+)", re.IGNORECASE)
# 顾客口述地址提取(checkoutCart 步骤描述/用户输入形态)
_STATED_ADDRESS_RE = re.compile(r"(?:shipping to|地址是|寄到|送到|邮寄到)\s*([^,，。\n]+)", re.IGNORECASE)
# 意图指向本轮推荐候选的词形(2026-09-15 S6 跨品类错单):「就要第一个/买第一件」
# 指代本轮推荐;无本轮候选时严禁拿购物车遗留品结算
_INTENT_TARGET_RE = re.compile(r"(?:就要|就买|买|要|拿下|选)[^,，。\n]{0,4}第[一二三四五六1-6]|第[一二三四五六1-6][款个件][^,，。\n]{0,6}(?:直接|马上)?下单")
# 明确指向购物车本身的措辞(放行)
_CART_ITSELF_RE = re.compile(r"(?:购物车里的?|车里的?|购物车的?)")


def _save_address_args(description: str) -> dict | None:
    """从快轨子任务描述解析 saveUserAddress 六字段;缺任一即返回 None
    (宁走诚实失败,严禁拿残参落库)。"""
    args: dict = {}
    for field in _SAVE_ADDR_FIELDS:
        m = re.search(rf"{field}\s*([^\s、,，;；]+)", description)
        if m:
            args[field] = m.group(1)
    if all(args.get(field) for field in _SAVE_ADDR_FIELDS):
        return args
    return None


def _has_current_candidates(desc_lower: str) -> bool:
    """步骤描述是否携带本轮推荐候选形(guide 步骤在前/描述含候选语义)。"""
    return "shoppingskill" in desc_lower or "shoppingskillskill" in desc_lower or "recommend" in desc_lower


def _intent_target_missing(user_input: str, has_candidates: bool) -> bool:
    """纯谓词(测试缝):意图指向本轮推荐候选 × 本轮无候选 → 指代悬空。
    明确指向购物车本身的措辞(「购物车里的东西结算」)不拦。"""
    if not user_input:
        return False
    if _CART_ITSELF_RE.search(user_input):
        return False
    return bool(_INTENT_TARGET_RE.search(user_input)) and not has_candidates


def try_match_executor_fast_path(
    description: str, user_input: str, allowed_tools: list[str], short_memory: list[dict] | None = None
) -> dict | None:
    desc_lower = description.lower()
    input_lower = (user_input or "").lower()
    extracted_order_id = extract_order_id(description, user_input, short_memory)

    # 🛡️ 纯沟通/展示/询问步骤不作为物理工具执行
    if _PURE_COMMUNICATION_RE.search(desc_lower) and not _COMMUNICATION_ACTION_RE.search(desc_lower):
        return None

    is_explicit_refund_action = (
        "processrefund" in desc_lower
        or "执行退款" in desc_lower
        or "处理退款" in desc_lower
        or "申请退款" in desc_lower
        or ("refund" in desc_lower and any(kw in desc_lower for kw in ("call", "execute", "initiate")))
    ) and "processRefund" in allowed_tools and extracted_order_id

    if is_explicit_refund_action:
        return {
            "toolName": "processRefund",
            "args": {"orderId": extracted_order_id, "reason": "Customer requested refund via smartServe"},
        }

    if (
        any(
            kw in desc_lower
            for kw in ("status", "carrier", "track", "getorderstatus", "物流", "进度", "发货")
        )
        and "getOrderStatus" in allowed_tools
        and extracted_order_id
    ):
        return {"toolName": "getOrderStatus", "args": {"orderId": extracted_order_id}}

    # 🏠 地址簿确定性执行(多意图一期,2026-09-12):saveUserAddress 是写动作,
    # 严禁空转给通用 LLM 步骤执行 —— 实弹 A11:未调工具即宣称「已成功保存」
    # (user_addresses 表 0 行)。六字段不全时不命中,宁走诚实失败不瞎猜。
    if "saveuseraddress" in desc_lower and "saveUserAddress" in allowed_tools:
        args = _save_address_args(description)
        if args is not None:
            return {"toolName": "saveUserAddress", "args": args}

    if (
        any(kw in desc_lower for kw in ("getuseraddresses", "地址簿列表", "收货地址列表"))
        and "getUserAddresses" in allowed_tools
    ):
        return {"toolName": "getUserAddresses", "args": {}}

    # 📊 真实排行确定性映射(遗留二期,2026-09-13):仅认 planner 快轨固定句式
    # (描述内嵌 rankingMetric N);深规划产出的自由描述可能带 category/limit
    # 参数,直配会吞参 —— 返回 None 落 LLM 兜底(rule 9 从历史抽参)。
    if (
        "queryproductranking" in desc_lower
        and "rankingmetric" in desc_lower
        and "queryProductRanking" in allowed_tools
    ):
        metric_match = _RANKING_METRIC_RE.search(description)
        return {
            "toolName": "queryProductRanking",
            "args": {"rankingMetric": metric_match.group(1) if metric_match else "volume"},
        }

    # 🛒 真·聊天下单确定性映射(遗留二期):checkoutCart 子任务直配工具;描述含
    # "cart" 会命中下方购物车技能分支,必须先行。地址保真(2026-09-13 用户
    # 实报):深规划把顾客给的地址写进步骤描述,快路径提取为显式地址 ——
    # 严禁静默回落地址簿默认地址。
    if "setdefaultaddress" in desc_lower and "setDefaultAddress" in allowed_tools:
        return {"toolName": "setDefaultAddress", "args": {}}
    if "checkoutcart" in desc_lower and "checkoutCart" in allowed_tools:
        # S6 守卫(2026-09-15):意图指向本轮推荐候选(第N个下单)但本轮无候选
        # —— 检索轮追问形输入未产出推荐,序数悬空,拿购物车遗留品结算是
        # 跨品类错单(实弹:推荐帐篷→就要第一个,结了老爹鞋+渔夫帽)。拒配
        # 工具,让步骤落入 LLM 兜底向用户确认目标商品。
        if _intent_target_missing(user_input or "", has_candidates=_has_current_candidates(desc_lower)):
            return None
        stated = _STATED_ADDRESS_RE.search(description) or _STATED_ADDRESS_RE.search(user_input or "")
        return {
            "toolName": "checkoutCart",
            "args": {"shippingAddress": stated.group(1).strip()} if stated else {},
        }

    if (
        any(
            kw in desc_lower
            for kw in ("changeshippingaddress", "modify_shipping_address", "修改地址", "改地址", "收货地址")
        )
        and "changeShippingAddress" in allowed_tools
        and extracted_order_id
    ):
        new_address = ""
        desc_match = _DESC_ADDRESS_RE.search(description)
        if desc_match and desc_match.group(1):
            new_address = desc_match.group(1).strip()
        else:
            addr_match = _INPUT_ADDRESS_RE.search(user_input or "")
            if addr_match and addr_match.group(1):
                new_address = addr_match.group(1).strip()
        return {
            "toolName": "changeShippingAddress",
            "args": {"orderId": extracted_order_id, "newAddress": new_address or "客户指定新地址"},
        }

    # 2026-09-07:返回 SkillsRegistry 真实技能 id(带 skill_ 前缀)。TS 基线此处
    # 返回伪名 cart_manage/shopping_guide —— 既不在 allowed_tools 白名单、也查不到
    # 注册表技能,分发门槛整段跳过,商品/购物车子任务空转至道歉降级(继承缺陷)。
    # 显式技能名优先(2026-09-13 一句话接力):复合计划子任务描述嵌入对方
    # 关键词(「Execute ShoppingGuideSkill … 加入购物车」),关键词匹配曾互相
    # 劫持 —— 描述点名技能 id 时直配,关键词只兜底无名描述。
    if "cartskill" in desc_lower:
        return {"toolName": "skill_cart_manage", "args": {"userInput": user_input}}
    if "shoppingguideskill" in desc_lower or "shopping_guide" in desc_lower:
        return {"toolName": "skill_shopping_guide", "args": {"userInput": user_input}}
    if any(kw in desc_lower for kw in ("cart", "加购物车", "加入购物车", "加购", "购物车", "结算", "改数量", "删商品")):
        return {"toolName": "skill_cart_manage", "args": {"userInput": user_input}}

    # 子串匹配(非正则):裸 "hot" 会误中 what/shot,故用完整词 popular/trending/best seller。
    if any(
        kw in desc_lower
        for kw in ("recommend", "推荐", "导购", "选品", "popular", "trending", "best seller", "bestseller")
    ):
        return {"toolName": "skill_shopping_guide", "args": {"userInput": user_input}}

    if (
        any(kw in desc_lower for kw in ("listuserorders", "list orders", "fetch recent orders", "全部订单", "历史订单", "名下订单"))
        and "listUserOrders" in allowed_tools
    ):
        unshipped = bool(_UNSHIPPED_RE.search(description) or _UNSHIPPED_RE.search(user_input or ""))
        return {"toolName": "listUserOrders", "args": {"shippingStatus": "UNSHIPPED"} if unshipped else {}}

    if (
        any(kw in desc_lower for kw in ("screenshot", "takescreenshot", "截图", "快照"))
        and "takeScreenshot" in allowed_tools
    ):
        return {"toolName": "takeScreenshot", "args": {"url": "http://localhost:3000"}}

    if (
        any(kw in desc_lower for kw in ("preference", "recorduserpreference", "偏好", "尺码", "鞋码"))
        and "recordUserPreference" in allowed_tools
    ):
        pref_type = "other"
        if any(kw in input_lower for kw in ("码", "尺码", "size")):
            pref_type = "size"
        elif any(kw in input_lower for kw in ("色", "颜色", "color")):
            pref_type = "color"
        elif any(kw in input_lower for kw in ("牌", "品牌", "brand")):
            pref_type = "brand"
        return {
            "toolName": "recordUserPreference",
            "args": {"preferenceType": pref_type, "preferenceValue": user_input},
        }

    return None
