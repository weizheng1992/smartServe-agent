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
