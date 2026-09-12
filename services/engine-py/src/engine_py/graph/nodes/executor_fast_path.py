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
    if any(kw in desc_lower for kw in ("cart", "加购物车", "加入购物车", "加购", "购物车", "结算", "改数量", "删商品")):
        return {"toolName": "skill_cart_manage", "args": {"userInput": user_input}}

    # 子串匹配(非正则):裸 "hot" 会误中 what/shot,故用完整词 popular/trending/best seller。
    if any(
        kw in desc_lower
        for kw in ("shopping_guide", "recommend", "推荐", "导购", "选品", "popular", "trending", "best seller", "bestseller")
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
