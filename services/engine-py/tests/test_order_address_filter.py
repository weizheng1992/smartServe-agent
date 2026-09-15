"""订单按收货地址过滤回归(2026-09-15 用户实报:问「收货地址是 3801 室的订单」,
文本声称筛出 10 笔,卡片却展示全部 30 笔 —— 根因:list_user_orders 只有发货
状态过滤,没有地址过滤;工具照实返回全量,卡片照实打包全量,而 LLM 文本
虚报了「已筛选」与笔数。双层不诚实,同根于查询能力缺失。

钉死 list_user_orders 的 shipping_address 子串过滤契约:
- 商户真单路径:shippingAddress(dict)序列化文本含过滤子串者保留;
- engine 本地表兜底路径:shipping_address 文本列同规则;
- 未传过滤 → 全量(既有契约不变);无匹配 → 诚实空;
- 工具封装 _list_user_orders 透传 shippingAddress(planner 填参通道)。
"""

from __future__ import annotations

import asyncio
import json

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

_MERCHANT_ORDERS_DDL = """
CREATE TABLE IF NOT EXISTS merchant_orders (
  order_id TEXT PRIMARY KEY,
  customer_id TEXT,
  status TEXT NOT NULL DEFAULT 'PAID',
  total_amount NUMERIC(10,2)
)
"""

# 会话级共享容器里先跑的套件可能建过富形态表:地址列 IF NOT EXISTS 自愈
# (沿 test_mock_purge 的列补齐先例,本套件不依赖文件名字典序)
_MERCHANT_ORDERS_COLUMN_PATCHES = [
    "ALTER TABLE merchant_orders ADD COLUMN IF NOT EXISTS shipping_address JSONB DEFAULT '{}'::jsonb",
    "ALTER TABLE merchant_orders ADD COLUMN IF NOT EXISTS created_at TIMESTAMP NOT NULL DEFAULT NOW()",
]

_UID = "CUST-ADDR-FILTER"
_ADDR_TARGET = "北京市朝阳区建国门外大街1号国贸大厦A座 3801室"
_ADDR_OTHER = "北京市海淀区旧地址1号院"

# (order_id, 地址, 状态)
_SEED = [
    ("ADDR-ORD-1", _ADDR_TARGET, "PAID"),
    ("ADDR-ORD-2", _ADDR_TARGET, "SHIPPED"),
    ("ADDR-ORD-3", _ADDR_OTHER, "DELIVERED"),
]


async def _setup_merchant_shelf(pg_factory):
    engine = pg_factory.kw["bind"]
    url = engine.url.render_as_string(hide_password=False)
    merchant_engine = create_async_engine(url, poolclass=NullPool)

    async with merchant_engine.begin() as conn:
        await conn.execute(text(_MERCHANT_ORDERS_DDL))
        for patch in _MERCHANT_ORDERS_COLUMN_PATCHES:
            await conn.execute(text(patch))
        await conn.execute(text("TRUNCATE merchant_orders"))
        for oid, addr, status in _SEED:
            await conn.execute(
                text(
                    "INSERT INTO merchant_orders (order_id, customer_id, status, total_amount, shipping_address) "
                    "VALUES (:oid, :uid, :status, 617, CAST(:addr AS jsonb))"
                ).bindparams(
                    oid=oid,
                    uid=_UID,
                    status=status,
                    addr=json.dumps({"recipientName": "张伟", "phone": "13800138000", "fullAddress": addr}, ensure_ascii=False),
                )
            )

    from engine_py.tools_registry import order_domain

    original_reader = order_domain._merchant_reader_engine
    order_domain._merchant_reader_engine = lambda: merchant_engine
    return merchant_engine, original_reader


async def _teardown_merchant_shelf(merchant_engine, original_reader) -> None:
    from engine_py.tools_registry import order_domain

    order_domain._merchant_reader_engine = original_reader
    async with merchant_engine.begin() as conn:
        await conn.execute(text("TRUNCATE merchant_orders"))
    await merchant_engine.dispose()


def test_address_filter_keeps_only_matching_merchant_orders(pg_factory):
    """地址子串过滤:仅保留 shippingAddress 含过滤串的商户真单。"""
    asyncio.run(_merchant_filter_scenario(pg_factory))


async def _merchant_filter_scenario(pg_factory) -> None:
    from engine_py.tools_registry.order_domain import OrderDomainService

    merchant_engine, original_reader = await _setup_merchant_shelf(pg_factory)
    try:
        res = await OrderDomainService.list_user_orders(user_id=_UID, shipping_address="3801")
        rows = res.get("orders") or []
        assert [r["orderId"] for r in rows] == ["ADDR-ORD-1", "ADDR-ORD-2"], (
            f"地址过滤应仅保留 3801 室两单,实际: {[r['orderId'] for r in rows]}"
        )
    finally:
        await _teardown_merchant_shelf(merchant_engine, original_reader)


def test_no_address_filter_returns_all(pg_factory):
    """未传地址过滤 → 全量(既有契约不变)。"""
    asyncio.run(_no_filter_scenario(pg_factory))


async def _no_filter_scenario(pg_factory) -> None:
    from engine_py.tools_registry.order_domain import OrderDomainService

    merchant_engine, original_reader = await _setup_merchant_shelf(pg_factory)
    try:
        res = await OrderDomainService.list_user_orders(user_id=_UID)
        assert len(res.get("orders") or []) == 3
    finally:
        await _teardown_merchant_shelf(merchant_engine, original_reader)


def test_address_filter_no_match_honest_empty(pg_factory):
    """地址无匹配 → 诚实空列表(不是错误,也不是全量兜底)。"""
    asyncio.run(_no_match_scenario(pg_factory))


async def _no_match_scenario(pg_factory) -> None:
    from engine_py.tools_registry.order_domain import OrderDomainService

    merchant_engine, original_reader = await _setup_merchant_shelf(pg_factory)
    try:
        res = await OrderDomainService.list_user_orders(user_id=_UID, shipping_address="不存在的地址99号")
        assert res.get("orders") == []
    finally:
        await _teardown_merchant_shelf(merchant_engine, original_reader)


def test_address_filter_engine_fallback_path(pg_factory):
    """商户库无单 → engine 本地表兜底路径同样按 shipping_address 文本过滤。"""
    asyncio.run(_engine_fallback_scenario(pg_factory))


async def _engine_fallback_scenario(pg_factory) -> None:
    from engine_py.tools_registry.order_domain import OrderDomainService

    merchant_engine, original_reader = await _setup_merchant_shelf(pg_factory)
    try:
        # engine 本地表兜底行:独立用户(商户库无该用户的单才会走兜底路径)
        eng_user = "CUST-ADDR-ENG"
        async with pg_factory.kw["bind"].begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO orders (order_id, status, carrier, tracking_number, estimated_delivery, "
                    "user_id, business_id, total_amount, shipping_address) "
                    "VALUES ('ENG-ADDR-1', 'paid', 'SF', 'SF001', now() + interval '3 days', "
                    ":u, 'ecommerce', 617, :addr) ON CONFLICT (order_id) DO NOTHING"
                ).bindparams(u=eng_user, addr=_ADDR_TARGET)
            )

        res = await OrderDomainService.list_user_orders(user_id=eng_user, shipping_address="3801")
        rows = res.get("orders") or []
        assert [r["orderId"] for r in rows] == ["ENG-ADDR-1"], (
            f"engine 兜底路径地址过滤失效,实际: {[r['orderId'] for r in rows]}"
        )
    finally:
        await _teardown_merchant_shelf(merchant_engine, original_reader)


def test_tool_wrapper_passes_shipping_address(pg_factory):
    """工具封装透传 shippingAddress(planner 填参通道):过滤真实生效。"""
    asyncio.run(_tool_wrapper_scenario(pg_factory))


async def _tool_wrapper_scenario(pg_factory) -> None:
    from engine_py.tools_registry.ecommerce_tools import _list_user_orders

    merchant_engine, original_reader = await _setup_merchant_shelf(pg_factory)
    try:
        res = await _list_user_orders({"userId": _UID, "shippingAddress": "3801"})
        rows = res.get("orders") or []
        assert [r["orderId"] for r in rows] == ["ADDR-ORD-1", "ADDR-ORD-2"], (
            f"工具封装未透传 shippingAddress,实际: {[r['orderId'] for r in rows]}"
        )
    finally:
        await _teardown_merchant_shelf(merchant_engine, original_reader)
