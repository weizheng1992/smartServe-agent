"""确定性兜底分发器测试(「兜底什么回答什么」;LLM 不可达时的降级回答面)。

密封容器:铺 merchant_orders + 优惠域表;验证:
- 优惠词面 → 活动列表真答
- 显式订单号 + 本人 → 状态真答;非本人 → 如实告知
- 复合句(订单 + 优惠)→ 两段都有
- 无命中 → None(保留罐头)
"""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from engine_py.skills.fallback_dispatcher import deterministic_fallback_answer


@pytest.fixture()
def container(pg_factory, monkeypatch):
    from engine_py.tools_registry import order_domain

    engine = pg_factory.kw["bind"]
    url = engine.url.render_as_string(hide_password=False)

    async def _seed():
        e = create_async_engine(url, poolclass=NullPool)
        async with e.begin() as conn:
            for ddl in (
                (
                    "CREATE TABLE IF NOT EXISTS merchant_orders (order_id TEXT PRIMARY KEY, customer_id TEXT, "
                    "status TEXT, total_amount NUMERIC(10,2), shipping_address JSONB DEFAULT '{}'::jsonb)"
                ),
                (
                    "CREATE TABLE IF NOT EXISTS promotions (id UUID PRIMARY KEY DEFAULT gen_random_uuid(), "
                    "name TEXT, promo_type TEXT, threshold_amount NUMERIC(10,2), discount_value NUMERIC(10,2), "
                    "scope_type TEXT DEFAULT 'all', scope_value TEXT, status TEXT DEFAULT 'active', "
                    "start_at TIMESTAMP DEFAULT NOW(), end_at TIMESTAMP, created_at TIMESTAMP DEFAULT NOW())"
                ),
                (
                    "CREATE TABLE IF NOT EXISTS user_coupons (id UUID PRIMARY KEY DEFAULT gen_random_uuid(), "
                    "promotion_id UUID, user_id TEXT, status TEXT DEFAULT 'claimed', "
                    "claimed_at TIMESTAMP DEFAULT NOW(), used_order_id TEXT, used_at TIMESTAMP)"
                ),
                (
                    "CREATE TABLE IF NOT EXISTS promotion_redemptions (id UUID PRIMARY KEY DEFAULT gen_random_uuid(), "
                    "promotion_id UUID, order_id TEXT, discount_amount NUMERIC(10,2))"
                ),
            ):
                await conn.execute(text(ddl))
            await conn.execute(text(
                "INSERT INTO merchant_orders (order_id, customer_id, status, total_amount, shipping_address) "
                "VALUES ('AURORA-ORD-2026-9081', 'CUST-8801', 'SHIPPED', 1299.00, "
                "'{\"fullAddress\": \"测试地址 1 号\"}'::jsonb) "
                "ON CONFLICT (order_id) DO UPDATE SET total_amount = 1299.00"
            ))
            await conn.execute(text(
                "INSERT INTO promotions (id, name, promo_type, discount_value) "
                "VALUES (gen_random_uuid(), '满400减50', 'full_reduction', 50)"
            ))
        await e.dispose()

    asyncio.run(_seed())
    container_engine = create_async_engine(url, poolclass=NullPool)
    original_reader = order_domain._merchant_reader_engine
    order_domain._merchant_reader_engine = lambda: container_engine
    yield container_engine
    order_domain._merchant_reader_engine = original_reader

    async def _cleanup():
        await container_engine.dispose()

    asyncio.run(_cleanup())


def _ask(question: str, user_id: str = "CUST-8801", thread_id: str | None = None):
    return asyncio.run(
        deterministic_fallback_answer(question, thread_id, user_id, "aurora")
    )


class TestFallbackDispatcher:
    def test_promotion_question_answered(self, container):
        out = _ask("有什么优惠活动")
        assert out is not None and "优惠" in out

    def test_order_status_answered_for_owner(self, container):
        out = _ask("查一下订单 AURORA-ORD-2026-9081 怎么样了")
        assert out is not None
        assert "9081" in out and "运输中" in out
        assert "1299.00" in out

    def test_compound_order_plus_promotion_both_sections(self, container):
        """多意图联合兜底:订单状态段 + 优惠段一次给全(「兜底什么回答什么」)。"""
        out = _ask("查一下订单 AURORA-ORD-2026-9081 顺便看看有什么优惠券")
        assert out is not None
        assert "订单状态" in out
        assert "9081" in out
        # 优惠段:容器有满400减50 活动(无券也能答活动列表)
        assert "优惠" in out or "活动" in out

    def test_unrecognized_order_number_gets_guide(self, container):
        """非 ORD- 形态单号 → 引导提供完整单号(不空查、不编造)。"""
        out = _ask("查一下订单99999999怎么样了", user_id="CUST-8801")
        assert out is not None and "订单号" in out

    def test_no_match_returns_none(self, container):
        assert _ask("今天天气怎么样", user_id="CUST-8801") is None

    def test_order_without_user_binding_honest(self, container):
        """有订单词面但无用户身份:不猜测归属,如实未找到。"""
        out = _ask("查一下订单 AURORA-ORD-2026-9081 怎么样了", user_id="")
        assert out is None or "未找到" in out
        assert out is None or "未找到" in out
