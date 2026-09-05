"""SPI 本地数据库适配器 — 镜像 tools/src/connectors/localDbSpiAdapter.ts。

TODO(Phase 1b):RemoteHttpSpiAdapter(HMAC)/ McpConnectorAdapter 随 connectors
批次移植;当前 mode != local_db 的租户回退本地适配器(行为差异已注明)。
"""

from __future__ import annotations

import datetime as _dt

from sqlalchemy import text

from ..db import get_session
from ..tools_registry.mall_domain import MallDomainService
from ..tools_registry.order_domain import OrderDomainService


class LocalDbSpiAdapter:
    async def get_user_info(self, params: dict) -> dict | None:
        raw_addresses = await OrderDomainService.get_user_addresses(
            {
                "userId": params.get("userId"),
                "userEmail": params.get("userEmail"),
                "threadId": params.get("threadId"),
                "businessId": params.get("tenantId"),
            }
        )
        addresses = [
            {
                "id": addr["id"],
                "recipientName": addr["receiverName"],
                "phone": addr["receiverPhone"],
                "fullAddress": addr["fullAddress"],
                "province": addr.get("province"),
                "city": addr.get("city"),
                "district": addr.get("district"),
                "isDefault": bool(addr.get("isDefault")),
            }
            for addr in raw_addresses
        ]
        default_addr = next((a for a in addresses if a["isDefault"]), addresses[0] if addresses else None)
        return {
            "userId": params.get("userId") or "anonymous_user",
            "name": (default_addr or {}).get("recipientName") or "平台尊贵会员",
            "phone": (default_addr or {}).get("phone"),
            "email": params.get("userEmail"),
            "memberLevel": "GOLD",
            "addresses": addresses,
        }

    async def list_orders(self, params: dict) -> list[dict]:
        orders = await OrderDomainService.get_user_orders_detailed(
            {
                "userId": params.get("userId"),
                "userEmail": params.get("userEmail"),
                "threadId": params.get("threadId"),
                "businessId": params.get("tenantId"),
            }
        )
        return [
            {
                "orderId": o["orderId"],
                "userId": params.get("userId") or "anonymous",
                "status": (str(o.get("status") or "PENDING").upper()),
                "totalAmount": o["totalAmount"],
                "currency": "CNY",
                "createdAt": str(o.get("createdAt") or _dt.datetime.now().isoformat()),
                "items": [
                    {
                        "skuId": "SKU-DEFAULT",
                        "productId": "PROD-DEFAULT",
                        "title": item.get("productName") or "商品",
                        "quantity": item.get("quantity") or 1,
                        "price": item.get("price") or 0,
                        "imageUrl": item.get("imageUrl"),
                    }
                    for item in (o.get("items") or [])
                ],
                "shippingAddress": {
                    "id": o.get("addressId"),
                    "recipientName": o.get("recipientName") or "顾客",
                    "phone": o.get("phone") or "",
                    "fullAddress": o.get("shippingAddress") or "",
                },
                **(
                    {
                        "tracking": {
                            "carrier": o.get("carrier") or "SF",
                            "trackingNumber": o["trackingNumber"],
                            "status": "IN_TRANSIT",
                        }
                    }
                    if o.get("trackingNumber")
                    else {}
                ),
                "isReturnable": True,
                "isAddressModifiable": str(o.get("status") or "").upper() in ("PENDING", "PAID", "PROCESSING"),
            }
            for o in orders
        ]

    async def get_order_detail(self, params: dict) -> dict | None:
        order = await OrderDomainService.find_order_by_id(params["orderId"], None, params["tenantId"])
        if not order:
            return None

        try:
            async with get_session() as session:
                item_rows = (
                    (
                        await session.execute(
                            text(
                                'SELECT oi.id, oi.product_id AS "productId", oi.quantity, '
                                'oi.price_at_purchase AS "price", p.name AS "title" '
                                "FROM order_items oi LEFT JOIN products p ON oi.product_id = p.id "
                                "WHERE oi.order_id = :oid"
                            ).bindparams(oid=params["orderId"])
                        )
                    )
                    .mappings()
                    .all()
                )
        except Exception:
            item_rows = []

        status = str(order.get("status") or "PENDING")
        return {
            "orderId": order.get("orderId"),
            "userId": order.get("userId"),
            "status": status.upper(),
            "totalAmount": order.get("totalAmount") or 0,
            "currency": "CNY",
            "createdAt": _dt.datetime.now().isoformat(),
            "items": [
                {
                    "skuId": i.get("productId") or "PROD-DEFAULT",
                    "productId": i.get("productId") or "PROD-DEFAULT",
                    "title": i.get("title") or "商品",
                    "quantity": i.get("quantity") or 1,
                    "price": i.get("price") or "0.00",
                }
                for i in item_rows
            ],
            "shippingAddress": {"recipientName": "收件人", "phone": "", "fullAddress": "北京市海淀区中关村南大街1号院"},
            "isReturnable": True,
            "isAddressModifiable": status.upper() in ("PENDING", "PAID", "PROCESSING"),
        }

    async def execute_order_action(self, req: dict) -> dict:
        if req["actionType"] == "REQUEST_REFUND":
            refund_amount = req.get("refundAmount")
            refund_amount_str = f"{refund_amount:.2f}" if isinstance(refund_amount, (int, float)) else refund_amount
            res = await OrderDomainService.process_refund(
                req["orderId"], req.get("reason") or "SOP 标准退款申请", None, refund_amount_str
            )
            message = res.get("error") or res.get("message") or "退款处理成功"
            return {
                "success": bool(res.get("refundedAmount") or "成功" in str(message)),
                "actionType": "REQUEST_REFUND",
                "orderId": req["orderId"],
                "actionId": req.get("idempotencyKey"),
                "refundId": (res.get("auditTrail") or {}).get("approvalId") or f"REFUND_{int(_dt.datetime.now().timestamp() * 1000)}",
                "refundedAmount": res.get("refundedAmount") or req.get("refundAmount"),
                "message": message,
            }

        if req["actionType"] == "MODIFY_ADDRESS":
            new_address = req.get("newAddress")
            new_address_str = new_address if isinstance(new_address, str) else (new_address or {}).get("fullAddress", "")
            res = await OrderDomainService.change_shipping_address(req["orderId"], new_address_str, None, True)
            return {
                "success": not res.get("error"),
                "actionType": "MODIFY_ADDRESS",
                "orderId": req["orderId"],
                "actionId": req.get("idempotencyKey"),
                "updatedAddress": new_address_str,
                "message": res.get("error") or res.get("message") or "收货地址修改成功",
            }

        return {
            "success": False,
            "actionType": req.get("actionType"),
            "orderId": req.get("orderId"),
            "message": f"未支持的操作动作: {req.get('actionType')}",
        }

    async def search_products(self, params: dict) -> list[dict]:
        try:
            async with get_session() as session:
                rows = (
                    (
                        await session.execute(
                            text(
                                'SELECT id, name AS "title", category, price, stock FROM products '
                                "WHERE (business_id = :bid OR :bid = 'ecommerce') "
                                "AND (:q::text IS NULL OR name ILIKE '%' || :q || '%' OR category ILIKE '%' || :q || '%') "
                                "LIMIT :lim"
                            ).bindparams(
                                bid=params.get("tenantId", "ecommerce"),
                                q=params.get("query") or None,
                                lim=params.get("limit") or 5,
                            )
                        )
                    )
                    .mappings()
                    .all()
                )
                return [
                    {
                        "productId": str(r["id"]),
                        "title": r["title"],
                        "description": "",
                        "price": float(r["price"] or 0),
                        "stock": int(r["stock"] or 0),
                        "category": r.get("category"),
                        "isAvailable": int(r["stock"] or 0) > 0,
                    }
                    for r in rows
                ]
        except Exception:
            return []


# shoppingGuideSkill 依赖 MallDomainService 已由 tools_registry 提供
_ = MallDomainService
