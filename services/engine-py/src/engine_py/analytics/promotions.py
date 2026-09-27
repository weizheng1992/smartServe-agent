"""优惠活动服务(20 号;阶段⑥)。

写操作业务模块,与 data agent 只读边界分开;**结算应用优惠(资金口径改动)
不在本模块 —— 独立实现票评审 ApprovalGatekeeper 联动后落地**(20-D3)。
本模块只管:活动 CRUD(商户库直写 + merchant_audit_logs 审计)与效果速览
(核销聚合,真实查询)。
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from ..tools_registry.order_domain import _merchant_writer_engine

PROMO_TYPES = ("full_reduction", "discount", "coupon")


def _parse_ts(raw) -> datetime | None:
    """datetime-local / ISO 字符串 → datetime;空串 = None(创建时缺省 NOW)。"""
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    return datetime.fromisoformat(s)


def _validate_window(start_at: datetime | None, end_at: datetime | None) -> str | None:
    if start_at and end_at and end_at <= start_at:
        return "结束时间必须晚于开始时间"
    return None


def _normalize_quota(promo_type: str, raw) -> int | None:
    """发放上限只对券型(coupon)有意义:非券型一律 None;空 = 不限;须为正整数。"""
    if promo_type != "coupon" or raw is None or raw == "":
        return None
    quota = int(raw)
    if quota <= 0:
        raise ValueError("发放上限须为正整数")
    return quota


def _effective_status(status: str, start_at, end_at, now: datetime) -> str:
    """生效态派生(与结算 _in_window 同口径,服务端推导,前端不自算):
    disabled > ended(过 end_at)> scheduled(未到 start_at)> running。"""
    if status == "disabled":
        return "disabled"
    if end_at and now >= end_at:
        return "ended"
    if start_at and now < start_at:
        return "scheduled"
    return "running"


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
    """活动列表(运营闭环 2026-09-27):每行带发放/核销聚合与生效态派生。

    聚合用标量子查询而非 JOIN+GROUP BY —— 券行×核销行会互相翻倍计数;
    uq_user_promo(promotion_id 首列)与 idx_promotion_redemptions_promo
    兜住子查询走索引,LIMIT 100 规模下无压力。
    """
    now = datetime.now()
    async with _merchant_writer_engine().connect() as conn:
        rows = (
            await conn.execute(
                text(
                    "SELECT p.id::text, p.name, p.promo_type, p.threshold_amount, p.discount_value, "
                    "p.scope_type, p.scope_value, p.status, p.start_at, p.end_at, p.total_quota, "
                    "(SELECT COUNT(*) FROM user_coupons uc WHERE uc.promotion_id = p.id) AS issued_count, "
                    "(SELECT COUNT(*) FROM user_coupons uc WHERE uc.promotion_id = p.id AND uc.status = 'used') AS used_count, "
                    "(SELECT COUNT(*) FROM promotion_redemptions pr WHERE pr.promotion_id = p.id) AS redemption_count, "
                    "(SELECT COALESCE(SUM(pr.discount_amount), 0) FROM promotion_redemptions pr WHERE pr.promotion_id = p.id) AS discount_total "
                    "FROM promotions p ORDER BY p.created_at DESC LIMIT 100"
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
            "totalQuota": r["total_quota"],
            "claimedCount": int(r["issued_count"]),  # 已发放张数(claimed+used 都占额度)
            "usedCount": int(r["used_count"]),
            "redemptionCount": int(r["redemption_count"]),
            "discountTotal": float(r["discount_total"]),
            "effectiveStatus": _effective_status(r["status"], r["start_at"], r["end_at"], now),
        }
        for r in rows
    ]


async def create_promotion(payload: dict, operator: str) -> dict:
    name = str(payload.get("name") or "").strip()
    promo_type = payload.get("promoType")
    value = payload.get("value")
    if not name or promo_type not in PROMO_TYPES or value is None:
        return {"error": "name/promoType/value 必传;promoType ∈ full_reduction|discount|coupon"}
    try:
        start_at = _parse_ts(payload.get("startAt"))
        end_at = _parse_ts(payload.get("endAt"))
        if err := _validate_window(start_at, end_at):
            return {"error": err}
        total_quota = _normalize_quota(promo_type, payload.get("totalQuota"))
    except ValueError as err:
        return {"error": f"时间窗/发放上限不合法:{err}"}
    promo_id = str(uuid.uuid4())
    async with _merchant_writer_engine().begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO promotions (id, name, promo_type, threshold_amount, discount_value, scope_type, scope_value, "
                "start_at, end_at, total_quota) "
                "VALUES (CAST(:id AS uuid), :name, :pt, :th, :v, :st, :sv, COALESCE(:sa, NOW()), :ea, :tq)"
            ).bindparams(
                id=promo_id, name=name, pt=promo_type,
                th=payload.get("threshold"), v=float(value),
                st=payload.get("scopeType") or "all", sv=payload.get("scopeValue"),
                sa=start_at, ea=end_at, tq=total_quota,
            )
        )
    await _audit("promo_create", operator, {
        "id": promo_id, "name": name, "promoType": promo_type,
        "startAt": start_at.isoformat() if start_at else None,
        "endAt": end_at.isoformat() if end_at else None,
        "totalQuota": total_quota,
    })
    return {"id": promo_id, "name": name}


async def update_promotion(promotion_id: str, patch: dict, operator: str) -> dict:
    """编辑活动(PATCH 单一实现,2026-09-27 运营闭环;路由只留 perm 闸与审计)。

    patch 只收**携带的字段**(key 存在才参与更新,未携带保持不变)——
    调用方须区分「未传」与「传 null」(网关侧用 pydantic model_fields_set)。
    语义:startAt 传空 = 保持原值(start_at NOT NULL 无「清空」义);endAt
    传空 = 置 NULL(长期);totalQuota 传 null = 清除上限;窗口校验基于合并后
    的起止(单改一端与库内另一端合判)。上限可缩到已发放数以下 —— 量控闸在
    领取时点,缩额只冻结后续发放,不追回已发券。
    """
    async with _merchant_writer_engine().begin() as conn:
        row = (
            await conn.execute(
                text(
                    "SELECT name, promo_type, threshold_amount, discount_value, scope_type, scope_value, "
                    "start_at, end_at, total_quota FROM promotions WHERE id = CAST(:id AS uuid)"
                ).bindparams(id=promotion_id)
            )
        ).mappings().first()
        if not row:
            return {"error": "活动不存在"}

        name = row["name"]
        if patch.get("name") is not None:
            name = str(patch["name"]).strip()
            if not name:
                return {"error": "name 不能为空"}
        threshold = patch["threshold"] if "threshold" in patch else row["threshold_amount"]
        value = row["discount_value"]
        if patch.get("value") is not None:
            value = float(patch["value"])
        scope_type = patch["scopeType"] if "scopeType" in patch else row["scope_type"]
        scope_value = patch["scopeValue"] if "scopeValue" in patch else row["scope_value"]
        start_at = row["start_at"]
        if "startAt" in patch:
            start_at = _parse_ts(patch["startAt"]) or row["start_at"]
        end_at = row["end_at"]
        if "endAt" in patch:
            end_at = _parse_ts(patch["endAt"])
        try:
            if err := _validate_window(start_at, end_at):
                return {"error": err}
            total_quota = row["total_quota"]
            if "totalQuota" in patch:
                total_quota = _normalize_quota(row["promo_type"], patch["totalQuota"])
        except ValueError as err:
            return {"error": f"时间窗/发放上限不合法:{err}"}

        await conn.execute(
            text(
                "UPDATE promotions SET name = :name, threshold_amount = :th, discount_value = :v, "
                "scope_type = :st, scope_value = :sv, start_at = :sa, end_at = :ea, total_quota = :tq "
                "WHERE id = CAST(:id AS uuid)"
            ).bindparams(
                id=promotion_id, name=name, th=threshold, v=value,
                st=scope_type or "all", sv=scope_value,
                sa=start_at, ea=end_at, tq=total_quota,
            )
        )
    await _audit("promo_update", operator, {
        "id": promotion_id, "name": name,
        "startAt": start_at.isoformat() if start_at else None,
        "endAt": end_at.isoformat() if end_at else None,
        "totalQuota": total_quota, "scopeType": scope_type, "scopeValue": scope_value,
    })
    return {"id": promotion_id, "name": name}


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
    幂等:同活动×同订单只记一次。订单不存在/未启用活动/窗口外 → error。
    窗口判定与结算 _in_window 同口径(2026-09-27 运营闭环):消除「列表看着
    已结束/未开始,补录核销却照收」的口径分裂。
    """
    now = datetime.now()
    async with _merchant_writer_engine().connect() as conn:
        promo = (
            await conn.execute(
                text("SELECT promo_type, threshold_amount, discount_value, status, start_at, end_at "
                     "FROM promotions WHERE id = CAST(:id AS uuid)")
                .bindparams(id=promotion_id)
            )
        ).mappings().first()
        if not promo:
            return {"error": "活动不存在"}
        if promo["status"] != "active":
            return {"error": "活动已停用,不可核销"}
        if promo["end_at"] and now >= promo["end_at"]:
            return {"error": "活动已结束,不可核销"}
        if promo["start_at"] and now < promo["start_at"]:
            return {"error": "活动尚未开始,不可核销"}
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
    """用户领券(仅 coupon 型活动;同活动同用户一次;须在售;发放上限量控)。

    量控闸(2026-09-27 运营闭环):total_quota 非空时 COUNT(已发放,含已核销)
    达上限即拒。应用层闸与上方查重同处一个并发窗口 —— 并发抢领瞬间可能超发
    个位数(每人限领 1 的 uq_user_promo 仍是最终防线),运营口径可接受;
    预算上限/每人限领 N 张明确不做(触碰结算资金口径 20-D3,留下一轮)。
    """
    async with _merchant_writer_engine().connect() as conn:
        promo = (
            await conn.execute(
                text("SELECT promo_type, status, total_quota FROM promotions WHERE id = CAST(:id AS uuid)").bindparams(id=promotion_id)
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
        if promo["total_quota"] is not None:
            issued = (
                await conn.execute(
                    text("SELECT COUNT(*) FROM user_coupons WHERE promotion_id = CAST(:id AS uuid)").bindparams(id=promotion_id)
                )
            ).scalar()
            if int(issued or 0) >= promo["total_quota"]:
                return {"error": "券发放已达上限,无法领取"}
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


async def record_promo_redemption(conn, promotion_id: str | None, order_id: str, discount: float) -> None:
    """核销流水统一落库(gateway/engine 结算共用,2026-09-23 收口双实现):
    promotion_redemptions 一行 = 订单×优惠×立减额;无优惠不落。"""
    if not promotion_id or discount <= 0:
        return
    await conn.execute(
        text("INSERT INTO promotion_redemptions (promotion_id, order_id, discount_amount) "
             "VALUES (CAST(:pid AS uuid), :oid, :amt)").bindparams(
                 pid=promotion_id, oid=order_id, amt=round(discount, 2))
    )


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
