"""复合「加购+下单」范围结算回归(2026-09-15 用户实报「说的第一个商品,为什么这么多」)。

事故链:用户「帮我把热销第一个的商品加入购物车，并下单使用地址列表第一个地址」
——「并」命中多意图候选,triage 让位 planner 深路径;planner 编排 导购→加购→
checkoutCart 三步,executor 快路径把 checkoutCart 直配工具时 args 只有地址,
checkout_user_cart 按**整车语义**把历史在车的 4 件一起结进订单(¥4455 = 新加
冲锋衣L 1299 + 老冲锋衣M 1299 + 渔夫帽 129 + 老爹鞋 899 + 背包 829)。用户只
要刚加的那一件。

钉死契约:
- 复合句(同句含加购动作 × 下单动作)的结算范围 = 本轮加购的行;范围结算后
  未指配的在车遗留品必须原样保留(严禁整车清空);
- 本轮加购未完成(addedThisTurn 空)× 复合句 → 诚实拒结,绝不拿遗留品开单
  (S6 跨品类错单守卫同哲学);
- 裸「下单」(无加购动作)保持整车结算旧契约不变。
"""

from __future__ import annotations

import asyncio

from sqlalchemy import text

from engine_py.graph.nodes.executor_fast_path import try_match_executor_fast_path

USER_INPUT = "帮我把热销第一个的商品加入购物车，并下单使用地址列表第一个地址"
_ADDR = {"recipientName": "张伟", "phone": "13800138000", "fullAddress": "北京市朝阳区建国门外大街1号国贸大厦A座 3801室"}


def test_composite_add_checkout_scopes_order_to_added_item(pg_factory):
    """契约 1:复合句结算只结本轮加购行,遗留品留在购物车(现状红:整车结算+清车)。"""
    from test_phase2_checkout_bridge import (
        UID,
        _read_cart,
        _seed_cart,
        _setup,
        _teardown,
    )

    async def scenario():
        engine, me, orig, embeds = await _setup(pg_factory)
        try:
            # 本轮加购:冲锋衣L;历史在车遗留:背包 x1 + 软壳冲锋衣 x2
            _seed_cart([
                {"skuId": "SPU-P2-CJ-SKU-0", "title": "极光 三合一冲锋衣(曜石黑 L)", "price": 1299.0, "quantity": 1},
                {"skuId": "SPU-P2-BAG-SKU-0", "title": "极光 高山徒步轻量化背包 38L", "price": 829.0, "quantity": 1},
                {"skuId": "SPU-P2-CJ2-SKU-0", "title": "极光 轻量软壳冲锋衣 M号", "price": 799.0, "quantity": 2},
            ])
            result = await MallDomainService.checkout_user_cart(
                {"userId": UID, "onlySkuIds": ["SPU-P2-CJ-SKU-0"], "shippingAddress": dict(_ADDR)}
            )
            async with me.connect() as conn:
                items = (
                    await conn.execute(
                        text(
                            "SELECT sku_code, quantity FROM merchant_order_items "
                            "WHERE order_id = :o ORDER BY sku_code"
                        ),
                        {"o": result.get("orderId") or ""},
                    )
                ).mappings().all()
                order = (
                    await conn.execute(
                        text("SELECT total_amount FROM merchant_orders WHERE order_id = :o"),
                        {"o": result.get("orderId") or ""},
                    )
                ).mappings().first()
            return result, items, order, _read_cart()
        finally:
            await _teardown(engine, me, orig, embeds)

    from engine_py.tools_registry.mall_domain import MallDomainService

    result, items, order, cart_after = asyncio.run(scenario())
    assert result.get("success") is True, result
    assert [r["sku_code"] for r in items] == ["SPU-P2-CJ-SKU-0"], (
        f"复合加购+下单必须只结本轮加购的那一件,实际订单明细: {[r['sku_code'] for r in items]}"
    )
    assert float(order["total_amount"]) == 1299.0, f"订单金额应只含新加冲锋衣L,实际: {order['total_amount']}"
    remaining = {i["skuId"] for i in cart_after}
    assert remaining == {"SPU-P2-BAG-SKU-0", "SPU-P2-CJ2-SKU-0"}, (
        f"未指配的在车遗留品必须原样保留,实际购物车: {cart_after!r}"
    )


def test_composite_scope_empty_refuses_and_keeps_cart(pg_factory):
    """契约 2:本轮加购未完成(addedThisTurn=[])× 复合句 → 诚实拒结,
    绝不拿购物车遗留品开单(S6 同哲学)。现状红:参数被无视 → 整车开单。"""
    from test_phase2_checkout_bridge import (
        UID,
        _read_cart,
        _seed_cart,
        _setup,
        _teardown,
    )

    from engine_py.tools_registry.mall_domain import MallDomainService

    async def scenario():
        engine, me, orig, embeds = await _setup(pg_factory)
        try:
            _seed_cart([
                {"skuId": "SPU-P2-BAG-SKU-0", "title": "背包", "price": 829.0, "quantity": 1},
            ])
            result = await MallDomainService.checkout_user_cart(
                {"userId": UID, "onlySkuIds": [], "shippingAddress": dict(_ADDR)}
            )
            async with me.connect() as conn:
                n_orders = (
                    await conn.execute(
                        text("SELECT COUNT(*) FROM merchant_orders WHERE order_id <> :h"),
                        {"h": "AURORA-ORD-2026-9001"},
                    )
                ).scalar()
            return result, n_orders, _read_cart()
        finally:
            await _teardown(engine, me, orig, embeds)

    result, n_orders, cart_after = asyncio.run(scenario())
    assert result.get("success") is False, f"加购未完成必须拒结,实际: {result}"
    assert n_orders == 0, "拒结不得落任何订单"
    assert len(cart_after) == 1, "拒结不得动购物车"


def test_fast_path_scopes_composite_and_preserves_bare_checkout():
    """契约 3:executor 快路径对复合句注入 onlySkuIds(本轮加购行);
    裸下单(无加购动作)保持整车语义不注入。"""
    allowed = ["checkoutCart"]
    desc = "Call checkoutCart to place the order, shipping to 北京市朝阳区建国门外大街1号"

    scoped = try_match_executor_fast_path(
        desc, USER_INPUT, allowed, [], cart_last_added=["SPU-P2-CJ-SKU-0"]
    )
    assert scoped is not None and scoped["toolName"] == "checkoutCart"
    assert scoped["args"].get("onlySkuIds") == ["SPU-P2-CJ-SKU-0"], (
        f"复合加购+下单的 checkoutCart 步骤必须携带本轮加购范围,实际 args: {scoped.get('args')}"
    )

    # 加购未完成:范围显式为空 → 仍须携带(服务层据此诚实拒结,不放行整车)
    empty_scoped = try_match_executor_fast_path(desc, USER_INPUT, allowed, [], cart_last_added=[])
    assert empty_scoped is not None and empty_scoped["args"].get("onlySkuIds") == []

    # 裸下单:整车契约不变(步骤描述含 checkoutCart 才进快路径分支)
    bare = try_match_executor_fast_path(
        "Call checkoutCart to place the order for the customer",
        "直接下单",
        allowed,
        [],
        cart_last_added=["SPU-P2-CJ-SKU-0"],
    )
    assert bare is not None and bare["toolName"] == "checkoutCart"
    assert "onlySkuIds" not in bare["args"], f"裸下单不得被范围化,实际 args: {bare['args']}"


def test_cart_skill_marks_added_this_turn():
    """契约 4(链路中段):技能加购成功/已在车拦截都要写 cartContext.addedThisTurn,
    executor 上行后快路径才有范围可注入。"""
    from engine_py.skills.cart_manage_skill import CartManageSkill
    from engine_py.tools_registry.mall_domain import MallDomainService

    async def scenario():
        MallDomainService._cart_storage.clear()
        try:
            skill = CartManageSkill()
            base_ctx = {
                "userId": "CUST-MARK-1",
                "threadId": "thread_mark_1",
                "input": "把第2件加入购物车",
                "slots": {},
                "extra": {
                    "guideContext": {
                        "candidateProducts": [
                            {"id": "SPU-A", "name": "冲锋衣 M", "price": 1299.0},
                            {"id": "SPU-B", "name": "背包 38L", "price": 829.0},
                        ]
                    },
                    "cartContext": {},
                },
            }
            added = await skill.execute({**base_ctx, "input": "把第2件加入购物车"})
            dup = await skill.execute({**base_ctx, "input": "把第2件加入购物车"})
            return added, dup
        finally:
            MallDomainService._cart_storage.clear()

    added, dup = asyncio.run(scenario())
    assert added["extra"]["cartContext"].get("addedThisTurn") == ["SPU-B"], (
        f"加购成功必须标记本轮加购行,实际: {added['extra']['cartContext']!r}"
    )
    assert dup["extra"]["cartContext"].get("addedThisTurn") == ["SPU-B"], (
        f"已在车拦截必须标记指名行(复合句结算范围),实际: {dup['extra']['cartContext']!r}"
    )
