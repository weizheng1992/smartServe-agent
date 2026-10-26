"""商户领域服务 — 移植 apps/merchant/src/services/merchantDomainService.ts(方法级 1:1)。"""

from __future__ import annotations

import datetime as _dt
import json
import os
import secrets
import time
import uuid as _u
from dataclasses import dataclass
from typing import Any

from engine_py.tools_registry.mall_domain import MallDomainService
from engine_py.tools_registry.order_domain import (
    generate_order_id,
    insert_merchant_order,
    insert_merchant_order_item,
    merchant_reader_engine,
    merchant_writer_engine,
)
from sqlalchemy import text

from .merchant_db import ensure_merchant_tables, merchant_engine


def _merchant_id() -> str:
    return os.environ.get("MERCHANT_ID", "aurora")


def _now_ms() -> int:
    return int(time.time() * 1000)


def _iso(row: Any, key: str) -> str:
    val = row.get(key)
    if not val:
        return _dt.datetime.now(_dt.UTC).isoformat()
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


async def _items_by_orders(conn: Any, order_ids: list) -> dict:
    """批量取行项目按 order_id 分组(列表页 N+1 根治;2026-09-26 夜审 ③#1)。"""
    if not order_ids:
        return {}
    rows = (
        await conn.execute(
            text("SELECT * FROM merchant_order_items WHERE order_id = ANY(:oids)"),
            {"oids": list(order_ids)},
        )
    ).mappings().all()
    grouped: dict = {}
    for r in rows:
        grouped.setdefault(r["order_id"], []).append(dict(r))
    return grouped


async def _spu_to_product(conn: Any, spu: Any, sku_rows: list | None = None) -> dict:
    if sku_rows is None:
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
        items_grouped = await _items_by_orders(conn, [r["order_id"] for r in rows])
        return [_order_from_row(row, items_grouped.get(row["order_id"], [])) for row in rows]


async def get_order_detail(order_id: str, business_id: str | None = None) -> dict | None:
    """订单详情(camelCase 同形序列化)。business_id 提供时即属主闸
    (2026-10-14 夜评批次:admin 订单链零租户过滤,A 店员工可读 B 店订单)——
    闸不中与查无同返回 None,调用方诚实 404,不泄存在性。"""
    await ensure_merchant_tables()
    async with merchant_engine().connect() as conn:
        if business_id:
            row = (
                await conn.execute(
                    text(
                        "SELECT * FROM merchant_orders WHERE order_id = :oid "
                        "AND LOWER(business_id) = :b LIMIT 1"
                    ),
                    {"oid": order_id, "b": business_id.strip().lower()},
                )
            ).mappings().first()
        else:
            row = (
                await conn.execute(text("SELECT * FROM merchant_orders WHERE order_id = :oid LIMIT 1"), {"oid": order_id})
            ).mappings().first()
        if row is None:
            return None
        items = await _fetch_items(conn, row["order_id"])
        return _order_from_row(row, items)


async def get_order_audit_logs(order_id: str) -> list[dict]:
    """订单关联审计时间线(SPI 动作/发货/退款):商户后台订单详情抽屉消费。"""
    await ensure_merchant_tables()
    async with merchant_engine().connect() as conn:
        rows = (
            await conn.execute(
                text("SELECT * FROM merchant_audit_logs WHERE order_id = :oid ORDER BY created_at ASC"),
                {"oid": order_id},
            )
        ).mappings().all()
        return [
            {k: (v.isoformat() if isinstance(v, _dt.datetime) else v) for k, v in dict(r).items()} for r in rows
        ]


class _IdempotentReplay(Exception):
    """同 idempotency_key 并发失利:审计 INSERT 撞唯一约束,败者回滚自身变更
    并回放胜者结果(唯一约束即幂等闸,替代旧「查后插」的竞态窗)。"""

    def __init__(self, log_row: dict) -> None:
        self.log_row = log_row
        super().__init__(str(log_row.get("id") or ""))


async def _audit_insert_idempotent(
    conn: Any, *, action_type: str, order_id: str, idempotency_key: str, payload_json: str, result_json: str,
    operator: str = "AGENT_SPI",
) -> None:
    """审计落账单点:ON CONFLICT DO NOTHING + RETURNING —— 插入成功返回;
    撞 key(并发败者)回读胜者行抛 _IdempotentReplay,由调用方事务整体回滚。
    operator 缺省 AGENT_SPI(SPI 通道既有语义);员工面动作(发货)传员工 email,
    订单详情审计时间线才看得到「谁发的货」(2026-10-25 客服优化批)。"""
    inserted = (
        await conn.execute(
            text(
                "INSERT INTO merchant_audit_logs (action_type, order_id, idempotency_key, operator, payload, result) "
                "VALUES (:at, :oid, :ik, :op, :p, :r) "
                "ON CONFLICT (idempotency_key) DO NOTHING RETURNING id"
            ),
            {
                "at": action_type,
                "oid": order_id,
                "ik": idempotency_key,
                "op": operator,
                "p": payload_json,
                "r": result_json,
            },
        )
    ).first()
    if inserted is not None:
        return
    winner = (
        await conn.execute(
            text("SELECT * FROM merchant_audit_logs WHERE idempotency_key = :ik LIMIT 1"),
            {"ik": idempotency_key},
        )
    ).mappings().first()
    raise _IdempotentReplay(dict(winner) if winner else {})


async def execute_order_action(req: dict, signature: str | None = None) -> dict:
    await ensure_merchant_tables()
    action_id = f"ACT_{_now_ms()}_{secrets.token_hex(2)}"

    def _replay_envelope(log_row: dict) -> dict:
        result = log_row.get("result")
        if isinstance(result, str):
            result = json.loads(result)
        return {
            **(result or {}),
            "success": True,
            "actionType": req["actionType"],
            "orderId": req["orderId"],
            "actionId": str(log_row.get("id") or ""),
            "message": "幂等防重响应：已成功执行过该指令",
        }

    try:
        async with merchant_engine().begin() as conn:
            # 幂等防重快路(重放免变更尝试;真正的并发闸在审计 INSERT 的
            # 唯一约束 —— async-4:旧「查后插」竞态败者 IntegrityError→500)
            if req.get("idempotencyKey"):
                log = (
                    await conn.execute(
                        text("SELECT * FROM merchant_audit_logs WHERE idempotency_key = :ik LIMIT 1"),
                        {"ik": req["idempotencyKey"]},
                    )
                ).mappings().first()
                if log is not None:
                    return _replay_envelope(dict(log))

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
                await _audit_insert_idempotent(
                    conn,
                    action_type="MODIFY_ADDRESS",
                    order_id=req["orderId"],
                    idempotency_key=req.get("idempotencyKey") or action_id,
                    payload_json=json.dumps({**req, "signature": signature}, ensure_ascii=False),
                    result_json=json.dumps(result_payload, ensure_ascii=False),
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
                await _audit_insert_idempotent(
                    conn,
                    action_type="REQUEST_REFUND",
                    order_id=req["orderId"],
                    idempotency_key=req.get("idempotencyKey") or action_id,
                    payload_json=json.dumps({**req, "signature": signature}, ensure_ascii=False),
                    result_json=json.dumps(result_payload, ensure_ascii=False),
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
    except _IdempotentReplay as replay:
        # 并发败者:自身变更随事务整体回滚(与旧 IntegrityError 回滚语义一致),
        # 回放胜者结果 —— 200 幂等重放,不再泄漏 500(store_spi:178 兜底退役)
        return _replay_envelope(replay.log_row)


async def search_products(query: str | None = None, category: str | None = None, limit: int = 10) -> list[dict]:
    """商品检索(SPI v1 /store 面用)。A8 收敛:词元切分与 WHERE 匹配子句
    与 engine 导购链同源(MallDomainService.search_terms / catalog_match
    单一实现)—— 整句 ILIKE 对口语措辞永远空手而归(engine 2026-09-11 同
    症状)。行形状 / SKU 分组 / created_at 排序仍是网关门户契约,不动;
    有 query 却提不出词元 = 无命中,诚实空(严禁变相浏览全货架)。"""
    await ensure_merchant_tables()
    terms = MallDomainService.search_terms(query) if query else []
    if query and not terms:
        return []
    conditions, q, _title_hit = MallDomainService.catalog_match(terms, category)
    q["lim"] = limit
    async with merchant_engine().connect() as conn:
        rows = (
            await conn.execute(
                text(
                    f"SELECT s.* FROM merchant_spus s WHERE {' AND '.join(conditions)} "
                    "ORDER BY s.created_at ASC LIMIT :lim"
                ),
                q,
            )
        ).mappings().all()
        # 命中 SPU 的 SKU 一次取回按 spu_id 分组(逐 SPU 单查的 1+N 同型根治)
        sku_grouped: dict = {}
        if rows:
            sku_rows = (
                await conn.execute(
                    text("SELECT * FROM merchant_skus WHERE spu_id = ANY(:sids) ORDER BY price ASC"),
                    {"sids": [r["id"] for r in rows]},
                )
            ).mappings().all()
            for sr in sku_rows:
                sku_grouped.setdefault(sr["spu_id"], []).append(sr)
        return [await _spu_to_product(conn, r, sku_grouped.get(r["id"], [])) for r in rows]


async def get_product_detail(product_id_or_id: str) -> dict | None:
    await ensure_merchant_tables()
    import re as _re

    is_uuid = bool(_re.match(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$", product_id_or_id))
    async with merchant_engine().connect() as conn:
        if is_uuid:
            # 单参单语境(2026-10-17 Story 9 e2e 实弹):uuid 列与 text 参数直比
            # 会炸 operator does not exist(text = uuid);而同参双语境(CAST 要
            # uuid、spu_code = :pid 要 text)会让 Postgres 类型推断直接失败 ——
            # 两坑都踩过后定式:按形状分流,uuid 分支只留 CAST 单比较。
            spu = (
                await conn.execute(
                    text("SELECT * FROM merchant_spus WHERE id = CAST(:pid AS uuid) LIMIT 1"),
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
    """单 SKU 直购薄前奏(2026-10-17 结算核归一):装配行请求与地址缺省,译
    信封 —— 落库编排全数下沉 _commit_order。错误文案保持本臂历史口径
    (「SKU 规格 …」/「库存不足：…」,经结构化错误子类翻译),线契约零变化。"""
    try:
        out = await _commit_order(
            customer_id=params["customerId"],
            items=[_OrderItemRequest(sku_code=params["skuCode"], quantity=params.get("quantity") or 1)],
            shipping_address={
                "recipientName": params.get("recipientName", "张伟"),
                "phone": params.get("recipientPhone", "13800138000"),
                "fullAddress": params.get("shippingAddress") or "北京市海淀区中关村南大街1号院8号楼1201室",
            },
            coupon_id=params.get("couponId"),
            skip_coupon=bool(params.get("skipCoupon")),
            business_id=params.get("businessId"),
            source="直购",
        )
    except _SkuMissing as err:
        return {"success": False, "message": f"SKU 规格 [{err.sku_code}] 不存在或已下架"}
    except _StockShortage as err:
        return {"success": False, "message": f"库存不足：{err.sku_title} 当前剩余 {err.remaining} 件"}
    except _CartError as err:
        return {"success": False, "message": err.message}
    return {
        "success": True,
        "orderId": out.order_id,
        "originalAmount": round(out.total_amount, 2),
        "discount": round(out.discount, 2),
        "promoName": out.promo_name,
        "payableAmount": round(out.total_amount - out.discount, 2),
    }


# 承运商译名单点(与 apps/merchant/src/lib/logistics.ts carrierLabel 同词表;
# 未知编码原样透传 —— 数据诚实律,严禁编造承运商缺省)
_CARRIER_LABELS = {"SF": "顺丰速运", "JD": "京东快递", "ZTO": "中通快递", "EMS": "邮政 EMS"}


async def ship_order(order_id: str, carrier_code: str, tracking_no: str,
                     business_id: str | None = None, operator: str = "AGENT_SPI") -> dict:
    """发货(真实世界副作用)。2026-10-25 客服优化批收口三个既有坑:

    1. **状态谓词**:UPDATE 带 ``status = 'PAID'`` 条件 —— 此前已退款/已发货单
       可被 API 直接打成 SHIPPED,前端按钮显隐是唯一状态闸。谓词不中回查现状:
       同单同运单号 = 幂等重放(网络重试不误报冲突),否则 stateConflict 由路由
       映射 409。
    2. **审计落账**:SHIP 动作写 merchant_audit_logs(operator=发货员工 email),
       与 MODIFY_ADDRESS/REQUEST_REFUND 同律;此前发货零审计,订单详情审计
       时间线看不到发货动作。
    3. **诚实轨迹**:tracking_info 落单节点「已发货 + 轨迹待更新」—— 旧实现的
       揽收/运输/派送三节点是硬编码伪造文案(违数据诚实律),真实物流源未接入
       前严禁宣称在途/派送中;坐席推物流卡会把该字段变成顾客可见断言。

    business_id 提供时即属主闸:闸不中 rowcount 0 走「订单不存在」,跨租户零
    副作用(2026-10-14 夜评批次)。
    """
    await ensure_merchant_tables()
    now = _dt.datetime.now(_dt.UTC)
    # 空入空出、未知编码原样透传 —— 严禁编造承运商缺省(路由层 or "SF" 已是活
    # 缺省,此处不再兜第二层假名;code-review Standards 轴 2026-10-25)
    _code = (carrier_code or "").strip()
    carrier_label = _CARRIER_LABELS.get(_code, _code)
    tracking_info = {
        "carrier": carrier_label,
        "trackingNumber": tracking_no,
        "status": "SHIPPED",
        "timeline": [
            {
                "time": now.isoformat(),
                "status": "已发货",
                "location": "",
                "description": f"商家已发货 · {carrier_label} · 运单号 {tracking_no}，物流轨迹待更新",
            }
        ],
    }
    ti_json = json.dumps(tracking_info, ensure_ascii=False)
    tenant_pred = "AND LOWER(business_id) = :b" if business_id else ""
    bind: dict = {"ti": ti_json, "oid": order_id}
    if business_id:
        bind["b"] = business_id.strip().lower()
    async with merchant_engine().begin() as conn:
        result = await conn.execute(
            text(
                "UPDATE merchant_orders SET status = 'SHIPPED', tracking_info = :ti, is_address_modifiable = FALSE "
                f"WHERE order_id = :oid AND status = 'PAID' {tenant_pred}"
            ),
            bind,
        )
        if (result.rowcount or 0) > 0:
            await _audit_insert_idempotent(
                conn,
                action_type="SHIP",
                order_id=order_id,
                idempotency_key=f"SHIP_{order_id}_{tracking_no}",
                payload_json=json.dumps(
                    {"orderId": order_id, "carrierCode": carrier_code, "trackingNo": tracking_no, "operator": operator},
                    ensure_ascii=False,
                ),
                result_json=json.dumps(
                    {"message": f"已发货 · {carrier_label} · 运单号 {tracking_no}", "status": "SHIPPED"},
                    ensure_ascii=False,
                ),
                operator=operator,
            )
            return {
                "success": True,
                "orderId": order_id,
                "message": "发货成功，已流转为已发货状态并锁定地址",
            }
        # 谓词不中:回查现状裁决 幂等重放 vs 状态冲突 vs 不存在
        row = (
            await conn.execute(
                text(f"SELECT status, tracking_info FROM merchant_orders WHERE order_id = :oid {tenant_pred} LIMIT 1"),
                {"oid": bind["oid"], **({"b": bind["b"]} if business_id else {})},
            )
        ).mappings().first()
        if row is None:
            return {"success": False, "message": "订单不存在"}
        current_status = str(row["status"])
        current_tracking_info = row["tracking_info"] if isinstance(row["tracking_info"], dict) else {}
        current_tracking = current_tracking_info.get("trackingNumber")
        current_carrier = current_tracking_info.get("carrier")
        if current_status == "SHIPPED" and current_tracking == tracking_no and current_carrier == carrier_label:
            return {
                "success": True,
                "orderId": order_id,
                "replay": True,
                "message": "该订单已按同一运单号发货，幂等放行",
            }
        return {
            "success": False,
            "stateConflict": True,
            "currentState": current_status,
            "message": f"订单当前状态为【{current_status}】，不可发货（仅待发货状态可发货）",
        }


async def get_admin_dashboard_data(business_id: str | None = None) -> dict:
    """运营台聚合数据。business_id 提供时按租户过滤订单与审计时间线
    (2026-10-14 夜评批次:A 店员工不得见 B 店订单);SPU/SKU 目录当前为
    平台共享单目录,不在本闸范围。"""
    await ensure_merchant_tables()
    async with merchant_engine().connect() as conn:
        if business_id:
            orders = [
                dict(r)
                for r in (
                    await conn.execute(
                        text("SELECT * FROM merchant_orders WHERE LOWER(business_id) = :b "
                             "ORDER BY created_at DESC LIMIT 50"),
                        {"b": business_id.strip().lower()},
                    )
                ).mappings().all()
            ]
            audit_logs = [
                dict(r)
                for r in (
                    await conn.execute(
                        text("SELECT a.* FROM merchant_audit_logs a "
                             "JOIN merchant_orders o ON a.order_id = o.order_id "
                             "WHERE LOWER(o.business_id) = :b "
                             "ORDER BY a.created_at DESC LIMIT 50"),
                        {"b": business_id.strip().lower()},
                    )
                ).mappings().all()
            ]
        else:
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


async def insert_customer(
    conn,
    *,
    customer_id: str,
    name: str,
    phone: str = "",
    email: str | None = None,
    member_level: str = "VIP",
    addresses: str = "[]",
    tags: str = "[]",
) -> None:
    """客户建档**原语**(列清单单点;连接与事务由调用方持有)。

    层次:A6 收口(2026-10-06)后建档列清单唯一于此;上层用例
    `create_customer_record`(自持事务 + uuid 段 cid)与注册/种子两调用方
    (auth/merchant_seed,自带连接语境)皆经本原语落库 —— 严禁绕开直写
    INSERT 列清单。"""

    await conn.execute(
        text(
            "INSERT INTO merchant_customers (customer_id, name, phone, email, member_level, addresses, tags) "
            "VALUES (:cid, :n, :p, :e, :lv, CAST(:addr AS jsonb), CAST(:tags AS jsonb))"
        ),
        {
            "cid": customer_id, "n": name, "p": phone, "e": email,
            "lv": member_level, "addr": addresses, "tags": tags,
        },
    )


# ── 客户域(A2 下沉,2026-10-06):CRUD 业务逻辑自 analytics 路由层迁入,
# 路由只留权限闸与 error-key → HTTP 映射(与 promotions.delete_promotion 同款形状)。
# 事务由各函数自持(writer 位),读走 reader 位。


async def customer_coupons_list(customer_id: str) -> list[dict]:
    """客户名下券列表(核销/发券面板回显)。"""

    async with merchant_reader_engine().connect() as conn:
        rows = (
            await conn.execute(
                text(
                    "SELECT uc.id::text AS id, p.name, p.discount_value::float AS value, uc.status, "
                    "uc.claimed_at, uc.used_order_id "
                    "FROM user_coupons uc JOIN promotions p ON p.id = uc.promotion_id "
                    "WHERE uc.user_id = :cid ORDER BY uc.claimed_at DESC LIMIT 50"
                ).bindparams(cid=customer_id)
            )
        ).mappings().all()
    return [
        {
            "id": r["id"], "name": r["name"], "value": r["value"], "status": r["status"],
            "claimedAt": r["claimed_at"].isoformat() if r["claimed_at"] else None,
            "usedOrderId": r["used_order_id"],
        }
        for r in rows
    ]


async def update_customer_member_level(customer_id: str, member_level: str) -> dict:
    """会员级编辑;查无返回 error-key。"""

    async with merchant_writer_engine().begin() as conn:
        result = await conn.execute(
            text("UPDATE merchant_customers SET member_level = :lv, updated_at = NOW() WHERE customer_id = :cid")
            .bindparams(lv=str(member_level or "VIP"), cid=customer_id)
        )
        if result.rowcount == 0:
            # error-key 机器键(夜评 2026-10-07):not_found 供路由 404 分叉,文案走 message
            return {"error": "not_found", "message": "客户不存在"}
    return {"customerId": customer_id, "memberLevel": member_level}


async def create_customer_record(name: str, phone: str, member_level: str = "VIP") -> dict:
    """新增客户**用例**(uuid 段 cid;自持 writer 事务,经 insert_customer
    原语落库 —— 原语/用例分层见其 docstring)。"""


    cid = f"CUST-{_u.uuid4().hex[:8].upper()}"
    async with merchant_writer_engine().begin() as conn:
        await insert_customer(conn, customer_id=cid, name=name, phone=phone, member_level=member_level)
    return {"customerId": cid}


async def delete_customer(customer_id: str) -> dict:
    """删除客户(订单引用护栏:名下有订单不可删)。"""

    async with merchant_writer_engine().begin() as conn:
        has_orders = (
            await conn.execute(
                text("SELECT 1 FROM merchant_orders WHERE customer_id = :c LIMIT 1").bindparams(c=customer_id)
            )
        ).first()
        if has_orders:
            return {"error": "客户名下有订单,不可删除"}
        await conn.execute(
            text("DELETE FROM merchant_customers WHERE customer_id = :c").bindparams(c=customer_id)
        )
    return {"success": True}


# ── SPU/SKU 目录域(A2 之二,2026-10-06):增删改查自 analytics 路由层迁入。
# 删除护栏(成交记录)与字段级更新白名单属目录业务规则,住领域层;
# 路由只留 prod:edit 权限闸与 error-key → HTTP 映射。


async def spus_list() -> list[dict]:

    async with merchant_reader_engine().connect() as conn:
        rows = (
            await conn.execute(
                text(
                    'SELECT s.id::text AS id, s.spu_code, s.title, s.category, s.status, '
                    's.owner_id::text AS "ownerId", '
                    "COALESCE(MIN(k.price), 0)::float AS price, COALESCE(SUM(k.stock), 0)::int AS stock "
                    "FROM merchant_spus s LEFT JOIN merchant_skus k ON k.spu_id = s.id "
                    "GROUP BY s.id, s.spu_code, s.title, s.category, s.status, s.owner_id ORDER BY s.title LIMIT 200"
                )
            )
        ).mappings().all()
    return [dict(r) for r in rows]


async def create_spu(title: str, category: str, price: float, stock: int, owner_id: str | None = None) -> dict:
    """新建 SPU + 默认 SKU 一体(异步pg 严格类型:uuid 列显式 CAST;
    main_image/sku_title/spec_attributes NOT NULL,落诚实默认值)。
    owner_id(Q15):负责人默认当前操作人,空 = 未分配(解析端诚实降级)。"""


    spu_id = str(_u.uuid4())
    code = f"SPU-{_u.uuid4().hex[:8].upper()}"
    async with merchant_writer_engine().begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO merchant_spus (id, spu_code, title, category, main_image, status, owner_id) "
                "VALUES (CAST(:id AS uuid), :code, :t, :cat, '', 'ON_SALE', :owner)"
            ).bindparams(id=spu_id, code=code, t=title, cat=category, owner=owner_id)
        )
        await conn.execute(
            text(
                "INSERT INTO merchant_skus (id, spu_id, sku_code, sku_title, spec_attributes, price, stock) "
                "VALUES (CAST(:id AS uuid), CAST(:spu AS uuid), :code, :st, CAST(:attrs AS jsonb), :price, :stock)"
            ).bindparams(
                id=str(_u.uuid4()), spu=spu_id, code=code + "-SKU-1",
                st=f"{title} 默认款", attrs="{}", price=float(price), stock=stock,
            )
        )
    return {"id": spu_id, "spuCode": code}


async def update_spu(spu_id: str, body: dict) -> dict:
    """字段级更新(status/title/price/stock/ownerId 携带即改;价格/库存落首个 SKU;
    ownerId 空串 = 清空负责人,Q15)。"""

    if "status" in body and body["status"] not in ("ON_SALE", "OFF_SALE"):
        return {"error": "status ∈ ON_SALE|OFF_SALE"}
    async with merchant_writer_engine().begin() as conn:
        if "ownerId" in body:
            await conn.execute(
                text("UPDATE merchant_spus SET owner_id = :o WHERE id = CAST(:id AS uuid)")
                .bindparams(o=(str(body["ownerId"]).strip() or None), id=spu_id)
            )
        if "status" in body:
            await conn.execute(
                text("UPDATE merchant_spus SET status = :s WHERE id = CAST(:id AS uuid)")
                .bindparams(s=body["status"], id=spu_id)
            )
        if "title" in body:
            await conn.execute(
                text("UPDATE merchant_spus SET title = :t WHERE id = CAST(:id AS uuid)")
                .bindparams(t=str(body["title"]), id=spu_id)
            )
        if "price" in body:
            await conn.execute(
                text(
                    "UPDATE merchant_skus SET price = :p WHERE id = "
                    "(SELECT id FROM merchant_skus WHERE spu_id = CAST(:id AS uuid) LIMIT 1)"
                ).bindparams(p=float(body["price"]), id=spu_id)
            )
        if "stock" in body:
            await conn.execute(
                text(
                    "UPDATE merchant_skus SET stock = :s WHERE id = "
                    "(SELECT id FROM merchant_skus WHERE spu_id = CAST(:id AS uuid) LIMIT 1)"
                ).bindparams(s=int(body["stock"]), id=spu_id)
            )
    return {"id": spu_id}


async def delete_spu(spu_id: str) -> dict:
    """删除 SPU(成交引用护栏:有订单明细不可删,可下架)。"""

    async with merchant_writer_engine().begin() as conn:
        code = (
            await conn.execute(
                text("SELECT spu_code FROM merchant_spus WHERE id = CAST(:id AS uuid)").bindparams(id=spu_id)
            )
        ).scalar()
        if not code:
            return {"error": "not_found", "message": "商品不存在"}
        referenced = (
            await conn.execute(
                text("SELECT 1 FROM merchant_order_items WHERE spu_id = :c LIMIT 1").bindparams(c=code)
            )
        ).first()
        if referenced:
            return {"error": "该商品已有成交记录,不可删除(可下架 OFF_SALE)"}
        await conn.execute(text("DELETE FROM merchant_skus WHERE spu_id = CAST(:id AS uuid)").bindparams(id=spu_id))
        await conn.execute(text("DELETE FROM merchant_spus WHERE id = CAST(:id AS uuid)").bindparams(id=spu_id))
    return {"success": True}


async def skus_stock_list() -> list[dict]:

    async with merchant_reader_engine().connect() as conn:
        rows = (
            await conn.execute(
                text(
                    "SELECT k.id::text AS id, k.sku_code, k.sku_title, s.id::text AS spu_id, "
                    "s.title AS spu_title, k.price::float AS price, k.stock, "
                    "k.spec_attributes::text AS spec_attributes "
                    "FROM merchant_skus k JOIN merchant_spus s ON s.id = k.spu_id "
                    "ORDER BY k.sku_code LIMIT 500"
                )
            )
        ).mappings().all()
    return [dict(r) for r in rows]


async def skus_list(spu_id: str) -> list[dict]:

    async with merchant_reader_engine().connect() as conn:
        rows = (
            await conn.execute(
                text(
                    "SELECT id::text, sku_code, sku_title, price::float AS price, stock, "
                    "spec_attributes::text AS spec_attributes FROM merchant_skus "
                    "WHERE spu_id = CAST(:id AS uuid) ORDER BY sku_code"
                ).bindparams(id=spu_id)
            )
        ).mappings().all()
    return [dict(r) for r in rows]


async def create_sku(spu_id: str, body: dict) -> dict:
    """新增 SKU(目标 SPU 存在性校验在领域层)。"""


    price = body.get("price")
    if price is None:
        return {"error": "price 必传"}
    sku_code = f"SKU-{_u.uuid4().hex[:10].upper()}"
    spec = body.get("specAttributes") or {}
    async with merchant_writer_engine().begin() as conn:
        spu = (
            await conn.execute(
                text("SELECT spu_code FROM merchant_spus WHERE id = CAST(:id AS uuid)").bindparams(id=spu_id)
            )
        ).first()
        if not spu:
            return {"error": "not_found", "message": "SPU 不存在"}
        await conn.execute(
            text(
                "INSERT INTO merchant_skus (id, spu_id, sku_code, sku_title, price, stock, spec_attributes) "
                "VALUES (CAST(:id AS uuid), CAST(:spu AS uuid), :code, :title, :price, :stock, CAST(:spec AS jsonb))"
            ).bindparams(
                id=str(_u.uuid4()), spu=spu_id, code=sku_code,
                title=body.get("skuTitle") or "", price=float(price),
                stock=int(body.get("stock") or 0), spec=json.dumps(spec, ensure_ascii=False),
            )
        )
    return {"skuCode": sku_code}


async def update_sku(sku_id: str, body: dict) -> dict:
    """SKU 字段级更新(price/stock/skuTitle 白名单;空补丁诚实拒绝;查无 404)。

    值域校验诚实 400(2026-10-17 Story 9 收口):price > 0 / stock >= 0 /
    skuTitle 非空 —— 此前负价负库存直接入库(商店 MIN(price) 会展示负价),
    查无 id 静默 success 回显 id(假成功)。
    """

    sets, params = [], {"id": sku_id}
    if "price" in body:
        price = float(body["price"])
        if not price > 0:
            return {"error": "invalid", "message": "价格必须为大于 0 的数值"}
        sets.append("price = :price")
        params["price"] = price
    if "stock" in body:
        stock = int(body["stock"])
        if stock < 0:
            return {"error": "invalid", "message": "库存不能为负数"}
        sets.append("stock = :stock")
        params["stock"] = stock
    if "skuTitle" in body:
        title = str(body["skuTitle"]).strip()
        if not title:
            return {"error": "invalid", "message": "规格名不能为空"}
        sets.append("sku_title = :skuTitle")
        params["skuTitle"] = title
    if not sets:
        return {"error": "无可更新字段"}
    async with merchant_writer_engine().begin() as conn:
        result = await conn.execute(
            text(f"UPDATE merchant_skus SET {', '.join(sets)} WHERE id = CAST(:id AS uuid)").bindparams(**params)
        )
    if result.rowcount == 0:
        return {"error": "not_found", "message": f"SKU {sku_id} 不存在"}
    return {"id": sku_id}


async def delete_sku(sku_id: str) -> dict:
    """删除 SKU(成交引用护栏:已有成交不可删,可改库存为 0)。"""

    async with merchant_writer_engine().begin() as conn:
        sold = (
            await conn.execute(
                text(
                    "SELECT 1 FROM merchant_order_items WHERE sku_code = "
                    "(SELECT sku_code FROM merchant_skus WHERE id = CAST(:id AS uuid)) LIMIT 1"
                ).bindparams(id=sku_id)
            )
        ).first()
        if sold:
            return {"error": "该 SKU 已有成交,不可删除(可改库存为 0)"}
        await conn.execute(text("DELETE FROM merchant_skus WHERE id = CAST(:id AS uuid)").bindparams(id=sku_id))
    return {"success": True}


def mask_phone(phone: str | None) -> str | None:
    """手机脱敏(A11 归位,2026-10-06:自 live_desk 路由迁入领域层):前 3 后 4,
    非 11 位只露后 4。凡向坐席/管理面呈现顾客手机号一律经此。"""
    if not phone:
        return None
    digits = phone.strip()
    if len(digits) >= 8:
        return f"{digits[:3]}****{digits[-4:]}"
    return f"****{digits[-4:]}" if digits else None


# 客户消费聚合口径单点(A7,2026-10-06):analytics 客户列表与 live_desk 坐席
# 上下文曾各写一份 SUM/COUNT —— 加退款排除一类口径变更只改其一即静默分叉。
CUSTOMER_SPEND_JOIN = (
    "FROM merchant_customers c LEFT JOIN merchant_orders o ON o.customer_id = c.customer_id"
)
CUSTOMER_SPEND_AGG = (
    "COALESCE(SUM(o.total_amount),0)::float AS total_spent, COUNT(o.order_id)::int AS order_count"
)


async def fetch_customers_with_spend(
    conn,
    *,
    customer_id: str | None = None,
    extra_column: str = "",
    limit: int | None = None,
) -> list[dict]:
    """客户档 + 消费聚合**唯一查询体**(A7 口径常量的查询侧收口,夜评 smell
    清尾):客户列表(analytics)与坐席上下文(live_desk)口径常量单点后查询
    本体仍各拼一份 —— 加列/改排序仍会单侧漂移。extra_column 传 addresses/tags
    等客户 jsonb 列(归一 COALESCE '[]'::jsonb → text);customer_id 传即单档;
    limit 传即截断。GROUP BY c.id 依赖 PG 主键函数依赖(列表旧六列 GROUP BY
    等价改写)。返回 mappings 行的 dict 列表。"""
    extra = f"COALESCE(c.{extra_column}, '[]'::jsonb)::text AS {extra_column}, " if extra_column else ""
    where = "WHERE c.customer_id = :cid" if customer_id else ""
    lim = f" LIMIT {int(limit)}" if limit else ""
    sql = (
        "SELECT c.customer_id, c.name, c.phone, COALESCE(c.email, '') AS email, "
        "COALESCE(c.member_level, 'VIP') AS member_level, "
        + extra
        + f"{CUSTOMER_SPEND_AGG} "
        f"{CUSTOMER_SPEND_JOIN} "
        f"{where} GROUP BY c.id{lim}"
    )
    params = {"cid": customer_id} if customer_id else {}
    return [dict(r) for r in (await conn.execute(text(sql), params)).mappings().all()]


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
    """保存客户地址簿条目(读整组 → 合并 → 整列覆写)。

    并发安全(async-3 收口,2026-10-18):读整组与覆写此前横跨两个独立连接,
    并发各存一条地址时后写者以自己读到的旧组整列覆写,先写者地址必丢 ——
    现取货/合并/覆写收进同一事务,`pg_advisory_xact_lock(hashtext(cid))` 按
    客户串行化(首存两并发都查不到行、无行可 FOR UPDATE,咨询锁补齐该窗口)。"""
    await ensure_merchant_tables()

    full_addr = (
        addr.get("fullAddress")
        or f"{addr.get('province') or ''}{addr.get('city') or ''}{addr.get('district') or ''}{addr.get('detailAddress') or ''}".strip()
        or "北京市海淀区中关村南大街1号院"
    )

    target_id = addr.get("id") or f"ADDR_{_now_ms()}_{secrets.token_hex(2)}"

    async with merchant_engine().begin() as conn:
        await conn.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:cid))"), {"cid": customer_id}
        )
        row = (
            await conn.execute(
                text("SELECT addresses FROM merchant_customers WHERE customer_id = :cid"),
                {"cid": customer_id},
            )
        ).mappings().first()
        current = row["addresses"] if row and isinstance(row["addresses"], list) else []

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

        # T7 契约揪出(2026-10-06):首存客户此前 UPDATE 0 行 —— 地址静默丢失
        # 却照报 success。upsert 建档+落地址一步原子(customer_id UNIQUE)。
        await conn.execute(
            text(
                "INSERT INTO merchant_customers (customer_id, name, phone, addresses) "
                "VALUES (:cid, :name, :phone, CAST(:a AS jsonb)) "
                "ON CONFLICT (customer_id) DO UPDATE SET addresses = CAST(:a AS jsonb), updated_at = NOW()"
            ),
            {
                "cid": customer_id,
                "name": addr.get("recipientName") or customer_id,
                "phone": addr.get("phone") or "",
                "a": json.dumps(updated, ensure_ascii=False),
            },
        )
    return {"success": True, "address": formatted, "addresses": updated}


class _CartError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class _SkuMissing(_CartError):
    """SKU 查无(结构化:直购/购物车两前奏文案口径不同,由各自翻译)。"""

    def __init__(self, sku_code: object) -> None:
        self.sku_code = sku_code
        super().__init__(f"商品规格 [{sku_code}] 不存在")


class _StockShortage(_CartError):
    """库存不足(remaining=扣减失利后实读存量;requested=本次需求合计)。"""

    def __init__(self, sku_title: str, remaining: int, requested: int) -> None:
        self.sku_title = sku_title
        self.remaining = remaining
        self.requested = requested
        super().__init__(f"商品 [{sku_title}] 库存不足，当前仅剩 {remaining} 件")


async def _generate_order_id(conn: Any) -> str:
    """订单号生成闸:机制单点在 engine order_domain.generate_order_id
    (架构审查 #4 步2,2026-10-04 —— 此前与 mall_domain.checkout 内联 loop
    靠注释互指对齐);本面只做通道语义翻译:六次全撞 → _CartError 整体回滚。"""

    candidate = await generate_order_id(conn)
    if candidate is None:
        raise _CartError("订单号生成冲突，请稍后重试。")
    return candidate


@dataclass(frozen=True)
class PromoPart:
    """单笔优惠(活动或券)的结算切片。"""

    discount: float
    name: str
    promo_id: str | None = None
    row_id: str | None = None  # 券:user_coupons.id(核销用)


@dataclass(frozen=True)
class PromotionResolution:
    """结算优惠决议(P1 类型化,2026-09-23 code-review):属性访问根除裸 dict
    的 KeyError 族(回落字典缺键曾致促销表异常时整单 500)。"""

    activity: PromoPart | None = None
    coupon: PromoPart | None = None

    @property
    def discount(self) -> float:
        return round(
            (self.activity.discount if self.activity else 0.0)
            + (self.coupon.discount if self.coupon else 0.0),
            2,
        )

    @property
    def promo_name(self) -> str | None:
        names = [p.name for p in (self.activity, self.coupon) if p]
        return " + ".join(names) if names else None

    @property
    def coupon_row_id(self) -> str | None:
        return self.coupon.row_id if self.coupon else None

    @classmethod
    def empty(cls) -> PromotionResolution:
        """优惠引擎异常回落:按原价结算、零优惠、不核销。"""
        return cls()


async def _resolve_promotion(
    conn: Any,
    customer_id: str,
    amount: float,
    scope: set[str] | None,
    coupon_id: str | None = None,
    skip_coupon: bool = False,
    business_id: str | None = None,
) -> PromotionResolution:
    """结算优惠决议(服务端唯一算价点,20-D3):全分支统一委托共享的
    resolve_stacked_promotions(2026-09-23 缺省语义漂移收口 —— 旧「缺省自动
    择优单选」与叠加语义并存属漂移,现已同化)。

    - coupon_id 指定 → 自选券与活动叠加:券按(原价-活动优惠)余额计算,不可用
      抛 _CartError 如实拒单(严禁静默按全款落账 —— 3c4c843 同族教训);活动已
      覆盖全部金额时券零抵扣,同样拒单让用户保留券面。
    - skip_coupon → 用户明确不用券(商城页「不使用优惠券」),仅活动。
    - 两者皆缺省 → 叠加 + 自动取余额下最优券(与聊天通道同语义)。"""
    from engine_py.analytics.promotion_engine import resolve_stacked_promotions

    try:
        stacked = await resolve_stacked_promotions(
            conn, customer_id, amount, scope,
            coupon_row_id=coupon_id or None, auto_pick_coupon=not skip_coupon and not coupon_id,
            business_id=business_id,
        )
    except ValueError as err:
        raise _CartError(str(err)) from err
    act, cpn = stacked.get("activity"), stacked.get("coupon")
    return PromotionResolution(
        activity=(
            PromoPart(discount=float(act["discount"]), name=act["name"], promo_id=act.get("promo_id"))
            if act
            else None
        ),
        coupon=(
            PromoPart(
                discount=float(cpn["discount"]), name=cpn["name"],
                promo_id=cpn.get("promotion_id"), row_id=cpn["coupon_row_id"],
            )
            if cpn
            else None
        ),
    )


async def _record_promo_redemption(conn: Any, promo_id: str | None, order_id: str, discount: float) -> None:
    """薄适配:核销流水 SQL 单一事实源在 engine promotions(收口双实现)。"""
    from engine_py.analytics import promotions as _promo_svc

    await _promo_svc.record_promo_redemption(conn, promo_id, order_id, discount)


@dataclass(frozen=True)
class _OrderItemRequest:
    """跨前奏→结算核的行请求(2026-10-17 结算核决议):只携带「要什么」,
    价格/快照等落库值一律核内事务自取 —— camelCase dict 接缝正是 costPrice
    幽灵键事故(主结算路快照恒 0)的温床,强类型令漏供给在类型层报错。"""

    sku_code: str
    quantity: int


@dataclass(frozen=True)
class _SettlementOutcome:
    """结算核产物:两前奏各自译成自家信封(直购 originalAmount / 购物车 totalAmount)。"""

    order_id: str
    total_amount: float
    discount: float
    promo_name: str | None


async def _commit_order(
    *,
    customer_id: str,
    items: list[_OrderItemRequest],
    shipping_address: dict,
    coupon_id: str | None = None,
    skip_coupon: bool = False,
    business_id: str | None = None,
    source: str = "结算",
) -> _SettlementOutcome:
    """商户结算核(2026-10-17 grilling 决议,CONTEXT.md「结算核 commit_order」):
    单 SKU 直购与购物车两条编排此前各持一份手抄落库段,已两度各自漂移 ——
    直购路径漏写 cost_at_purchase(旧 :530 注释在案),购物车路径同洞至今
    (旧 :1358 读的 costPrice 键无人写入,快照恒 0,ADR-0003 毛利口径失效)。
    归一后本函数唯一拥有:取货 → 存在/库存校验 → 优惠决议 → 条件扣减 →
    插单 → 防双花核销 → 核销流水 → 行项目。

    接口不变量:
    - 核全权管事务(取货入事务):价格/库存以事务内时点为准,根除直购路径
      旧「事务外 connect 预读、begin 后不复读」的陈价雷(对抗核验 async-5)。
    - 扣减统一条件 UPDATE(stock >= 需求合计;rowcount=0 即并发失利,实读
      存量给诚实文案,异常整体回滚)—— 废弃购物车臂 FOR UPDATE+无条件
      UPDATE 的第二套超卖语义,防超卖不因入口不同而不同。
    - 券校验/核销冲突抛 _CartError 整体回滚,严禁事务块内 return 造成半截
      写入被隐式提交(原直购路径注释语义,随核收编)。
    - 线契约零变化:查无/缺货经结构化子类由前奏翻译,信封字段两臂各自保留;
      仅「券失效∧缺货并发」时错误优先级归直购形(决议先于扣减),终态不变。"""
    await ensure_merchant_tables()

    async with merchant_engine().begin() as conn:
        order_id = await _generate_order_id(conn)

        # 取货(事务内):一次取回全部涉及 SKU(N+1 根治,2026-09-26 夜审 ③#9)。
        # 不加 FOR UPDATE:扣减由条件 UPDATE 原子把关,读侧无需先锁行。
        sku_rows = (
            await conn.execute(
                text(
                    "SELECT s.*, p.title as spu_title, p.main_image as spu_image, p.id as spu_id, p.spu_code "
                    "FROM merchant_skus s JOIN merchant_spus p ON s.spu_id = p.id "
                    "WHERE s.sku_code = ANY(:codes)"
                ),
                {"codes": [item.sku_code for item in items]},
            )
        ).mappings().all()
        sku_by_code = {r["sku_code"]: r for r in sku_rows}

        # 行决议 + 算价:同码多条目需求累计(与原购物车逐条目累计语义等价)
        lines: list[dict] = []
        demanded: dict = {}
        total_amount = 0.0
        for item in items:
            sku = sku_by_code.get(item.sku_code)
            if sku is None:
                raise _SkuMissing(item.sku_code)
            quantity = item.quantity or 1
            lines.append(
                {
                    "spu_id": sku["spu_id"],
                    "sku_code": sku["sku_code"],
                    "title": sku["spu_title"],
                    "sku_title": sku["sku_title"],
                    "quantity": quantity,
                    "price": sku["price"],
                    "image_url": sku["image_url"] or sku["spu_image"],
                    "spec_summary": " / ".join(f"{k}:{v}" for k, v in (sku["spec_attributes"] or {}).items()),
                    # ADR-0003 成交进价快照:直取 SKU 行,不经中间 dict 再造
                    # (旧接缝正是快照丢失点)
                    "cost_at_purchase": float(sku.get("cost_price") or 0),
                }
            )
            total_amount += float(sku["price"]) * quantity
            demanded[sku["sku_code"]] = demanded.get(sku["sku_code"], 0) + quantity

        # 优惠引擎(20-D3):SAVEPOINT 隔离,失败按原价结算不毒化事务
        try:
            promo = await _resolve_promotion(
                conn,
                customer_id,
                round(total_amount, 2),
                {str(r["spu_code"]) for r in sku_rows} or None,
                coupon_id=coupon_id,
                skip_coupon=skip_coupon,
                business_id=business_id,
            )
        except _CartError:
            raise
        except Exception as promo_err:
            print(f"[MerchantDomain:{source}] 优惠计算失败,按原价结算: {promo_err}")
            promo = PromotionResolution.empty()
        discount = promo.discount

        # 条件 UPDATE(stock >= 需求合计)原子防超卖:rowcount=0 即并发失利,
        # 实读存量抛 _StockShortage 整体回滚 —— 事务外预检只是诚实文案的旧
        # 形态随核退役,COMMITTED 快照在 resolve 与扣减之间可被并发单改掉。
        for code, qty in demanded.items():
            decremented = await conn.execute(
                text(
                    "UPDATE merchant_skus SET stock = stock - :qty "
                    "WHERE sku_code = :code AND stock >= :qty"
                ).bindparams(qty=qty, code=code)
            )
            if not decremented.rowcount:
                fresh = (
                    await conn.execute(
                        text("SELECT sku_title, stock FROM merchant_skus WHERE sku_code = :code"),
                        {"code": code},
                    )
                ).mappings().first()
                if fresh is None:
                    raise _SkuMissing(code)
                raise _StockShortage(fresh["sku_title"], fresh["stock"], qty)

        await insert_merchant_order(
            conn,
            order_id=order_id,
            customer_id=customer_id,
            total_amount=total_amount - discount,
            discount_amount=discount,
            shipping_address_json=json.dumps(shipping_address, ensure_ascii=False),
            # 订单租户列(2026-10-14 夜评批次):店铺面单店口径,与券查询同律
            business_id=business_id or "aurora",
        )
        if promo.coupon_row_id:
            from engine_py.analytics import promotions as _promo_svc

            # 条件核销防双花:False=该券已被并发订单用掉,整体回滚拒单
            if not await _promo_svc.mark_coupon_used(conn, promo.coupon_row_id, order_id):
                raise _CartError("优惠券已被使用，请刷新券包后重试")
        if promo.activity:
            await _record_promo_redemption(conn, promo.activity.promo_id, order_id, promo.activity.discount)
        if promo.coupon:
            await _record_promo_redemption(conn, promo.coupon.promo_id, order_id, promo.coupon.discount)
        for line in lines:
            await insert_merchant_order_item(
                conn,
                order_id=order_id,
                spu_id=line["spu_id"],
                sku_code=line["sku_code"],
                title=line["title"],
                sku_title=line["sku_title"],
                quantity=line["quantity"],
                price=line["price"],
                image_url=line["image_url"],
                spec_summary=line["spec_summary"],
                cost_at_purchase=line["cost_at_purchase"],
            )
    return _SettlementOutcome(
        order_id=order_id,
        total_amount=total_amount,
        discount=discount,
        promo_name=promo.promo_name,
    )


async def create_order_from_cart(
    customer_id: str,
    items: list[dict],
    shipping_address: dict,
    coupon_id: str | None = None,
    skip_coupon: bool = False,
    business_id: str | None = None,
) -> dict:
    """购物车主结算薄前奏(2026-10-17 结算核归一):dict 行请求转强类型,
    译信封;落库编排见 _commit_order(本臂历史缺货/查无文案即核缺省)。"""
    if not items:
        return {"success": False, "message": "结算购物车条目不能为空"}
    try:
        out = await _commit_order(
            customer_id=customer_id,
            items=[
                _OrderItemRequest(sku_code=item["skuCode"], quantity=item.get("quantity") or 1)
                for item in items
            ],
            shipping_address=shipping_address,
            coupon_id=coupon_id,
            skip_coupon=skip_coupon,
            business_id=business_id,
            source="购物车",
        )
    except _CartError as err:
        return {"success": False, "message": err.message}
    return {
        "success": True,
        "orderId": out.order_id,
        "totalAmount": round(out.total_amount, 2),
        "discount": round(out.discount, 2),
        "promoName": out.promo_name,
        "payableAmount": round(out.total_amount - out.discount, 2),
    }


async def preview_cart_pricing(customer_id: str, items: list[dict], business_id: str | None = None) -> dict:
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
            # 逐条目单查的 N+1 根治(2026-09-26 夜审 ③#9):一次取回全部涉及 SKU
            sku_rows = (
                await conn.execute(
                    text(
                        "SELECT s.price, s.sku_code, p.spu_code FROM merchant_skus s "
                        "JOIN merchant_spus p ON s.spu_id = p.id WHERE s.sku_code = ANY(:codes)"
                    ),
                    {"codes": list({item["skuCode"] for item in items})},
                )
            ).mappings().all()
            price_by_code = {r["sku_code"]: r for r in sku_rows}
            for item in items:
                sku = price_by_code.get(item["skuCode"])
                if sku is None:
                    return {"success": False, "message": f"商品规格 [{item['skuCode']}] 不存在"}
                quantity = item.get("quantity") or 1
                total_amount += float(sku["price"]) * quantity
                total_quantity += quantity
                scope.add(str(sku["spu_code"]))

            from engine_py.analytics.promotion_engine import best_for_amount, list_usable_user_coupons

            amount = round(total_amount, 2)
            auto = await best_for_amount(conn, amount, scope, exclude_coupon=True, business_id=business_id)
            # 叠加口径(与 _resolve_promotion 一致):活动先减,券按余额抵扣封顶
            activity_discount = auto["discount"] if auto else 0.0
            coupons = await list_usable_user_coupons(
                conn, customer_id, round(amount - activity_discount, 2), business_id
            )
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
