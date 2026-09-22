"""优惠活动服务(20 号;阶段⑥)。

写操作业务模块,与 data agent 只读边界分开;**结算应用优惠(资金口径改动)
不在本模块 —— 独立实现票评审 ApprovalGatekeeper 联动后落地**(20-D3)。
本模块只管:活动 CRUD(商户库直写 + merchant_audit_logs 审计)与效果速览
(核销聚合,真实查询)。
"""

from __future__ import annotations

import json
import uuid

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from ..tools_registry.order_domain import _merchant_writer_engine

PROMO_TYPES = ("full_reduction", "discount", "coupon")


async def _audit(action: str, operator: str, payload: dict) -> None:
    """审计(20-D5):写操作落 merchant_audit_logs;失败不炸主流程但打印。"""
    try:
        async with _merchant_writer_engine().begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO merchant_audit_logs (action_type, order_id, idempotency_key, operator, payload) "
                    "VALUES (:a, 'PROMOTION', :ik, :op, CAST(:p AS JSONB))"
                ).bindparams(a=action, ik=f"promo_{uuid.uuid4().hex[:16]}", op=operator, p=json.dumps(payload, ensure_ascii=False))
            )
    except Exception as err:
        print(f"[Promotions] audit failed: {err}")


async def list_promotions() -> list[dict]:
    async with _merchant_writer_engine().connect() as conn:
        rows = (
            await conn.execute(
                text(
                    'SELECT id::text, name, promo_type, threshold_amount, discount_value, scope_type, '
                    "scope_value, status, start_at, end_at FROM promotions ORDER BY created_at DESC LIMIT 100"
                )
            )
        ).mappings().all()
    return [
        {
            "id": r["id"], "name": r["name"], "promoType": r["promo_type"],
            "threshold": float(r["threshold_amount"]) if r["threshold_amount"] is not None else None,
            "value": float(r["discount_value"]), "scopeType": r["scope_type"], "scopeValue": r["scope_value"],
            "status": r["status"],
            "startAt": r["start_at"].isoformat() if r["start_at"] else None,
            "endAt": r["end_at"].isoformat() if r["end_at"] else None,
        }
        for r in rows
    ]


async def create_promotion(payload: dict, operator: str) -> dict:
    name = str(payload.get("name") or "").strip()
    promo_type = payload.get("promoType")
    value = payload.get("value")
    if not name or promo_type not in PROMO_TYPES or value is None:
        return {"error": "name/promoType/value 必传;promoType ∈ full_reduction|discount|coupon"}
    promo_id = str(uuid.uuid4())
    async with _merchant_writer_engine().begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO promotions (id, name, promo_type, threshold_amount, discount_value, scope_type, scope_value) "
                "VALUES (CAST(:id AS uuid), :name, :pt, :th, :v, :st, :sv)"
            ).bindparams(
                id=promo_id, name=name, pt=promo_type,
                th=payload.get("threshold"), v=float(value),
                st=payload.get("scopeType") or "all", sv=payload.get("scopeValue"),
            )
        )
    await _audit("promo_create", operator, {"id": promo_id, "name": name, "promoType": promo_type})
    return {"id": promo_id, "name": name}


async def set_promotion_status(promotion_id: str, status: str, operator: str) -> dict:
    if status not in ("active", "disabled"):
        return {"error": "status ∈ active|disabled"}
    async with _merchant_writer_engine().begin() as conn:
        result = await conn.execute(
            text("UPDATE promotions SET status = :s WHERE id = CAST(:id AS uuid)").bindparams(s=status, id=promotion_id)
        )
        if result.rowcount == 0:
            return {"error": "活动不存在"}
    await _audit("promo_status", operator, {"id": promotion_id, "status": status})
    return {"id": promotion_id, "status": status}


async def redeem(promotion_id: str, order_id: str, operator: str) -> dict:
    """补录核销(20-D4 订单↔优惠关联):对已存在的订单登记某活动的优惠金额。

    优惠额由服务端按活动规则 × 订单实付计算(不在本模块动结算链,20-D3);
    幂等:同活动×同订单只记一次。订单不存在/未启用活动 → error。
    """
    async with _merchant_writer_engine().connect() as conn:
        promo = (
            await conn.execute(
                text("SELECT promo_type, threshold_amount, discount_value, status FROM promotions WHERE id = CAST(:id AS uuid)")
                .bindparams(id=promotion_id)
            )
        ).mappings().first()
        if not promo:
            return {"error": "活动不存在"}
        if promo["status"] != "active":
            return {"error": "活动已停用,不可核销"}
        order = (
            await conn.execute(
                text("SELECT total_amount FROM merchant_orders WHERE order_id = :oid").bindparams(oid=order_id)
            )
        ).mappings().first()
        if not order:
            return {"error": f"订单不存在:{order_id}"}
        dup = (
            await conn.execute(
                text("SELECT 1 FROM promotion_redemptions WHERE promotion_id = CAST(:id AS uuid) AND order_id = :oid LIMIT 1")
                .bindparams(id=promotion_id, oid=order_id)
            )
        ).first()
        if dup:
            return {"error": "该订单已核销过此活动(幂等拦截)"}

    total = float(order["total_amount"])
    if promo["promo_type"] == "full_reduction":
        threshold = float(promo["threshold_amount"] or 0)
        if total < threshold:
            return {"error": f"订单实付 ¥{total:.2f} 未达满减门槛 ¥{threshold:.2f}"}
        discount = float(promo["discount_value"])
    elif promo["promo_type"] == "discount":
        discount = round(total * (100 - float(promo["discount_value"])) / 100, 2)
    else:
        discount = float(promo["discount_value"])
    discount = min(discount, total)

    async with _merchant_writer_engine().begin() as conn:
        await conn.execute(
            text("INSERT INTO promotion_redemptions (promotion_id, order_id, discount_amount) "
                 "VALUES (CAST(:pid AS uuid), :oid, :amt)").bindparams(pid=promotion_id, oid=order_id, amt=discount)
        )
    await _audit("promo_redeem", operator, {"promotionId": promotion_id, "orderId": order_id, "discount": discount})
    return {"promotionId": promotion_id, "orderId": order_id, "discount": discount}


async def claim_coupon(promotion_id: str, user_id: str) -> dict:
    """用户领券(仅 coupon 型活动;同活动同用户一次;须在售)。"""
    async with _merchant_writer_engine().connect() as conn:
        promo = (
            await conn.execute(
                text("SELECT promo_type, status FROM promotions WHERE id = CAST(:id AS uuid)").bindparams(id=promotion_id)
            )
        ).mappings().first()
        if not promo or promo["status"] != "active":
            return {"error": "活动不存在或已停用"}
        if promo["promo_type"] != "coupon":
            return {"error": "该活动类型无需领券(结算自动应用)"}
        dup = (
            await conn.execute(
                text("SELECT 1 FROM user_coupons WHERE promotion_id = CAST(:id AS uuid) AND user_id = :u LIMIT 1")
                .bindparams(id=promotion_id, u=user_id)
            )
        ).first()
        if dup:
            return {"error": "已领取过该券"}
    try:
        async with _merchant_writer_engine().begin() as conn:
            await conn.execute(
                text("INSERT INTO user_coupons (promotion_id, user_id) VALUES (CAST(:id AS uuid), :u)")
                .bindparams(id=promotion_id, u=user_id)
            )
    except IntegrityError:
        # 并发双领兜底:应用层查重与应用层插入之间存在窗口,唯一约束(uq_user_promo)
        # 是最终防线 —— 冲突即视为已领取,与串行语义一致
        return {"error": "已领取过该券"}
    await _audit("coupon_claim", user_id, {"promotionId": promotion_id})
    return {"promotionId": promotion_id, "userId": user_id}


async def my_coupons(user_id: str) -> list[dict]:
    """我的券:claimed(可用)+ used(已核销)全量带 status —— 核销态必须仍在
    列表(2026-09-21 bug:修前只回 claimed,商品页 claimedIds 丢记录,领券按钮
    复现,重复领取 400「已领取过该券」);可用性由消费方按 status 过滤。"""
    async with _merchant_writer_engine().connect() as conn:
        rows = (
            await conn.execute(
                text(
                    "SELECT uc.id, uc.promotion_id, p.name, p.discount_value, uc.claimed_at, uc.status "
                    "FROM user_coupons uc "
                    "JOIN promotions p ON p.id = uc.promotion_id "
                    "WHERE uc.user_id = :u AND p.promo_type = 'coupon' "
                    "ORDER BY uc.claimed_at DESC"
                ).bindparams(u=user_id)
            )
        ).mappings().all()
    return [{"id": r["id"], "promotionId": r["promotion_id"], "name": r["name"],
             "value": float(r["discount_value"]),
             "status": r["status"],
             "claimedAt": r["claimed_at"].isoformat() if r["claimed_at"] else None} for r in rows]


async def mark_coupon_used(conn, coupon_row_id: str, order_id: str) -> bool:
    """结算用券后置已用(与订单同事务)。

    条件核销防双花(2026-09-22):WHERE 带 status='claimed' 并校验影响行数 ——
    同用户并发两笔结算都能通过可用性读(普通 SELECT),只有这里的条件更新是
    最终防线;返回 False 时调用方必须整体回滚拒单,严禁继续落单。
    """
    result = await conn.execute(
        text(
            "UPDATE user_coupons SET status = 'used', used_order_id = :o, used_at = NOW() "
            "WHERE id = CAST(:id AS uuid) AND status = 'claimed'"
        ).bindparams(o=order_id, id=coupon_row_id)
    )
    return result.rowcount > 0


async def effect_overview() -> dict:
    """效果速览(20-D4):核销单数/优惠总额/最近核销;真实聚合,零活动诚实空。"""
    async with _merchant_writer_engine().connect() as conn:
        row = (
            await conn.execute(
                text(
                    "SELECT COUNT(*) AS redemptions, COALESCE(SUM(discount_amount), 0)::float AS total_discount "
                    "FROM promotion_redemptions"
                )
            )
        ).mappings().first()
        active = (
            await conn.execute(text("SELECT COUNT(*) AS c FROM promotions WHERE status = 'active'"))
        ).scalar()
    return {"activePromotions": int(active or 0), "redemptions": int(row["redemptions"]), "totalDiscount": float(row["total_discount"])}
