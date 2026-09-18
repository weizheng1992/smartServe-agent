"""优惠活动/优惠券查询技能测试(PromotionQuerySkill;商城对话闭环 20 号)。

密封容器:铺优惠域表 + 三类活动种子;reader 指向容器;验证在售列表规则文案/
我的券/诚实空/注册。用户身份直接经 context.user_id 传入(生产由线程归属解析)。
"""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from engine_py.skills.contract import SkillContext
from engine_py.skills.promotion_skill import PromotionQuerySkill


@pytest.fixture()
def container(pg_factory, monkeypatch):
    """铺优惠域表 + 三类活动种子;reader 指向容器并还原。"""
    from engine_py.tools_registry import order_domain

    engine = pg_factory.kw["bind"]
    url = engine.url.render_as_string(hide_password=False)

    async def _seed():
        e = create_async_engine(url, poolclass=NullPool)
        async with e.begin() as conn:
            for ddl in (
                (
                    "CREATE TABLE IF NOT EXISTS promotions (id UUID PRIMARY KEY DEFAULT gen_random_uuid(), "
                    "name TEXT, promo_type TEXT, threshold_amount NUMERIC(10,2), discount_value NUMERIC(10,2), "
                    "scope_type TEXT DEFAULT 'all', scope_value TEXT, status TEXT DEFAULT 'active', "
                    "start_at TIMESTAMP DEFAULT NOW(), end_at TIMESTAMP, created_at TIMESTAMP DEFAULT NOW())"
                ),
                (
                    "CREATE TABLE IF NOT EXISTS promotion_redemptions (id UUID PRIMARY KEY DEFAULT gen_random_uuid(), "
                    "promotion_id UUID, order_id TEXT, discount_amount NUMERIC(10,2), created_at TIMESTAMP DEFAULT NOW())"
                ),
                (
                    "CREATE TABLE IF NOT EXISTS user_coupons (id UUID PRIMARY KEY DEFAULT gen_random_uuid(), "
                    "promotion_id UUID, user_id TEXT, status TEXT DEFAULT 'claimed', used_order_id TEXT, "
                    "claimed_at TIMESTAMP DEFAULT NOW(), used_at TIMESTAMP)"
                ),
            ):
                await conn.execute(text(ddl))
            await conn.execute(text("DELETE FROM promotion_redemptions"))
            await conn.execute(text("DELETE FROM user_coupons"))
            await conn.execute(text("DELETE FROM promotions"))
            for name, ptype, th, val in (
                ("开学季满400减50", "full_reduction", 400, 50),
                ("冲锋衣88折", "discount", None, 88),
                ("新客50元券", "coupon", None, 50),
            ):
                await conn.execute(text(
                    "INSERT INTO promotions (id, name, promo_type, threshold_amount, discount_value) "
                    "VALUES (gen_random_uuid(), :n, :t, :th, :v)"
                ).bindparams(n=name, t=ptype, th=th, v=val))
        await e.dispose()

    asyncio.run(_seed())
    original_reader = order_domain._merchant_reader_engine
    container_engine = create_async_engine(url, poolclass=NullPool)
    order_domain._merchant_reader_engine = lambda: container_engine
    yield container_engine
    order_domain._merchant_reader_engine = original_reader

    async def _cleanup():
        await container_engine.dispose()

    asyncio.run(_cleanup())


@pytest.fixture()
def skill(container):
    return PromotionQuerySkill()


def _ctx(user_id: str | None = None, question: str = "有什么优惠活动") -> SkillContext:
    return SkillContext(thread_id=None, user_id=user_id, tenant_id="aurora", input=question)


class TestPromotionQuerySkill:
    def test_registered_in_registry(self):
        from engine_py.skills import SkillRegistry

        SkillRegistry._ensure_initialized()
        assert "skill_promotion_query" in SkillRegistry._skills
        assert "promotion_query" in SkillRegistry._skills["skill_promotion_query"].metadata["triggerIntents"]

    def test_lists_three_promo_types_with_rules(self, container):
        result = asyncio.run(PromotionQuerySkill().execute(_ctx("CUST-8801")))
        assert result.success is True
        assert "满 ¥400 减 ¥50" in result.output
        assert "8.8 折" in result.output
        assert "¥50 券" in result.output
        assert "自动应用最优优惠" in result.output  # 使用说明

    def test_honest_empty_when_no_promos(self, container):
        async def _clear():
            e = create_async_engine(container.url.render_as_string(hide_password=False), poolclass=NullPool)
            async with e.begin() as conn:
                await conn.execute(text("DELETE FROM promotions"))
            await e.dispose()

        asyncio.run(_clear())
        result = asyncio.run(PromotionQuerySkill().execute(_ctx("CUST-8801")))
        assert "没有进行中" in result.output

    def test_my_coupons_listed_for_user(self, container):
        async def _claim():
            e = create_async_engine(container.url.render_as_string(hide_password=False), poolclass=NullPool)
            async with e.begin() as conn:
                pid = (await conn.execute(text(
                    "SELECT id FROM promotions WHERE promo_type = 'coupon' LIMIT 1"
                ))).scalar()
                await conn.execute(text(
                    "INSERT INTO user_coupons (promotion_id, user_id) VALUES (:p, 'CUST-8801')"
                ).bindparams(p=pid))
            await e.dispose()

        asyncio.run(_claim())
        result = asyncio.run(PromotionQuerySkill().execute(_ctx("CUST-8801")))
        assert "我的优惠券" in result.output
        assert "¥50 券" in result.output

    def test_other_user_sees_no_coupons(self, container):
        """已领券属于领取者:其他用户不展示(查询按 user_id 过滤)。"""
        async def _claim():
            e = create_async_engine(container.url.render_as_string(hide_password=False), poolclass=NullPool)
            async with e.begin() as conn:
                pid = (await conn.execute(text(
                    "SELECT id FROM promotions WHERE promo_type = 'coupon' LIMIT 1"
                ))).scalar()
                await conn.execute(text(
                    "INSERT INTO user_coupons (promotion_id, user_id) VALUES (:p, 'CUST-8801')"
                ).bindparams(p=pid))
            await e.dispose()

        asyncio.run(_claim())
        result = asyncio.run(PromotionQuerySkill().execute(_ctx("CUST-9999")))
        assert "我的优惠券" not in result.output
