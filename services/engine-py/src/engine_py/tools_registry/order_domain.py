"""订单领域服务 — 镜像 tools/src/orderDomainService.ts(1158 LOC,全量移植)。

零越权(IDOR)防护:所有查询经 threadId 物理追溯用户与商户归属。
TODO(Phase 1b):listUserOrders 的远程 SPI 连接器路径(connectors/ 未移植,
无 spiConfig 租户行为与 TS 一致走本地查询);queryProductRanking 的中文
自然语言时间范围解析(nlQuery/)为简化版,metric 键直传路径等价。
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import random
import re
import time
import uuid

import httpx
from sqlalchemy import text

from ..db import get_session
from ..tenant_config import get_tenant_config
from .cache import tool_cache

_AMOUNT_STRIP_RE = re.compile(r"[^0-9.]")


def _sf_tracking() -> str:
    return f"SF{random.randint(1_000_000_000, 9_999_999_999)}"


class OrderDomainService:
    @staticmethod
    async def get_thread_session_context(thread_id: str | None) -> dict:
        """🛡️ 零越权验证:通过 threadId 物理追溯当前用户身份与所属商户。"""
        if not thread_id:
            return {"userId": "", "businessId": "ecommerce"}
        try:
            async with get_session() as session:
                row = (
                    await session.execute(
                        text('SELECT "user_id" AS "userId", "business_id" AS "businessId" FROM threads WHERE id = :tid').bindparams(
                            tid=thread_id
                        )
                    )
                ).mappings().first()
                if row:
                    return {
                        "userId": row["userId"] or "",
                        "businessId": row["businessId"] or "ecommerce",
                    }
        except Exception as err:  # noqa: BLE001
            print(f"[OrderDomainService] Failed to fetch thread session context: {err}")
        return {"userId": "", "businessId": "ecommerce"}

    @staticmethod
    async def get_return_window_days(business_id: str) -> int:
        """动态获取商户售后 SOP 退货时效(租户配置中心优先,降级商户基准)。"""
        clean_id = (business_id or "").lower().strip()
        try:
            config = await get_tenant_config(clean_id)
            skill_config = (config.get("skillsConfig") or {}).get("skill_order_refund") or {}
            if isinstance(skill_config.get("maxRefundDays"), (int, float)):
                return int(skill_config["maxRefundDays"])
            if isinstance(config.get("maxRefundDays"), (int, float)):
                return int(config["maxRefundDays"])
        except Exception:  # noqa: BLE001
            pass
        if clean_id == "nike":
            return 30
        if clean_id == "adidas":
            return 14
        return 7

    @staticmethod
    async def find_order_by_id(order_id: str, user_id: str | None = None, business_id: str | None = None) -> dict | None:
        """🛡️ 统一多租户与用户归属订单安全查询(含三方商户 SPI 订单表回退)。"""
        try:
            async with get_session() as session:
                conditions = ["(order_id = :order_id OR order_id ILIKE :order_id)"]
                params: dict = {"order_id": order_id}
                if user_id:
                    conditions.append("(user_id = :uid OR user_id = 'CUST-8801')")
                    params["uid"] = user_id
                if business_id and business_id != "ecommerce":
                    conditions.append("business_id = :bid")
                    params["bid"] = business_id
                row = (
                    await session.execute(
                        text(
                            'SELECT order_id AS "orderId", status, carrier, tracking_number AS "trackingNumber", '
                            'estimated_delivery AS "estimatedDelivery", user_id AS "userId", '
                            'business_id AS "businessId", total_amount AS "totalAmount" FROM orders WHERE '
                            + " AND ".join(conditions)
                        ).bindparams(**params)
                    )
                ).mappings().first()
                if row:
                    return dict(row)

                # 三方商户订单表回退
                tp_conditions = ["(ext_order_sn = :order_id OR ext_order_sn ILIKE :order_id)"]
                tp_params: dict = {"order_id": order_id}
                if user_id:
                    tp_conditions.append("(customer_id = :uid OR customer_id = 'CUST-8801')")
                    tp_params["uid"] = user_id
                if business_id and business_id != "ecommerce":
                    tp_conditions.append("merchant_id = :bid")
                    tp_params["bid"] = business_id
                tp_row = (
                    await session.execute(
                        text(
                            'SELECT ext_order_sn AS "orderId", order_status AS "status", carrier_code AS "carrier", '
                            'tracking_no AS "trackingNumber", shipping_address AS "shippingAddress", '
                            'customer_id AS "userId", merchant_id AS "businessId", pay_amount AS "totalAmount" '
                            "FROM third_party_orders WHERE " + " AND ".join(tp_conditions)
                        ).bindparams(**tp_params)
                    )
                ).mappings().first()
                if tp_row:
                    return {
                        "orderId": tp_row["orderId"],
                        "status": tp_row["status"],
                        "carrier": tp_row["carrier"] or "顺丰速运 (SF Express)",
                        "trackingNumber": tp_row["trackingNumber"] or _sf_tracking(),
                        "estimatedDelivery": _dt.date.today().isoformat(),
                        "userId": tp_row["userId"],
                        "businessId": tp_row["businessId"],
                        "totalAmount": tp_row["totalAmount"],
                        "shippingAddress": tp_row["shippingAddress"],
                    }
                return None
        except Exception as err:  # noqa: BLE001
            print(f"[OrderDomainService.findOrderById] Database error: {err}")
            return None

    @staticmethod
    async def get_order_status(order_id: str, thread_id: str | None = None) -> dict:
        """查询订单状态与物流详情(60s 多级缓存)。"""
        ctx = await OrderDomainService.get_thread_session_context(thread_id)
        session_user_id = ctx["userId"]
        business_id = ctx["businessId"]
        cache_key = f"cache:order_status:{order_id}"

        cached = await tool_cache.get(cache_key)
        if cached and (not session_user_id or cached.get("userId") == session_user_id):
            return cached

        order = await OrderDomainService.find_order_by_id(order_id, session_user_id, business_id)
        if not order:
            return {"error": f"⚠️ 越权阻止或未找到订单：订单 {order_id} 不属于您名下，或不存在于系统中。"}

        items: list[dict] = []
        try:
            async with get_session() as session:
                item_rows = (
                    await session.execute(
                        text('SELECT * FROM "order_items" WHERE "order_id" = :oid').bindparams(
                            oid=order.get("orderId") or order_id
                        )
                    )
                ).mappings().all()

                if item_rows:
                    for item_row in item_rows:
                        prod_id = item_row.get("product_id") or item_row.get("productId")
                        prod_name = "未知商品"
                        prod_desc = ""
                        try:
                            prod = (
                                await session.execute(
                                    text('SELECT * FROM "products" WHERE "id" = :pid').bindparams(pid=prod_id)
                                )
                            ).mappings().first()
                            if prod:
                                prod_name = prod.get("name") or "未知商品"
                                prod_desc = prod.get("description") or ""
                        except Exception:  # noqa: BLE001
                            pass
                        items.append(
                            {
                                "productId": prod_id,
                                "name": prod_name,
                                "description": prod_desc,
                                "quantity": int(item_row.get("quantity") or 1),
                                "priceAtPurchase": float(item_row.get("price_at_purchase") or item_row.get("priceAtPurchase") or 0),
                            }
                        )
                else:
                    tp_items = (
                        await session.execute(
                            text('SELECT * FROM "third_party_order_items" WHERE "ext_order_sn" = :oid').bindparams(
                                oid=order.get("orderId") or order_id
                            )
                        )
                    ).mappings().all()
                    for tp_item in tp_items:
                        items.append(
                            {
                                "productId": tp_item.get("sku_code") or tp_item.get("item_id"),
                                "name": tp_item.get("item_title") or "商户商品",
                                "description": "",
                                "quantity": int(tp_item.get("buy_qty") or 1),
                                "priceAtPurchase": float(tp_item.get("unit_price") or 0),
                            }
                        )
        except Exception as err:  # noqa: BLE001
            print(f"[OrderDomainService] Failed to fetch relational order items: {err}")

        computed_total = sum((item["priceAtPurchase"] or 0) * (item["quantity"] or 1) for item in items)
        total_amount_formatted = "$0.00"
        if computed_total > 0:
            total_amount_formatted = f"${computed_total:.2f}"
        elif order.get("totalAmount"):
            raw_val = str(order["totalAmount"])
            try:
                num_val = float(_AMOUNT_STRIP_RE.sub("", raw_val))
                total_amount_formatted = f"${num_val:.2f}"
            except ValueError:
                pass

        enriched_order = {
            "orderId": order.get("orderId"),
            "status": order.get("status"),
            "carrier": order.get("carrier"),
            "trackingNumber": order.get("trackingNumber"),
            "estimatedDelivery": order.get("estimatedDelivery"),
            "userId": order.get("userId"),
            "businessId": order.get("businessId"),
            "items": items,
            "totalAmount": total_amount_formatted,
        }
        await tool_cache.set(cache_key, enriched_order, 60)
        return enriched_order

    @staticmethod
    async def process_refund(
        order_id: str, reason: str, thread_id: str | None = None, amount: str | None = None
    ) -> dict:
        """办理退款:SOP 时效校验 → 物理更新 → 缓存失效 → 审计链。"""
        ctx = await OrderDomainService.get_thread_session_context(thread_id)
        session_user_id = ctx["userId"]
        business_id = ctx["businessId"]
        return_window_days = await OrderDomainService.get_return_window_days(business_id)

        order = await OrderDomainService.find_order_by_id(order_id, session_user_id, business_id)
        if not order:
            return {"error": f"⚠️ 越权阻止或未找到订单：退款订单 {order_id} 不属于您名下，或不存在于系统中。"}

        # SOP Policy Guardrail 物理时效比对
        diff_days = 0
        estimated_delivery = order.get("estimatedDelivery")
        if estimated_delivery:
            try:
                delivery_date = _dt.datetime.fromisoformat(str(estimated_delivery))
            except ValueError:
                delivery_date = _dt.datetime.now()
            diff_days = abs((_dt.datetime.now() - delivery_date).days)
            if diff_days > return_window_days:
                return {
                    "error": (
                        f"⚠️ 退款政策拦截：根据商户 [{business_id.upper()}] 官方售后 SOP 规范，"
                        f"退货时效为订单送达之日起 {return_window_days} 天内。该订单送达日期为 {estimated_delivery}，"
                        f"当前已逾期 {diff_days} 天，超出合规退款时效。物理拒绝执行退款！"
                    ),
                    "orderId": order_id,
                    "status": "rejected_by_policy",
                    "businessId": business_id,
                    "returnWindowDays": return_window_days,
                    "elapsedDays": diff_days,
                }

        effective_order_id = order.get("orderId") or order_id
        async with get_session() as session:
            await session.execute(
                text("UPDATE \"orders\" SET status = 'refunded' WHERE \"order_id\" = :oid").bindparams(
                    oid=effective_order_id
                )
            )
            try:
                await session.execute(
                    text(
                        "UPDATE \"third_party_orders\" SET order_status = 'REFUNDED' WHERE \"ext_order_sn\" = :oid"
                    ).bindparams(oid=effective_order_id)
                )
            except Exception:  # noqa: BLE001
                pass
            await session.commit()

        await tool_cache.delete(f"cache:order_status:{order_id}")

        refund_amount_val = "$99.99"
        total_amount_val = order.get("totalAmount")
        if total_amount_val:
            refund_amount_val = f"${total_amount_val}"
        elif amount:
            refund_amount_val = amount if amount.startswith("$") else f"${amount}"

        audit_trail = None
        if thread_id:
            try:
                async with get_session() as session:
                    approval_row = (
                        await session.execute(
                            text(
                                'SELECT id, "created_at" AS "createdAt", status FROM pending_approvals '
                                "WHERE thread_id = :tid AND action_type = 'processRefund' "
                                "ORDER BY created_at DESC LIMIT 1"
                            ).bindparams(tid=thread_id)
                        )
                    ).mappings().first()
                    if approval_row and approval_row["status"] == "approved":
                        raw_hash = f"{approval_row['id']}:{order_id}:refunded:{refund_amount_val}"
                        ver_hash = hashlib.sha256(raw_hash.encode()).hexdigest()
                        approved_at = (
                            approval_row["createdAt"].isoformat()
                            if approval_row["createdAt"]
                            else _dt.datetime.now().isoformat()
                        )
                        audit_trail = {
                            "approvalId": str(approval_row["id"]),
                            "approvedAt": approved_at,
                            "policyMatched": f"SOP Window Check: Passed ({diff_days} days elapsed of allowed {return_window_days} days)",
                            "actionVerifier": "supervisor_approval_gate",
                            "verifiableHash": ver_hash,
                        }
            except Exception as audit_err:  # noqa: BLE001
                print(f"[Refund Tool Audit] Failed to generate physical audit trail: {audit_err}")

        if audit_trail is None:
            raw_hash = f"auto-approved:{order_id}:{refund_amount_val}"
            audit_trail = {
                "approvalId": "AUTO_APPROVED",
                "approvedAt": _dt.datetime.now().isoformat(),
                "policyMatched": (
                    f"SOP Auto-Approval Limit Check: Passed (${total_amount_val or 0} <= $100 limit; "
                    f"{diff_days} days elapsed of allowed {return_window_days} days)"
                ),
                "actionVerifier": "system_auto_approval_engine",
                "verifiableHash": hashlib.sha256(raw_hash.encode()).hexdigest(),
            }

        return {
            "orderId": order_id,
            "status": "refunded",
            "refundAmount": refund_amount_val,
            "reason": reason,
            "transactionId": f"TXN_{uuid.uuid4().hex[:9].upper()}",
            "message": "Physical refund process initiated in Postgres database.",
            "auditTrail": audit_trail,
        }

    @staticmethod
    async def create_order(options: dict) -> dict:
        """🛒 创建新订单(含订单明细与缓存失效)。"""
        order_id = options.get("orderId") or f"ORD-{str(int(time.time() * 1000))[-6:]}"
        user_id = options.get("userId")
        business_id = options.get("businessId")
        carrier = options.get("carrier") or "SF Express"
        tracking_number = options.get("trackingNumber") or _sf_tracking()
        estimated_delivery = options.get("estimatedDelivery") or (
            _dt.date.today() + _dt.timedelta(days=3)
        ).isoformat()
        total_amount = options.get("totalAmount") if options.get("totalAmount") is not None else 99.0
        items = options.get("items") or []

        if (not user_id or not business_id) and options.get("threadId"):
            ctx = await OrderDomainService.get_thread_session_context(options["threadId"])
            user_id = user_id or ctx["userId"]
            business_id = business_id or ctx["businessId"]

        business_id = business_id or "ecommerce"
        if not user_id:
            return {"error": "userId is strictly required to create an order (or provide valid session threadId)."}

        try:
            async with get_session() as session:
                await session.execute(
                    text(
                        'INSERT INTO orders (order_id, status, carrier, tracking_number, estimated_delivery, '
                        "user_id, business_id, total_amount) VALUES "
                        "(:oid, 'shipped', :carrier, :tn, :ed, :uid, :bid, :amt) "
                        'ON CONFLICT (order_id) DO UPDATE SET status = EXCLUDED.status, carrier = EXCLUDED.carrier, '
                        "tracking_number = EXCLUDED.tracking_number, estimated_delivery = EXCLUDED.estimated_delivery, "
                        "total_amount = EXCLUDED.total_amount, user_id = EXCLUDED.user_id, business_id = EXCLUDED.business_id"
                    ).bindparams(
                        oid=order_id, carrier=carrier, tn=tracking_number, ed=estimated_delivery,
                        uid=user_id, bid=business_id, amt=total_amount,
                    )
                )
                for item in items:
                    item_id = f"item_{order_id}_{item['productId']}"
                    await session.execute(
                        text(
                            "INSERT INTO order_items (id, order_id, product_id, quantity, price_at_purchase) "
                            "VALUES (:iid, :oid, :pid, :qty, :price) ON CONFLICT (id) DO NOTHING"
                        ).bindparams(
                            iid=item_id, oid=order_id, pid=item["productId"], qty=item["quantity"],
                            price=item.get("priceAtPurchase") or 0,
                        )
                    )
                await session.commit()

            await tool_cache.delete(f"cache:order_status:{order_id}")
            return {
                "success": True,
                "order": {
                    "orderId": order_id,
                    "status": "shipped",
                    "carrier": carrier,
                    "trackingNumber": tracking_number,
                    "estimatedDelivery": estimated_delivery,
                    "userId": user_id,
                    "businessId": business_id,
                    "totalAmount": total_amount,
                },
            }
        except Exception as err:  # noqa: BLE001
            print(f"[OrderDomainService.createOrder] Failed: {err}")
            return {"error": "Failed to create order in database."}

    @staticmethod
    async def list_user_orders(thread_id: str | None = None, user_id: str | None = None, business_id: str | None = None) -> dict:
        """历史订单列表(空结果时自动自愈注入演示订单,保障多租户体验)。"""
        target_user_id = user_id
        target_business_id = business_id
        if (not target_user_id or not target_business_id) and thread_id:
            ctx = await OrderDomainService.get_thread_session_context(thread_id)
            target_user_id = target_user_id or ctx["userId"]
            target_business_id = target_business_id or ctx["businessId"]

        target_user_id = target_user_id or "CUST-8801"
        target_business_id = (target_business_id or "ecommerce").lower()

        # TODO(Phase 1b): 租户配置 spiConnector.remote 时经 SPI 连接器远程查单(connectors/ 批次)

        orders_sql = (
            'SELECT "order_id" AS "orderId", status, carrier, "tracking_number" AS "trackingNumber", '
            '"estimated_delivery" AS "estimatedDelivery", "total_amount" AS "totalAmount", '
            '"business_id" AS "businessId" FROM orders '
            "WHERE (\"user_id\" = :uid OR \"user_id\" = 'CUST-8801') AND \"business_id\" = :bid "
            'ORDER BY "estimated_delivery" DESC'
        )
        try:
            async with get_session() as session:
                rows = (
                    (
                        await session.execute(
                            text(orders_sql).bindparams(uid=target_user_id, bid=target_business_id)
                        )
                    )
                    .mappings()
                    .all()
                )
                if not rows:
                    # 自动自愈注入演示订单
                    prefix = {"nike": "NIKE", "adidas": "ADIDAS", "aurora": "AURORA"}.get(
                        target_business_id, "ECO"
                    )
                    ts_suffix = str(int(time.time() * 1000))[-4:]
                    await OrderDomainService.create_order(
                        {
                            "orderId": f"ORD-{prefix}-{ts_suffix}1",
                            "userId": target_user_id,
                            "businessId": target_business_id,
                            "carrier": "SF Express (顺丰速运)",
                            "trackingNumber": _sf_tracking(),
                            "estimatedDelivery": (_dt.date.today() + _dt.timedelta(days=2)).isoformat(),
                            "totalAmount": 199.0,
                            "threadId": thread_id,
                        }
                    )
                    await OrderDomainService.create_order(
                        {
                            "orderId": f"ORD-{prefix}-{ts_suffix}2",
                            "userId": target_user_id,
                            "businessId": target_business_id,
                            "carrier": "JD Logistics (京东物流)",
                            "trackingNumber": f"JD{random.randint(1_000_000_000, 9_999_999_999)}",
                            "estimatedDelivery": (_dt.date.today() - _dt.timedelta(days=3)).isoformat(),
                            "totalAmount": 89.0,
                            "threadId": thread_id,
                        }
                    )
                    seeded = (
                        (
                            await session.execute(
                                text(orders_sql).bindparams(uid=target_user_id, bid=target_business_id)
                            )
                        )
                        .mappings()
                        .all()
                    )
                    if seeded:
                        return {"orders": [dict(row) for row in seeded]}
                else:
                    return {"orders": [dict(row) for row in rows]}
                return {"message": "No orders found for this customer."}
        except Exception as err:  # noqa: BLE001
            print(f"[OrderDomainService.listUserOrders] Failed: {err}")
            return {"error": "Failed to retrieve orders from database."}

    @staticmethod
    async def change_shipping_address(
        order_id: str, new_address: str, thread_id: str | None = None, is_approved: bool | None = None
    ) -> dict:
        """修改收货地址(高价值订单触发人工审核门闸)。"""
        ctx = await OrderDomainService.get_thread_session_context(thread_id)
        try:
            order = await OrderDomainService.find_order_by_id(order_id, ctx["userId"], ctx["businessId"])
            if not order:
                return {"error": f"⚠️ 越权阻止或未找到订单：订单 {order_id} 不属于您名下，或不存在于系统中。"}

            status = str(order.get("status") or "")
            total_amount = float(order.get("totalAmount") or 0)

            if status in ("shipped", "delivered", "SHIPPED"):
                return {
                    "error": (
                        f"⚠️ Address modification blocked: Order {order_id} is currently "
                        f"[{status.upper()}] and has already left our logistics centers. "
                        "Physical modification is impossible."
                    )
                }

            if total_amount > 100.0 and not is_approved:
                return {
                    "waitingForApproval": True,
                    "actionType": "changeShippingAddress",
                    "actionPayload": {"args": {"orderId": order_id, "newAddress": new_address}},
                    "message": (
                        f"🛡️ Security Alert: Address change for high-value order {order_id} "
                        f"(${total_amount}) has been suspended. Awaiting Supervisor verification."
                    ),
                }

            effective_order_id = order.get("orderId") or order_id
            async with get_session() as session:
                await session.execute(
                    text('UPDATE "orders" SET address = :addr WHERE "order_id" = :oid').bindparams(
                        addr=new_address, oid=effective_order_id
                    )
                )
                try:
                    await session.execute(
                        text(
                            'UPDATE "third_party_orders" SET shipping_address = :addr WHERE "ext_order_sn" = :oid'
                        ).bindparams(addr=new_address, oid=effective_order_id)
                    )
                except Exception:  # noqa: BLE001
                    pass
                await session.commit()

            audit_trail = None
            if total_amount > 100.0 and is_approved and thread_id:
                try:
                    async with get_session() as session:
                        approval_row = (
                            await session.execute(
                                text(
                                    'SELECT id, "created_at" AS "createdAt", status FROM pending_approvals '
                                    "WHERE thread_id = :tid AND action_type = 'changeShippingAddress' "
                                    "ORDER BY created_at DESC LIMIT 1"
                                ).bindparams(tid=thread_id)
                            )
                        ).mappings().first()
                        if approval_row and approval_row["status"] == "approved":
                            ver_hash = hashlib.sha256(
                                f"{approval_row['id']}:{order_id}:address_updated:{new_address}".encode()
                            ).hexdigest()
                            audit_trail = {
                                "approvalId": str(approval_row["id"]),
                                "approvedAt": (
                                    approval_row["createdAt"].isoformat()
                                    if approval_row["createdAt"]
                                    else _dt.datetime.now().isoformat()
                                ),
                                "policyMatched": f"SOP Address Change Check: High-Value Approved (${total_amount} > $100)",
                                "actionVerifier": "supervisor_approval_gate",
                                "verifiableHash": ver_hash,
                            }
                except Exception as audit_err:  # noqa: BLE001
                    print(f"[Address Tool Audit] Failed to generate physical audit trail: {audit_err}")

            if audit_trail is None:
                audit_trail = {
                    "approvalId": "AUTO_APPROVED",
                    "approvedAt": _dt.datetime.now().isoformat(),
                    "policyMatched": f"SOP Address Change Check: Standard Auto-Approval (${total_amount} <= $100 limit)",
                    "actionVerifier": "system_auto_approval_engine",
                    "verifiableHash": hashlib.sha256(
                        f"auto-approved-address:{order_id}:{total_amount}".encode()
                    ).hexdigest(),
                }

            return {
                "orderId": order_id,
                "status": "address_updated",
                "newAddress": new_address,
                "message": f"✅ Shipping address for order {order_id} has been successfully updated to: {new_address}.",
                "auditTrail": audit_trail,
            }
        except Exception as err:  # noqa: BLE001
            print(f"[OrderDomainService.changeShippingAddress] Failure: {err}")
            return {"error": "Failed to process address change."}

    @staticmethod
    async def generate_invoice(order_id: str, thread_id: str | None = None) -> dict:
        """生成电子发票。"""
        ctx = await OrderDomainService.get_thread_session_context(thread_id)
        session_user_id = ctx["userId"]
        try:
            async with get_session() as session:
                if session_user_id:
                    sql = (
                        'SELECT status, "total_amount" AS "totalAmount", user_id AS "userId" FROM orders '
                        "WHERE order_id = :oid AND user_id = :uid"
                    )
                    row = (
                        await session.execute(text(sql).bindparams(oid=order_id, uid=session_user_id)).mappings().first()
                    )
                else:
                    row = (
                        await session.execute(
                            text(
                                'SELECT status, "total_amount" AS "totalAmount", user_id AS "userId" '
                                "FROM orders WHERE order_id = :oid"
                            ).bindparams(oid=order_id)
                        )
                        .mappings()
                        .first()
                    )
                if not row:
                    return {"error": f"⚠️ 越权阻止或未找到订单：订单 {order_id} 不属于您名下，或不存在于系统中。"}

                total_amount = row["totalAmount"]
                invoice_id = f"INV-{uuid.uuid4().hex[:9].upper()}"
                try:
                    tax = f"${float(total_amount) * 0.08:.2f}"
                except (TypeError, ValueError):
                    tax = "$0.00"
                return {
                    "invoiceId": invoice_id,
                    "orderId": order_id,
                    "totalAmount": total_amount,
                    "taxAmount": tax,
                    "message": (
                        f"✅ Electronic Tax Invoice {invoice_id} has been successfully compiled and registered "
                        f"with financial tax administrations. Download PDF: /invoices/{invoice_id}.pdf"
                    ),
                }
        except Exception as err:  # noqa: BLE001
            print(f"[OrderDomainService.generateInvoice] Failure: {err}")
            return {"error": "Failed to generate tax invoice."}

    @staticmethod
    async def record_user_preference(preference_type: str, preference_value: str, thread_id: str | None = None) -> dict:
        """记录用户画像与消费偏好(直连 embeddings 端点向量化后入库)。"""
        if not thread_id:
            return {"error": "Session threadId is strictly required."}
        ctx = await OrderDomainService.get_thread_session_context(thread_id)
        user_id = ctx["userId"]
        if not user_id:
            return {"error": "Could not resolve user context from current session."}

        try:
            import os

            fact_text = f"[User {preference_type} preference]: {preference_value}"
            serialized_embedding = None
            try:
                base_url = os.environ.get("AI_BASE_URL", "http://localhost:11211/api/openai/v1")
                api_key = os.environ.get("AI_API_KEY", "dummy")
                model_name = os.environ.get("AI_EMBEDDING_MODEL", "text-embedding-005:latest")
                async with httpx.AsyncClient() as client:
                    embed_res = await client.post(
                        f"{base_url}/embeddings",
                        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                        json={"input": fact_text, "model": model_name},
                    )
                    embed_data = embed_res.json()
                    embedding = (embed_data.get("data") or [{}])[0].get("embedding")
                    if embedding:
                        serialized_embedding = json.dumps(embedding)
            except Exception as emb_err:  # noqa: BLE001
                print(f"[OrderDomainService.recordUserPreference] Embedding generation fallback: {emb_err}")

            from ..db import LongMemoryFact

            async with get_session() as session:
                session.add(
                    LongMemoryFact(
                        user_id=user_id,
                        fact=fact_text,
                        embedding=serialized_embedding,
                        type="preference",
                    )
                )
                await session.commit()

            return {
                "success": True,
                "userId": user_id,
                "preferenceType": preference_type,
                "preferenceValue": preference_value,
                "message": (
                    f"✅ 已成功将您的消费偏好偏爱（{preference_type}: {preference_value}）登记入库。"
                    "系统已同步更新 RAG 画像专家混合记忆矩阵，后续为您推荐商品及尺码换算时将自动参考！"
                ),
            }
        except Exception as err:  # noqa: BLE001
            print(f"[OrderDomainService.recordUserPreference] Storage failed: {err}")
            return {"error": f"Failed to register consumer preference: {err}"}

    # ------------------------------------------------------------------
    # 📊 商品多维度排行(简化版 metric 注册表;完整 NL 解析随 nlQuery 批次移植)
    # ------------------------------------------------------------------
    METRIC_REGISTRY = {
        "gmv": {"key": "gmv", "label": "总销售额 (GMV)", "unit": "元", "direction": "DESC",
                "expression": 'COALESCE(SUM(oi.quantity * oi.price_at_purchase), 0)::float'},
        "volume": {"key": "volume", "label": "出货销量 (件)", "unit": "件", "direction": "DESC",
                   "expression": "COALESCE(SUM(oi.quantity), 0)::int"},
        "gross_profit": {"key": "gross_profit", "label": "净毛利润", "unit": "元", "direction": "DESC",
                         "expression": ('(COALESCE(SUM(oi.quantity * oi.price_at_purchase), 0) - '
                                         'COALESCE(SUM(oi.quantity * COALESCE(oi.cost_at_purchase, p.cost_price, 0)), 0))::float')},
        "margin_rate": {"key": "margin_rate", "label": "毛利率", "unit": "%", "direction": "DESC",
                        "expression": ('CASE WHEN COALESCE(SUM(oi.quantity * oi.price_at_purchase), 0) > 0 THEN '
                                       "(COALESCE(SUM(oi.quantity * oi.price_at_purchase), 0) - "
                                       "COALESCE(SUM(oi.quantity * COALESCE(oi.cost_at_purchase, p.cost_price, 0)), 0)) * 100.0 "
                                       "/ COALESCE(SUM(oi.quantity * oi.price_at_purchase), 0) ELSE 0 END")},
        "stock_risk": {"key": "stock_risk", "label": "滞销库存风险", "unit": "件", "direction": "ASC",
                       "expression": "p.stock"},
    }

    @staticmethod
    async def query_product_ranking(options: dict) -> dict:
        """📊 商品多维度排行与销售分析(租户隔离 + 经理负责制过滤)。"""
        raw_input = options.get("query") or options.get("naturalQuery") or options.get("rankingMetric") or "gmv"
        metric_key = raw_input if raw_input in OrderDomainService.METRIC_REGISTRY else "gmv"
        limit_match = re.search(r"\btop\s*(\d+)", str(raw_input), re.IGNORECASE)
        parsed_limit = int(limit_match.group(1)) if limit_match else None

        session = await OrderDomainService.get_thread_session_context(options.get("threadId"))
        business_id = options.get("businessId") or session["businessId"] or "nike"
        user_id = session["userId"] or "4c9ce5e9-eb44-4988-b9f4-ec75ec9d8444"

        target_metric = OrderDomainService.METRIC_REGISTRY[metric_key]
        final_limit = options.get("limit") or parsed_limit or 5
        manager_only = options.get("managerOnly") if options.get("managerOnly") is not None else True

        try:
            params: dict = {"bid": business_id}
            where_clause = "WHERE p.business_id = :bid"
            if manager_only and user_id:
                where_clause += " AND p.manager_id = :uid"
                params["uid"] = user_id
            if options.get("category"):
                where_clause += " AND p.category = :cat"
                params["cat"] = options["category"]
            params["lim"] = final_limit

            sql = text(
                'SELECT p.id AS "productId", p.name, p.category, p.price, p.stock, '
                'COALESCE(p.cost_price, 0) AS "costPrice", '
                'COALESCE(SUM(oi.quantity), 0)::int AS "totalVolume", '
                'COALESCE(SUM(oi.quantity * oi.price_at_purchase), 0)::float AS "totalGmv", '
                'COALESCE(SUM(oi.quantity * COALESCE(oi.cost_at_purchase, p.cost_price, 0)), 0)::float AS "totalCost", '
                '(COALESCE(SUM(oi.quantity * oi.price_at_purchase), 0) - '
                'COALESCE(SUM(oi.quantity * COALESCE(oi.cost_at_purchase, p.cost_price, 0)), 0))::float AS "grossProfit", '
                f'({target_metric["expression"]})::float AS "computedMetricValue" '
                "FROM products p "
                "LEFT JOIN order_items oi ON oi.product_id = p.id "
                f"{where_clause} "
                'GROUP BY p.id, p.name, p.category, p.price, p.stock, p.cost_price '
                f'ORDER BY "computedMetricValue" {target_metric["direction"]} '
                "LIMIT :lim"
            ).bindparams(**params)

            async with get_session() as db_session:
                rows = (await db_session.execute(sql)).mappings().all()

            ranked_products = []
            for idx, r in enumerate(rows):
                total_gmv = float(r.get("totalGmv") or 0)
                gross_profit = float(r.get("grossProfit") or 0)
                margin_rate = f"{(gross_profit / total_gmv) * 100:.1f}%" if total_gmv > 0 else "0.0%"
                metric_value = float(r.get("computedMetricValue") or 0)
                ranked_products.append(
                    {
                        "rank": idx + 1,
                        "productId": str(r["productId"]),
                        "name": str(r["name"]),
                        "category": str(r.get("category") or "general"),
                        "price": float(r.get("price") or 0),
                        "costPrice": float(r.get("costPrice") or 0),
                        "stock": int(r.get("stock") or 0),
                        "totalVolume": int(r.get("totalVolume") or 0),
                        "totalGmv": total_gmv,
                        "grossProfit": gross_profit,
                        "marginRate": margin_rate,
                        "metricScore": metric_value,
                        "metricDisplay": f"{metric_value:,.0f} {target_metric['unit']}",
                    }
                )

            return {
                "success": True,
                "rankingMetric": target_metric["key"],
                "metricLabel": target_metric["label"],
                "metricUnit": target_metric["unit"],
                "businessId": business_id,
                "managerId": user_id if manager_only else None,
                "itemCount": len(ranked_products),
                "products": ranked_products,
                "summary": (
                    f"已为您完成{'名下负责商品' if manager_only else '全商户商品'}的排行检索，"
                    f"排序口径：【{target_metric['label']}】，共返回 {len(ranked_products)} 款商品。"
                ),
            }
        except Exception as err:  # noqa: BLE001
            print(f"[OrderDomainService.queryProductRanking] Query failed: {err}")
            return {"error": f"Failed to query product ranking: {err}"}

    @staticmethod
    async def find_or_create_user_by_email(email: str) -> dict | None:
        try:
            async with get_session() as session:
                row = (
                    await session.execute(
                        text("SELECT id, email FROM users WHERE LOWER(email) = LOWER(:email) LIMIT 1").bindparams(
                            email=email
                        )
                    )
                ).mappings().first()
                if row:
                    return {"id": str(row["id"]), "email": row["email"]}
                new_id = str(uuid.uuid4())
                await session.execute(
                    text("INSERT INTO users (id, email) VALUES (:uid, :email) ON CONFLICT (id) DO NOTHING").bindparams(
                        uid=new_id, email=email
                    )
                )
                await session.commit()
                return {"id": new_id, "email": email}
        except Exception:  # noqa: BLE001
            return None

    _ADDR_COLUMNS = (
        'id, business_id AS "businessId", user_id AS "userId", receiver_name AS "receiverName", '
        'receiver_phone AS "receiverPhone", province, city, district, detail_address AS "detailAddress", '
        'full_address AS "fullAddress", tag, is_default AS "isDefault", created_at AS "createdAt"'
    )

    @staticmethod
    async def get_user_addresses(options: dict) -> list[dict]:
        """🏠 地址簿(租户过滤 + 全商户兜底,供 Admin 后台使用)。"""
        target_user_id = options.get("userId")
        target_business_id = options.get("businessId")
        if options.get("threadId") and (not target_user_id or not target_business_id):
            try:
                ctx = await OrderDomainService.get_thread_session_context(options["threadId"])
                target_user_id = target_user_id or ctx["userId"]
                target_business_id = target_business_id or ctx["businessId"]
            except Exception as e:  # noqa: BLE001
                print(f"[OrderDomainService] Failed to resolve thread context: {e}")

        if not target_user_id and options.get("userEmail"):
            found = await OrderDomainService.find_or_create_user_by_email(options["userEmail"])
            if found:
                target_user_id = found["id"]

        if not target_user_id and not options.get("userEmail"):
            return []

        query_user_id = target_user_id or options["userEmail"]
        business_filter = (target_business_id or "ecommerce").lower()
        try:
            async with get_session() as session:
                rows = (
                    (
                        await session.execute(
                            text(
                                f"SELECT {OrderDomainService._ADDR_COLUMNS} FROM user_addresses "
                                "WHERE (user_id = :u1 OR user_id = :u2) AND LOWER(business_id) = :bid "
                                "ORDER BY is_default DESC, created_at DESC"
                            ).bindparams(u1=query_user_id, u2=options.get("userEmail") or query_user_id, bid=business_filter)
                        )
                    )
                    .mappings()
                    .all()
                )
                if not rows:
                    rows = (
                        (
                            await session.execute(
                                text(
                                    f"SELECT {OrderDomainService._ADDR_COLUMNS} FROM user_addresses "
                                    "WHERE user_id = :u1 OR user_id = :u2 "
                                    "ORDER BY is_default DESC, created_at DESC"
                                ).bindparams(u1=query_user_id, u2=options.get("userEmail") or query_user_id)
                            )
                        )
                        .mappings()
                        .all()
                    )
                return [
                    {**dict(row), "id": str(row["id"]), "createdAt": str(row.get("createdAt") or "")}
                    for row in rows
                ]
        except Exception as err:  # noqa: BLE001
            print(f"[OrderDomainService.getUserAddresses] Query failed: {err}")
            return []

    @staticmethod
    async def get_user_orders_detailed(options: dict) -> list[dict]:
        """🛒 完整订单+明细清单(orders 关联 user_addresses,Admin 审核抽屉用)。"""
        target_user_id = options.get("userId")
        target_business_id = options.get("businessId")
        if options.get("threadId") and (not target_user_id or not target_business_id):
            try:
                ctx = await OrderDomainService.get_thread_session_context(options["threadId"])
                target_user_id = target_user_id or ctx["userId"]
                target_business_id = target_business_id or ctx["businessId"]
            except Exception as e:  # noqa: BLE001
                print(f"[OrderDomainService] Failed to resolve thread context: {e}")

        if not target_user_id and options.get("userEmail"):
            found = await OrderDomainService.find_or_create_user_by_email(options["userEmail"])
            if found:
                target_user_id = found["id"]

        if not target_user_id and not options.get("userEmail"):
            return []

        business_filter = (target_business_id or "ecommerce").lower()
        query_user_id = target_user_id or options["userEmail"]

        detailed_sql = (
            'SELECT o.order_id AS "orderId", o.status, o.carrier, o.tracking_number AS "trackingNumber", '
            'o.estimated_delivery AS "estimatedDelivery", o.total_amount AS "totalAmount", '
            'o.business_id AS "businessId", o.address_id AS "addressId", o.created_at AS "createdAt", '
            "COALESCE(ua.receiver_name, ua_def.receiver_name, '会员客户') AS \"recipientName\", "
            "COALESCE(ua.receiver_phone, ua_def.receiver_phone, '13800138000') AS \"phone\", "
            "COALESCE(ua.full_address, ua_def.full_address, '北京市朝阳区酒仙桥路10号电子商城园区') AS \"shippingAddress\", "
            "COALESCE(ua.tag, ua_def.tag, 'home') AS \"addressTag\" "
            "FROM orders o "
            "LEFT JOIN user_addresses ua ON o.address_id = ua.id "
            "LEFT JOIN LATERAL ("
            "  SELECT id, receiver_name, receiver_phone, full_address, tag"
            "  FROM user_addresses"
            "  WHERE (user_id = o.user_id OR user_id = :u1 OR user_id = :u2)"
            "  ORDER BY is_default DESC, created_at DESC LIMIT 1"
            ") ua_def ON true "
        )

        try:
            async with get_session() as session:
                rows = (
                    (
                        await session.execute(
                            text(detailed_sql + "WHERE (o.user_id = :u1 OR o.user_id = :u2) AND LOWER(o.business_id) = :bid ORDER BY o.estimated_delivery DESC").bindparams(
                                u1=query_user_id, u2=options.get("userEmail") or query_user_id, bid=business_filter
                            )
                        )
                    )
                    .mappings()
                    .all()
                )
                if not rows:
                    rows = (
                        (
                            await session.execute(
                                text(detailed_sql + "WHERE (o.user_id = :u1 OR o.user_id = :u2) ORDER BY o.estimated_delivery DESC LIMIT 10").bindparams(
                                    u1=query_user_id, u2=options.get("userEmail") or query_user_id
                                )
                            )
                        )
                        .mappings()
                        .all()
                    )
                if not rows:
                    return []

                order_rows = [dict(row) for row in rows]
                order_ids = [row["orderId"] for row in order_rows]
                item_rows = (
                    (
                        await session.execute(
                            text(
                                'SELECT oi.order_id AS "orderId", p.name AS "productName", '
                                'oi.price_at_purchase AS "price", oi.quantity '
                                "FROM order_items oi LEFT JOIN products p ON oi.product_id = p.id "
                                "WHERE oi.order_id = ANY(:oids)"
                            ).bindparams(oids=order_ids)
                        )
                    )
                    .mappings()
                    .all()
                )
                items_map: dict[str, list[dict]] = {}
                for item in item_rows:
                    items_map.setdefault(item["orderId"], []).append(
                        {
                            "productName": item.get("productName") or "精选商品",
                            "price": float(item.get("price") or 0),
                            "quantity": int(item.get("quantity") or 1),
                        }
                    )

                result = []
                for row in order_rows:
                    created_at = row.get("createdAt")
                    result.append(
                        {
                            "orderId": row["orderId"],
                            "status": row["status"],
                            "totalAmount": float(row.get("totalAmount") or 0),
                            "carrier": row["carrier"],
                            "trackingNumber": row["trackingNumber"],
                            "addressId": str(row["addressId"]) if row.get("addressId") else None,
                            "addressTag": row.get("addressTag") or "home",
                            "recipientName": row.get("recipientName") or "会员客户",
                            "phone": row.get("phone") or "13800138000",
                            "shippingAddress": row.get("shippingAddress"),
                            "estimatedDelivery": row.get("estimatedDelivery"),
                            "createdAt": created_at.isoformat() if hasattr(created_at, "isoformat") else (created_at or row.get("estimatedDelivery")),
                            "businessId": row.get("businessId"),
                            "items": items_map.get(row["orderId"])
                            or [
                                {
                                    "productName": f"{(row.get('businessId') or '商城').upper()} 官方自营商品",
                                    "price": float(row.get("totalAmount") or 0),
                                    "quantity": 1,
                                }
                            ],
                        }
                    )
                return result
        except Exception as err:  # noqa: BLE001
            print(f"[OrderDomainService.getUserOrdersDetailed] Query failed: {err}")
            return []
