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
    return val.isoformat() if val else _dt.datetime.now().isoformat()


def _order_from_row(row: Any, items: list[dict]) -> dict:
    return {
        "orderId": row["order_id"],
        "userId": row["customer_id"],
        "status": row["status"],
        "totalAmount": float(row["total_amount"]),
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
                    "SELECT s.*, p.title as spu_title, p.main_image as spu_image, p.id as spu_id "
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

    async with merchant_engine().begin() as conn:
        await conn.execute(
            text("UPDATE merchant_skus SET stock = stock - :qty WHERE sku_code = :code"),
            {"qty": quantity, "code": params["skuCode"]},
        )
        await conn.execute(
            text(
                "INSERT INTO merchant_orders (order_id, customer_id, status, total_amount, currency, "
                "shipping_address, is_returnable, is_address_modifiable) "
                "VALUES (:oid, :cid, 'PAID', :amt, 'CNY', :addr, TRUE, TRUE)"
            ),
            {
                "oid": order_id,
                "cid": params["customerId"],
                "amt": pay_amount,
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
    return {"success": True, "orderId": order_id}


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
    import time

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


async def create_order_from_cart(customer_id: str, items: list[dict], shipping_address: dict) -> dict:
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
                            "SELECT s.*, p.title as spu_title, p.main_image as spu_image, p.id as spu_id "
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
                        "skuCode": sku["sku_code"],
                        "spuTitle": sku["spu_title"],
                        "skuTitle": sku["sku_title"],
                        "quantity": quantity,
                        "price": float(sku["price"]),
                        "imageUrl": sku["image_url"] or sku["spu_image"],
                        "specSummary": spec_summary,
                    }
                )

            await conn.execute(
                text(
                    "INSERT INTO merchant_orders (order_id, customer_id, status, total_amount, currency, "
                    "shipping_address, is_returnable, is_address_modifiable) "
                    "VALUES (:oid, :cid, 'PAID', :amt, 'CNY', :addr, TRUE, TRUE)"
                ),
                {
                    "oid": order_id,
                    "cid": customer_id,
                    "amt": total_amount,
                    "addr": json.dumps(shipping_address, ensure_ascii=False),
                },
            )
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
    return {"success": True, "orderId": order_id, "totalAmount": total_amount}
