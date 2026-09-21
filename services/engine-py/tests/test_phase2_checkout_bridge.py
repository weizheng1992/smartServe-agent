"""遗留二期红灯回路(2026-09-13,spec: .scratch/phase2-bridging-checkout/spec.md)。

三项:①真·聊天下单 checkout_user_cart(与商城页 create_order_from_cart 同一
真账本语义:FOR UPDATE 锁库存/扣减/PAID/cost_at_purchase 快照/清车,任一行
失败整单不落);②订单→购物车桥接 add_order_item_to_cart(顾客买过的商品按
当前在售 SKU 真实回车);③指标×导购复合句 planner 确定性快轨 + executor
queryProductRanking/checkoutCart 确定性映射(拒答偶发从根上消失)。

密封商户库 DDL 镜像生产列(merchant_db.py):sku_title/spec_attributes/
image_url/cost_price、order_items.cost_at_purchase —— 快照与规格展示都吃真列。
"""

from __future__ import annotations

import asyncio
import json
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from engine_py.skills.contract import SkillContext

UID = "CUST-8801"
TID = "phase2_thread"

_MERCHANT_DDL = [
    # 促销三表(优惠引擎面:2026-09-21 券账本回归测试所需;形状与 gateway merchant_db 对齐)
    """
    CREATE TABLE IF NOT EXISTS promotions (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      name TEXT NOT NULL,
      promo_type TEXT NOT NULL,
      threshold_amount NUMERIC(10,2),
      discount_value NUMERIC(10,2) NOT NULL,
      scope_type TEXT NOT NULL DEFAULT 'all',
      scope_value TEXT,
      status TEXT NOT NULL DEFAULT 'active',
      start_at TIMESTAMP NOT NULL DEFAULT NOW(),
      end_at TIMESTAMP,
      created_at TIMESTAMP NOT NULL DEFAULT NOW()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS promotion_redemptions (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      promotion_id UUID NOT NULL REFERENCES promotions(id),
      order_id TEXT NOT NULL,
      discount_amount NUMERIC(10,2) NOT NULL,
      created_at TIMESTAMP NOT NULL DEFAULT NOW()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS user_coupons (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      promotion_id UUID NOT NULL REFERENCES promotions(id),
      user_id TEXT NOT NULL,
      status TEXT NOT NULL DEFAULT 'claimed',
      used_order_id TEXT,
      used_at TIMESTAMP,
      claimed_at TIMESTAMP NOT NULL DEFAULT NOW(),
      CONSTRAINT uq_user_promo UNIQUE (promotion_id, user_id)
    )
    """,
    # 防御式建表:容器与相邻套件共享,严禁 DROP 改形状 —— CREATE IF NOT EXISTS
    # + ADD COLUMN IF NOT EXISTS 补齐本套所需列,表形状取并集兼容双方。
    """
    CREATE TABLE IF NOT EXISTS merchant_spus (
      id UUID PRIMARY KEY,
      spu_code TEXT NOT NULL UNIQUE,
      title TEXT NOT NULL,
      subtitle TEXT,
      description TEXT,
      category TEXT NOT NULL DEFAULT '户外机能',
      main_image TEXT,
      specs JSONB DEFAULT '{}'::jsonb,
      status TEXT NOT NULL DEFAULT 'ON_SALE',
      created_at TIMESTAMP NOT NULL DEFAULT NOW()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS merchant_skus (
      id UUID PRIMARY KEY,
      spu_id UUID NOT NULL REFERENCES merchant_spus(id) ON DELETE CASCADE,
      sku_code TEXT NOT NULL UNIQUE,
      sku_title TEXT,
      price NUMERIC(10,2) NOT NULL,
      stock INTEGER NOT NULL DEFAULT 0,
      spec_attributes JSONB DEFAULT '{}'::jsonb,
      image_url TEXT,
      cost_price NUMERIC(10,2) NOT NULL DEFAULT 0,
      created_at TIMESTAMP NOT NULL DEFAULT NOW()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS merchant_orders (
      order_id TEXT PRIMARY KEY,
      customer_id TEXT NOT NULL,
      status TEXT NOT NULL,
      total_amount NUMERIC(12,2) NOT NULL DEFAULT 0,
      currency TEXT DEFAULT 'CNY',
      shipping_address JSONB DEFAULT '{}'::jsonb,
      is_returnable BOOLEAN DEFAULT TRUE,
      is_address_modifiable BOOLEAN DEFAULT TRUE,
      created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
      updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    """
    ALTER TABLE merchant_orders ADD COLUMN IF NOT EXISTS discount_amount NUMERIC(12,2) NOT NULL DEFAULT 0
    """,
    """
    CREATE TABLE IF NOT EXISTS merchant_customers (
      customer_id TEXT PRIMARY KEY,
      name TEXT,
      addresses JSONB DEFAULT '[]'::jsonb
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS merchant_order_items (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      order_id TEXT NOT NULL,
      spu_id TEXT NOT NULL,
      sku_code TEXT NOT NULL,
      title TEXT,
      sku_title TEXT,
      quantity INTEGER NOT NULL DEFAULT 1,
      price NUMERIC(10,2) NOT NULL DEFAULT 0,
      image_url TEXT,
      spec_summary TEXT,
      cost_at_purchase NUMERIC(10,2) NOT NULL DEFAULT 0
    )
    """,
    "ALTER TABLE merchant_skus ADD COLUMN IF NOT EXISTS sku_title TEXT",
    "ALTER TABLE merchant_skus ADD COLUMN IF NOT EXISTS spec_attributes JSONB DEFAULT '{}'::jsonb",
    "ALTER TABLE merchant_skus ADD COLUMN IF NOT EXISTS image_url TEXT",
    "ALTER TABLE merchant_skus ADD COLUMN IF NOT EXISTS cost_price NUMERIC(10,2) NOT NULL DEFAULT 0",
    "ALTER TABLE merchant_order_items ADD COLUMN IF NOT EXISTS sku_title TEXT",
    "ALTER TABLE merchant_order_items ADD COLUMN IF NOT EXISTS spec_summary TEXT",
    "ALTER TABLE merchant_order_items ADD COLUMN IF NOT EXISTS image_url TEXT",
    "ALTER TABLE merchant_order_items ADD COLUMN IF NOT EXISTS cost_at_purchase NUMERIC(10,2) NOT NULL DEFAULT 0",
]

# (spu_code, title, category, status, [(sku_code, sku_title, price, stock, cost), ...])
_SPUS = [
    ("SPU-P2-CJ", "极光 三合一全天候户外硬壳冲锋衣", "户外机能", "ON_SALE", [
        ("SPU-P2-CJ-SKU-0", "L号 三合一", 1299.0, 5, 650.0),
        ("SPU-P2-CJ-SKU-1", "XL号 三合一", 1349.0, 2, 680.0),
    ]),
    ("SPU-P2-BAG", "极光 高山徒步轻量化背包 38L", "背包收纳", "ON_SALE", [
        ("SPU-P2-BAG-SKU-0", "38L 标准版", 829.0, 20, 400.0),
    ]),
    ("SPU-P2-OLD", "极光 旧款冲锋衣(已下架)", "户外机能", "OFF_SALE", [
        ("SPU-P2-OLD-SKU-0", "M号", 999.0, 5, 500.0),
    ]),
    ("SPU-P2-CJ2", "极光 轻量软壳冲锋衣", "户外机能", "ON_SALE", [
        ("SPU-P2-CJ2-SKU-0", "M号 软壳", 799.0, 8, 390.0),
    ]),
]

HISTORY_ORDER_ID = "AURORA-ORD-2026-9001"


def _spu_id(code: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, code))


async def _setup(pg_factory):
    from engine_py.tools_registry import order_domain
    from engine_py.tools_registry.mall_domain import MallDomainService

    engine = pg_factory.kw["bind"]
    url = engine.url.render_as_string(hide_password=False)
    merchant_engine = create_async_engine(url, poolclass=NullPool)

    async with merchant_engine.begin() as conn:
        for ddl in _MERCHANT_DDL:
            await conn.execute(text(ddl))
        await conn.execute(text("TRUNCATE merchant_order_items, merchant_orders"))
        await conn.execute(text("TRUNCATE merchant_skus, merchant_spus CASCADE"))
        # 促销三表一并清场:他文件(如 fallback_dispatcher 满400减50)种下的活动/券
        # 不得污染本套结算账(2026-09-21 实证 real_order 被 −50 打红)
        await conn.execute(text("TRUNCATE promotions, user_coupons, promotion_redemptions"))
        for spu_code, title, category, status, skus in _SPUS:
            await conn.execute(
                text(
                    "INSERT INTO merchant_spus (id, spu_code, title, subtitle, description, category, "
                    "main_image, specs, status) VALUES ("
                    "CAST(:id AS uuid), :code, :title, :sub, :desc, :cat, :img, CAST(:specs AS jsonb), :status)"
                ).bindparams(
                    id=_spu_id(spu_code), code=spu_code, title=title,
                    sub=f"{title} 卖点", desc=f"{title} 长文案", cat=category,
                    img=f"https://img.test/{spu_code}.png",
                    specs=json.dumps({"材质": "GORE-TEX"}, ensure_ascii=False), status=status,
                )
            )
            for sku_code, sku_title, price, stock, cost in skus:
                await conn.execute(
                    text(
                        "INSERT INTO merchant_skus (id, spu_id, sku_code, sku_title, price, stock, "
                        "spec_attributes, image_url, cost_price) VALUES ("
                        "CAST(:id AS uuid), CAST(:sid AS uuid), :code, :st, :price, :stock, CAST(:spec AS jsonb), :img, :cost)"
                    ).bindparams(
                        id=uuid.uuid5(uuid.NAMESPACE_URL, sku_code), sid=_spu_id(spu_code),
                        code=sku_code, st=sku_title, price=price, stock=stock,
                        spec=json.dumps({"尺码": sku_title}, ensure_ascii=False),
                        img=f"https://img.test/{sku_code}.png", cost=cost,
                    )
                )
        # 历史订单:买过 SPU-P2-CJ(冲锋衣)与 SPU-P2-OLD(旧款已下架)
        await conn.execute(
            text(
                "INSERT INTO merchant_orders (order_id, customer_id, status, total_amount, shipping_address) "
                "VALUES (:oid, :uid, 'PAID', 2298, CAST(:addr AS jsonb))"
            ).bindparams(
                oid=HISTORY_ORDER_ID, uid=UID,
                addr=json.dumps({"recipientName": "张伟", "phone": "13800138000", "fullAddress": "北京市朝阳区旧地址"}, ensure_ascii=False),
            )
        )
        for spu_code, sku_code, title, sku_title in (
            ("SPU-P2-CJ", "SPU-P2-CJ-SKU-0", "极光 三合一全天候户外硬壳冲锋衣", "L号 三合一"),
            ("SPU-P2-OLD", "SPU-P2-OLD-SKU-0", "极光 旧款冲锋衣(已下架)", "M号"),
        ):
            await conn.execute(
                text(
                    "INSERT INTO merchant_order_items (order_id, spu_id, sku_code, title, sku_title, "
                    "quantity, price, spec_summary, cost_at_purchase) VALUES "
                    "(:oid, :sid, :code, :t, :st, 1, 1299.0, '尺码:X', 650.0)"
                ).bindparams(oid=HISTORY_ORDER_ID, sid=_spu_id(spu_code), code=sku_code, t=title, st=sku_title)
            )

    original = order_domain._merchant_reader_engine
    original_writer = getattr(order_domain, "_merchant_writer_engine", None)
    order_domain._merchant_reader_engine = lambda: merchant_engine
    # 阶段①只读收紧后:结算写事务走 writer(与生产一致,测试同指容器)
    order_domain._merchant_writer_engine = lambda: merchant_engine

    async def _sealed_embed(*_args, **_kwargs):
        raise RuntimeError("embedding sealed in this suite")

    original_embeds = (
        MallDomainService.__dict__["_embed_query"],
        MallDomainService.__dict__["_embed_texts"],
    )
    MallDomainService._embed_query = staticmethod(_sealed_embed)
    MallDomainService._embed_texts = staticmethod(_sealed_embed)

    return engine, merchant_engine, (original, original_writer), original_embeds


async def _teardown(engine, merchant_engine, original, original_embeds):
    from engine_py.tools_registry import order_domain
    from engine_py.tools_registry.mall_domain import MallDomainService

    reader_original, writer_original = original
    order_domain._merchant_reader_engine = reader_original
    order_domain._merchant_writer_engine = writer_original
    MallDomainService._embed_query = original_embeds[0]
    MallDomainService._embed_texts = original_embeds[1]
    MallDomainService._cart_storage.clear()
    await merchant_engine.dispose()


def _seed_cart(items: list[dict]) -> None:
    from engine_py.tools_registry.mall_domain import MallDomainService

    MallDomainService._cart_storage[UID] = items


def _read_cart() -> list[dict]:
    from engine_py.tools_registry.mall_domain import MallDomainService

    return MallDomainService._cart_storage.get(UID) or []


# ── ①checkout_user_cart:真·聊天下单 ───────────────────────────────────────


def test_checkout_creates_real_order(pg_factory):
    """SPU 行(skuId=spu_code)+ SKU 行(skuId=sku_code)混合车:PAID 真单 +
    明细 cost_at_purchase 快照 + 库存扣减 + 清车,整单金额 = MIN 价 SKU 结算。"""
    from engine_py.tools_registry.mall_domain import MallDomainService

    async def scenario():
        engine, me, orig, embeds = await _setup(pg_factory)
        try:
            _seed_cart([
                {"skuId": "SPU-P2-CJ", "title": "极光 三合一全天候户外硬壳冲锋衣", "price": 1299.0, "quantity": 1},
                {"skuId": "SPU-P2-BAG-SKU-0", "title": "极光 高山徒步轻量化背包 38L", "price": 829.0, "quantity": 2},
            ])
            result = await MallDomainService.checkout_user_cart(
                {"userId": UID, "threadId": TID,
                 "shippingAddress": {"recipientName": "张伟", "phone": "13800138000", "fullAddress": "上海市浦东新区世纪大道100号"}}
            )
            async with me.connect() as conn:
                order = (await conn.execute(
                    text("SELECT status, total_amount, shipping_address FROM merchant_orders WHERE order_id=:o"),
                    {"o": result["orderId"]},
                )).mappings().first()
                items = (await conn.execute(
                    text("SELECT sku_code, quantity, price, cost_at_purchase FROM merchant_order_items ORDER BY sku_code")
                )).mappings().all()
                cj_stock = (await conn.execute(
                    text("SELECT stock FROM merchant_skus WHERE sku_code='SPU-P2-CJ-SKU-0'")
                )).scalar()
                bag_stock = (await conn.execute(
                    text("SELECT stock FROM merchant_skus WHERE sku_code='SPU-P2-BAG-SKU-0'")
                )).scalar()
            return result, order, items, cj_stock, bag_stock
        finally:
            await _teardown(engine, me, orig, embeds)

    result, order, items, cj_stock, bag_stock = asyncio.run(scenario())
    assert result.get("success") is True, result
    assert result.get("orderId", "").startswith("AURORA-ORD-2026-")
    assert order is not None and order["status"] == "PAID"
    # 冲锋衣双 SKU 取最低价 1299(L号);背包 SKU 直配 829×2
    assert float(order["total_amount"]) == 1299.0 + 829.0 * 2
    assert order["shipping_address"]["fullAddress"] == "上海市浦东新区世纪大道100号"
    by_sku = {r["sku_code"]: r for r in items}
    assert float(by_sku["SPU-P2-CJ-SKU-0"]["cost_at_purchase"]) == 650.0, "快照必须落 sku.cost_price"
    assert float(by_sku["SPU-P2-BAG-SKU-0"]["cost_at_purchase"]) == 400.0
    assert cj_stock == 4 and bag_stock == 18, "库存必须物理扣减"
    assert _read_cart() == [], "下单后购物车必须清空"


def test_checkout_coupon_discount_reaches_order_row(pg_factory):
    """用户券必须在订单账面落地:total_amount=实付(原价−优惠)、discount_amount=优惠额。

    2026-09-21 用户实报 bug(订单 AURORA-ORD-2026-1155 实证):引擎侧结算
    INSERT 只写原价、无 discount_amount —— promotion_redemptions 记了 ¥50、
    券被核销,订单账面却全款,商城订单页看不到任何优惠。
    """
    import uuid as _uuid

    from engine_py.tools_registry.mall_domain import MallDomainService

    async def scenario():
        engine, me, orig, embeds = await _setup(pg_factory)
        try:
            async with me.begin() as conn:
                pid = str(_uuid.uuid4())
                await conn.execute(text(
                    "INSERT INTO promotions (id, name, promo_type, status, discount_value, scope_type) "
                    "VALUES (CAST(:i AS uuid), '契约新客券', 'coupon', 'active', 50, 'all')"
                ).bindparams(i=pid))
                await conn.execute(text(
                    "INSERT INTO user_coupons (promotion_id, user_id) VALUES (CAST(:i AS uuid), :u)"
                ).bindparams(i=pid, u=UID))
            _seed_cart([
                {"skuId": "SPU-P2-BAG-SKU-0", "title": "极光 高山徒步轻量化背包 38L", "price": 829.0, "quantity": 1},
            ])
            result = await MallDomainService.checkout_user_cart(
                {"userId": UID, "threadId": TID,
                 "shippingAddress": {"recipientName": "张伟", "phone": "13800138000", "fullAddress": "上海市浦东新区世纪大道100号"}}
            )
            async with me.connect() as conn:
                order = (await conn.execute(
                    text("SELECT total_amount, discount_amount FROM merchant_orders WHERE order_id=:o"),
                    {"o": result["orderId"]},
                )).mappings().first()
                coupon = (await conn.execute(
                    text("SELECT status, used_order_id FROM user_coupons WHERE user_id=:u"),
                    {"u": UID},
                )).mappings().first()
            return result, order, coupon, pid
        finally:
            # 收尾自清:种下的活动/券不向他文件泄漏(共享 pg_factory 库跨文件存活)
            try:
                async with me.begin() as conn:
                    await conn.execute(text("DELETE FROM user_coupons WHERE user_id=:u").bindparams(u=UID))
                    await conn.execute(text(
                        "DELETE FROM promotion_redemptions WHERE promotion_id=CAST(:i AS uuid)"
                    ).bindparams(i=pid))
                    await conn.execute(text("DELETE FROM promotions WHERE id=CAST(:i AS uuid)").bindparams(i=pid))
            finally:
                await _teardown(engine, me, orig, embeds)

    result, order, coupon, _pid = asyncio.run(scenario())
    assert result.get("success") is True, result
    assert float(result["payableAmount"]) == 779.0, f"券后实付应为 779: {result}"
    assert order is not None, "订单必须存在"
    assert float(order["total_amount"]) == 779.0, (
        f"订单 total_amount 必须是实付 779(原价 829 − 券 50),实为 {order['total_amount']}"
    )
    assert float(order["discount_amount"]) == 50.0, (
        f"订单 discount_amount 必须落 ¥50 优惠,实为 {order['discount_amount']}"
    )
    assert coupon["status"] == "used" and coupon["used_order_id"] == result["orderId"]


def test_checkout_insufficient_stock_no_order(pg_factory):
    """任一行库存不足:整单不落(与商城页 all-or-nothing 一致),回复如实点名。"""
    from engine_py.tools_registry.mall_domain import MallDomainService

    async def scenario():
        engine, me, orig, embeds = await _setup(pg_factory)
        try:
            _seed_cart([
                {"skuId": "SPU-P2-CJ", "title": "冲锋衣", "price": 1299.0, "quantity": 999},
            ])
            result = await MallDomainService.checkout_user_cart(
                {"userId": UID, "shippingAddress": "上海市浦东新区世纪大道100号"}
            )
            cart_after = _read_cart()
            async with me.connect() as conn:
                n_orders = (await conn.execute(
                    text("SELECT COUNT(*) FROM merchant_orders WHERE order_id <> :h"), {"h": HISTORY_ORDER_ID}
                )).scalar()
                stock = (await conn.execute(text("SELECT stock FROM merchant_skus WHERE sku_code='SPU-P2-CJ-SKU-0'"))).scalar()
            return result, n_orders, stock, cart_after
        finally:
            await _teardown(engine, me, orig, embeds)

    result, n_orders, stock, cart_after = asyncio.run(scenario())
    assert result.get("success") is False
    assert "库存" in (result.get("message") or "")
    assert n_orders == 0, "失败行必须整单不落"
    assert stock == 5, "不得扣减库存"
    assert len(cart_after) == 1, "购物车不清空"


def test_checkout_empty_cart_and_no_address_honest(pg_factory):
    from engine_py.tools_registry.mall_domain import MallDomainService

    async def scenario():
        engine, me, orig, embeds = await _setup(pg_factory)
        try:
            empty = await MallDomainService.checkout_user_cart({"userId": UID})
            _seed_cart([{"skuId": "SPU-P2-CJ", "title": "冲锋衣", "price": 1299.0, "quantity": 1}])
            # UID 无地址簿行 → needsAddress 诚实追问
            no_addr = await MallDomainService.checkout_user_cart({"userId": UID})
            return empty, no_addr
        finally:
            await _teardown(engine, me, orig, embeds)

    empty, no_addr = asyncio.run(scenario())
    assert empty.get("success") is False and "空" in (empty.get("message") or "")
    assert no_addr.get("success") is False and no_addr.get("needsAddress") is True
    assert "地址" in (no_addr.get("message") or "")


def test_checkout_uses_default_address(pg_factory):
    """无显式地址:取地址簿 is_default 行(real-data-only:严禁假地址兜底)。"""
    from engine_py.tools_registry.mall_domain import MallDomainService

    async def scenario():
        engine, me, orig, embeds = await _setup(pg_factory)
        try:
            async with me.begin() as conn:
                await conn.execute(text(
                    "INSERT INTO merchant_customers (customer_id, addresses) VALUES "
                    "(:u, CAST(:a AS jsonb)) ON CONFLICT (customer_id) DO UPDATE SET addresses = EXCLUDED.addresses"
                ).bindparams(
                    u=UID,
                    a='[{"id":"addr_d","recipientName":"张伟","phone":"13800138000",'
                      '"fullAddress":"北京市海淀区中关村南大街1号","isDefault":true}]',
                ))
            _seed_cart([{"skuId": "SPU-P2-BAG-SKU-0", "title": "背包", "price": 829.0, "quantity": 1}])
            result = await MallDomainService.checkout_user_cart({"userId": UID})
            async with me.connect() as conn:
                addr = (await conn.execute(
                    text("SELECT shipping_address->>'fullAddress' FROM merchant_orders WHERE order_id=:o"),
                    {"o": result["orderId"]},
                )).scalar()
            return result, addr
        finally:
            await _teardown(engine, me, orig, embeds)

    result, addr = asyncio.run(scenario())
    assert result.get("success") is True
    assert addr == "北京市海淀区中关村南大街1号"


# ── ②订单→购物车桥接 ─────────────────────────────────────────────────────


def test_bridge_adds_purchased_item(pg_factory):
    from engine_py.tools_registry.mall_domain import MallDomainService

    async def scenario():
        engine, me, orig, embeds = await _setup(pg_factory)
        try:
            result = await MallDomainService.add_order_item_to_cart(
                {"userId": UID, "threadId": TID, "keyword": "三合一"}
            )
            cart = _read_cart()
            return result, cart
        finally:
            await _teardown(engine, me, orig, embeds)

    result, cart = asyncio.run(scenario())
    assert result.get("success") is True, result
    assert len(cart) == 1
    assert cart[0]["skuId"] == "SPU-P2-CJ-SKU-0", "必须解析为当前在售最低价 SKU"
    assert float(cart[0]["price"]) == 1299.0


def test_bridge_no_match_and_off_shelf_honest(pg_factory):
    from engine_py.tools_registry.mall_domain import MallDomainService

    async def scenario():
        engine, me, orig, embeds = await _setup(pg_factory)
        try:
            no_match = await MallDomainService.add_order_item_to_cart(
                {"userId": UID, "keyword": "滑雪板"}
            )
            # 买过但已下架:如实拒绝,不入车
            off = await MallDomainService.add_order_item_to_cart(
                {"userId": UID, "keyword": "旧款"}
            )
            return no_match, off
        finally:
            await _teardown(engine, me, orig, embeds)

    no_match, off = asyncio.run(scenario())
    assert no_match.get("success") is False and "没有找到" in (no_match.get("message") or "")
    assert off.get("success") is False and "下架" in (off.get("message") or "")
    assert _read_cart() == []


def test_bridge_multiple_matches_asks_to_pick(pg_factory):
    """「冲锋衣」命中硬壳+软壳两 SPU:列出让顾客挑,严禁静默选一个。"""
    from engine_py.tools_registry.mall_domain import MallDomainService

    async def scenario():
        engine, me, orig, embeds = await _setup(pg_factory)
        try:
            # 追加一笔软壳冲锋衣历史单
            async with me.begin() as conn:
                await conn.execute(
                    text(
                        "INSERT INTO merchant_orders (order_id, customer_id, status, total_amount) "
                        "VALUES ('AURORA-ORD-2026-9002', :uid, 'PAID', 799)"
                    ).bindparams(uid=UID)
                )
                await conn.execute(
                    text(
                        "INSERT INTO merchant_order_items (order_id, spu_id, sku_code, title, sku_title, "
                        "quantity, price) VALUES ('AURORA-ORD-2026-9002', :sid, 'SPU-P2-CJ2-SKU-0', "
                        "'极光 轻量软壳冲锋衣', 'M号 软壳', 1, 799)"
                    ).bindparams(sid=_spu_id("SPU-P2-CJ2"))
                )
            result = await MallDomainService.add_order_item_to_cart(
                {"userId": UID, "keyword": "冲锋衣"}
            )
            return result
        finally:
            await _teardown(engine, me, orig, embeds)

    result = asyncio.run(scenario())
    assert result.get("success") is False
    assert "三合一" in (result.get("message") or "") and "软壳" in (result.get("message") or "")


# ── ③planner 指标×导购确定性快轨 + executor 映射 ──────────────────────────


class _FakeShortMemory:
    def __init__(self, thread_id: str) -> None:
        pass

    async def get_messages(self) -> list:
        return []


class TestPlannerMetricGuideFastTrack:
    def _plan(self, monkeypatch: pytest.MonkeyPatch, intents: list[dict], input_text: str) -> dict:
        from engine_py.graph.nodes import planner as planner_mod

        monkeypatch.setattr(planner_mod, "ShortMemory", _FakeShortMemory)

        def _no_llm(*args, **kwargs):
            raise AssertionError("指标×导购复合句必须走确定性快轨,不得消耗 LLM")

        monkeypatch.setattr(planner_mod, "planner_llm", _no_llm)
        state = {"intents": intents, "input": input_text, "short_memory": []}
        return asyncio.run(planner_mod.planner_node(state))

    def test_metric_plus_guide_plans_ranking_and_guide(self, monkeypatch):
        """A7 实弹句:GMV+推荐 → 排行(gmv)+导购双子任务,零 LLM 拒答面。"""
        plan = self._plan(
            monkeypatch,
            [
                {"intent": "metric_query", "confidence": 0.9, "type": "primary"},
                {"intent": "shopping_guide", "confidence": 0.85, "type": "secondary"},
            ],
            "看看上个月GMV多少，顺便推荐下卖得好的商品",
        )
        descs = [st["description"] for st in plan["task_plan"]["subtasks"]]
        assert any("queryProductRanking" in d and "gmv" in d for d in descs)
        assert any("ShoppingGuideSkill" in d for d in descs)

    def test_ordinal_guide_cart_composite_two_stage(self, monkeypatch):
        """序数形 guide×cart 复合句(无全量词)确定性两段(code-review 2026-09-14
        补钉 dbde52f 口径:cd32139 全量词门槛已被泛化,序数形是三段编排的原始
        靶形)—— 导购写候选在前、CartSkill 序数入车在后,零 LLM。"""
        plan = self._plan(
            monkeypatch,
            [
                {"intent": "shopping_guide", "confidence": 0.9, "type": "primary"},
                {"intent": "cart_manage", "confidence": 0.85, "type": "secondary"},
            ],
            "推荐几款短袖，把第一个加入购物车",
        )
        descs = [st["description"] for st in plan["task_plan"]["subtasks"]]
        assert any("ShoppingGuideSkill" in d for d in descs), "导购半必须偿付(写候选)"
        assert any("CartSkill" in d for d in descs), "序数加购半必须偿付"
        guide_idx = next(i for i, d in enumerate(descs) if "ShoppingGuideSkill" in d)
        cart_idx = next(i for i, d in enumerate(descs) if "CartSkill" in d)
        assert guide_idx < cart_idx, "有状态 SOP 链:必须先写候选后序数入车"
        assert not any("queryProductRanking" in d for d in descs), "无指标词不得混入排行"

    def test_ordinal_three_stage_with_checkout_and_metric_not_hijacked(self, monkeypatch):
        """dbde52f 原始靶形:「查询卖的好的短袖,把第一个加入购物车,然后结算」——
        句含「卖的好」指标词,指标轨必须让位三段轨(cart 在场);三段齐全且零 LLM。"""
        plan = self._plan(
            monkeypatch,
            [
                {"intent": "shopping_guide", "confidence": 0.9, "type": "primary"},
                {"intent": "cart_manage", "confidence": 0.85, "type": "secondary"},
            ],
            "查询卖的好的短袖，把第一个加入购物车，然后结算",
        )
        descs = [st["description"] for st in plan["task_plan"]["subtasks"]]
        assert any("ShoppingGuideSkill" in d for d in descs)
        assert any("CartSkill" in d for d in descs)
        assert any("checkoutCart" in d for d in descs), "结算段必须确定性追加"
        assert not any("queryProductRanking" in d for d in descs), "指标轨不得劫持三段轨"

    def test_volume_wording_maps_to_volume_metric(self, monkeypatch):
        plan = self._plan(
            monkeypatch,
            [{"intent": "shopping_guide", "confidence": 0.9, "type": "primary"}],
            "推荐下卖得好的商品，再看看销量排行",
        )
        descs = [st["description"] for st in plan["task_plan"]["subtasks"]]
        assert any("queryProductRanking" in d and "volume" in d for d in descs)

    def test_refund_not_hijacked_by_metric_track(self, monkeypatch):
        """资金动作在场:指标×导购快轨不得劫持(让位深规划按资金纪律编排)。"""
        from engine_py.graph.nodes import planner as planner_mod

        monkeypatch.setattr(planner_mod, "ShortMemory", _FakeShortMemory)
        called = {"llm": False}

        class _FakeResponse:
            content = '{"goal": "deep", "subtasks": [{"id": "s1", "description": "deep plan step"}]}'

        class _FakeLLM:
            async def ainvoke(self, prompt):
                called["llm"] = True
                return _FakeResponse()

        monkeypatch.setattr(planner_mod, "planner_llm", lambda: _FakeLLM())
        state = {
            "intents": [
                {"intent": "refund", "confidence": 0.9, "type": "primary"},
                {"intent": "shopping_guide", "confidence": 0.85, "type": "secondary"},
            ],
            "input": "看看GMV，推荐跑步鞋，然后把订单AURORA-ORD-2026-9094退了",
            "short_memory": [],
        }
        result = asyncio.run(planner_mod.planner_node(state))
        descs = [st.get("description", "") for st in result["task_plan"]["subtasks"]]
        assert not called["llm"], "显式单号退款快轨应确定性处理"
        assert any("processRefund" in d for d in descs), "退款半必须保留"
        assert any("ShoppingGuideSkill" in d for d in descs), "导购半必须偿付,不得静默吞"
        assert any("queryProductRanking" in d for d in descs), "指标半必须偿付"


class TestExecutorFastPathMapping:
    def test_ranking_description_maps_metric(self):
        from engine_py.graph.nodes.executor_fast_path import try_match_executor_fast_path

        result = try_match_executor_fast_path(
            description="Call queryProductRanking with rankingMetric gmv to fetch real sales ranking",
            user_input="看看GMV",
            allowed_tools=["queryProductRanking"],
        )
        assert result == {"toolName": "queryProductRanking", "args": {"rankingMetric": "gmv"}}

    def test_ranking_deep_plan_description_falls_to_llm(self):
        """深规划自由描述(可能带 category/limit 参数)不得被快路径吞参。"""
        from engine_py.graph.nodes.executor_fast_path import try_match_executor_fast_path

        result = try_match_executor_fast_path(
            description="Call queryProductRanking to rank backpacks by sales",
            user_input="看看背包卖得怎么样",
            allowed_tools=["queryProductRanking"],
        )
        assert result is None, "无 pinned 句式必须落 LLM 兜底"

    def test_checkout_description_maps_tool(self):
        from engine_py.graph.nodes.executor_fast_path import try_match_executor_fast_path

        result = try_match_executor_fast_path(
            description="Call checkoutCart to place a real order from the customer's current cart items",
            user_input="把购物车里的东西结算下单",
            allowed_tools=["checkoutCart"],
        )
        assert result == {"toolName": "checkoutCart", "args": {}}

    def test_checkout_cart_tool_registered_and_whitelisted(self):
        from engine_py.graph.nodes.step_execution_engine import _base_executor_tools
        from engine_py.tools_registry import get_tool

        assert get_tool("checkoutCart") is not None
        assert "checkoutCart" in _base_executor_tools


# ── 评审修复批:超卖/否定词/复合吞/桥接口径 ─────────────────────────────


def test_checkout_concurrent_stock_loss_no_order(pg_factory):
    """并发失利:resolve 与扣减之间库存被抢走 → 条件 UPDATE rowcount=0,
    整单不落且不产生负库存。"""
    from engine_py.tools_registry.mall_domain import MallDomainService

    async def scenario():
        engine, me, orig, embeds = await _setup(pg_factory)
        try:
            _seed_cart([{"skuId": "SPU-P2-BAG-SKU-0", "title": "背包", "price": 829.0, "quantity": 1}])
            # 模拟并发:resolve 前库存 20,真结算时只剩 0(被并发单买空)
            async with me.begin() as conn:
                await conn.execute(text("UPDATE merchant_skus SET stock = 0 WHERE sku_code='SPU-P2-BAG-SKU-0'"))
            # 绕过 resolve 预检直接构造竞态:把库存恢复 1 条件 —— 用 monkey 场景:
            # resolve 需要 stock>0 才入选,故并发窗口用 patch 固定 resolve 结果

            real_resolve = MallDomainService._resolve_purchasable_sku

            async def _racy_resolve(conn, **kw):
                row = await real_resolve(conn, **kw)
                if row:
                    # resolve 返回后、UPDATE 前库存被并发清零
                    await conn.execute(
                        text("UPDATE merchant_skus SET stock = 0 WHERE sku_code = :c").bindparams(
                            c=row["sku_code"]
                        )
                    )
                return row

            monkey_target = MallDomainService._resolve_purchasable_sku
            MallDomainService._resolve_purchasable_sku = staticmethod(_racy_resolve)
            try:
                result = await MallDomainService.checkout_user_cart({"userId": UID, "shippingAddress": "上海市浦东新区世纪大道100号"})
            finally:
                MallDomainService._resolve_purchasable_sku = monkey_target
            async with me.connect() as conn:
                n_orders = (await conn.execute(
                    text("SELECT COUNT(*) FROM merchant_orders WHERE order_id <> :h"), {"h": HISTORY_ORDER_ID}
                )).scalar()
                stock = (await conn.execute(text("SELECT stock FROM merchant_skus WHERE sku_code='SPU-P2-BAG-SKU-0'"))).scalar()
            return result, n_orders, stock
        finally:
            await _teardown(engine, me, orig, embeds)

    result, n_orders, stock = asyncio.run(scenario())
    assert result.get("success") is False and "库存不足" in (result.get("message") or "")
    assert n_orders == 0 and stock == 0, "不落单且不得打出负库存"


def test_bridge_excludes_refunded_orders(pg_factory):
    """已退款单的商品不得桥接(与排行/资金口径一致)。"""
    from engine_py.tools_registry.mall_domain import MallDomainService

    async def scenario():
        engine, me, orig, embeds = await _setup(pg_factory)
        try:
            async with me.begin() as conn:
                await conn.execute(
                    text("UPDATE merchant_orders SET status='REFUNDED' WHERE order_id=:h").bindparams(h=HISTORY_ORDER_ID)
                )
            result = await MallDomainService.add_order_item_to_cart({"userId": UID, "keyword": "三合一"})
            return result
        finally:
            await _teardown(engine, me, orig, embeds)

    result = asyncio.run(scenario())
    assert result.get("success") is False and "没有找到" in (result.get("message") or "")


# ── 购物车 SOP 分支路由 ───────────────────────────────────────────────────


def _skill_ctx(input_text: str) -> SkillContext:
    return SkillContext(
        thread_id=TID,
        tenant_id="ecommerce",
        user_id=UID,
        input=input_text,
    )


class TestCartSkillBranches:
    def test_checkout_branch_calls_real_checkout(self, monkeypatch):
        from engine_py.skills.cart import CartManageSkill
        from engine_py.tools_registry.mall_domain import MallDomainService

        calls: list[dict] = []

        async def _fake_checkout(params: dict) -> dict:
            calls.append(params)
            return {"success": True, "orderId": "AURORA-ORD-2026-7777", "totalAmount": 1299.0,
                    "items": [], "shippingAddress": "默认地址"}

        monkeypatch.setattr(MallDomainService, "checkout_user_cart", staticmethod(_fake_checkout))
        result = asyncio.run(CartManageSkill().execute(_skill_ctx("把购物车里的东西结算下单"))).to_dict()
        assert len(calls) == 1 and calls[0].get("userId") == UID
        assert "AURORA-ORD-2026-7777" in (result.get("output") or "")

    def test_bare_jiesuan_stays_view(self, monkeypatch):
        """裸「结算」保持查看摘要语义(旧契约),不得误开真实订单。"""
        from engine_py.skills.cart import CartManageSkill
        from engine_py.tools_registry.mall_domain import MallDomainService

        calls: list[dict] = []

        async def _fake_checkout(params: dict) -> dict:
            calls.append(params)
            return {"success": True, "orderId": "X"}

        async def _fake_summary(params: dict) -> dict:
            return {"cart": {"items": [], "totalQuantity": 0, "totalAmount": 0, "payableAmount": 0}}

        monkeypatch.setattr(MallDomainService, "checkout_user_cart", staticmethod(_fake_checkout))
        monkeypatch.setattr(MallDomainService, "get_cart_summary", staticmethod(_fake_summary))
        result = asyncio.run(CartManageSkill().execute(_skill_ctx("结算"))).to_dict()
        assert not calls, "裸结算严禁触发真实下单"
        assert result.get("success") is True

    def test_negation_never_checks_out(self, monkeypatch):
        """「我还没下单/先不付款」等否定形严禁开出真单。"""
        from engine_py.skills.cart import CartManageSkill
        from engine_py.tools_registry.mall_domain import MallDomainService

        calls: list = []

        async def _fake_checkout(params: dict) -> dict:
            calls.append(params)
            return {"success": True, "orderId": "X"}

        monkeypatch.setattr(MallDomainService, "checkout_user_cart", staticmethod(_fake_checkout))
        for phrase in ("我还没下单呢", "先不付款", "货到付款可以吗", "不要下单"):
            asyncio.run(CartManageSkill().execute(_skill_ctx(phrase))).to_dict()
        assert not calls, f"否定形误触结算: {calls}"

    def test_delete_plus_checkout_yields_to_delete(self, monkeypatch):
        """「删掉背包然后结算下单」:删除半必须先被执行,严禁吞掉删半带
        着不要的商品开出真单。"""
        from engine_py.skills.cart import CartManageSkill
        from engine_py.tools_registry.mall_domain import MallDomainService

        checkout_calls: list = []

        async def _fake_checkout(params: dict) -> dict:
            checkout_calls.append(params)
            return {"success": True, "orderId": "X"}

        async def _fake_summary(params: dict) -> dict:
            return {"cart": {"items": [{"skuId": "BAG-1", "title": "背包", "price": 829.0, "quantity": 1}],
                             "totalQuantity": 1, "totalAmount": 829, "payableAmount": 829}}

        async def _fake_has_cart(params: dict) -> bool:
            return True

        async def _fake_update(params: dict) -> dict:
            return {"success": True}

        monkeypatch.setattr(MallDomainService, "checkout_user_cart", staticmethod(_fake_checkout))
        monkeypatch.setattr(MallDomainService, "get_cart_summary", staticmethod(_fake_summary))
        monkeypatch.setattr(MallDomainService, "has_cart", staticmethod(_fake_has_cart))
        monkeypatch.setattr(MallDomainService, "update_cart_item", staticmethod(_fake_update))
        result = asyncio.run(CartManageSkill().execute(_skill_ctx("删掉背包然后结算下单"))).to_dict()
        assert not checkout_calls, "复合删除+结算不得直接开单"
        assert result.get("success") is True

    def test_bridge_branch_calls_order_item_bridge(self, monkeypatch):
        from engine_py.skills.cart import CartManageSkill
        from engine_py.tools_registry.mall_domain import MallDomainService

        calls: list[dict] = []

        async def _fake_bridge(params: dict) -> dict:
            calls.append(params)
            return {"success": True, "message": "已将您订单里的冲锋衣加入购物车"}

        monkeypatch.setattr(MallDomainService, "add_order_item_to_cart", staticmethod(_fake_bridge))
        result = asyncio.run(CartManageSkill().execute(_skill_ctx("把我最近的订单里的那件冲锋衣加入购物车"))).to_dict()
        assert len(calls) == 1 and calls[0].get("keyword"), "必须带商品关键词"
        assert "冲锋衣" in (result.get("output") or "")


if __name__ == "__main__":
    pytest.main([__file__])


class TestPlannerMetricSoloFastTrack:
    """单意图 metric_query 确定性快轨(2026-09-14 nightly 巡检钉)。

    「最赚钱的商品排行」曾落 LLM 深规划自选 volume(利润榜变销量榜,回复自称
    「利润表现优异」实为销量排序)——排行 metric 是纯词表映射,与 address_manage
    同理必须零 LLM 确定性执行。"""

    def _plan(self, monkeypatch: pytest.MonkeyPatch, input_text: str) -> dict:
        from engine_py.graph.nodes import planner as planner_mod

        monkeypatch.setattr(planner_mod, "ShortMemory", _FakeShortMemory)

        def _no_llm(*args, **kwargs):
            raise AssertionError("单意图排行句必须走确定性快轨,不得消耗 LLM")

        monkeypatch.setattr(planner_mod, "planner_llm", _no_llm)
        state = {
            "intents": [{"intent": "metric_query", "confidence": 0.97, "type": "primary"}],
            "input": input_text,
            "short_memory": [],
        }
        return asyncio.run(planner_mod.planner_node(state))

    def test_zhuanqian_maps_to_gross_profit(self, monkeypatch):
        plan = self._plan(monkeypatch, "最赚钱的商品排行")
        descs = [st["description"] for st in plan["task_plan"]["subtasks"]]
        assert len(descs) == 1
        assert "queryProductRanking" in descs[0] and "gross_profit" in descs[0]

    def test_margin_rate_and_volume_wording(self, monkeypatch):
        descs_margin = [st["description"] for st in self._plan(monkeypatch, "毛利率排行")["task_plan"]["subtasks"]]
        assert "margin_rate" in descs_margin[0]
        descs_volume = [st["description"] for st in self._plan(monkeypatch, "销量排行")["task_plan"]["subtasks"]]
        assert "volume" in descs_volume[0]
