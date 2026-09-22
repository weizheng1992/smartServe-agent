"""购物车动作表 — 动词的声明式优先级表与处理器。

此前 execute() 是 15 段顺序 if 链,分支顺序本身就是语义,S6 跨品类错单、
幻影 Nike、双规格去重全部诞生于链上缝隙的优先级误判;现动词 = 表中一行
(探测谓词 + 处理器),优先级显式由表序表达。处理器内的业务逻辑与拆分前
逐字等价(17 个技能测试文件为行为保真安全网)。"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from ...tools_registry.mall_domain import MallDomainService
from . import resolver as R
from .cards import CHECKOUT_ACTIONS, VIEW_ACTIONS, build_cart_card, normalize_lines


@dataclass
class CartEnv:
    """一次技能调用的解析环境:动作表探测器与处理器共读(包私有接缝)。"""

    user_input: str
    slots: dict
    guide_context: dict
    cart_context: dict
    short_memory: list
    user_id: str | None
    thread_id: str | None

    @classmethod
    def from_context(cls, context) -> CartEnv:
        return cls(
            user_input=(context.input or "").strip(),
            slots=context.slots or {},
            guide_context=context.guide_context or {},
            cart_context=context.cart_context or {},
            short_memory=context.short_memory or [],
            user_id=context.user_id,
            thread_id=context.thread_id,
        )


@dataclass(frozen=True)
class CartAction:
    name: str
    detect: Callable[[CartEnv], bool]
    handle: Callable[[CartEnv], Awaitable[dict]]


_SKILL_ID = "skill_cart_manage"


def _rejected_response(add_res: dict, guide_context: dict, existing_cart: dict) -> dict | None:
    """入车被服务层拒绝(缺价等)时如实回传,不播报成功卡 —— skill 层
    success 语义是「技能处理完成」:业务失败经 output 文案如实送达用户
    (2026-09-12 real-data-only/01:宁可追问,不可编造)。非拒绝返回 None。
    addedThisTurn=[]:本轮加购未完成,复合「加购+下单」句的结算半据此拒结。"""
    if add_res.get("success"):
        return None
    return {
        "success": True,
        "skillId": _SKILL_ID,
        "output": add_res.get("message") or "该商品暂时无法加入购物车，请稍后再试。",
        "nextAction": "finish",
        "extra": {
            "guideContext": guide_context,
            "cartContext": {**(existing_cart or {}), "addedThisTurn": []},
        },
    }


def _no_add_extra(env: CartEnv) -> dict:
    """无加购动词的旁路响应 extra:cartContext 显式置 addedThisTurn=[],
    复合「加购+下单」句的结算半据此诚实拒结,不拿遗留品开单。"""
    return {
        "guideContext": env.guide_context,
        "cartContext": {**(env.cart_context or {}), "addedThisTurn": []},
    }


# ---------------------------------------------------------------------------
# 0. 结算下单(真·聊天下单,2026-09-13):拦截在查看之前;裸「结算」保持查看
# 摘要旧契约。S6 跨品类错单守卫:「就要第一个,直接下单」的「第一个」指向
# 本轮推荐候选;候选为空时指代悬空,拿购物车遗留品结算是错单,诚实反问。
# ---------------------------------------------------------------------------
def _detect_checkout(env: CartEnv) -> bool:
    return bool(
        R._CHECKOUT_RE.search(env.user_input)
        and not R._ADD_RE.search(env.user_input)
        and not R._DELETE_RE.search(env.user_input)
        and not R._CHECKOUT_NEG_RE.search(env.user_input)
    )


async def _checkout(env: CartEnv) -> dict:
    _guide_ctx = env.guide_context
    _has_candidates = bool(_guide_ctx.get("candidateProducts") or _guide_ctx.get("candidateProductIds"))
    if R._ORDINAL_CHECKOUT_RE.search(env.user_input) and not _has_candidates:
        return {
            "success": True,
            "output": (
                "您说的「第一个」我这边还没有对应的推荐列表——刚才没能为您展示商品。"
                "请告诉我您想买的商品(例如「推荐帐篷」),确认推荐结果后再说「下单」,我马上为您办理。"
            ),
            "nextAction": "finish",
            "extra": {**_no_add_extra(env)},
        }
    # 显式地址跟随(「寄到/送到/地址为…」),否则服务层取地址簿默认
    addr_match = R._CHECKOUT_ADDR_RE.search(env.user_input)
    checkout_res = await MallDomainService.checkout_user_cart(
        {
            "userId": env.user_id,
            "threadId": env.thread_id,
            "shippingAddress": addr_match.group(1).strip() if addr_match else None,
        }
    )
    if checkout_res.get("success"):
        lines = "\n".join(f"• {line}" for line in checkout_res.get("items") or [])
        return {
            "success": True,
            "output": (
                f"🎉 下单成功！订单号 [{checkout_res.get('orderId')}]。\n\n"
                f"{lines}\n\n"
                + (
                    f"💰 商品金额: ¥{checkout_res.get('totalAmount')}\n"
                    f"🎁 优惠「{checkout_res['promo']['name']}」已抵扣 ¥{checkout_res['promo']['discount']}\n"
                    f"✅ 实付金额: ¥{checkout_res.get('payableAmount')}\n"
                    if checkout_res.get("promo")
                    else f"💰 实付金额: ¥{checkout_res.get('totalAmount')}\n"
                )
                + f"📦 收货地址: {checkout_res.get('shippingAddress')}\n\n"
                "可在「我的订单」中随时查看物流状态。"
            ),
            "nextAction": "finish",
            "extra": {"cartContext": {"items": [], "totalAmount": 0}, "guideContext": env.guide_context},
        }
    return {
        "success": True,
        "output": checkout_res.get("message") or "结算未完成，请稍后再试。",
        "nextAction": "finish",
        "extra": {**_no_add_extra(env)},
    }


# ---------------------------------------------------------------------------
# 0.5 订单→购物车桥接:「订单(里)的 X 加入购物车」—— 商户真单明细按关键词
# 回查,当前在售 SKU 真实入车;找不到/多命中/已下架均如实回复。
# ---------------------------------------------------------------------------
def _detect_bridge(env: CartEnv) -> bool:
    return bool(R._BRIDGE_KEYWORD_RE.search(env.user_input) and R._ADD_RE.search(env.user_input))


async def _bridge(env: CartEnv) -> dict:
    bridge_match = R._BRIDGE_KEYWORD_RE.search(env.user_input)
    bridge_res = await MallDomainService.add_order_item_to_cart(
        {
            "userId": env.user_id,
            "threadId": env.thread_id,
            "keyword": (bridge_match.group(1) or "").strip(),
        }
    )
    return {
        "success": True,
        "output": bridge_res.get("message") or "该商品暂时无法加入购物车，请稍后再试。",
        "nextAction": "finish",
        "extra": {
            "cartContext": {
                **(bridge_res.get("cart") or env.cart_context),
                "addedThisTurn": (
                    [bridge_res["lastModifiedItemId"]] if bridge_res.get("lastModifiedItemId") else []
                ),
            },
            "guideContext": env.guide_context,
        },
    }


# ---------------------------------------------------------------------------
# 1. 查看购物车与算价(_VIEW_ONLY_RE 恒为模块级常量)
# ---------------------------------------------------------------------------
def _detect_view(env: CartEnv) -> bool:
    return bool(R._VIEW_ONLY_RE.search(env.user_input) and not R._VIEW_EXCLUDE_RE.search(env.user_input))


async def _view(env: CartEnv) -> dict:
    summary_res = await MallDomainService.get_cart_summary(
        {"userId": env.user_id, "threadId": env.thread_id}
    )
    cart_data = summary_res.get("cart") or {}
    cart_items = cart_data.get("items") or []
    card = build_cart_card(
        action_type="view",
        title=f"购物车明细 ({cart_data.get('totalQuantity') or len(cart_items)} 件)",
        total_quantity=cart_data.get("totalQuantity") or len(cart_items),
        total_amount=cart_data.get("payableAmount") or cart_data.get("totalAmount") or 0,
        items=normalize_lines(cart_items),
        actions=CHECKOUT_ACTIONS + [{"label": "清空购物车", "action": "clear_cart"}],
    )
    items_text = "\n".join(
        f"{idx + 1}. {i.get('title')} x{i.get('quantity')} (¥{i.get('price')})"
        for idx, i in enumerate(cart_items)
    )
    return {
        "success": True,
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
            "guideContext": env.guide_context,
        },
    }


# ---------------------------------------------------------------------------
# 2. 删除与清空(含共享目标解析链)
# ---------------------------------------------------------------------------
def _detect_delete(env: CartEnv) -> bool:
    return bool(R._DELETE_RE.search(env.user_input) and not R._ADD_RE.search(env.user_input))


async def _delete(env: CartEnv) -> dict:
    summary_res = await MallDomainService.get_cart_summary(
        {"userId": env.user_id, "threadId": env.thread_id}
    )
    current_items = (summary_res.get("cart") or {}).get("items") or env.cart_context.get("items") or []

    # 空车守卫(2026-09-06):summary 对空 storage 返回演示默认车,
    # 不可据此播报移除;以 has_cart 真值为准
    if not await MallDomainService.has_cart({"userId": env.user_id, "threadId": env.thread_id}):
        return {
            "success": True,
            "output": "购物车还是空的，没有可移除的商品。如需选购，可对我说“推荐跑鞋”或“查看购物车”。",
            "nextAction": "finish",
            "extra": _no_add_extra(env),
        }

    if R._CLEAR_RE.search(env.user_input):
        for item in current_items:
            await MallDomainService.update_cart_item(
                {"skuId": item["skuId"], "quantity": 0, "userId": env.user_id, "threadId": env.thread_id}
            )
        return {
            "success": True,
            "output": "已成功清空购物车中的所有商品。如需重新选购，请随时告诉我！🛒",
            "cards": [build_cart_card(action_type="cleared", title="购物车已清空", items=[], currency="CNY")],
            "nextAction": "finish",
            "extra": {"cartContext": {"items": [], "totalAmount": 0}, "guideContext": env.guide_context},
        }

    target_item, out_of_range = R.resolve_cart_item(
        env.user_input, current_items, env.cart_context.get("lastModifiedItemId")
    )
    if out_of_range is not None:
        # 越界守卫(2026-09-06):此前越界序数静默落兜底链误删首款
        return {
            "success": True,
            "output": (
                f"购物车中没有第{out_of_range + 1}件商品（当前共 {len(current_items)} 件），未做任何移除。\n"
                "如需查看明细，可说“查看购物车”。"
            ),
            "nextAction": "finish",
            "extra": _no_add_extra(env),
        }

    if target_item:
        update_res = await MallDomainService.update_cart_item(
            {"skuId": target_item["skuId"], "quantity": 0, "userId": env.user_id, "threadId": env.thread_id}
        )
        updated_cart = update_res.get("cart") or {}
        # 移除后回 cart_card(2026-09-14):商户门户悬浮窗以卡片为快照同步
        # localStorage —— 不回卡则商城页删除永不生效(引擎删了、页面还在)
        remaining_items = updated_cart.get("items") or []
        card = build_cart_card(
            action_type="removed",
            title=f"已移除 {target_item.get('title')}",
            total_quantity=updated_cart.get("totalQuantity") or 0,
            total_amount=updated_cart.get("totalAmount") or 0,
            items=normalize_lines(remaining_items),
        )
        return {
            "success": True,
            "output": (
                f"🗑️ 已成功将【{target_item.get('title')}】从购物车中移除！\n"
                f"当前购物车共有 {updated_cart.get('totalQuantity') or 0} 件商品，"
                f"总金额 ¥{updated_cart.get('totalAmount') or 0} 元。"
            ),
            "cards": [card],
            "nextAction": "finish",
            "extra": {
                "cartContext": {"items": remaining_items, "totalAmount": updated_cart.get("totalAmount")},
                "guideContext": env.guide_context,
            },
        }
    return {
        "success": True,
        "output": "购物车中暂无该商品或已为空，无需重复移除。",
        "nextAction": "finish",
        "extra": _no_add_extra(env),
    }


# ---------------------------------------------------------------------------
# 3. 数量修改(目标解析链与删除分支同缝)
# ---------------------------------------------------------------------------
def _detect_qty(env: CartEnv) -> bool:
    return bool(R._QTY_UPDATE_RE.search(env.user_input))


async def _update_qty(env: CartEnv) -> dict:
    new_qty = int(R._QTY_UPDATE_RE.search(env.user_input).group(1))
    summary_res = await MallDomainService.get_cart_summary(
        {"userId": env.user_id, "threadId": env.thread_id}
    )
    current_items = (summary_res.get("cart") or {}).get("items") or env.cart_context.get("items") or []

    # 空车守卫(2026-09-06):与删除分支同理,防幻影改量播报
    if not await MallDomainService.has_cart({"userId": env.user_id, "threadId": env.thread_id}):
        return {
            "success": True,
            "output": "购物车还是空的，先加入商品后再调整数量。如需选购，可对我说“推荐跑鞋”。",
            "nextAction": "finish",
            "extra": _no_add_extra(env),
        }

    target_item, out_of_range = R.resolve_cart_item(
        env.user_input, current_items, env.cart_context.get("lastModifiedItemId")
    )
    if out_of_range is not None:
        # 越界守卫(2026-09-06):越界序数不得错改首款/lastModified
        return {
            "success": True,
            "output": (
                f"购物车中没有第{out_of_range + 1}件商品（当前共 {len(current_items)} 件），数量未调整。\n"
                "如需查看明细，可说“查看购物车”。"
            ),
            "nextAction": "finish",
            "extra": _no_add_extra(env),
        }

    # 目标 SKU 解析失败诚实拦截(2026-09-12):改量指令解析不到目标时不许
    # 错改幻影商品,宁可追问。
    target_sku = (target_item or {}).get("skuId") or env.cart_context.get("lastModifiedItemId")
    if not target_sku:
        return {
            "success": True,
            "output": (
                "未能定位您想调整数量的商品，请直接说\"把【商品名】数量改成N\"，"
                "或先\"查看购物车\"确认当前明细。"
            ),
            "nextAction": "finish",
            "extra": _no_add_extra(env),
        }
    update_res = await MallDomainService.update_cart_item(
        {"skuId": target_sku, "quantity": new_qty, "userId": env.user_id, "threadId": env.thread_id}
    )
    updated_cart = update_res.get("cart") or {}
    return {
        "success": True,
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
            "guideContext": env.guide_context,
        },
    }


# ---------------------------------------------------------------------------
# 3b. 模糊指代追问
# ---------------------------------------------------------------------------
def _detect_vague(env: CartEnv) -> bool:
    return bool(R._VAGUE_RE.search(env.user_input))


async def _ask_which(env: CartEnv) -> dict:
    candidates = env.guide_context.get("candidateProducts") or []
    if candidates:
        list_text = "\n".join(f"{i + 1}. 【{c['name']}】 ¥{c['price']}" for i, c in enumerate(candidates))
        return {
            "success": True,
            "output": (
                f"请问您想将哪一款推荐商品加入购物车呢？\n\n{list_text}\n\n"
                "您可以直接对我说“把第1件加入购物车”或“把第2件加入购物车”，我立即为您办理！🛒"
            ),
            "nextAction": "finish",
            "extra": _no_add_extra(env),
        }
    return {
        "success": True,
        "output": "请问您想将哪一款商品加入购物车呢？您可以直接对我说“把第1件加入购物车”或“把第2件加入购物车”，我立即为您办理！🛒",
        "nextAction": "finish",
        "extra": _no_add_extra(env),
    }


# ---------------------------------------------------------------------------
# 4a. 全量加购:"全部/所有/都" + 多候选且无序数词 → 逐一入车
# ---------------------------------------------------------------------------
def _detect_add_all(env: CartEnv) -> bool:
    if not (R._ADD_ALL_RE.search(env.user_input) and not R._ORDINAL_FULL_RE.search(env.user_input)):
        return False
    candidates, _ = R.candidate_pool(env.guide_context, env.short_memory, env.user_input)
    return len(candidates) > 1


async def _add_all(env: CartEnv) -> dict:
    candidate_products, candidate_list = R.candidate_pool(env.guide_context, env.short_memory, env.user_input)
    # 重复分区(2026-09-06 产品语义):新款入车;已在车的不自动累量,列表提示
    summary_res = await MallDomainService.get_cart_summary(
        {"userId": env.user_id, "threadId": env.thread_id}
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
                    **env.guide_context,
                    "candidateProductIds": candidate_list,
                    "candidateProducts": candidate_products,
                },
            },
        }

    qty_match_all = R._QTY_BUY_RE.search(env.user_input)
    per_qty = int(qty_match_all.group(1)) if qty_match_all else 1
    updated_cart = {}
    for prod in new_products:
        add_res = await MallDomainService.add_to_cart(
            {
                "skuId": prod["id"],
                "quantity": per_qty,
                "title": prod.get("name") or "精选推荐商品",
                "price": prod.get("price"),
                "imageUrl": prod.get("imageUrl"),
                "userId": env.user_id,
                "threadId": env.thread_id,
            }
        )
        rejected = _rejected_response(add_res, env.guide_context, env.cart_context)
        if rejected:
            return rejected
        updated_cart = add_res.get("cart") or {}
    added_titles = "、".join(str(p.get("name") or p["id"]) for p in new_products)
    card = build_cart_card(
        action_type="added",
        title=f"已加入购物车 ({len(new_products)} 款)",
        total_quantity=updated_cart.get("totalQuantity") or len(new_products) * per_qty,
        total_amount=updated_cart.get("totalAmount")
        or sum((p.get("price") or 0) * per_qty for p in new_products),
        items=normalize_lines(updated_cart.get("items"), default_quantity=per_qty),
        actions=VIEW_ACTIONS,
    )
    return {
        "success": True,
        "output": (
            f"🎉 已成功将 {len(new_products)} 款商品加入购物车：{added_titles}！\n"
            f"当前购物车共有 {updated_cart.get('totalQuantity') or len(new_products) * per_qty} 件商品，"
            f"总金额 ¥{updated_cart.get('totalAmount') or 0} 元。\n\n"
            "如需结算买单或调整数量，请随时告诉我！"
        )
        + dup_notice,
        "cards": [card],
        "nextAction": "finish",
        "extra": {
            "cartContext": {
                "lastModifiedItemId": candidate_products[-1]["id"],
                "items": updated_cart.get("items"),
                "totalAmount": updated_cart.get("totalAmount"),
                # 本轮全量加购的行(复合「加购+下单」句的结算范围;已在车的未重复加入,不入范围)
                "addedThisTurn": [p["id"] for p in new_products],
            },
            "guideContext": {
                **env.guide_context,
                "candidateProductIds": candidate_list,
                "candidateProducts": candidate_products,
            },
        },
    }


# ---------------------------------------------------------------------------
# 4b. 单品加购(序数/指名直配/候选兜底)
# ---------------------------------------------------------------------------
async def _add(env: CartEnv) -> dict:
    target_sku_id = env.slots.get("skuId") or env.slots.get("productId") or ""
    target_title = "精选推荐商品"
    # 无价不编价(2026-09-12):价格未知保持 None,服务层对缺价拒绝入车。
    target_price: float | None = None
    target_spec: dict | None = None
    # 点名直配的引用键(2026-09-14):skuCode 钉确切规格、spuId 回指 SPU,
    # 经 add_to_cart 落在车行上;非点名路径为空 dict,行形状不变。
    target_refs: dict = {}

    # 图片透传(2026-09-15 用户实报):车行缺图曾致前端卡片图不对
    candidate_products, candidate_list = R.candidate_pool(env.guide_context, env.short_memory, env.user_input)
    target_image_url = next(
        (p.get("imageUrl") for p in candidate_products if p.get("id") == target_sku_id), None
    )

    ordinal_match = R._ORDINAL_FULL_RE.search(env.user_input)
    if ordinal_match:
        ordinal_char = ordinal_match.group(1) or ordinal_match.group(2) or ordinal_match.group(3)
        target_index = R.ordinal_to_index(ordinal_char)
        if target_index < len(candidate_products):
            prod = candidate_products[target_index]
            target_sku_id = prod["id"]
            target_title = prod["name"]
            target_price = prod.get("price")
        elif target_index < len(candidate_list):
            target_sku_id = candidate_list[target_index]
            target_title = f"推荐商品 #{target_index + 1} ({target_sku_id})"

    # 序数越界守卫(2026-09-12):序数解析不出有效目标时诚实反问,严禁静默
    # 落 candidate[0] —— 推荐仅 2 款时「把第四个加入购物车」曾错加第 1 款。
    broad_ordinal = R._ORD_ANY_RE.search(env.user_input)
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
            "output": (f"{head}\n\n{list_text}\n\n可直接说要哪一款，例如“把第1件加入购物车”。🛒"),
            "nextAction": "finish",
            "extra": _no_add_extra(env),
        }

    # 按名直配(2026-09-14):剥动作词后仍有实质内容 = 用户点了名,先查商户
    # 真货架直配(真 sku_code/真价);配不中或歧义诚实反问,严禁静默替他款。
    # 优先级(2026-09-15):named_query 非空时直配压过 slots.productId 遗留目标
    # —— planner 会把上一轮推荐填进 step args,显式点名必须压过上下文遗留。
    named_query = R.named_query_remainder(env.user_input)
    # 检索诉求句严禁进按名直配(2026-09-15 幻影守卫回归):残词是检索半而非点名。
    if R._SEARCH_INTENT_RE.search(named_query or ""):
        named_query = ""
    if named_query:
        shelf_hit = await MallDomainService.find_shelf_sku_by_description(named_query)
        if shelf_hit:
            # 点名直配行以 SKU 码为主键(与商城页加购同构);行上同时携带
            # spuId(SPU 回指)与干净 SPU 标题;结算 sku_code 直配优先不被换规格。
            target_sku_id = shelf_hit["skuCode"]
            target_title = shelf_hit["spuTitle"]
            target_price = shelf_hit["price"]
            target_spec = shelf_hit.get("spec")
            target_image_url = shelf_hit.get("imageUrl")
            target_refs = {"skuCode": shelf_hit["skuCode"], "spuId": shelf_hit["spuCode"]}
        else:
            # 配不中二分:纯指代交回既有槽位/候选链;仍有实质内容 → 诚实反问。
            residue = R._NAMED_DEIXIS_STRIP_RE.sub(" ", named_query).strip(" \t,，。.!！?？:；;的了")
            if residue:
                if candidate_products:
                    list_text = "\n".join(
                        f"{i + 1}. 【{c['name']}】 ¥{c['price']}" for i, c in enumerate(candidate_products)
                    )
                    return {
                        "success": True,
                        "output": (
                            f"没有在店内找到「{residue}」对应的在售规格，未加入任何商品。\n"
                            f"请问您想要哪一款？店内现货:{list_text}\n\n"
                            "可直接说「把第1件加入购物车」，或告诉我完整的商品名与规格。🛒"
                        ),
                        "nextAction": "finish",
                        "extra": _no_add_extra(env),
                    }
                return {
                    "success": True,
                    "output": (
                        f"没有在店内找到「{residue}」对应的在售规格，未加入任何商品。\n"
                        "您可以先让我为您推荐商品（例如\"推荐几款短袖\"），再说\"把第1件加入购物车\"即可！🛒"
                    ),
                    "nextAction": "finish",
                    "extra": _no_add_extra(env),
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
            # 无任何候选可解析时诚实反问(2026-09-12):无上下文的加购指令宁可
            # 追问,不可编造目标商品(幻影入车症状的最后一道假货出口)。
            return {
                "success": True,
                "output": (
                    "请问您想将哪一款商品加入购物车呢？\n"
                    "您可以先让我为您推荐商品（例如\"推荐几款短袖\"），再说\"把第1件加入购物车\"即可！🛒"
                ),
                "nextAction": "finish",
                "extra": _no_add_extra(env),
            }

    qty_match = R._QTY_BUY_RE.search(env.user_input)
    quantity = int(qty_match.group(1)) if qty_match else 1

    # 已在车拦截(2026-09-06 产品语义):重复加购不自动累量,提示当前数量与改量入口。
    # 判据含 skuCode(2026-09-15):行按 skuId 或钉住的 skuCode 任一命中即视为同规格重复。
    pre_summary = await MallDomainService.get_cart_summary(
        {"userId": env.user_id, "threadId": env.thread_id}
    )
    pre_cart = pre_summary.get("cart") or {}
    dup_item = next(
        (
            i
            for i in (pre_cart.get("items") or [])
            if i.get("skuId") == target_sku_id or i.get("skuCode") == target_sku_id
        ),
        None,
    )
    if dup_item:
        dup_title = str(dup_item.get("title") or target_title)
        cur_qty = int(dup_item.get("quantity") or 1)
        return {
            "success": True,
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
                    # 已在车拦截:未新加,但用户指名的就是这件 —— 复合
                    # 「加购+下单」句的结算范围按指名行走
                    "addedThisTurn": [target_sku_id],
                },
                "guideContext": {
                    **env.guide_context,
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
            "spec": target_spec,
            "skuCode": target_refs.get("skuCode"),
            "spuId": target_refs.get("spuId"),
            "imageUrl": target_image_url,
            "userId": env.user_id,
            "threadId": env.thread_id,
        }
    )
    rejected = _rejected_response(add_res, env.guide_context, env.cart_context)
    if rejected:
        return rejected
    updated_cart = add_res.get("cart") or {}

    card = build_cart_card(
        action_type="added",
        title=f"已加入购物车: {target_title}",
        total_quantity=updated_cart.get("totalQuantity") or quantity,
        total_amount=updated_cart.get("totalAmount") or (target_price or 0) * quantity,
        items=normalize_lines(
            updated_cart.get("items"),
            default_quantity=quantity,
            fallback_title=target_title,
            fallback_price=target_price,
        ),
        actions=VIEW_ACTIONS,
    )

    return {
        "success": True,
        "output": (
            f"🎉 已成功将【{target_title}】(x{quantity}) 加入购物车！\n"
            f"当前购物车共有 {updated_cart.get('totalQuantity') or quantity} 件商品，"
            f"总金额 ¥{updated_cart.get('totalAmount') or (target_price or 0) * quantity} 元。\n\n"
            "如需结算买单或调整数量，请随时告诉我！"
        ),
        "cards": [card],
        "nextAction": "finish",
        "extra": {
            "cartContext": {
                "lastModifiedItemId": target_sku_id,
                "items": updated_cart.get("items"),
                "totalAmount": updated_cart.get("totalAmount"),
                # 本轮加购行(复合「加购+下单」句的结算范围,2026-09-15)
                "addedThisTurn": [target_sku_id],
            },
            "guideContext": {**env.guide_context, "candidateProductIds": candidate_list, "candidateProducts": candidate_products},
        },
    }


# 声明式动作表:表序 = 优先级(原 if 链顺序的显式化)。
# 「add」为兜底动词,恒真探测器必须殿后。
ACTION_TABLE: list[CartAction] = [
    CartAction("checkout", _detect_checkout, _checkout),
    CartAction("order_bridge", _detect_bridge, _bridge),
    CartAction("view", _detect_view, _view),
    CartAction("delete", _detect_delete, _delete),
    CartAction("update_qty", _detect_qty, _update_qty),
    CartAction("ask_which", _detect_vague, _ask_which),
    CartAction("add_all", _detect_add_all, _add_all),
    CartAction("add", lambda env: True, _add),
]
