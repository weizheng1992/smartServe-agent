"""优惠活动/优惠券查询技能测试(PromotionQuerySkill;商城对话闭环 20 号)。

密封容器:铺优惠域表 + 三类活动种子;reader 指向容器;验证在售列表规则文案/
我的券/诚实空/注册。用户身份直接经 context.user_id 传入(生产由线程归属解析)。
"""

from __future__ import annotations

import asyncio
import uuid as _uuid

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


def _seed_claimed_and_used(container, user_id: str = "CUST-8801") -> None:
    """种 1 张可用券 + 1 张已核销券。必须挂**两张不同** coupon 型活动:
    uq_user_promo 限同活动同用户一行(共享容器里该约束由相邻套件 DDL 建立)。"""
    async def _seed():
        e = create_async_engine(container.url.render_as_string(hide_password=False), poolclass=NullPool)
        async with e.begin() as conn:
            claimed_pid = str(_uuid.uuid4())
            used_pid = str(_uuid.uuid4())
            await conn.execute(text(
                "INSERT INTO promotions (id, name, promo_type, status, discount_value) "
                "VALUES (CAST(:i AS uuid), '券包回归可用券', 'coupon', 'active', 30)"
            ).bindparams(i=claimed_pid))
            await conn.execute(text(
                "INSERT INTO promotions (id, name, promo_type, status, discount_value) "
                "VALUES (CAST(:i AS uuid), '券包回归已用券', 'coupon', 'active', 20)"
            ).bindparams(i=used_pid))
            await conn.execute(text(
                "INSERT INTO user_coupons (promotion_id, user_id, status) VALUES (CAST(:p AS uuid), :u, 'claimed')"
            ).bindparams(p=claimed_pid, u=user_id))
            await conn.execute(text(
                "INSERT INTO user_coupons (promotion_id, user_id, status, used_order_id, used_at) "
                "VALUES (CAST(:p AS uuid), :u, 'used', 'AURORA-ORD-2026-9856', NOW())"
            ).bindparams(p=used_pid, u=user_id))
        await e.dispose()

    asyncio.run(_seed())


class TestCouponWalletQueries:
    """券向问法(2026-09-22 实弹):「我的优惠券」「我使用过的优惠券」此前与
    活动查询同一模板 —— 券包被活动列表淹没,已核销券完全不出现。"""

    def test_my_coupons_query_shows_claimed_and_used(self, container):
        _seed_claimed_and_used(container)
        result = asyncio.run(PromotionQuerySkill().execute(_ctx("CUST-8801", "我的优惠券")))
        assert result.success is True
        assert "¥30 券" in result.output, f"可用券必须出现: {result.output}"
        assert "已使用" in result.output, f"已核销券必须出现: {result.output}"
        assert "9856" in result.output, f"已核销券须带核销单号: {result.output}"

    def test_used_coupons_query_shows_used_only(self, container):
        _seed_claimed_and_used(container)
        result = asyncio.run(PromotionQuerySkill().execute(_ctx("CUST-8801", "我使用过的优惠券")))
        assert result.success is True
        assert "¥20 券" in result.output
        assert "已使用" in result.output
        assert "9856" in result.output
        # 券向核销查询聚焦已用券,不回活动列表
        assert "在售优惠活动" not in result.output

    def test_used_coupons_via_hexiao_phrasing(self, container):
        """「已经核销的优惠券」同属核销查询;「核销规则」等规则咨询须不入。"""
        from engine_py.skills.promotion_skill import _USED_COUPON_RE

        assert _USED_COUPON_RE.search("已经核销的优惠券有哪些")
        assert _USED_COUPON_RE.search("核销记录")
        assert not _USED_COUPON_RE.search("优惠券核销规则是什么")
        assert not _USED_COUPON_RE.search("怎么使用优惠券")

        _seed_claimed_and_used(container)
        result = asyncio.run(PromotionQuerySkill().execute(_ctx("CUST-8801", "已经核销的优惠券有哪些")))
        assert "在售优惠活动" not in result.output
        assert "9856" in result.output

    def test_my_coupons_honest_empty(self, container):
        result = asyncio.run(PromotionQuerySkill().execute(_ctx("CUST-8801", "我的优惠券")))
        assert "还没有领取" in result.output or "暂无" in result.output, result.output

    def test_general_promo_query_template_unchanged(self, container):
        """非券向问法保持原模板:活动列表 + claimed 券(既有口径不漂移)。"""
        result = asyncio.run(PromotionQuerySkill().execute(_ctx("CUST-8801")))
        assert "在售优惠活动" in result.output
        assert "自动应用最优优惠" in result.output


def _seed_deal_catalog(container) -> None:
    """种两款在售商品(A ¥899 / B ¥169):88 折全场活动下 A 立减更大。

    形状并集纪律(3c4c843 同款):共享容器里 merchant_spus/skus 的建表形状
    由先到文件决定,本用例 ADD COLUMN IF NOT EXISTS 补齐所需列;严禁全表
    DELETE 他套件的目录行,断言只盯本用例种的两款商品的相对排序。
    """
    async def _seed():
        e = create_async_engine(container.url.render_as_string(hide_password=False), poolclass=NullPool)
        async with e.begin() as conn:
            for ddl in (
                "CREATE TABLE IF NOT EXISTS merchant_spus (id UUID PRIMARY KEY DEFAULT gen_random_uuid(), "
                "spu_code TEXT UNIQUE, title TEXT, main_image TEXT, status TEXT DEFAULT 'ON_SALE')",
                "CREATE TABLE IF NOT EXISTS merchant_skus (id UUID PRIMARY KEY DEFAULT gen_random_uuid(), "
                "spu_id UUID REFERENCES merchant_spus(id), sku_code TEXT UNIQUE, sku_title TEXT, price NUMERIC(10,2), stock INT)",
                "ALTER TABLE merchant_spus ADD COLUMN IF NOT EXISTS status TEXT",
                "ALTER TABLE merchant_spus ADD COLUMN IF NOT EXISTS main_image TEXT",
                "ALTER TABLE merchant_skus ADD COLUMN IF NOT EXISTS price NUMERIC(10,2)",
                "ALTER TABLE merchant_skus ADD COLUMN IF NOT EXISTS stock INT",
            ):
                await conn.execute(text(ddl))
            for code, title, sku, price in (
                ("CT-DEAL-A", "冠军款老爹鞋", "CT-DEAL-A-SKU", 899),
                ("CT-DEAL-B", "基础款袜子", "CT-DEAL-B-SKU", 169),
            ):
                # 查后插(禁 ON CONFLICT):共享容器里表形状由先到文件决定,
                # spu_code 未必带唯一约束,ON CONFLICT 会直接报错
                spu_exists = (
                    await conn.execute(text("SELECT 1 FROM merchant_spus WHERE spu_code = :c").bindparams(c=code))
                ).first()
                if spu_exists is None:
                    # id 显式生成:共享容器的建表形状未必带 DEFAULT gen_random_uuid()
                    await conn.execute(text(
                        "INSERT INTO merchant_spus (id, spu_code, title, status) "
                        "VALUES (gen_random_uuid(), :c, :t, 'ON_SALE')"
                    ).bindparams(c=code, t=title))
                sku_exists = (
                    await conn.execute(text("SELECT 1 FROM merchant_skus WHERE sku_code = :k").bindparams(k=sku))
                ).first()
                if sku_exists is None:
                    await conn.execute(text(
                        "INSERT INTO merchant_skus (id, spu_id, sku_code, sku_title, price, stock) "
                        "SELECT gen_random_uuid(), p.id, :k, '默认', :p, 10 FROM merchant_spus p WHERE p.spu_code = :c"
                    ).bindparams(k=sku, p=price, c=code))
            await conn.execute(text(
                "UPDATE merchant_spus SET status='ON_SALE' WHERE spu_code IN ('CT-DEAL-A','CT-DEAL-B')"
            ))
        await e.dispose()

    asyncio.run(_seed())


class TestPromoDealRecommendation:
    """优惠荐品(2026-09-22 实弹):「推荐优惠最大的商品」曾被导购域按销量
    推荐答非所问 —— 优惠词面 + 荐品问法须由本技能按立减额荐品。"""

    def test_recommend_products_sorted_by_discount(self, container):
        _seed_deal_catalog(container)
        result = asyncio.run(PromotionQuerySkill().execute(_ctx("CUST-8801", "推荐优惠最大的商品")))
        assert result.success is True
        assert "优惠力度最大" in result.output
        # 899×88折 立减 107.88 > 169×88折 立减 20.28:A 必须排前
        assert result.output.index("冠军款老爹鞋") < result.output.index("基础款袜子")
        assert "冲锋衣88折" in result.output and "立减" in result.output

    def test_recommend_honest_empty_without_promos(self, container):
        _seed_deal_catalog(container)
        async def _clear():
            e = create_async_engine(container.url.render_as_string(hide_password=False), poolclass=NullPool)
            async with e.begin() as conn:
                await conn.execute(text("DELETE FROM promotions"))
            await e.dispose()

        asyncio.run(_clear())
        result = asyncio.run(PromotionQuerySkill().execute(_ctx("CUST-8801", "推荐优惠最大的商品")))
        assert "没有" in result.output and "优惠推荐" in result.output

    def test_category_guidelines_own_deal_recommendation(self):
        """LLM 分类器类目指南必须把「优惠+荐品」句式划归 8b(21:22 误路由根因)。"""
        from engine_py.triage.intent_registry import CATEGORY_GUIDELINES

        assert "推荐优惠最大的商品" in CATEGORY_GUIDELINES
        assert "优惠力度" in CATEGORY_GUIDELINES

    def test_single_clause_deal_ask_absorbs_guide_intent(self):
        """同句双中(优惠+推荐)由 promotion 吸收 guide,不得拆双意图编排
        (实弹:双意图下导购按销量推荐的输出盖掉优惠荐品);复合句保留双意图。"""
        from engine_py.triage.slot_extractor import SlotExtractor

        entries = SlotExtractor.extract_all("推荐优惠最大的商品", None, None, None)
        assert len(entries) == 1 and entries[0]["intentType"] == "promotion_query"

        both = SlotExtractor.extract_all("有什么优惠活动，顺便推荐连衣裙", None, None, None)
        intents = [e["intentType"] for e in both]
        assert "promotion_query" in intents and "shopping_guide" in intents

    def test_fast_track_matches_decided_intent_over_guide_keywords(self):
        """快轨技能匹配必须认已决意图:promotion_query 不得被导购技能的
        「推荐」关键词兜底按注册顺序截胡(21:22 实弹根因的最后一环)。"""
        from engine_py.skills import SkillRegistry
        from engine_py.skills.contract import SkillContext

        SkillRegistry._ensure_initialized()
        ctx = SkillContext(
            thread_id=None,
            user_id="CUST-8801",
            tenant_id="aurora",
            input="推荐优惠最大的商品",
            slots={"activeIntent": "promotion_query"},
        )
        skill = SkillRegistry.find_matching_skill(ctx)
        assert skill is not None
        assert skill.metadata["id"] == "skill_promotion_query", (
            f"promotion_query 意图必须匹配优惠技能,实为 {skill.metadata['id']}"
        )
