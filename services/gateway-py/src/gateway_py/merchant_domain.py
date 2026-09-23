"""商户领域服务 — 移植 apps/merchant/src/services/merchantDomainService.ts(方法级 1:1)。"""

from __future__ import annotations

import datetime as _dt
import json
import os
import random
import secrets
from typing import Any

from sqlalchemy import text

from .merchant_db import ensure_merchant_tables, merchant_engine


def _merchant_id() -> str:
    return os.environ.get("MERCHANT_ID", "aurora")


def _api_secret() -> str:
    return os.environ.get("MERCHANT_API_SECRET") or os.environ.get("API_SECRET") or "aurora_secret_key_8899"


def _now_ms() -> int:
    import time

    return int(time.time() * 1000)


def _iso(row: Any, key: str) -> str:
    val = row.get(key)
    if not val:
        return _dt.datetime.now().isoformat()
    if val.tzinfo is None:
        # 库为 TIMESTAMP WITHOUT TIME ZONE 且 TimeZone=UTC(实弹:naive 值被
        # 前端 new Date 按本地解析,下单时间显示早 8 小时)—— 补 UTC 时区后
        # 转本地,产出带偏移的 ISO,JS 端渲染即正确
        val = val.replace(tzinfo=_dt.UTC)
    return val.astimezone().isoformat()


def _order_from_row(row: Any, items: list[dict]) -> dict:
    _discount = float(row.get("discount_amount") or 0)
    return {
        "orderId": row["order_id"],
        "userId": row["customer_id"],
        "status": row["status"],
        # 账本语义(3c4c843 起):total_amount=实付,discount_amount=优惠;
        # originalAmount=原价合计,供订单页原价/优惠/实付三行展示
        "totalAmount": float(row["total_amount"]),
        "discountAmount": _discount,
        "originalAmount": round(float(row["total_amount"]) + _discount, 2),
        "currency": row["currency"] or "CNY",
        "createdAt": _iso(row, "created_at"),
        "shippingAddress": row["shipping_address"] or {},
        "tracking": row["tracking_info"],
        "isAddressModifiable": bool(row["is_address_modifiable"]),
        "isReturnable": bool(row["is_returnable"]),
        "items": [
            {
                "skuId": item["sku_code"],
                "productId": item["spu_id"] or item["sku_code"],
                "title": item["title"],
                "quantity": item["quantity"],
                "price": float(item["price"]) if item["price"] is not None else None,
                "imageUrl": item["image_url"],
                "specSummary": item["spec_summary"],
            }
            for item in items
        ],
    }


async def _fetch_items(conn: Any, order_id: str) -> list[dict]:
    rows = (await conn.execute(text("SELECT * FROM merchant_order_items WHERE order_id = :oid"), {"oid": order_id})).mappings().all()
    return [dict(r) for r in rows]


async def _spu_to_product(conn: Any, spu: Any) -> dict:
    sku_rows = (
        await conn.execute(
            text("SELECT * FROM merchant_skus WHERE spu_id = :sid ORDER BY price ASC"), {"sid": spu["id"]}
        )
    ).mappings().all()

    skus = []
    for row in sku_rows:
        skus.append(
            {
                "skuCode": row["sku_code"],
                "skuTitle": row["sku_title"],
                "specAttributes": row["spec_attributes"],
                "price": float(row["price"]),
                "originalPrice": float(row["original_price"]) if row["original_price"] is not None else None,
                "stock": row["stock"],
                "imageUrl": row["image_url"] or spu["main_image"],
                "barCode": row["barcode"],
            }
        )

    total_stock = sum(s["stock"] for s in skus)
    min_price = min((s["price"] for s in skus), default=0)
    with_orig = [s["originalPrice"] for s in skus if s["originalPrice"] is not None]
    min_orig = min(with_orig) if with_orig else None

    return {
        "productId": spu["spu_code"],
        "spuId": str(spu["id"]),
        "title": spu["title"],
        "subtitle": spu["subtitle"],
        "description": spu["description"],
        "price": min_price,
        "originalPrice": min_orig,
        "stock": total_stock,
        "category": spu["category"],
        "brand": spu["brand"],
        "imageUrl": spu["main_image"],
        "detailImages": spu["banner_images"] or [],
        "specDimensions": spu["spec_dimensions"] or [],
        "skus": skus,
        "specs": spu["specs"] or {},
        "isAvailable": total_stock > 0,
    }


async def get_user_info(params: dict) -> dict | None:
    await ensure_merchant_tables()
    async with merchant_engine().connect() as conn:
        conditions = []
        q: dict = {}
        if params.get("userId"):
            q["uid"] = params["userId"]
            conditions.append("(customer_id = :uid OR customer_id = 'CUST-8801')")
        elif params.get("userEmail"):
            q["email"] = params["userEmail"]
            conditions.append("email = :email")
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        row = (await conn.execute(text(f"SELECT * FROM merchant_customers {where} LIMIT 1"), q)).mappings().first()
        if row is None:
            row = (
                await conn.execute(
                    text("SELECT * FROM merchant_customers WHERE customer_id = :cid LIMIT 1"), {"cid": "CUST-8801"}
                )
            ).mappings().first()
        if row is None:
            return None
        return {
            "userId": row["customer_id"],
            "name": row["name"],
            "phone": row["phone"],
            "email": row["email"],
            "memberLevel": row["member_level"],
            "addresses": row["addresses"] or [],
            "tags": row["tags"] or [],
        }


async def list_orders(params: dict) -> list[dict]:
    await ensure_merchant_tables()
    cust_id = params.get("userId") or "CUST-8801"
    async with merchant_engine().connect() as conn:
        # 2026-09-05:严格归属匹配——不再 OR CUST-8801 混入演示用户的订单
        conditions = ["customer_id = :c1"]
        q: dict = {"c1": cust_id}
        if params.get("status"):
            q["status"] = params["status"].upper()
            conditions.append("status = :status")
        limit = params.get("limit") or 10
        sql = (
            f"SELECT * FROM merchant_orders WHERE {' AND '.join(conditions)} "
            "ORDER BY created_at DESC LIMIT :lim"
        )
        q["lim"] = limit
        rows = (await conn.execute(text(sql), q)).mappings().all()
        results = []
        for row in rows:
            items = await _fetch_items(conn, row["order_id"])
            results.append(_order_from_row(row, items))
        return results


async def get_order_detail(order_id: str) -> dict | None:
    await ensure_merchant_tables()
    async with merchant_engine().connect() as conn:
        row = (
            await conn.execute(text("SELECT * FROM merchant_orders WHERE order_id = :oid LIMIT 1"), {"oid": order_id})
        ).mappings().first()
        if row is None:
            return None
        items = await _fetch_items(conn, row["order_id"])
        return _order_from_row(row, items)


async def execute_order_action(req: dict, signature: str | None = None) -> dict:
    await ensure_merchant_tables()
    action_id = f"ACT_{_now_ms()}_{secrets.token_hex(2)}"

    async with merchant_engine().begin() as conn:
        # 幂等防重
        if req.get("idempotencyKey"):
            log = (
                await conn.execute(
                    text("SELECT * FROM merchant_audit_logs WHERE idempotency_key = :ik LIMIT 1"),
                    {"ik": req["idempotencyKey"]},
                )
            ).mappings().first()
            if log is not None:
                result = log["result"]
                if isinstance(result, str):
                    result = json.loads(result)
                return {
                    **(result or {}),
                    "success": True,
                    "actionType": req["actionType"],
                    "orderId": req["orderId"],
                    "actionId": str(log["id"]),
                    "message": "幂等防重响应：已成功执行过该指令",
                }

        order = (
            await conn.execute(
                text("SELECT * FROM merchant_orders WHERE order_id = :oid LIMIT 1"), {"oid": req["orderId"]}
            )
        ).mappings().first()
        if order is None:
            return {
                "success": False,
                "actionType": req["actionType"],
                "orderId": req["orderId"],
                "message": f"订单 [{req['orderId']}] 不存在",
            }
        shipping = order["shipping_address"] or {}

        if req["actionType"] == "MODIFY_ADDRESS":
            if bool(order["is_address_modifiable"]) is False or order["status"] in ("SHIPPED", "DELIVERED"):
                return {
                    "success": False,
                    "actionType": "MODIFY_ADDRESS",
                    "orderId": req["orderId"],
                    "message": f"修改失败：订单当前状态为【{order['status']}】，包裹已发出或完结，禁止修改地址。",
                }

            new_addr = req.get("newAddress") or {}
            address_str = new_addr if isinstance(new_addr, str) else (new_addr.get("fullAddress") or "")

            updated = {
                "recipientName": (None if isinstance(new_addr, str) else new_addr.get("recipientName"))
                or shipping.get("recipientName")
                or "客户",
                "phone": (None if isinstance(new_addr, str) else new_addr.get("phone"))
                or shipping.get("phone")
                or "13800000000",
                "fullAddress": address_str,
            }
            await conn.execute(
                text("UPDATE merchant_orders SET shipping_address = :a WHERE order_id = :oid"),
                {"a": json.dumps(updated, ensure_ascii=False), "oid": req["orderId"]},
            )
            result_payload = {"updatedAddress": address_str, "message": "收货地址修改成功"}
            await conn.execute(
                text(
                    "INSERT INTO merchant_audit_logs (action_type, order_id, idempotency_key, operator, payload, result) "
                    "VALUES (:at, :oid, :ik, 'AGENT_SPI', :p, :r)"
                ),
                {
                    "at": "MODIFY_ADDRESS",
                    "oid": req["orderId"],
                    "ik": req.get("idempotencyKey") or action_id,
                    "p": json.dumps({**req, "signature": signature}, ensure_ascii=False),
                    "r": json.dumps(result_payload, ensure_ascii=False),
                },
            )
            return {
                "success": True,
                "actionType": "MODIFY_ADDRESS",
                "orderId": req["orderId"],
                "actionId": action_id,
                **result_payload,
            }

        if req["actionType"] == "REQUEST_REFUND":
            refund_id = f"RF_AURORA_{_now_ms()}"
            await conn.execute(
                text("UPDATE merchant_orders SET status = 'REFUNDED', is_returnable = FALSE WHERE order_id = :oid"),
                {"oid": req["orderId"]},
            )
            result_payload = {
                "refundId": refund_id,
                "refundedAmount": req.get("refundAmount") or float(order["total_amount"]),
                "message": "极光潮品退款已受理入账",
            }
            await conn.execute(
                text(
                    "INSERT INTO merchant_audit_logs (action_type, order_id, idempotency_key, operator, payload, result) "
                    "VALUES (:at, :oid, :ik, 'AGENT_SPI', :p, :r)"
                ),
                {
                    "at": "REQUEST_REFUND",
                    "oid": req["orderId"],
                    "ik": req.get("idempotencyKey") or action_id,
                    "p": json.dumps({**req, "signature": signature}, ensure_ascii=False),
                    "r": json.dumps(result_payload, ensure_ascii=False),
                },
            )
            return {
                "success": True,
                "actionType": "REQUEST_REFUND",
                "orderId": req["orderId"],
                "actionId": action_id,
                **result_payload,
            }

        return {
            "success": False,
            "actionType": req["actionType"],
            "orderId": req["orderId"],
            "message": f"未知的操作指令: {req['actionType']}",
        }


async def search_products(query: str | None = None, category: str | None = None, limit: int = 10) -> list[dict]:
    await ensure_merchant_tables()
    async with merchant_engine().connect() as conn:
        conditions = ["status = 'ON_SALE'"]
        q: dict = {}
        if query:
            q["kw"] = f"%{query}%"
            conditions.append("(title ILIKE :kw OR subtitle ILIKE :kw OR category ILIKE :kw OR description ILIKE :kw)")
        if category:
            q["cat"] = category
            conditions.append("category = :cat")
        q["lim"] = limit
        rows = (
            await conn.execute(
                text(
                    f"SELECT * FROM merchant_spus WHERE {' AND '.join(conditions)} ORDER BY created_at ASC LIMIT :lim"
                ),
                q,
            )
        ).mappings().all()
        return [await _spu_to_product(conn, r) for r in rows]


async def get_product_detail(product_id_or_id: str) -> dict | None:
    await ensure_merchant_tables()
    import re as _re

    is_uuid = bool(_re.match(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$", product_id_or_id))
    async with merchant_engine().connect() as conn:
        if is_uuid:
            spu = (
                await conn.execute(
                    text("SELECT * FROM merchant_spus WHERE id = :pid OR spu_code = :pid LIMIT 1"),
                    {"pid": product_id_or_id},
                )
            ).mappings().first()
        else:
            spu = (
                await conn.execute(
                    text("SELECT * FROM merchant_spus WHERE spu_code = :pid LIMIT 1"), {"pid": product_id_or_id}
                )
            ).mappings().first()
        if spu is None:
            return None
        return await _spu_to_product(conn, spu)


async def place_order(params: dict) -> dict:
    await ensure_merchant_tables()
    async with merchant_engine().connect() as conn:
        sku = (
            await conn.execute(
                text(
                    "SELECT s.*, p.title as spu_title, p.main_image as spu_image, p.id as spu_id, p.spu_code "
                    "FROM merchant_skus s JOIN merchant_spus p ON s.spu_id = p.id "
                    "WHERE s.sku_code = :code LIMIT 1"
                ),
                {"code": params["skuCode"]},
            )
        ).mappings().first()
        if sku is None:
            return {"success": False, "message": f"SKU 规格 [{params['skuCode']}] 不存在或已下架"}
        quantity = params.get("quantity") or 1
        if sku["stock"] < quantity:
            return {"success": False, "message": f"库存不足：{sku['sku_title']} 当前剩余 {sku['stock']} 件"}

        order_id = f"AURORA-ORD-2026-{random.randint(1000, 9999)}"
        pay_amount = float(sku["price"]) * quantity
        spec_summary = " / ".join(f"{k}:{v}" for k, v in (sku["spec_attributes"] or {}).items())

    # 券校验/核销冲突要回滚整个写入事务(库存+订单),_CartError 在块外翻译成
    # success False —— 严禁在事务块内 return 造成半截写入被隐式提交
    try:
        async with merchant_engine().begin() as conn:
            # 优惠引擎(20-D3):SAVEPOINT 隔离,失败按原价结算不毒化事务
            try:
                promo = await _resolve_promotion(
                    conn,
                    params["customerId"],
                    round(pay_amount, 2),
                    {str(sku["spu_code"])} if "spu_code" in sku else None,
                    coupon_id=params.get("couponId"),
                    skip_coupon=bool(params.get("skipCoupon")),
                )
            except _CartError:
                raise
            except Exception as promo_err:
                print(f"[MerchantDomain] 优惠计算失败,按原价结算: {promo_err}")
                promo = _empty_promo()
            discount = promo["discount"]
            promo_name = promo["promo_name"]

            await conn.execute(
                text("UPDATE merchant_skus SET stock = stock - :qty WHERE sku_code = :code"),
                {"qty": quantity, "code": params["skuCode"]},
            )
            await conn.execute(
                text(
                    "INSERT INTO merchant_orders (order_id, customer_id, status, total_amount, discount_amount, currency, "
                    "shipping_address, is_returnable, is_address_modifiable) "
                    "VALUES (:oid, :cid, 'PAID', :amt, :disc, 'CNY', :addr, TRUE, TRUE)"
                ),
                {
                    "oid": order_id,
                    "cid": params["customerId"],
                    "amt": round(pay_amount - discount, 2),
                    "disc": round(discount, 2),
                    "addr": json.dumps(
                        {
                            "recipientName": params.get("recipientName", "张伟"),
                            "phone": params.get("recipientPhone", "13800138000"),
                            "fullAddress": params.get("shippingAddress") or "北京市海淀区中关村南大街1号院8号楼1201室",
                        },
                        ensure_ascii=False,
                    ),
                },
            )
            if promo["coupon_row_id"]:
                from engine_py.analytics import promotions as _promo_svc

                # 条件核销防双花:False=该券已被并发订单用掉,整体回滚拒单
                if not await _promo_svc.mark_coupon_used(conn, promo["coupon_row_id"], order_id):
                    raise _CartError("优惠券已被使用，请刷新券包后重试")
            await _record_promo_redemption(conn, (promo["activity"] or {}).get("promo_id"), order_id, (promo["activity"] or {}).get("discount", 0.0))
            await _record_promo_redemption(conn, (promo["coupon"] or {}).get("promo_id"), order_id, (promo["coupon"] or {}).get("discount", 0.0))
            await conn.execute(
                text(
                    "INSERT INTO merchant_order_items (order_id, spu_id, sku_code, title, sku_title, quantity, price, "
                    "image_url, spec_summary) VALUES (:oid, :spu, :code, :t, :st, :qty, :price, :img, :spec)"
                ),
                {
                    "oid": order_id,
                    "spu": str(sku["spu_id"]),
                    "code": sku["sku_code"],
                    "t": sku["spu_title"],
                    "st": sku["sku_title"],
                    "qty": quantity,
                    "price": sku["price"],
                    "img": sku["image_url"] or sku["spu_image"],
                    "spec": spec_summary,
                },
            )
    except _CartError as err:
        return {"success": False, "message": err.message}
    return {
        "success": True,
        "orderId": order_id,
        "originalAmount": round(pay_amount, 2),
        "discount": round(discount, 2),
        "promoName": promo_name,
        "payableAmount": round(pay_amount - discount, 2),
    }


async def ship_order(order_id: str, carrier_code: str, tracking_no: str) -> dict:
    await ensure_merchant_tables()
    now = _dt.datetime.now()

    def _t(hours: int) -> str:
        return (now - _dt.timedelta(hours=hours)).isoformat()

    tracking_info = {
        "carrier": "顺丰速运" if carrier_code == "SF" else (carrier_code or "顺丰速运"),
        "trackingNumber": tracking_no,
        "status": "IN_TRANSIT",
        "latestLocation": "北京市朝阳区三里屯派件部",
        "timeline": [
            {
                "time": _t(4),
                "status": "揽收成功",
                "location": "极光潮品华北智能一号仓",
                "description": "包裹已由顺丰速运揽收并打包出库",
            },
            {
                "time": _t(2),
                "status": "运输中",
                "location": "北京顺丰转运中心",
                "description": "快件已到达北京顺丰转运中心，正发往朝阳区三里屯营业点",
            },
            {
                "time": now.isoformat(),
                "status": "派送中",
                "location": "北京市朝阳区三里屯派件部",
                "description": "顺丰快递员已接单，正在派送途中 (联系电话: 95338)",
            },
        ],
    }
    async with merchant_engine().begin() as conn:
        result = await conn.execute(
            text(
                "UPDATE merchant_orders SET status = 'SHIPPED', tracking_info = :ti, is_address_modifiable = FALSE "
                "WHERE order_id = :oid"
            ),
            {"ti": json.dumps(tracking_info, ensure_ascii=False), "oid": order_id},
        )
    updated = result.rowcount or 0
    return {
        "success": updated > 0,
        "message": "发货成功，已流转为已发货状态并锁定地址" if updated > 0 else "订单不存在",
    }


async def get_admin_dashboard_data() -> dict:
    await ensure_merchant_tables()
    async with merchant_engine().connect() as conn:
        orders = [dict(r) for r in (await conn.execute(text("SELECT * FROM merchant_orders ORDER BY created_at DESC LIMIT 50"))).mappings().all()]
        audit_logs = [dict(r) for r in (await conn.execute(text("SELECT * FROM merchant_audit_logs ORDER BY created_at DESC LIMIT 50"))).mappings().all()]
        spus = [dict(r) for r in (await conn.execute(text("SELECT * FROM merchant_spus ORDER BY created_at ASC"))).mappings().all()]
        skus = [
            dict(r)
            for r in (
                await conn.execute(
                    text(
                        "SELECT s.*, p.title as spu_title, p.brand, p.category "
                        "FROM merchant_skus s JOIN merchant_spus p ON s.spu_id = p.id "
                        "ORDER BY p.title, s.price ASC"
                    )
                )
            ).mappings().all()
        ]

        def _jsonify(rows: list[dict]) -> list[dict]:
            out = []
            for r in rows:
                out.append({k: (v.isoformat() if isinstance(v, _dt.datetime) else v) for k, v in r.items()})
            return out

        return {
            "orders": _jsonify(orders),
            "auditLogs": _jsonify(audit_logs),
            "spus": _jsonify(spus),
            "inventory": [
                {
                    "sku_code": r["sku_code"],
                    "item_title": r["sku_title"],
                    "selling_price": float(r["price"]),
                    "available_qty": r["stock"],
                    "category_name": r["category"],
                    "spec_attributes": r["spec_attributes"],
                }
                for r in skus
            ],
            "skus": _jsonify(skus),
        }


async def get_customer_addresses(customer_id: str = "CUST-8801") -> list[dict]:
    await ensure_merchant_tables()
    async with merchant_engine().connect() as conn:
        row = (
            await conn.execute(
                text("SELECT addresses FROM merchant_customers WHERE customer_id = :cid LIMIT 1"), {"cid": customer_id}
            )
        ).mappings().first()
    if row is None or not isinstance(row["addresses"], list):
        return []
    return row["addresses"]


async def save_customer_address(customer_id: str, addr: dict) -> dict:
    await ensure_merchant_tables()
    current = await get_customer_addresses(customer_id)

    full_addr = (
        addr.get("fullAddress")
        or f"{addr.get('province') or ''}{addr.get('city') or ''}{addr.get('district') or ''}{addr.get('detailAddress') or ''}".strip()
        or "北京市海淀区中关村南大街1号院"
    )

    target_id = addr.get("id") or f"ADDR_{_now_ms()}_{secrets.token_hex(2)}"
    should_be_default = bool(addr.get("isDefault") or not current)

    formatted = {
        "id": target_id,
        "recipientName": addr["recipientName"],
        "phone": addr["phone"],
        "province": addr.get("province"),
        "city": addr.get("city"),
        "district": addr.get("district"),
        "detailAddress": addr.get("detailAddress"),
        "fullAddress": full_addr,
        "isDefault": should_be_default,
    }

    updated = [dict(a) for a in current]
    if should_be_default:
        updated = [{**a, "isDefault": False} for a in updated]

    existing = next((i for i, a in enumerate(updated) if a.get("id") == target_id), -1)
    if existing >= 0:
        updated[existing] = formatted
    elif should_be_default:
        updated.insert(0, formatted)
    else:
        updated.append(formatted)

    async with merchant_engine().begin() as conn:
        await conn.execute(
            text("UPDATE merchant_customers SET addresses = :a WHERE customer_id = :cid"),
            {"a": json.dumps(updated, ensure_ascii=False), "cid": customer_id},
        )
    return {"success": True, "address": formatted, "addresses": updated}


class _CartError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


async def _resolve_promotion(
    conn: Any,
    customer_id: str,
    amount: float,
    scope: set[str] | None,
    coupon_id: str | None = None,
    skip_coupon: bool = False,
) -> dict:
    """结算优惠决议(服务端唯一算价点,20-D3;选券重构 2026-09-22)。

    叠加语义(2026-09-22 用户决议,替代先前的互斥版):满减/折扣活动自动必享,
    券由用户自选且可叠加 —— 活动先减,券按余额抵扣封顶,金额永不为负;满减
    门槛始终按原价合计判定(行业惯例,非活动后余额)。

    - coupon_id 指定 → 自选券与活动叠加:券按(原价-活动优惠)余额计算,不可用
      抛 _CartError 如实拒单(严禁静默按全款落账 —— 3c4c843 同族教训);活动已
      覆盖全部金额时券零抵扣,同样拒单让用户保留券面。
    - skip_coupon → 用户明确不用券(商城页「不使用优惠券」),仅活动。
    - 两者皆缺省 → 历史自动择优(活动 vs 券取优惠大者,单选不叠加;仅旧调用
      兼容 —— 商城结算页总是显式传券语义,聊天通道已改走共享的
      resolve_stacked_promotions 叠加)。
    返回结构化 activity/coupon 两笔(核销流水分落 promotion_redemptions)+
    兼容字段 discount(合计)/promo_name(组合)/coupon_row_id(核销券)。
    """
    from engine_py.analytics.promotion_engine import (
        best_for_amount,
        best_user_coupon,
        resolve_stacked_promotions,
    )

    result: dict = {
        "activity": None,
        "coupon": None,
        "discount": 0.0,
        "promo_name": None,
        "coupon_row_id": None,
    }
    if coupon_id:
        # 自选券与活动叠加;券不可用/零抵扣由共享决议抛 ValueError,如实拒单
        try:
            stacked = await resolve_stacked_promotions(conn, customer_id, amount, scope, coupon_row_id=coupon_id)
        except ValueError as err:
            raise _CartError(str(err)) from err
        act, cpn = stacked["activity"], stacked["coupon"]
        result["activity"] = (
            {"discount": act["discount"], "name": act["name"], "promo_id": act["promo_id"]} if act else None
        )
        result["coupon"] = (
            {
                "discount": cpn["discount"], "name": cpn["name"],
                "row_id": cpn["coupon_row_id"], "promo_id": cpn["promotion_id"],
            }
            if cpn
            else None
        )
    elif skip_coupon:
        stacked = await resolve_stacked_promotions(conn, customer_id, amount, scope, auto_pick_coupon=False)
        act = stacked["activity"]
        result["activity"] = (
            {"discount": act["discount"], "name": act["name"], "promo_id": act["promo_id"]} if act else None
        )
    else:
        # 历史自动择优:活动 vs 券取优惠大者,单选不叠加(旧调用/契约兼容)
        auto = await best_for_amount(conn, amount, scope, exclude_coupon=True)
        user_coupon = await best_user_coupon(conn, customer_id, amount)
        if user_coupon and (not auto or user_coupon["discount"] > auto["discount"]):
            result["coupon"] = {
                "discount": user_coupon["discount"], "name": user_coupon["name"],
                "row_id": user_coupon["coupon_row_id"], "promo_id": user_coupon["promotion_id"],
            }
        elif auto:
            result["activity"] = {"discount": auto["discount"], "name": auto["name"], "promo_id": auto["promo_id"]}
    result["discount"] = round(
        (result["activity"] or {}).get("discount", 0.0) + (result["coupon"] or {}).get("discount", 0.0), 2
    )
    names = [p["name"] for p in (result["activity"], result["coupon"]) if p]
    result["promo_name"] = " + ".join(names) if names else None
    result["coupon_row_id"] = (result["coupon"] or {}).get("row_id")
    return result


def _empty_promo() -> dict:
    """优惠引擎异常回落形状(与 _resolve_promotion 返回同构):按原价结算、
    零优惠、不核销。2026-09-23 code-review 硬伤:两处内联兜底字典缺
    activity/coupon 键,后续 (promo["activity"] or {}) 必抛 KeyError ——
    促销表缺失等异常时「失败按原价结算」失效、整单 500。"""
    return {
        "activity": None,
        "coupon": None,
        "discount": 0.0,
        "promo_name": None,
        "coupon_row_id": None,
    }


async def _record_promo_redemption(conn: Any, promo_id: str | None, order_id: str, discount: float) -> None:
    """核销流水与引擎侧账本对齐(mall_domain 同表);无优惠不落。"""
    if not promo_id or discount <= 0:
        return
    await conn.execute(
        text("INSERT INTO promotion_redemptions (promotion_id, order_id, discount_amount) "
             "VALUES (CAST(:pid AS uuid), :oid, :amt)").bindparams(pid=promo_id, oid=order_id, amt=round(discount, 2))
    )


async def create_order_from_cart(
    customer_id: str,
    items: list[dict],
    shipping_address: dict,
    coupon_id: str | None = None,
    skip_coupon: bool = False,
) -> dict:
    if not items:
        return {"success": False, "message": "结算购物车条目不能为空"}
    await ensure_merchant_tables()

    order_id = f"AURORA-ORD-2026-{random.randint(1000, 9999)}"
    items_to_insert: list[dict] = []
    total_amount = 0.0

    try:
        async with merchant_engine().begin() as conn:
            for item in items:
                sku = (
                    await conn.execute(
                        text(
                            "SELECT s.*, p.title as spu_title, p.main_image as spu_image, p.id as spu_id, p.spu_code "
                            "FROM merchant_skus s JOIN merchant_spus p ON s.spu_id = p.id "
                            "WHERE s.sku_code = :code FOR UPDATE"
                        ),
                        {"code": item["skuCode"]},
                    )
                ).mappings().first()
                if sku is None:
                    raise _CartError(f"商品规格 [{item['skuCode']}] 不存在")
                quantity = item.get("quantity") or 1
                if sku["stock"] < quantity:
                    raise _CartError(f"商品 [{sku['sku_title']}] 库存不足，当前仅剩 {sku['stock']} 件")

                await conn.execute(
                    text("UPDATE merchant_skus SET stock = stock - :qty WHERE sku_code = :code"),
                    {"qty": quantity, "code": item["skuCode"]},
                )
                total_amount += float(sku["price"]) * quantity
                spec_summary = " / ".join(f"{k}:{v}" for k, v in (sku["spec_attributes"] or {}).items())
                items_to_insert.append(
                    {
                        "spuId": str(sku["spu_id"]),
                        "spuCode": str(sku["spu_code"]),
                        "skuCode": sku["sku_code"],
                        "spuTitle": sku["spu_title"],
                        "skuTitle": sku["sku_title"],
                        "quantity": quantity,
                        "price": float(sku["price"]),
                        "imageUrl": sku["image_url"] or sku["spu_image"],
                        "specSummary": spec_summary,
                    }
                )

            # 优惠引擎(20-D3):SAVEPOINT 隔离,失败按原价不毒化事务;
            # 选券/不用券语义见 _resolve_promotion(2026-09-22 结算页重构)
            try:
                promo = await _resolve_promotion(
                    conn,
                    customer_id,
                    round(total_amount, 2),
                    {str(oi["spuCode"]) for oi in items_to_insert},
                    coupon_id=coupon_id,
                    skip_coupon=skip_coupon,
                )
            except _CartError:
                raise
            except Exception as promo_err:
                print(f"[MerchantDomain] 购物车结算优惠计算失败,按原价: {promo_err}")
                promo = _empty_promo()
            discount = promo["discount"]
            promo_name = promo["promo_name"]

            await conn.execute(
                text(
                    "INSERT INTO merchant_orders (order_id, customer_id, status, total_amount, discount_amount, currency, "
                    "shipping_address, is_returnable, is_address_modifiable) "
                    "VALUES (:oid, :cid, 'PAID', :amt, :disc, 'CNY', :addr, TRUE, TRUE)"
                ),
                {
                    "oid": order_id,
                    "cid": customer_id,
                    "amt": round(total_amount - discount, 2),
                    "disc": round(discount, 2),
                    "addr": json.dumps(shipping_address, ensure_ascii=False),
                },
            )
            if promo["coupon_row_id"]:
                from engine_py.analytics import promotions as _promo_svc

                # 条件核销防双花:False=券已被并发订单用掉,整体回滚拒单
                if not await _promo_svc.mark_coupon_used(conn, promo["coupon_row_id"], order_id):
                    raise _CartError("优惠券已被使用，请刷新券包后重试")
            await _record_promo_redemption(conn, (promo["activity"] or {}).get("promo_id"), order_id, (promo["activity"] or {}).get("discount", 0.0))
            await _record_promo_redemption(conn, (promo["coupon"] or {}).get("promo_id"), order_id, (promo["coupon"] or {}).get("discount", 0.0))
            for oi in items_to_insert:
                await conn.execute(
                    text(
                        "INSERT INTO merchant_order_items (order_id, spu_id, sku_code, title, sku_title, quantity, "
                        "price, image_url, spec_summary) VALUES (:oid, :spu, :code, :t, :st, :qty, :price, :img, :spec)"
                    ),
                    {
                        "oid": order_id,
                        "spu": oi["spuId"],
                        "code": oi["skuCode"],
                        "t": oi["spuTitle"],
                        "st": oi["skuTitle"],
                        "qty": oi["quantity"],
                        "price": oi["price"],
                        "img": oi["imageUrl"],
                        "spec": oi["specSummary"],
                    },
                )
    except _CartError as err:
        return {"success": False, "message": err.message}
    return {
        "success": True,
        "orderId": order_id,
        "totalAmount": round(total_amount, 2),
        "discount": round(discount, 2),
        "promoName": promo_name,
        "payableAmount": round(total_amount - discount, 2),
    }


async def preview_cart_pricing(customer_id: str, items: list[dict]) -> dict:
    """结算页只读试算(2026-09-22 选券重构):原价、活动优惠、券包逐张可用性。

    只读:不加锁、不减库存、不落任何表。金额口径与 create_order_from_cart
    完全一致(同价同 scope),但试算≠下单承诺 —— 并发库存以下单事务为准。
    券包仅回可用张(coupon 型无门槛,claimed+在售+在有效期即可用),前端
    选择器以此为准;/api/store/coupons 的全量含已核销态仅供 claimedIds 判重。
    """
    if not items:
        return {"success": False, "message": "试算商品不能为空"}
    await ensure_merchant_tables()
    total_amount = 0.0
    total_quantity = 0
    scope: set[str] = set()
    try:
        async with merchant_engine().connect() as conn:
            for item in items:
                sku = (
                    await conn.execute(
                        text(
                            "SELECT s.price, p.spu_code FROM merchant_skus s "
                            "JOIN merchant_spus p ON s.spu_id = p.id WHERE s.sku_code = :code LIMIT 1"
                        ),
                        {"code": item["skuCode"]},
                    )
                ).mappings().first()
                if sku is None:
                    return {"success": False, "message": f"商品规格 [{item['skuCode']}] 不存在"}
                quantity = item.get("quantity") or 1
                total_amount += float(sku["price"]) * quantity
                total_quantity += quantity
                scope.add(str(sku["spu_code"]))

            from engine_py.analytics.promotion_engine import best_for_amount, list_usable_user_coupons

            amount = round(total_amount, 2)
            auto = await best_for_amount(conn, amount, scope, exclude_coupon=True)
            # 叠加口径(与 _resolve_promotion 一致):活动先减,券按余额抵扣封顶
            activity_discount = auto["discount"] if auto else 0.0
            coupons = await list_usable_user_coupons(conn, customer_id, round(amount - activity_discount, 2))
    except Exception as err:
        return {"success": False, "message": f"试算失败: {err}"}
    return {
        "success": True,
        "totalQuantity": total_quantity,
        "originalAmount": amount,
        "activity": {"name": auto["name"], "discount": auto["discount"]} if auto else None,
        "coupons": [
            {
                "couponId": c["coupon_row_id"],
                "promotionId": c["promotion_id"],
                "name": c["name"],
                "value": c["value"],
                "usable": True,
                "discount": c["discount"],
            }
            for c in coupons
        ],
        "bestCouponId": (max(coupons, key=lambda c: c["discount"])["coupon_row_id"]) if coupons else None,
    }
