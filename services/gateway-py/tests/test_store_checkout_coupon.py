"""结算选券回归(2026-09-22 结算页重构):/api/store/orders 的 couponId 三语义
(缺省自动择优单选 / "none" 明确不用券 / 指定 id 自选券与活动叠加 —— 活动先减、
券按余额抵扣封顶,实付永不为负)+ 只读试算端点 /api/store/checkout/preview。

纪律(3c4c843 教训):促销三表跨套件泄漏曾把无关订单打成优惠价 —— 本文件
全部用独立用户 + CT-SELC 前缀唯一编码,收尾自清,不动他套件的数据。
"""

from __future__ import annotations

import re
import uuid as _uuid

from sqlalchemy import text

from gateway_py.merchant_db import ensure_merchant_tables, merchant_engine

_UID = "CUST-CT-SELC-A"
_SPUCODE = "CT-SELC-SPU-1"
_SKUCODE = "CT-SELC-SKU-1"
_PRICE = 300.0
_PROMO_TAG = "CT-SELC-PROMO-TAG"


async def _seed_catalog() -> None:
    await ensure_merchant_tables()
    async with merchant_engine().begin() as conn:
        existing = (
            await conn.execute(text("SELECT 1 FROM merchant_skus WHERE sku_code = :c"), {"c": _SKUCODE})
        ).first()
        if existing is None:
            await conn.execute(
                text(
                    "INSERT INTO merchant_spus (spu_code, title, main_image) "
                    "VALUES (:sc, '选券回归测试商品', 'x.png')"
                ).bindparams(sc=_SPUCODE)
            )
            await conn.execute(
                text(
                    "INSERT INTO merchant_skus (spu_id, sku_code, sku_title, spec_attributes, price, stock) "
                    "SELECT p.id, :kc, '默认规格', CAST(:spec AS jsonb), :price, 99 "
                    "FROM merchant_spus p WHERE p.spu_code = :sc"
                ).bindparams(kc=_SKUCODE, spec='{"颜色":"黑"}', price=_PRICE, sc=_SPUCODE)
            )


async def _seed_coupon(user_id: str, value: float) -> str:
    """种一张已领取的券,返回 user_coupons.id(核销断言要用行 id)。"""
    promo_id = str(_uuid.uuid4())
    async with merchant_engine().begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO promotions (id, name, promo_type, status, discount_value, scope_type) "
                "VALUES (CAST(:i AS uuid), :n, 'coupon', 'active', :v, 'all')"
            ).bindparams(i=promo_id, n=f"{_PROMO_TAG}券{value}", v=value)
        )
        await conn.execute(
            text(
                "INSERT INTO user_coupons (promotion_id, user_id) VALUES (CAST(:i AS uuid), :u)"
            ).bindparams(i=promo_id, u=user_id)
        )
        row = (
            await conn.execute(
                text("SELECT id FROM user_coupons WHERE user_id = :u AND promotion_id = CAST(:i AS uuid)").bindparams(
                    u=user_id, i=promo_id
                )
            )
        ).mappings().first()
    assert row is not None
    return str(row["id"])


async def _seed_activity(threshold: float, value: float) -> str:
    promo_id = str(_uuid.uuid4())
    async with merchant_engine().begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO promotions (id, name, promo_type, status, discount_value, threshold_amount, scope_type) "
                "VALUES (CAST(:i AS uuid), :n, 'full_reduction', 'active', :v, :t, 'all')"
            ).bindparams(i=promo_id, n=f"{_PROMO_TAG}满{threshold}减{value}", v=value, t=threshold)
        )
    return promo_id


async def _cleanup() -> None:
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
        # FK 纪律:先删引用行(含他人名下种子券),再删被引用的活动
        await conn.execute(
            text(
                "DELETE FROM user_coupons WHERE user_id = :u OR promotion_id IN "
                "(SELECT id FROM promotions WHERE name LIKE :p)"
            ).bindparams(u=_UID, p=f"{_PROMO_TAG}%")
        )
        await conn.execute(text("DELETE FROM promotions WHERE name LIKE :p").bindparams(p=f"{_PROMO_TAG}%"))
        await conn.execute(text("DELETE FROM merchant_skus WHERE sku_code = :c").bindparams(c=_SKUCODE))
        await conn.execute(text("DELETE FROM merchant_spus WHERE spu_code = :c").bindparams(c=_SPUCODE))


async def _order_rows(order_id: str) -> dict:
    async with merchant_engine().connect() as conn:
        order = (
            await conn.execute(
                text(
                    "SELECT total_amount, discount_amount FROM merchant_orders WHERE order_id = :o"
                ).bindparams(o=order_id)
            )
        ).mappings().first()
        redemptions = (
            await conn.execute(
                text("SELECT discount_amount FROM promotion_redemptions WHERE order_id = :o").bindparams(o=order_id)
            )
        ).scalars().all()
    return {
        "total": float(order["total_amount"]) if order else None,
        "discount": float(order["discount_amount"]) if order else 0.0,
        "redemptions": [float(r) for r in redemptions],
    }


async def _coupon_status(coupon_row_id: str) -> str | None:
    async with merchant_engine().connect() as conn:
        row = (
            await conn.execute(
                text("SELECT status FROM user_coupons WHERE id = CAST(:i AS uuid)").bindparams(i=coupon_row_id)
            )
        ).first()
    return row[0] if row else None


async def test_default_auto_applies_best_coupon(client, contract_fixtures):
    """缺省 couponId=历史自动择优语义不变(立即购买/旧调用兼容)。"""
    await _seed_catalog()
    coupon_id = await _seed_coupon(_UID, 50)
    try:
        res = await client.post(
            "/api/store/orders",
            json={"customerId": _UID, "items": [{"skuCode": _SKUCODE, "quantity": 1}]},
        )
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["success"] is True
        assert body["discount"] == 50.0
        assert body["payableAmount"] == 250.0
        rows = await _order_rows(body["orderId"])
        assert rows["total"] == 250.0 and rows["discount"] == 50.0
        assert await _coupon_status(coupon_id) == "used"
        # 订单接口必须带优惠字段与带时区的 createdAt(实弹:naive UTC 曾被前端
        # 按本地解析,下单时间显示早 8 小时;优惠未展示只显实付)
        listed = (await client.get("/api/store/orders", params={"customerId": _UID})).json()["orders"]
        mine = next(o for o in listed if o["orderId"] == body["orderId"])
        assert float(mine["discountAmount"]) == 50.0
        assert float(mine["originalAmount"]) == 300.0
        assert float(mine["totalAmount"]) == 250.0
        assert re.search(r"[+-]\d{2}:\d{2}$", mine["createdAt"]), f"createdAt 缺时区偏移: {mine['createdAt']}"
    finally:
        await _cleanup()


async def test_selected_coupon_stacks_with_activity(client, contract_fixtures):
    """叠加语义(2026-09-22 用户决议):指定券与活动同时生效 —— 活动先减,
    券按余额抵扣;核销流水分两笔落,未选的券不动。"""
    await _seed_catalog()
    big = await _seed_coupon(_UID, 50)
    small = await _seed_coupon(_UID, 10)
    await _seed_activity(200, 30)
    try:
        res = await client.post(
            "/api/store/orders",
            json={
                "customerId": _UID,
                "items": [{"skuCode": _SKUCODE, "quantity": 1}],
                "couponId": small,
            },
        )
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["success"] is True
        # 活动 30 先减,券 ¥10 按余额(270)抵 10,合计 40
        assert body["discount"] == 40.0
        assert body["payableAmount"] == 260.0
        assert "满200减30" in body["promoName"] and "券10" in body["promoName"]
        assert await _coupon_status(small) == "used"
        assert await _coupon_status(big) == "claimed"
        rows = await _order_rows(body["orderId"])
        # 活动/券各落一笔核销流水
        assert sorted(rows["redemptions"]) == [10.0, 30.0]
    finally:
        await _cleanup()


async def test_stacking_caps_at_zero_payable(client, contract_fixtures):
    """叠加封顶:活动+券可把实付减到 0,但绝不超扣为负。(目录价 300)"""
    await _seed_catalog()
    coupon_id = await _seed_coupon(_UID, 50)
    await _seed_activity(100, 250)  # 满100减250,对 300 减 250
    try:
        res = await client.post(
            "/api/store/orders",
            json={"customerId": _UID, "items": [{"skuCode": _SKUCODE, "quantity": 1}], "couponId": coupon_id},
        )
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["success"] is True
        # 250(活动) + min(50, 300-250=50)=50 → 合计 300,实付 0
        assert body["discount"] == 300.0
        assert body["payableAmount"] == 0.0
        rows = await _order_rows(body["orderId"])
        assert rows["total"] == 0.0
        assert sorted(rows["redemptions"]) == [50.0, 250.0]
    finally:
        await _cleanup()


async def test_selected_coupon_rejected_when_zero_remaining(client, contract_fixtures):
    """活动已覆盖全部应付金额时选券:如实拒单,券不被白烧(零抵扣核销禁止)。"""
    await _seed_catalog()
    coupon_id = await _seed_coupon(_UID, 50)
    await _seed_activity(100, 300)  # 对 300 全额覆盖,余额为 0
    try:
        res = await client.post(
            "/api/store/orders",
            json={"customerId": _UID, "items": [{"skuCode": _SKUCODE, "quantity": 1}], "couponId": coupon_id},
        )
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["success"] is False
        assert "不可叠加" in body["message"]
        assert await _coupon_status(coupon_id) == "claimed", "拒单后券必须保持可用,严禁零抵扣核销"
        async with merchant_engine().connect() as conn:
            orders = (
                await conn.execute(
                    text("SELECT 1 FROM merchant_orders WHERE customer_id = :u").bindparams(u=_UID)
                )
            ).first()
        assert orders is None
    finally:
        await _cleanup()


async def test_skip_coupon_keeps_coupon_and_uses_activity(client, contract_fixtures):
    """couponId="none"=明确不用券:券保持 claimed,活动照常自动生效。"""
    await _seed_catalog()
    coupon_id = await _seed_coupon(_UID, 50)
    await _seed_activity(200, 30)
    try:
        res = await client.post(
            "/api/store/orders",
            json={
                "customerId": _UID,
                "items": [{"skuCode": _SKUCODE, "quantity": 1}],
                "couponId": "none",
            },
        )
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["success"] is True
        assert body["discount"] == 30.0
        assert body["payableAmount"] == 270.0
        assert await _coupon_status(coupon_id) == "claimed"
    finally:
        await _cleanup()


async def test_foreign_or_used_coupon_rejected_no_order(client, contract_fixtures):
    """他人/已用券指定下单:如实拒单,零落账零扣库存(严禁静默全款)。"""
    await _seed_catalog()
    others = await _seed_coupon("CUST-CT-SELC-OTHER", 50)
    try:
        res = await client.post(
            "/api/store/orders",
            json={"customerId": _UID, "items": [{"skuCode": _SKUCODE, "quantity": 1}], "couponId": others},
        )
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["success"] is False
        assert "不可叠加" in body["message"]
        async with merchant_engine().connect() as conn:
            orders = (
                await conn.execute(
                    text("SELECT 1 FROM merchant_orders WHERE customer_id = :u").bindparams(u=_UID)
                )
            ).first()
            stock = (
                await conn.execute(
                    text("SELECT stock FROM merchant_skus WHERE sku_code = :c").bindparams(c=_SKUCODE)
                )
            ).scalar()
        assert orders is None, "拒单后不得残留订单(事务须整体回滚)"
        assert stock == 99, "拒单后库存不得被扣"
    finally:
        await _cleanup()


async def test_coupon_cannot_be_reused_across_orders(client, contract_fixtures):
    """防双花(2026-09-22):券一经核销,二次指定下单必须拒单,且不重复抵扣。"""
    await _seed_catalog()
    coupon_id = await _seed_coupon(_UID, 50)
    try:
        first = await client.post(
            "/api/store/orders",
            json={"customerId": _UID, "items": [{"skuCode": _SKUCODE, "quantity": 1}], "couponId": coupon_id},
        )
        assert first.status_code == 200 and first.json()["success"] is True

        second = await client.post(
            "/api/store/orders",
            json={"customerId": _UID, "items": [{"skuCode": _SKUCODE, "quantity": 1}], "couponId": coupon_id},
        )
        assert second.status_code == 200, second.text
        body = second.json()
        assert body["success"] is False, f"已核销券必须拒单: {body}"
        async with merchant_engine().connect() as conn:
            orders = (
                await conn.execute(
                    text("SELECT count(*) FROM merchant_orders WHERE customer_id = :u").bindparams(u=_UID)
                )
            ).scalar()
            stock = (
                await conn.execute(
                    text("SELECT stock FROM merchant_skus WHERE sku_code = :c").bindparams(c=_SKUCODE)
                )
            ).scalar()
        assert orders == 1, "拒单后不得产生第二笔订单"
        assert stock == 98, "第二单库存扣减必须随事务回滚"

        # 底层防线:mark_coupon_used 对已核销券返回 False(并发双花的最终闸)
        from engine_py.analytics import promotions as _promo_svc

        async with merchant_engine().begin() as conn:
            assert await _promo_svc.mark_coupon_used(conn, coupon_id, "ORD-X") is False
    finally:
        await _cleanup()


async def test_user_coupons_unique_constraint_blocks_double_claim(client, contract_fixtures):
    """同活动同人仅一行(uq_user_promo):应用层查重的并发窗口由约束兜底。"""
    await _seed_catalog()
    from sqlalchemy.exc import IntegrityError

    await ensure_merchant_tables()
    promo_id = await _seed_coupon(_UID, 50)  # 已占一行
    try:
        async with merchant_engine().begin() as conn:
            try:
                await conn.execute(
                    text(
                        "INSERT INTO user_coupons (promotion_id, user_id) "
                        "VALUES (CAST(:p AS uuid), :u)"
                    ).bindparams(p=promo_id, u=_UID)
                )
                raised = False
            except IntegrityError:
                raised = True
        assert raised, "同活动同人第二行必须被唯一约束拒绝"
    finally:
        await _cleanup()


async def test_checkout_preview_readonly(client, contract_fixtures):
    """试算端点:原价/活动/券包逐张可用性,且完全只读(零订单零核销)。"""
    await _seed_catalog()
    big = await _seed_coupon(_UID, 50)
    small = await _seed_coupon(_UID, 10)
    await _seed_activity(200, 30)
    try:
        res = await client.post(
            "/api/store/checkout/preview",
            json={
                "customerId": _UID,
                "items": [{"skuCode": _SKUCODE, "quantity": 2}],
            },
        )
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["success"] is True
        assert body["originalAmount"] == 600.0
        assert body["totalQuantity"] == 2
        assert body["activity"] == {"name": f"{_PROMO_TAG}满200减30", "discount": 30.0}
        coupons = {c["couponId"]: c for c in body["coupons"]}
        assert set(coupons) == {big, small}
        assert coupons[big]["discount"] == 50.0 and coupons[big]["usable"] is True
        assert body["bestCouponId"] == big
        # 只读:预览后无订单、券未核销
        async with merchant_engine().connect() as conn:
            orders = (
                await conn.execute(
                    text("SELECT 1 FROM merchant_orders WHERE customer_id = :u").bindparams(u=_UID)
                )
            ).first()
        assert orders is None
        assert await _coupon_status(big) == "claimed"
    finally:
        await _cleanup()
