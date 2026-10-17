"""结算核差分回归(2026-10-17 结算核归一,CONTEXT.md「结算核 commit_order」):
/api/store/orders 的两条臂(直购 = 无 items / 购物车 = items 列表)在归一前是
两份手抄落库编排,已两度各自漂移 —— 直购臂漏写 cost_at_purchase(旧 :530 注释
在案),购物车臂同洞至今(:1358 读无人写入的 costPrice 键,快照恒 0,ADR-0003
毛利口径失效)。本册钉两件事:

1. 购物车臂 cost 快照落库非零(本 bug 的直接回归);
2. 双臂同参同果差分:同客户/同 SKU/同数量 → 订单行、行项目(含快照)、
   库存扣减逐键相等;查无/缺货两臂各自历史文案,零落账零扣库存。

纪律(3c4c843 教训,同 test_store_checkout_coupon):独立用户 + CT-SETL 前缀
唯一编码,收尾自清,不动他套件的数据。优惠不种:残留促销对两臂同参同apply,
差分断言天然免疫;消费方断言只看相等性不看绝对值。
"""

from __future__ import annotations

import uuid as _uuid

from sqlalchemy import text

from gateway_py.merchant_db import ensure_merchant_tables, merchant_engine
from tests.merchant_seed_helpers import seed_merchant_catalog

_UID = "CUST-CT-SETL-A"
_SPUCODE = "CT-SETL-SPU-1"
_SKUCODE = "CT-SETL-SKU-1"
_PRICE = 300.0
_COST = 100.0


async def _seed_catalog(*, stock: int = 10, sku_code: str = _SKUCODE) -> None:
    """种一个含 cost_price 的 SKU(cost 快照断言的数据基础;旧两臂均不断言)。"""
    await ensure_merchant_tables()
    async with merchant_engine().begin() as conn:
        await seed_merchant_catalog(
            conn,
            spu_code=f"{_SPUCODE}-{sku_code.rsplit('-', 1)[-1]}",
            sku_code=sku_code,
            price=_PRICE,
            stock=stock,
            cost_price=_COST,
            title="结算核差分测试商品",
            spec='{"颜色":"黑"}',
        )


async def _cleanup(*, sku_codes: list[str] | None = None) -> None:
    codes = sku_codes or [_SKUCODE]
    spu_codes = [f"{_SPUCODE}-{c.rsplit('-', 1)[-1]}" for c in codes]
    async with merchant_engine().begin() as conn:
        await conn.execute(
            text(
                "DELETE FROM merchant_order_items WHERE order_id IN "
                "(SELECT order_id FROM merchant_orders WHERE customer_id = :u)"
            ).bindparams(u=_UID)
        )
        await conn.execute(
            text(
                "DELETE FROM promotion_redemptions WHERE order_id IN "
                "(SELECT order_id FROM merchant_orders WHERE customer_id = :u)"
            ).bindparams(u=_UID)
        )
        await conn.execute(text("DELETE FROM merchant_orders WHERE customer_id = :u").bindparams(u=_UID))
        for c in codes:
            await conn.execute(text("DELETE FROM merchant_skus WHERE sku_code = :c").bindparams(c=c))
        for sc in spu_codes:
            await conn.execute(text("DELETE FROM merchant_spus WHERE spu_code = :c").bindparams(c=sc))


async def _order_line_rows(order_id: str) -> list[dict]:
    async with merchant_engine().connect() as conn:
        rows = (
            await conn.execute(
                text(
                    "SELECT sku_code, quantity, price, cost_at_purchase FROM merchant_order_items "
                    "WHERE order_id = :o ORDER BY sku_code, quantity"
                ).bindparams(o=order_id)
            )
        ).mappings().all()
        order = (
            await conn.execute(
                text(
                    "SELECT total_amount, discount_amount, business_id FROM merchant_orders "
                    "WHERE order_id = :o"
                ).bindparams(o=order_id)
            )
        ).mappings().first()
    return {
        "items": [
            {
                "sku_code": r["sku_code"],
                "quantity": r["quantity"],
                "price": float(r["price"]),
                "cost_at_purchase": float(r["cost_at_purchase"]),
            }
            for r in rows
        ],
        "total": float(order["total_amount"]) if order else None,
        "discount": float(order["discount_amount"]) if order else None,
        "business_id": order["business_id"] if order else None,
    }


async def _stock_of(sku_code: str = _SKUCODE) -> int | None:
    async with merchant_engine().connect() as conn:
        return (
            await conn.execute(
                text("SELECT stock FROM merchant_skus WHERE sku_code = :c").bindparams(c=sku_code)
            )
        ).scalar()


async def test_cart_cost_snapshot_lands_nonzero(client, contract_fixtures):
    """主结算路快照回归(本批修的在册真 bug):cost_at_purchase 必须等于
    SKU cost_price,严禁回落 0(旧行为:items 组装丢键 → :1358 恒 0)。"""
    await _seed_catalog()
    try:
        res = await client.post(
            "/api/store/orders",
            json={
                "customerId": _UID,
                "items": [{"skuCode": _SKUCODE, "quantity": 1}],
                "shippingAddress": {"recipientName": "差分", "phone": "13800000000", "fullAddress": "测试路1号"},
            },
        )
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["success"] is True, body
        rows = await _order_line_rows(body["orderId"])
        assert rows["items"][0]["cost_at_purchase"] == _COST, (
            f"购物车臂快照必须落 cost_price: {rows['items']}"
        )
    finally:
        await _cleanup()


async def test_parity_direct_vs_cart_same_input(client, contract_fixtures):
    """双臂同参同果(结算核归一的核心契约):同客户/同 SKU/同数量,订单行、
    行项目逐键相等(含 cost 快照),库存扣减相等;信封字段各自保留
    (直购 originalAmount / 购物车 totalAmount)。"""
    await _seed_catalog(stock=10)
    try:
        direct = await client.post(
            "/api/store/orders",
            json={"customerId": _UID, "skuCode": _SKUCODE, "quantity": 2, "businessId": "aurora"},
        )
        assert direct.status_code == 200, direct.text
        direct_body = direct.json()
        assert direct_body["success"] is True, direct_body

        cart = await client.post(
            "/api/store/orders",
            json={
                "customerId": _UID,
                "items": [{"skuCode": _SKUCODE, "quantity": 2}],
                "shippingAddress": {"recipientName": "差分", "phone": "13800000000", "fullAddress": "测试路1号"},
                "businessId": "aurora",
            },
        )
        assert cart.status_code == 200, cart.text
        cart_body = cart.json()
        assert cart_body["success"] is True, cart_body

        # 信封:金额相等,字段名两臂各自保留
        assert direct_body["originalAmount"] == cart_body["totalAmount"] == 600.0
        assert direct_body["payableAmount"] == cart_body["payableAmount"]
        assert direct_body["discount"] == cart_body["discount"]
        assert "totalAmount" not in direct_body and "originalAmount" not in cart_body

        direct_rows = await _order_line_rows(direct_body["orderId"])
        cart_rows = await _order_line_rows(cart_body["orderId"])
        assert direct_rows["items"] == cart_rows["items"], "双臂行项目必须逐键相等(含快照)"
        assert direct_rows["total"] == cart_rows["total"]
        assert direct_rows["discount"] == cart_rows["discount"]
        assert direct_rows["business_id"] == cart_rows["business_id"] == "aurora"
        # 快照非零(ADR-0003:两臂此前各漏过一次,此断言 today 起两臂都钉死)
        assert cart_rows["items"][0]["cost_at_purchase"] == _COST
        assert await _stock_of() == 6, "两臂各扣 2,库存 10 → 6"
    finally:
        await _cleanup()


async def test_stock_shortage_parity_and_rollback(client, contract_fixtures):
    """缺货差分:两臂各自历史文案,零落账零扣库存(整体回滚)。"""
    await _seed_catalog(stock=1)
    try:
        direct = await client.post(
            "/api/store/orders",
            json={"customerId": _UID, "skuCode": _SKUCODE, "quantity": 2},
        )
        assert direct.status_code == 200, direct.text
        direct_body = direct.json()
        assert direct_body["success"] is False
        assert direct_body["message"].startswith("库存不足："), direct_body

        cart = await client.post(
            "/api/store/orders",
            json={
                "customerId": _UID,
                "items": [{"skuCode": _SKUCODE, "quantity": 2}],
                "shippingAddress": {"recipientName": "差分", "phone": "13800000000", "fullAddress": "测试路1号"},
            },
        )
        assert cart.status_code == 200, cart.text
        cart_body = cart.json()
        assert cart_body["success"] is False
        assert "库存不足，当前仅剩 1 件" in cart_body["message"], cart_body

        async with merchant_engine().connect() as conn:
            orders = (
                await conn.execute(
                    text("SELECT count(*) FROM merchant_orders WHERE customer_id = :u").bindparams(u=_UID)
                )
            ).scalar()
        assert orders == 0, "拒单后不得残留订单(事务须整体回滚)"
        assert await _stock_of() == 1, "拒单后库存不得被扣"
    finally:
        await _cleanup()


async def test_sku_missing_parity(client, contract_fixtures):
    """查无差分:两臂各自历史文案(SKU 规格 … / 商品规格 …),零落账。"""
    await _seed_catalog()
    ghost = f"CT-SETL-GHOST-{_uuid.uuid4().hex[:8]}"
    try:
        direct = await client.post(
            "/api/store/orders",
            json={"customerId": _UID, "skuCode": ghost, "quantity": 1},
        )
        assert direct.status_code == 200, direct.text
        assert direct.json() == {
            "success": False,
            "message": f"SKU 规格 [{ghost}] 不存在或已下架",
        }

        cart = await client.post(
            "/api/store/orders",
            json={
                "customerId": _UID,
                "items": [{"skuCode": ghost, "quantity": 1}],
                "shippingAddress": {"fullAddress": "测试路1号"},
            },
        )
        assert cart.status_code == 200, cart.text
        assert cart.json() == {
            "success": False,
            "message": f"商品规格 [{ghost}] 不存在",
        }
    finally:
        await _cleanup()


async def test_same_code_entries_aggregate_demand(client, contract_fixtures):
    """同码多条目:需求合计一把条件扣减(语义与原逐条目累计等价),
    行项目仍逐条目落(两行 1+2),库存一次扣 3。"""
    sku2 = "CT-SETL-SKU-AGG"
    await _seed_catalog(stock=3, sku_code=sku2)
    try:
        res = await client.post(
            "/api/store/orders",
            json={
                "customerId": _UID,
                "items": [
                    {"skuCode": sku2, "quantity": 1},
                    {"skuCode": sku2, "quantity": 2},
                ],
                "shippingAddress": {"fullAddress": "测试路1号"},
            },
        )
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["success"] is True, body
        rows = await _order_line_rows(body["orderId"])
        assert [r["quantity"] for r in rows["items"]] == [1, 2], "行项目逐条目落,不合并"
        assert all(r["cost_at_purchase"] == _COST for r in rows["items"])
        # 原价绝对、实付相对:共享容器可能有他册残留促销(实弹:store_promotions
        # 残留活动把 900 打成 820),断言只钉「原价−信封优惠=DB 实付=信封实付」
        assert round(sum(r["price"] * r["quantity"] for r in rows["items"]), 2) == _PRICE * 3
        assert body["discount"] == round(_PRICE * 3 - body["payableAmount"], 2)
        assert rows["total"] == body["payableAmount"]
        assert await _stock_of(sku2) == 0, "同码需求合计一把扣(3 → 0)"
    finally:
        await _cleanup(sku_codes=[sku2])
