"""购物车管理技能 — 镜像 cartManageSkill.ts(查看/删除/改量/指代消解加购,431 LOC)。"""

from __future__ import annotations

import re

from ..tools_registry.mall_domain import MallDomainService
from .base_skill import BaseSkill

_ORDINAL_RE = re.compile(r"(?:把)?第\s*(\d+|[一二三四五六七八九十两])\s*[件款个双]?")
# 数字串经 _ordinal_to_index 换算(支持「第10件」多位),汉字查表
_INDEX_MAP = {"一": 0, "二": 1, "两": 1, "三": 2, "四": 3, "五": 4, "六": 5, "七": 6, "八": 7, "九": 8, "十": 9}
# 词表外大序数兜底(第十一/第100…):只在「诚实反问」时作存在性判定用
_ORD_ANY_RE = re.compile(r"第\s*[0-9一二三四五六七八九十百千]+")


def _ordinal_to_index(token: str) -> int:
    """序数字符 → 0 基下标:数字串按位值换算(第10件=9),汉字查表。"""
    if token.isdigit():
        return int(token) - 1
    return _INDEX_MAP.get(token, 0)

_VIEW_ONLY_RE = re.compile(
    r"(?:查看购物车|看下购物车|购物车总价|看购物车|购物车里|购物车有什么|多少钱|算下总价|结算|去买单|去结算)"
)
_VIEW_EXCLUDE_RE = re.compile(r"(?:加购物车|加入购物车|放进购物车|放入购物车|加购|买第|要第|改成|修改|删除|移除|删掉)")
_DELETE_RE = re.compile(r"(?:删除|移除|删掉|去掉|不要了|清空)")
_ADD_RE = re.compile(r"(?:加购物车|加入购物车|放进购物车|放入购物车|加购)")
# 真·聊天下单触发(遗留二期,2026-09-13):拦截在查看分支前;裸「结算」保持
# 查看摘要旧契约,「下单/去结算/提交订单/付款」才开真实订单。
_CHECKOUT_RE = re.compile(r"(?:结算下单|去结算|提交订单|付款|[^\s]下单|^下单|(?:然后|再|接着|帮忙|帮我|给我)结算)")
# 否定/非结算形守卫:「我还没下单」「先不付款」「货到付款」严禁开出真单
_CHECKOUT_NEG_RE = re.compile(r"(?:还没|没有|不用|不要|先不|暂不|别|[^\s]个下单|货到付款|未付款)")
# 检索/推荐诉求(2026-09-13):在场时禁用加购的历史回溯候选(幻影守卫)
_SEARCH_INTENT_RE = re.compile(r"(?:推荐|询|问|看看|看看有|找|挑|评价|口碑|热销|爆款|有什么)")
_CHECKOUT_ADDR_RE = re.compile(r"(?:寄到|送到|地址为|地址是|邮寄到)\s*([^,，。!！?？\n]+)")
# 订单→购物车桥接:「订单(里)的 X 加入购物车」—— X 为历史购买商品关键词
_BRIDGE_KEYWORD_RE = re.compile(
    r"(?:订单|买过)[^。！？]{0,10}里?[面中]?的([^,，。！？]+?)(?:加入|加购|放进|放入|扔进|来一|买一)"
)
_CLEAR_RE = re.compile(r"(?:清空|全部删除|全删)")
_QTY_UPDATE_RE = re.compile(r"(?:改成|修改为|数量设为|变成|改为|调整为|增加到|减少到)\s*(\d+)\s*件?")
_VAGUE_RE = re.compile(r"(?:第几|哪件|哪款|哪一个)")
_ORDINAL_FULL_RE = re.compile(
    r"(?:把)?第\s*(\d+|[一二三四五六七八九十两])\s*[件款个双]"
    r"|买第\s*(\d+|[一二三四五六七八九十两])"
    r"|第\s*(\d+|[一二三四五六七八九十两])\s*款"
)
_ADD_ALL_RE = re.compile(r"(?:全部|所有|都)")
_NAME_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z]{2,}")
# 品牌与通用款型词不计分:点名"A款"不得因共享 Nike/Run 等泛词误中"B款"
_GENERIC_NAME_TOKENS = {"nike", "run", "air"}


def _match_cart_item_by_name(user_input: str, items: list[dict]) -> dict | None:
    """按商品名定位购物车条目:标题整串包含优先,否则拉丁特征词得分匹配。

    - 仅取拉丁词(≥3字母)且忽略大小写;数字串不参与:改量/序数词指令中的
      数字("数量改成3"/"第2件")会与标题款号("Invincible Run 3")撞分致歧义。
    - 得分 <1 返回 None(如纯中文泛称"跑鞋"无法区分多款),交回原兜底链。
    """
    for item in items:
        title = str(item.get("title") or item.get("name") or "")
        if title and title in user_input:
            return item
    input_tokens = {t.lower() for t in _NAME_TOKEN_RE.findall(user_input)}
    best_item: dict | None = None
    best_score = 0
    for item in items:
        title = str(item.get("title") or item.get("name") or "")
        title_tokens = {t.lower() for t in _NAME_TOKEN_RE.findall(title)}
        score = len((title_tokens & input_tokens) - _GENERIC_NAME_TOKENS)
        if score > best_score:
            best_item, best_score = item, score
    return best_item if best_score >= 1 else None
_QTY_BUY_RE = re.compile(r"(?:数量|买|要|加|购)\s*(\d+)\s*件?")
_HISTORY_ITEM_RE = re.compile(r"(\d+)\.\s*【([^】]+)】\s*¥?(\d+(?:\.\d+)?)")


class CartManageSkill(BaseSkill):
    metadata = {
        "id": "skill_cart_manage",
        "name": "交易与购物车管理 Agent SOP",
        "description": "参数核验、加购、商品规格变更、购物车结算与优惠汇总",
        "category": "in_sale",
        "triggerIntents": ["cart_manage", "cart_add", "cart_update"],
        "requiredTools": ["addToCart", "getCartSummary", "updateCartItem"],
        "version": "1.0.0",
    }

    _CAN_HANDLE_RE = re.compile(
        r"(?:加购物车|加入购物车|放进购物车|加购|购物车|结算|买第|件加入|款加入|放入购物车|"
        r"第[0-9一二三四五六七八九十两几][件款个双]|要第|删除|移除|删掉|清空|改成\s*\d+|修改为\s*\d+|数量设为\s*\d+)"
    )

    @staticmethod
    def _add_rejected_response(
        add_res: dict, guide_context: dict | None, existing_cart: dict | None
    ) -> dict | None:
        """入车被服务层拒绝(缺价等)时如实回传,不播报成功卡 —— skill 层
        success 语义是「技能处理完成」:业务失败经 output 文案如实送达用户
        (2026-09-12 real-data-only/01:宁可追问,不可编造)。非拒绝返回 None。"""
        if add_res.get("success"):
            return None
        return {
            "success": True,
            "skillId": CartManageSkill.metadata["id"],
            "output": add_res.get("message") or "该商品暂时无法加入购物车，请稍后再试。",
            "nextAction": "finish",
            "extra": {"guideContext": guide_context, "cartContext": existing_cart},
        }

    def can_handle(self, context: dict) -> bool:
        if super().can_handle(context):
            return True
        user_input = (context.get("input") or "").lower()
        return bool(self._CAN_HANDLE_RE.search(user_input))

    async def execute(self, context: dict) -> dict:
        user_input = (context.get("input") or "").strip()
        extra = context.get("extra") or {}
        guide_context = extra.get("guideContext") or {}
        existing_cart = extra.get("cartContext") or {}

        # 0. 结算下单(遗留二期,2026-09-13):真·聊天下单,拦截在查看分支之前
        # —— 裸「结算」仍是查看摘要(旧契约),「下单/去结算/提交订单/付款」才开单。
        # 复合守卫:同句含删除/加购动作时让位(「删掉背包然后结算下单」先删后说,
        # 严禁吞掉删除半带着不要的商品开出真单 —— rule 7 复合偿付纪律)
        if (
            _CHECKOUT_RE.search(user_input)
            and not _ADD_RE.search(user_input)
            and not _DELETE_RE.search(user_input)
            and not _CHECKOUT_NEG_RE.search(user_input)
        ):
            # 显式地址跟随(「寄到/送到/地址为…」),否则服务层取地址簿默认
            addr_match = _CHECKOUT_ADDR_RE.search(user_input)
            checkout_res = await MallDomainService.checkout_user_cart(
                {
                    "userId": context.get("userId"),
                    "threadId": context.get("threadId"),
                    "shippingAddress": addr_match.group(1).strip() if addr_match else None,
                }
            )
            if checkout_res.get("success"):
                lines = "\n".join(f"• {line}" for line in checkout_res.get("items") or [])
                return {
                    "success": True,
                    "skillId": self.metadata["id"],
                    "output": (
                        f"🎉 下单成功！订单号 [{checkout_res.get('orderId')}]。\n\n"
                        f"{lines}\n\n"
                        f"💰 实付金额: ¥{checkout_res.get('totalAmount')}\n"
                        f"📦 收货地址: {checkout_res.get('shippingAddress')}\n\n"
                        "可在「我的订单」中随时查看物流状态。"
                    ),
                    "nextAction": "finish",
                    "extra": {"cartContext": {"items": [], "totalAmount": 0}, "guideContext": guide_context},
                }
            return {
                "success": True,
                "skillId": self.metadata["id"],
                "output": checkout_res.get("message") or "结算未完成，请稍后再试。",
                "nextAction": "finish",
                "extra": {"cartContext": existing_cart, "guideContext": guide_context},
            }

        # 0.5 订单→购物车桥接(遗留二期):「订单里的 X 加入购物车」—— 商户真单
        # 明细按关键词回查,当前在售 SKU 真实入车;找不到/多命中/已下架均如实回复。
        bridge_match = _BRIDGE_KEYWORD_RE.search(user_input)
        if bridge_match and _ADD_RE.search(user_input):
            bridge_res = await MallDomainService.add_order_item_to_cart(
                {
                    "userId": context.get("userId"),
                    "threadId": context.get("threadId"),
                    "keyword": (bridge_match.group(1) or "").strip(),
                }
            )
            return {
                "success": True,
                "skillId": self.metadata["id"],
                "output": bridge_res.get("message") or "该商品暂时无法加入购物车，请稍后再试。",
                "nextAction": "finish",
                "extra": {
                    "cartContext": bridge_res.get("cart") or existing_cart,
                    "guideContext": guide_context,
                },
            }

        # 1. 查看购物车与算价结算(_VIEW_ONLY_RE 等均为模块级常量,不可经 self. 访问)
        if _VIEW_ONLY_RE.search(user_input) and not _VIEW_EXCLUDE_RE.search(user_input):
            summary_res = await MallDomainService.get_cart_summary(
                {"userId": context.get("userId"), "threadId": context.get("threadId")}
            )
            cart_data = summary_res.get("cart") or {}
            cart_items = cart_data.get("items") or []
            card = {
                "type": "cart_card",
                "data": {
                    "actionType": "view",
                    "title": f"购物车明细 ({cart_data.get('totalQuantity') or len(cart_items)} 件)",
                    "totalQuantity": cart_data.get("totalQuantity") or len(cart_items),
                    "totalAmount": cart_data.get("payableAmount") or cart_data.get("totalAmount") or 0,
                    "currency": "CNY",
                    "items": [
                        {
                            "id": i.get("skuId") or i.get("id"),
                            "skuId": i.get("skuId") or i.get("id"),
                            "title": i.get("title") or i.get("name"),
                            "price": float(i.get("price") or 0),
                            "quantity": int(i.get("quantity") or 1),
                            "imageUrl": i.get("imageUrl"),
                            "specSummary": i.get("specSummary"),
                        }
                        for i in cart_items
                    ],
                    "actions": [{"label": "去结算", "action": "checkout_cart"}, {"label": "清空购物车", "action": "clear_cart"}],
                },
            }
            items_text = "\n".join(
                f"{idx + 1}. {i.get('title')} x{i.get('quantity')} (¥{i.get('price')})"
                for idx, i in enumerate(cart_items)
            )
            return {
                "success": True,
                "skillId": self.metadata["id"],
                "output": (
                    f"您的购物车目前共有 {cart_data.get('totalQuantity') or 0} 件商品：\n\n{items_text or '（暂无商品）'}\n\n"
                    f"💰 商品总价: ¥{cart_data.get('totalAmount') or 0}元\n"
                    f"🎁 预估优惠: -¥{cart_data.get('discount') or 0}元\n"
                    f"💵 实付预估: ¥{cart_data.get('payableAmount') or 0}元"
                ),
                "cards": [card],
                "nextAction": "finish",
                "extra": {
                    "cartContext": {"items": cart_items, "totalAmount": cart_data.get("totalAmount")},
                    "guideContext": guide_context,
                },
            }

        # 2. 购物车删除与清空
        if _DELETE_RE.search(user_input) and not _ADD_RE.search(user_input):
            summary_res = await MallDomainService.get_cart_summary(
                {"userId": context.get("userId"), "threadId": context.get("threadId")}
            )
            current_items = (summary_res.get("cart") or {}).get("items") or existing_cart.get("items") or []

            # 空车守卫(2026-09-06):summary 对空 storage 返回演示默认车,
            # 不可据此播报移除;以 has_cart 真值为准
            if not await MallDomainService.has_cart({"userId": context.get("userId"), "threadId": context.get("threadId")}):
                return {
                    "success": True,
                    "skillId": self.metadata["id"],
                    "output": "购物车还是空的，没有可移除的商品。如需选购，可对我说“推荐跑鞋”或“查看购物车”。",
                    "nextAction": "finish",
                    "extra": {"guideContext": guide_context, "cartContext": existing_cart},
                }

            if _CLEAR_RE.search(user_input):
                for item in current_items:
                    await MallDomainService.update_cart_item(
                        {"skuId": item["skuId"], "quantity": 0, "userId": context.get("userId"), "threadId": context.get("threadId")}
                    )
                return {
                    "success": True,
                    "skillId": self.metadata["id"],
                    "output": "已成功清空购物车中的所有商品。如需重新选购，请随时告诉我！🛒",
                    "cards": [
                        {
                            "type": "cart_card",
                            "data": {"actionType": "cleared", "title": "购物车已清空", "items": [], "currency": "CNY"},
                        }
                    ],
                    "nextAction": "finish",
                    "extra": {"cartContext": {"items": [], "totalAmount": 0}, "guideContext": guide_context},
                }

            # 目标解析链:序数词 → 商品名匹配(2026-09-06 修复:此前点名商品被忽略,
            # 兜底 lastModifiedItemId/items[0] 误删他款)→ lastModifiedItemId → 首款
            ordinal_match = _ORDINAL_RE.search(user_input)
            target_item = None
            if ordinal_match:
                target_index = _ordinal_to_index(ordinal_match.group(1))
                if target_index >= len(current_items):
                    # 越界守卫(2026-09-06):此前越界序数静默落兜底链误删首款
                    return {
                        "success": True,
                        "skillId": self.metadata["id"],
                        "output": (
                            f"购物车中没有第{target_index + 1}件商品（当前共 {len(current_items)} 件），未做任何移除。\n"
                            "如需查看明细，可说“查看购物车”。"
                        ),
                        "nextAction": "finish",
                        "extra": {"guideContext": guide_context, "cartContext": existing_cart},
                    }
                target_item = current_items[target_index]
            else:
                target_item = _match_cart_item_by_name(user_input, current_items)
            if target_item is None and existing_cart.get("lastModifiedItemId"):
                target_item = next((i for i in current_items if i.get("skuId") == existing_cart["lastModifiedItemId"]), None)
            if target_item is None and current_items:
                target_item = current_items[0]

            if target_item:
                update_res = await MallDomainService.update_cart_item(
                    {"skuId": target_item["skuId"], "quantity": 0, "userId": context.get("userId"), "threadId": context.get("threadId")}
                )
                updated_cart = update_res.get("cart") or {}
                # 移除后回 cart_card(2026-09-14):商户门户悬浮窗以卡片为快照同步
                # localStorage —— 不回卡则商城页删除永不生效(引擎删了、页面还在)
                remaining_items = updated_cart.get("items") or []
                card = {
                    "type": "cart_card",
                    "data": {
                        "actionType": "removed",
                        "title": f"已移除 {target_item.get('title')}",
                        "totalQuantity": updated_cart.get("totalQuantity") or 0,
                        "totalAmount": updated_cart.get("totalAmount") or 0,
                        "currency": "CNY",
                        "items": [
                            {
                                "id": i.get("skuId") or i.get("id"),
                                "skuId": i.get("skuId") or i.get("id"),
                                "title": i.get("title") or i.get("name"),
                                "price": float(i.get("price") or 0),
                                "quantity": int(i.get("quantity") or 1),
                            }
                            for i in remaining_items
                        ],
                    },
                }
                return {
                    "success": True,
                    "skillId": self.metadata["id"],
                    "output": (
                        f"🗑️ 已成功将【{target_item.get('title')}】从购物车中移除！\n"
                        f"当前购物车共有 {updated_cart.get('totalQuantity') or 0} 件商品，"
                        f"总金额 ¥{updated_cart.get('totalAmount') or 0} 元。"
                    ),
                    "cards": [card],
                    "nextAction": "finish",
                    "extra": {
                        "cartContext": {"items": remaining_items, "totalAmount": updated_cart.get("totalAmount")},
                        "guideContext": guide_context,
                    },
                }
            return {
                "success": True,
                "skillId": self.metadata["id"],
                "output": "购物车中暂无该商品或已为空，无需重复移除。",
                "nextAction": "finish",
                "extra": {"guideContext": guide_context, "cartContext": existing_cart},
            }

        # 3. 数量修改
        update_match = _QTY_UPDATE_RE.search(user_input)
        if update_match:
            new_qty = int(update_match.group(1))
            summary_res = await MallDomainService.get_cart_summary(
                {"userId": context.get("userId"), "threadId": context.get("threadId")}
            )
            current_items = (summary_res.get("cart") or {}).get("items") or existing_cart.get("items") or []

            # 空车守卫(2026-09-06):与删除分支同理,防幻影改量播报
            if not await MallDomainService.has_cart({"userId": context.get("userId"), "threadId": context.get("threadId")}):
                return {
                    "success": True,
                    "skillId": self.metadata["id"],
                    "output": "购物车还是空的，先加入商品后再调整数量。如需选购，可对我说“推荐跑鞋”。",
                    "nextAction": "finish",
                    "extra": {"guideContext": guide_context, "cartContext": existing_cart},
                }

            # 目标解析链与删除分支对齐:序数词 → 商品名匹配 → lastModifiedItemId → 首款
            ordinal_match = _ORDINAL_RE.search(user_input)
            target_item = None
            if ordinal_match:
                target_index = _ordinal_to_index(ordinal_match.group(1))
                if target_index >= len(current_items):
                    # 越界守卫(2026-09-06):越界序数不得错改首款/lastModified
                    return {
                        "success": True,
                        "skillId": self.metadata["id"],
                        "output": (
                            f"购物车中没有第{target_index + 1}件商品（当前共 {len(current_items)} 件），数量未调整。\n"
                            "如需查看明细，可说“查看购物车”。"
                        ),
                        "nextAction": "finish",
                        "extra": {"guideContext": guide_context, "cartContext": existing_cart},
                    }
                target_item = current_items[target_index]
            else:
                target_item = _match_cart_item_by_name(user_input, current_items)
            if target_item is None and existing_cart.get("lastModifiedItemId"):
                target_item = next((i for i in current_items if i.get("skuId") == existing_cart["lastModifiedItemId"]), None)
            if target_item is None and current_items:
                target_item = current_items[0]

            # 目标 SKU 解析失败诚实拦截(2026-09-12):旧兜底硬编码 AJ1 假 SKU,
            # 改量指令解析不到目标时不许错改幻影商品。上游 :227 空车守卫已拦
            # 空车,这里只剩"有车但全链解析失败"的罕见残余,宁可追问。
            target_sku = (target_item or {}).get("skuId") or existing_cart.get("lastModifiedItemId")
            if not target_sku:
                return {
                    "success": True,
                    "skillId": self.metadata["id"],
                    "output": (
                        "未能定位您想调整数量的商品，请直接说\"把【商品名】数量改成N\"，"
                        "或先\"查看购物车\"确认当前明细。"
                    ),
                    "nextAction": "finish",
                    "extra": {"guideContext": guide_context, "cartContext": existing_cart},
                }
            update_res = await MallDomainService.update_cart_item(
                {"skuId": target_sku, "quantity": new_qty, "userId": context.get("userId"), "threadId": context.get("threadId")}
            )
            updated_cart = update_res.get("cart") or {}
            return {
                "success": True,
                "skillId": self.metadata["id"],
                "output": (
                    f"✏️ 已成功将【{(target_item or {}).get('title') or '商品'}】数量调整为 {new_qty} 件！\n"
                    f"当前购物车共有 {updated_cart.get('totalQuantity') or new_qty} 件商品，"
                    f"总金额 ¥{updated_cart.get('totalAmount') or 0} 元。"
                ),
                "nextAction": "finish",
                "extra": {
                    "cartContext": {
                        "lastModifiedItemId": target_sku,
                        "items": updated_cart.get("items"),
                        "totalAmount": updated_cart.get("totalAmount"),
                    },
                    "guideContext": guide_context,
                },
            }

        # 3b. 模糊指代追问
        if _VAGUE_RE.search(user_input):
            candidates = guide_context.get("candidateProducts") or []
            if candidates:
                list_text = "\n".join(f"{i + 1}. 【{c['name']}】 ¥{c['price']}" for i, c in enumerate(candidates))
                return {
                    "success": True,
                    "skillId": self.metadata["id"],
                    "output": (
                        f"请问您想将哪一款推荐商品加入购物车呢？\n\n{list_text}\n\n"
                        "您可以直接对我说“把第1件加入购物车”或“把第2件加入购物车”，我立即为您办理！🛒"
                    ),
                    "nextAction": "finish",
                    "extra": {"guideContext": guide_context, "cartContext": existing_cart},
                }
            return {
                "success": True,
                "skillId": self.metadata["id"],
                "output": "请问您想将哪一款商品加入购物车呢？您可以直接对我说“把第1件加入购物车”或“把第2件加入购物车”，我立即为您办理！🛒",
                "nextAction": "finish",
                "extra": {"guideContext": guide_context, "cartContext": existing_cart},
            }

        # 4. 加购执行(含跨 Agent 指代消解)
        slots = context.get("slots") or {}
        target_sku_id = slots.get("skuId") or slots.get("productId") or ""
        target_title = "精选推荐商品"
        # 无价不编价(2026-09-12):旧初始化 899.0 恰为已拆除的 Pegasus 假商品价,
        # 服务层对缺价拒绝入车 —— 技能层同原则透传真价,价格未知保持 None。
        target_price: float | None = None

        candidate_products = guide_context.get("candidateProducts") or []
        candidate_list = guide_context.get("candidateProductIds") or []

        # guideContext 为空时从近期对话历史智能回溯推荐候选。
        # 幻影守卫(2026-09-13 用户实报):句中带检索/推荐诉求(「询评价好的
        # 短袖」)而本轮无候选时,历史回溯会把上一轮的别的商品当成「第一个」
        # 入车 —— 检索诉求在场一律禁用回溯,诚实反问。
        short_mem = extra.get("shortMemory") or []
        if not candidate_list and short_mem and not _SEARCH_INTENT_RE.search(user_input):
            for msg in reversed(short_mem):
                if msg.get("role") == "assistant" and isinstance(msg.get("content"), str) and "推荐商品" in msg["content"]:
                    parsed_products = [
                        {"id": f"prod_recommend_{m.group(1)}", "name": m.group(2), "price": float(m.group(3))}
                        for m in _HISTORY_ITEM_RE.finditer(msg["content"])
                    ]
                    if parsed_products:
                        candidate_products = parsed_products
                        candidate_list = [p["id"] for p in parsed_products]
                        break

        # 4a. 全量加购(2026-09-06 修复):"全部/所有/都" + 多候选且无序数词 → 逐一入车。
        # 此前该措辞落到 candidate[0] 兜底,导购推荐 3 款用户说"3个全部加入购物车"仅 1 款入车。
        # 序数词共存("第1件和第2件都加入")仍走下方单目标指代解析,不误扩为全量。
        if (
            _ADD_ALL_RE.search(user_input)
            and not _ORDINAL_FULL_RE.search(user_input)
            and len(candidate_products) > 1
        ):
            # 重复分区(2026-09-06 产品语义):新款入车;已在车的不自动累量,列表提示
            summary_res = await MallDomainService.get_cart_summary(
                {"userId": context.get("userId"), "threadId": context.get("threadId")}
            )
            existing_map = {i.get("skuId"): i for i in ((summary_res.get("cart") or {}).get("items") or [])}
            new_products = [p for p in candidate_products if p["id"] not in existing_map]
            dup_items = [existing_map[p["id"]] for p in candidate_products if p["id"] in existing_map]
            dup_notice = ""
            if dup_items:
                dup_text = "、".join(f"【{i.get('title')}】x{i.get('quantity') or 1}" for i in dup_items)
                dup_notice = f"\n\n🛎️ 以下 {len(dup_items)} 款已在购物车,未重复加入:{dup_text}"

            if not new_products:
                return {
                    "success": True,
                    "skillId": self.metadata["id"],
                    "output": (
                        f"🛎️ 这 {len(dup_items)} 款商品都已在购物车中,本次未重复加入:{dup_text}\n"
                        "如需增加数量,请说\"把第1件数量改成2\";如需查看,可说\"查看购物车\"。"
                    ),
                    "nextAction": "finish",
                    "extra": {
                        "cartContext": {
                            "items": (summary_res.get("cart") or {}).get("items") or [],
                            "totalAmount": (summary_res.get("cart") or {}).get("totalAmount"),
                        },
                        "guideContext": {
                            **guide_context,
                            "candidateProductIds": candidate_list,
                            "candidateProducts": candidate_products,
                        },
                    },
                }

            qty_match_all = _QTY_BUY_RE.search(user_input)
            per_qty = int(qty_match_all.group(1)) if qty_match_all else 1
            updated_cart = {}
            for prod in new_products:
                add_res = await MallDomainService.add_to_cart(
                    {
                        "skuId": prod["id"],
                        "quantity": per_qty,
                        "title": prod.get("name") or "精选推荐商品",
                        "price": prod.get("price"),
                        "userId": context.get("userId"),
                        "threadId": context.get("threadId"),
                    }
                )
                rejected = self._add_rejected_response(add_res, guide_context, existing_cart)
                if rejected:
                    return rejected
                updated_cart = add_res.get("cart") or {}
            added_titles = "、".join(str(p.get("name") or p["id"]) for p in new_products)
            card = {
                "type": "cart_card",
                "data": {
                    "actionType": "added",
                    "title": f"已加入购物车 ({len(new_products)} 款)",
                    "totalQuantity": updated_cart.get("totalQuantity") or len(new_products) * per_qty,
                    "totalAmount": updated_cart.get("totalAmount") or sum(
                        (p.get("price") or 0) * per_qty for p in new_products
                    ),
                    "currency": "CNY",
                    "items": [
                        {
                            "id": it.get("skuId") or it.get("id"),
                            "skuId": it.get("skuId") or it.get("id"),
                            "title": it.get("title") or it.get("name"),
                            "price": float(it.get("price") or 0),
                            "quantity": int(it.get("quantity") or per_qty),
                            "imageUrl": it.get("imageUrl"),
                            "specSummary": it.get("specSummary"),
                        }
                        for it in (updated_cart.get("items") or [])
                    ],
                    "actions": [
                        {"label": "去结算", "action": "checkout_cart"},
                        {"label": "查看购物车", "action": "view_cart"},
                    ],
                },
            }
            return {
                "success": True,
                "skillId": self.metadata["id"],
                "output": (
                    f"🎉 已成功将 {len(new_products)} 款商品加入购物车：{added_titles}！\n"
                    f"当前购物车共有 {updated_cart.get('totalQuantity') or len(new_products) * per_qty} 件商品，"
                    f"总金额 ¥{updated_cart.get('totalAmount') or 0} 元。\n\n"
                    "如需结算买单或调整数量，请随时告诉我！"
                ) + dup_notice,
                "cards": [card],
                "nextAction": "finish",
                "extra": {
                    "cartContext": {
                        "lastModifiedItemId": candidate_products[-1]["id"],
                        "items": updated_cart.get("items"),
                        "totalAmount": updated_cart.get("totalAmount"),
                    },
                    "guideContext": {
                        **guide_context,
                        "candidateProductIds": candidate_list,
                        "candidateProducts": candidate_products,
                    },
                },
            }

        ordinal_match = _ORDINAL_FULL_RE.search(user_input)
        if ordinal_match:
            ordinal_char = ordinal_match.group(1) or ordinal_match.group(2) or ordinal_match.group(3)
            target_index = _ordinal_to_index(ordinal_char)
            if target_index < len(candidate_products):
                prod = candidate_products[target_index]
                target_sku_id = prod["id"]
                target_title = prod["name"]
                target_price = prod.get("price")
            elif target_index < len(candidate_list):
                target_sku_id = candidate_list[target_index]
                target_title = f"推荐商品 #{target_index + 1} ({target_sku_id})"

        # 序数越界守卫(2026-09-12):序数解析不出有效目标时诚实反问,严禁静默
        # 落 candidate[0] —— 推荐仅 2 款时「把第四个加入购物车」曾错加第 1 款
        # 并撞上「已在购物车」提示(用户实报)。与删除/改量分支 2026-09-06 越界
        # 守卫同类症状,加购分支补齐;词表外大序数(第十一+)同口径,不猜不装。
        broad_ordinal = _ORD_ANY_RE.search(user_input)
        if not target_sku_id and broad_ordinal and (candidate_products or candidate_list):
            pool = candidate_products or [
                {"id": cid, "name": f"推荐商品 #{i + 1}", "price": None} for i, cid in enumerate(candidate_list)
            ]
            list_text = "\n".join(
                f"{i + 1}. 【{c['name']}】" + (f" ¥{c['price']}" if c.get("price") is not None else "")
                for i, c in enumerate(pool)
            )
            if ordinal_match:
                head = f"本次推荐只有 {len(pool)} 款商品，没有第{target_index + 1}款，未加入任何商品。"
            else:
                head = f"没有定位到您说的「{broad_ordinal.group(0)}」，本次推荐共 {len(pool)} 款，未加入任何商品。"
            return {
                "success": True,
                "skillId": self.metadata["id"],
                "output": (
                    f"{head}\n\n{list_text}\n\n"
                    "可直接说要哪一款，例如“把第1件加入购物车”。🛒"
                ),
                "nextAction": "finish",
                "extra": {"guideContext": guide_context, "cartContext": existing_cart},
            }

        if not target_sku_id:
            if candidate_products:
                prod = candidate_products[0]
                target_sku_id = prod["id"]
                target_title = prod["name"]
                target_price = prod.get("price")
            elif candidate_list:
                target_sku_id = candidate_list[0]
                target_title = f"推荐商品 #1 ({target_sku_id})"
            else:
                # 无任何候选可解析时诚实反问(2026-09-12):旧兜底硬编码 Nike
                # Pegasus 假商品入车 —— 无上下文的加购指令宁可追问,不可编造
                # 目标商品(幻影入车症状的最后一道假货出口)。
                return {
                    "success": True,
                    "skillId": self.metadata["id"],
                    "output": (
                        "请问您想将哪一款商品加入购物车呢？\n"
                        "您可以先让我为您推荐商品（例如\"推荐几款短袖\"），再说\"把第1件加入购物车\"即可！🛒"
                    ),
                    "nextAction": "finish",
                    "extra": {"guideContext": guide_context, "cartContext": existing_cart},
                }

        qty_match = _QTY_BUY_RE.search(user_input)
        quantity = int(qty_match.group(1)) if qty_match else 1

        # 已在车拦截(2026-09-06 产品语义):重复加购不自动累量,提示当前数量与改量入口
        pre_summary = await MallDomainService.get_cart_summary(
            {"userId": context.get("userId"), "threadId": context.get("threadId")}
        )
        pre_cart = pre_summary.get("cart") or {}
        dup_item = next((i for i in (pre_cart.get("items") or []) if i.get("skuId") == target_sku_id), None)
        if dup_item:
            dup_title = str(dup_item.get("title") or target_title)
            cur_qty = int(dup_item.get("quantity") or 1)
            return {
                "success": True,
                "skillId": self.metadata["id"],
                "output": (
                    f"🛒 【{dup_title}】已在购物车中(x{cur_qty} 件),本次未重复加入。\n"
                    f'如需增加数量,请说"把 {dup_title} 数量改成{cur_qty + 1}";'
                    '如需查看明细,可说"查看购物车"。'
                ),
                "nextAction": "finish",
                "extra": {
                    "cartContext": {
                        "lastModifiedItemId": target_sku_id,
                        "items": pre_cart.get("items") or [],
                        "totalAmount": pre_cart.get("totalAmount"),
                    },
                    "guideContext": {
                        **guide_context,
                        "candidateProductIds": candidate_list,
                        "candidateProducts": candidate_products,
                    },
                },
            }

        add_res = await MallDomainService.add_to_cart(
            {
                "skuId": target_sku_id,
                "quantity": quantity,
                "title": target_title,
                "price": target_price,
                "userId": context.get("userId"),
                "threadId": context.get("threadId"),
            }
        )
        rejected = self._add_rejected_response(add_res, guide_context, existing_cart)
        if rejected:
            return rejected
        updated_cart = add_res.get("cart") or {}

        card = {
            "type": "cart_card",
            "data": {
                "actionType": "added",
                "title": f"已加入购物车: {target_title}",
                "totalQuantity": updated_cart.get("totalQuantity") or quantity,
                "totalAmount": updated_cart.get("totalAmount") or target_price * quantity,
                "currency": "CNY",
                "items": (
                    [
                        {
                            "id": it.get("skuId") or it.get("id"),
                            "skuId": it.get("skuId") or it.get("id"),
                            "title": it.get("title") or it.get("name") or target_title,
                            "price": float(it.get("price") or target_price),
                            "quantity": int(it.get("quantity") or quantity),
                            "imageUrl": it.get("imageUrl"),
                            "specSummary": it.get("specSummary"),
                        }
                        for it in (updated_cart.get("items") or [])
                    ]
                    if updated_cart.get("items")
                    else [{"id": target_sku_id, "skuId": target_sku_id, "title": target_title, "price": target_price, "quantity": quantity}]
                ),
                "actions": [{"label": "去结算", "action": "checkout_cart"}, {"label": "查看购物车", "action": "view_cart"}],
            },
        }

        return {
            "success": True,
            "skillId": self.metadata["id"],
            "output": (
                f"🎉 已成功将【{target_title}】(x{quantity}) 加入购物车！\n"
                f"当前购物车共有 {updated_cart.get('totalQuantity') or quantity} 件商品，"
                f"总金额 ¥{updated_cart.get('totalAmount') or target_price * quantity} 元。\n\n"
                "如需结算买单或调整数量，请随时告诉我！"
            ),
            "cards": [card],
            "nextAction": "finish",
            "extra": {
                "cartContext": {
                    "lastModifiedItemId": target_sku_id,
                    "items": updated_cart.get("items"),
                    "totalAmount": updated_cart.get("totalAmount"),
                },
                "guideContext": {**guide_context, "candidateProductIds": candidate_list, "candidateProducts": candidate_products},
            },
        }
