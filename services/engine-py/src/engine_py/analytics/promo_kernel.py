"""促销语义内核(2026-10-03 收口):生效态/窗口谓词/优惠计算的唯一出处。

promotions.py(写面 CRUD/核销)与 promotion_engine.py(读面定价/荐品)共享
同一张 promotions 表与同一套业务口径 —— 收口前各持一份时钟(_utcnow ×2)与
各一套「还活着」判定(_effective_status vs _in_window,now==end 瞬时边界
曾互相矛盾),两处漂移即错价或错展示。改口径只改本 module。

边界约定(与 fetch_active_promos 的 SQL 闸严格一致):
- 窗口内 ⇔ start_at ≤ now < end_at(SQL 闸 end_at > NOW();旧 _in_window
  用 now > end,与 SQL 闸在 now==end 瞬时分歧 —— 候选集恒经 SQL 闸预过滤,
  分歧不可达,归一无行为变化);ended ⇔ now ≥ end_at,两谓词自此同源。
- 时钟一律 UTC-naive(列默认 NOW() 落 naive UTC;本地 naive now 在非 UTC
  部署偏整个时区,2026-09-29 夜审 F15 实弹)。

刻意不收口:promotion_engine 的三处「选最优」循环是真实策略差异(范围/
全局分桶、荐品 promoPrice 载荷、立减额封顶),强行合一制造参数汤 ——
kernel 只供 compute_discount 公式,分桶策略留在各调用点。
"""

from __future__ import annotations

from datetime import UTC, datetime


def utcnow() -> datetime:
    """UTC-naive 钟(与库钟同源的唯一出处)。"""
    return datetime.now(UTC).replace(tzinfo=None)


def effective_status(status: str, start_at, end_at, now: datetime | None = None) -> str:
    """生效态派生(列表/详情展示口径):disabled > ended > scheduled > running。"""
    now = now or utcnow()
    if status == "disabled":
        return "disabled"
    if end_at and now >= end_at:
        return "ended"
    if start_at and now < start_at:
        return "scheduled"
    return "running"


def in_window(promo: dict, now: datetime | None = None) -> bool:
    """窗口内判定(结算候选复检口径):start_at ≤ now < end_at。"""
    now = now or utcnow()
    start = promo.get("start_at")
    end = promo.get("end_at")
    if start and now < start:
        return False
    if end and now >= end:
        return False
    return True


def compute_discount(promo: dict, amount: float) -> float | None:
    """单活动对金额的优惠额;不满足门槛返回 None。规则唯一出处。

    full_reduction: 实付 ≥ threshold → 减 discount_value;discount:
    discount_value 为折扣率(85 = 8.5 折);coupon: 券面额封顶金额。
    金额永不为负由调用方 min(discount, amount) 保证。
    """
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
