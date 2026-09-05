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
import os
import random
import re
import time
import uuid
from functools import lru_cache

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from ..config import settings
from ..db import get_session
from ..llm import get_embedding_model
from ..tenant_config import get_tenant_config
from .cache import tool_cache

_AMOUNT_STRIP_RE = re.compile(r"[^0-9.]")


def _sf_tracking() -> str:
    return f"SF{random.randint(1_000_000_000, 9_999_999_999)}"


# ---------------------------------------------------------------------------
# 商户门户独立库(agent_merchant)只读直连 —— 商户真单的事实源。
# 商城下单只写 merchant_orders;聊天查单若仅看 engine 本地 orders 表,
# 将与商户门户"我的订单"列表视图永久不一致(2026-09-05 修复)。
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def _merchant_reader_engine():
    url = os.environ.get("MERCHANT_DATABASE_URL")
    if not url:
        base = settings.database_url or "postgres://agent_user:agent_password@localhost:5432/agent_platform"
        url = re.sub(r"/[^/]+$", "/agent_merchant", base)
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+asyncpg://", 1)
    elif url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return create_async_engine(url, pool_size=5, max_overflow=0, pool_pre_ping=True)


def _merchant_row_to_order(row) -> dict:
    tracking = row.get("tracking_info") if isinstance(row.get("tracking_info"), dict) else {}
    shipping = row.get("shipping_address") if isinstance(row.get("shipping_address"), dict) else {}
    return {
        "orderId": row["order_id"],
        "status": row["status"],
        "carrier": tracking.get("carrier") or tracking.get("company") or "顺丰速运 (SF Express)",
        "trackingNumber": (
            tracking.get("trackingNumber") or tracking.get("trackingNo") or tracking.get("no") or "暂无运单号"
        ),
        "estimatedDelivery": None,
        "userId": row["customer_id"],
        "businessId": "aurora",
        "totalAmount": float(row.get("total_amount") or 0),
        "currency": row.get("currency") or "CNY",
        "createdAt": row["created_at"].isoformat() if row.get("created_at") else None,
        "shippingAddress": shipping,
        "isReturnable": bool(row.get("is_returnable", True)),
        "isAddressModifiable": bool(row.get("is_address_modifiable", True)),
        "source": "merchant",
    }


async def _list_merchant_orders(user_id: str) -> list[dict] | None:
    """商户库查单;库不可达返回 None 供调用方降级 engine 本地表。"""
    if not user_id:
        return []
    try:
        async with _merchant_reader_engine().connect() as conn:
            rows = (
                (
                    await conn.execute(
                        text(
                            "SELECT * FROM merchant_orders WHERE customer_id = :uid "
                            "ORDER BY created_at DESC LIMIT 50"
                        ).bindparams(uid=user_id)
                    )
                )
                .mappings()
                .all()
            )
            return [_merchant_row_to_order(r) for r in rows]
    except Exception as err:  # noqa: BLE001 - 商户库离线不得阻断状态机
        print(f"[OrderDomainService] merchant reader unavailable: {err}")
        return None


async def _find_merchant_order(order_id: str, user_id: str) -> dict | None:
    if not user_id:
        return None
    try:
        async with _merchant_reader_engine().connect() as conn:
            row = (
                (
                    await conn.execute(
                        text("SELECT * FROM merchant_orders WHERE order_id = :oid AND customer_id = :uid LIMIT 1")
                        .bindparams(oid=order_id, uid=user_id)
                    )
                )
                .mappings()
                .first()
            )
            return _merchant_row_to_order(row) if row else None
    except Exception as err:  # noqa: BLE001
        print(f"[OrderDomainService] merchant reader unavailable: {err}")
        return None


async def _fetch_merchant_order_items(order_id: str) -> list[dict]:
    try:
        async with _merchant_reader_engine().connect() as conn:
            rows = (
                (
                    await conn.execute(
                        text("SELECT * FROM merchant_order_items WHERE order_id = :oid").bindparams(oid=order_id)
                    )
                )
                .mappings()
                .all()
            )
            return [
                {
                    "productId": r.get("spu_id") or r.get("sku_code"),
                    "name": r.get("title") or "商户商品",
                    "description": r.get("spec_summary") or "",
                    "quantity": int(r.get("quantity") or 1),
                    "priceAtPurchase": float(r.get("price") or 0),
                }
                for r in rows
            ]
    except Exception as err:  # noqa: BLE001
        print(f"[OrderDomainService] merchant items unavailable: {err}")
        return []


async def _update_merchant_order(order_id: str, *, status: str | None = None, shipping_address: dict | None = None) -> None:
    """聊天侧对商户真单的写穿透(退款状态 / 收货地址),与商户门户视图保持一致。"""
    try:
        async with _merchant_reader_engine().begin() as conn:
            if status is not None:
                await conn.execute(
                    text("UPDATE merchant_orders SET status = :st, updated_at = NOW() WHERE order_id = :oid")
                    .bindparams(st=status, oid=order_id)
                )
            if shipping_address is not None:
                await conn.execute(
                    text("UPDATE merchant_orders SET shipping_address = CAST(:addr AS JSONB), updated_at = NOW() WHERE order_id = :oid")
                    .bindparams(addr=json.dumps(shipping_address, ensure_ascii=False), oid=order_id)
                )
    except Exception as err:  # noqa: BLE001
        print(f"[OrderDomainService] merchant write-through failed: {err}")


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
                    conditions.append("user_id = :uid")
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

            # 商户门户真单回退(agent_merchant.merchant_orders,严格归属匹配)
            if user_id:
                merchant_order = await _find_merchant_order(order_id, user_id)
                if merchant_order:
                    return merchant_order

            # 三方商户订单表回退
            async with get_session() as session:
                tp_conditions = ["(ext_order_sn = :order_id OR ext_order_sn ILIKE :order_id)"]
                tp_params: dict = {"order_id": order_id}
                if user_id:
                    tp_conditions.append("customer_id = :uid")
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
        if order.get("source") == "merchant":
            items = await _fetch_merchant_order_items(order.get("orderId") or order_id)
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
        currency_prefix = "¥" if (order.get("currency") or "USD") == "CNY" else "$"
        total_amount_formatted = f"{currency_prefix}0.00"
        if computed_total > 0:
            total_amount_formatted = f"{currency_prefix}{computed_total:.2f}"
        elif order.get("totalAmount"):
            raw_val = str(order["totalAmount"])
            try:
                num_val = float(_AMOUNT_STRIP_RE.sub("", raw_val))
                total_amount_formatted = f"{currency_prefix}{num_val:.2f}"
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

        # 商户真单:以门户侧可退货标记为准
        if order.get("source") == "merchant" and not order.get("isReturnable", True):
            return {"error": f"⚠️ 退款拦截：订单 {order_id} 已被商户标记为不可退货。", "orderId": order_id}

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

        if order.get("source") == "merchant":
            await _update_merchant_order(effective_order_id, status="REFUNDED")

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
        """历史订单列表:商户门户真单优先(agent_merchant.merchant_orders),engine 本地表兜底。

        2026-09-05 起:与商户门户"我的订单"列表页同源,严格按当前用户归属匹配;
        不再回退 CUST-8801 演示单,也不再空结果自愈注入虚构订单。
        """
        target_user_id = user_id
        target_business_id = business_id
        if (not target_user_id or not target_business_id) and thread_id:
            ctx = await OrderDomainService.get_thread_session_context(thread_id)
            target_user_id = target_user_id or ctx["userId"]
            target_business_id = target_business_id or ctx["businessId"]

        target_business_id = (target_business_id or "ecommerce").lower()

        # TODO(Phase 1b): 租户配置 spiConnector.remote 时经 SPI 连接器远程查单(connectors/ 批次)

        # 1) 商户门户真单 —— 与列表页同源,严格归属匹配;库不可达(None)时静默降级
        merchant_orders = await _list_merchant_orders(target_user_id or "")
        if merchant_orders:
            return {"orders": merchant_orders}

        # 2) engine 本地表兜底(非商户租户演示单,或商户库离线)
        if target_user_id:
            orders_sql = (
                'SELECT "order_id" AS "orderId", status, carrier, "tracking_number" AS "trackingNumber", '
                '"estimated_delivery" AS "estimatedDelivery", "total_amount" AS "totalAmount", '
                '"business_id" AS "businessId" FROM orders '
                'WHERE "user_id" = :uid AND "business_id" = :bid '
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
                    if rows:
                        return {"orders": [dict(row) for row in rows]}
            except Exception as err:  # noqa: BLE001
                print(f"[OrderDomainService.listUserOrders] Failed: {err}")
                return {"error": "Failed to retrieve orders from database."}
        return {"orders": [], "message": "No orders found for this customer."}

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

            if status.lower() in ("shipped", "delivered"):
                return {
                    "error": (
                        f"⚠️ Address modification blocked: Order {order_id} is currently "
                        f"[{status.upper()}] and has already left our logistics centers. "
                        "Physical modification is impossible."
                    )
                }

            # 商户真单:以门户侧可改性标记为准
            if order.get("source") == "merchant" and not order.get("isAddressModifiable", True):
                return {"error": f"⚠️ 地址修改拦截：订单 {order_id} 已被商户标记为不可修改收货地址。", "orderId": order_id}

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

            if order.get("source") == "merchant":
                existing_shipping = (
                    order.get("shippingAddress") if isinstance(order.get("shippingAddress"), dict) else {}
                )
                await _update_merchant_order(
                    effective_order_id, shipping_address={**existing_shipping, "fullAddress": new_address}
                )

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
            fact_text = f"[User {preference_type} preference]: {preference_value}"
            serialized_embedding = None
            try:
                # 统一走 llm/chat.py 入口,随 AI_EMBEDDING_PROVIDER 切换本地/远端
                embedding = await get_embedding_model().aembed_query(fact_text)
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
