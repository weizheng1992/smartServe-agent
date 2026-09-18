"""优惠引擎(20 号 D1-D4 落地;阶段⑥兑现:订单计算优惠金额)。

服务端唯一算价点:
- best_for_amount(active_promos, amount, scope_spus) → 选最优活动并算优惠额;
- 结算链(mall_domain.checkout_user_cart)对订单实付应用优惠,并落
  promotion_redemptions(订单↔优惠关联);
- 商品促销价(promo_for_spu)供商城展示(划线价)。

规则(与 promotions.py CRUD 同一张 promotions 表):
- full_reduction: 实付 ≥ threshold_amount → 减 discount_value;
- discount: discount_value 为折扣率(85 = 8.5 折) → 优惠 = 原价 × (100-值)%;
- coupon: 券面额 discount_value(结算自动应用,无门槛)。
只取 status='active' 且在有效期内;多活动可满足时取优惠额最大者;金额永不为负。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import text


def _compute_discount(promo: dict, amount: float) -> float | None:
    """单活动对金额的优惠额;不满足门槛返回 None。规则唯一出处。"""
    ptype = promo["promo_type"]
    value = float(promo["discount_value"])
    if ptype == "full_reduction":
        threshold = float(promo["threshold_amount"] or 0)
        return value if amount >= threshold else None
    if ptype == "discount":
        rate = min(max(value, 1.0), 99.0)
        return round(amount * (100 - rate) / 100, 2)
    if ptype == "coupon":
        return min(value, amount)
    return None


def _in_window(promo: dict, now: datetime | None = None) -> bool:
    now = now or datetime.now()
    start = promo.get("start_at")
    end = promo.get("end_at")
    if start and now < start:
        return False
    if end and now > end:
        return False
    return True


async def fetch_active_promos(conn) -> list[dict]:
    rows = (
        await conn.execute(
            text(
                "SELECT id::text, name, promo_type, threshold_amount, discount_value, "
                "scope_type, scope_value FROM promotions "
                "WHERE status = 'active' AND (end_at IS NULL OR end_at > NOW())"
            )
        )
    ).mappings().all()
    return [dict(r) for r in rows]


async def best_for_amount(conn, amount: float, scope_spus: set[str] | None = None,
                          exclude_coupon: bool = False) -> dict | None:
    """对该金额选最优活动;scope_spus 非空时优先取命中商品范围的活动。

    返回 {promo_id, name, promo_type, discount} 或 None(无可用活动 —— 调用方
    按原价结算,诚实无优惠)。
    """
    promos = await fetch_active_promos(conn)
    promos = [p for p in promos if _in_window(p)]
    if exclude_coupon:
        promos = [p for p in promos if p["promo_type"] != "coupon"]  # 券类须用户领取后使用(20-D4)
    best: dict | None = None
    scoped_best: dict | None = None
    for p in promos:
        # 范围活动仅当金额口径内商品命中范围才参与(简化:按 SPU 编码集合)
        if p["scope_type"] == "spu" and scope_spus is not None:
            if p["scope_value"] not in scope_spus:
                continue
        discount = _compute_discount(p, amount)
        if discount is None:
            continue
        candidate = {
            "promo_id": p["id"], "name": p["name"], "promo_type": p["promo_type"],
            "discount": min(discount, amount),
        }
        if p["scope_type"] != "all":
            scoped_best = candidate if (not scoped_best or candidate["discount"] > scoped_best["discount"]) else scoped_best
        else:
            best = candidate if (not best or candidate["discount"] > best["discount"]) else best
    # 范围活动优先(更精准),否则全局最优
    return scoped_best or best


async def promo_for_spu(conn, spu_code: str, price: float) -> dict | None:
    """商品促销价(商城展示):命中的最优活动 + 促销价。无 → None(原价展示)。"""
    promos = [
        p for p in await fetch_active_promos(conn)
        if p["scope_type"] in ("all", "spu") and (p["scope_type"] != "spu" or p["scope_value"] == spu_code)
    ]
    best: dict | None = None
    for p in promos:
        discount = _compute_discount(p, price)
        if discount is None:
            continue
        if not best or discount > best["discount"]:
            best = {"promo_id": p["id"], "name": p["name"], "discount": discount,
                    "promoPrice": round(max(price - discount, 0), 2)}
    return best


async def best_user_coupon(conn, user_id: str, amount: float) -> dict | None:
    """用户已领取且未使用的券中,对面额取最优(仅 coupon 型)。"""
    rows = (
        await conn.execute(
            text(
                "SELECT uc.id AS coupon_id, p.name, p.promo_type, p.discount_value, p.threshold_amount "
                "FROM user_coupons uc JOIN promotions p ON p.id = uc.promotion_id "
                "WHERE uc.user_id = :u AND uc.status = 'claimed' AND p.status = 'active' "
                "AND p.promo_type = 'coupon' AND (p.end_at IS NULL OR p.end_at > NOW())"
            ).bindparams(u=user_id)
        )
    ).mappings().all()
    best = None
    for r in rows:
        discount = _compute_discount(dict(r), amount)
        if discount is None:
            continue
        candidate = {"coupon_row_id": r["coupon_id"], "name": r["name"], "discount": min(discount, amount)}
        if not best or candidate["discount"] > best["discount"]:
            best = candidate
    return best
