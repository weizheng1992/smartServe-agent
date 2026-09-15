"""购物车卡片与回复文案组装 — 四处逐字复制的 cart_card 行规范化收敛于此。

行形状:id/skuId/skuCode/spuId 回指键 + 标题/价格/数量/图片/规格摘要;
缺省值逐字段兜底,绝不编价(缺价 None 原样透传,real-data-only/01)。"""

from __future__ import annotations


def normalize_lines(
    items: list[dict] | None,
    *,
    default_quantity: int = 1,
    fallback_title: str | None = None,
    fallback_price: float | None = None,
) -> list[dict]:
    """车行 → 卡片行:id/skuId/skuCode/spuId 四回指键 + 展示字段。
    items 为空时按 fallback 组一行(加购成功卡的最小心智模型)。"""
    lines = [
        {
            "id": i.get("skuId") or i.get("id"),
            "skuId": i.get("skuId") or i.get("id"),
            "skuCode": i.get("skuCode") or i.get("skuId") or i.get("id"),
            "spuId": i.get("spuId") or i.get("skuId") or i.get("id"),
            "title": i.get("title") or i.get("name") or fallback_title,
            "price": float(i.get("price") or fallback_price or 0),
            "quantity": int(i.get("quantity") or default_quantity),
            "imageUrl": i.get("imageUrl"),
            "specSummary": i.get("specSummary"),
        }
        for i in (items or [])
    ]
    if not lines and fallback_title is not None:
        lines = [
            {
                "id": None,
                "skuId": None,
                "skuCode": None,
                "spuId": None,
                "title": fallback_title,
                "price": float(fallback_price or 0),
                "quantity": default_quantity,
                "imageUrl": None,
                "specSummary": None,
            }
        ]
    return lines


def build_cart_card(
    *,
    action_type: str,
    title: str,
    items: list[dict] | None = None,
    total_quantity: int | None = None,
    total_amount: float | None = None,
    currency: str = "CNY",
    actions: list[dict] | None = None,
) -> dict:
    return {
        "type": "cart_card",
        "data": {
            "actionType": action_type,
            "title": title,
            "totalQuantity": total_quantity,
            "totalAmount": total_amount,
            "currency": currency,
            "items": items or [],
            **({"actions": actions} if actions else {}),
        },
    }


CHECKOUT_ACTIONS = [{"label": "去结算", "action": "checkout_cart"}]
VIEW_ACTIONS = [{"label": "去结算", "action": "checkout_cart"}, {"label": "查看购物车", "action": "view_cart"}]
