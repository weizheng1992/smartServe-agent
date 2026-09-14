"""评价流完整性红灯回路(2026-09-13 用户实报:复合评价流四症)。

用户句:「询评价好的短袖，并把第一个加入购物车，地址是北京市…1201室，然后结算」
实际:①谎报无短袖(评价词元死串)②幻影入车(历史回溯候选 + candidate[0] 兜底
把上一轮的慢跑裤当成「第一个」)③「地址是…」被当改单地址拿已发货旧单撞墙
④结算用了地址簿默认地址而丢弃句中显式地址。

修复面:①真实评价数据面(商户库 product_reviews 表 + seed + 查询重写);
②加购序数的历史回溯候选在含检索诉求的句子中禁用;③改单意图对「下单/结算」
复合语境让位;④checkoutCart 地址保真(快路径从步骤描述提取显式地址)。
"""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import text

from engine_py.graph.nodes.executor_fast_path import try_match_executor_fast_path
from engine_py.tools_registry.mall_domain import MallDomainService
from engine_py.triage.slot_extractor import SlotExtractor

# ── ①真实评价数据面 ──────────────────────────────────────────────────────


class TestReviewDataSource:
    def test_reviews_query_reads_merchant_reviews(self, pg_factory, monkeypatch):
        """query_product_reviews 必须读商户真评价表(演示数据边界),按商品名
        可查,返回真实评分与内容;engine 本地 products 域旧路径退役。"""
        from sqlalchemy.ext.asyncio import create_async_engine
        from sqlalchemy.pool import NullPool

        from engine_py.tools_registry import order_domain

        engine = pg_factory.kw["bind"]
        merchant_engine = create_async_engine(url=engine.url.render_as_string(hide_password=False), poolclass=NullPool)
        original = order_domain._merchant_reader_engine

        async def setup():
            async with merchant_engine.begin() as conn:
                await conn.execute(text(
                    "CREATE TABLE IF NOT EXISTS merchant_spus ("
                    " id UUID PRIMARY KEY, spu_code TEXT UNIQUE, title TEXT NOT NULL,"
                    " subtitle TEXT, description TEXT, category TEXT, main_image TEXT, specs JSONB DEFAULT '{}'::jsonb, status TEXT DEFAULT 'ON_SALE')"
                ))
                await conn.execute(text(
                    "INSERT INTO merchant_spus (id, spu_code, title) VALUES "
                    "(CAST(:sid AS uuid), 'SPU-R-1', '极光 420g重磅毛圈棉抽绳束脚慢跑裤') "
                    "ON CONFLICT (id) DO UPDATE SET title = EXCLUDED.title"
                ).bindparams(sid="11111111-1111-1111-1111-111111111111"))
                await conn.execute(text(
                    "CREATE TABLE IF NOT EXISTS merchant_product_reviews ("
                    " id UUID PRIMARY KEY DEFAULT gen_random_uuid(),"
                    " spu_id UUID NOT NULL, sku_code TEXT,"
                    " customer_id TEXT, rating INT NOT NULL, content TEXT,"
                    " created_at TIMESTAMP DEFAULT NOW())"
                ))
                await conn.execute(text("TRUNCATE merchant_product_reviews"))
                await conn.execute(text(
                    "INSERT INTO merchant_product_reviews (spu_id, rating, content, customer_id) VALUES "
                    "(CAST(:sid AS uuid), 5, '面料厚实不起球，版型正，回头复购。', 'CUST-A'),"
                    "(CAST(:sid AS uuid), 4, '束脚设计好看，腰头松紧合适。', 'CUST-B')"
                ).bindparams(sid="11111111-1111-1111-1111-111111111111"))

        asyncio.run(setup())
        order_domain._merchant_reader_engine = lambda: merchant_engine
        try:
            result = asyncio.run(MallDomainService.query_product_reviews({"productName": "慢跑裤"}))
            print("DEBUG-REVIEW-RESULT:", result)
        finally:
            order_domain._merchant_reader_engine = original
            asyncio.run(merchant_engine.dispose())

        assert result.get("success") is True, result
        reviews = result.get("reviews") or []
        assert len(reviews) == 2
        assert any("不起球" in (r.get("content") or "") for r in reviews)
        assert result.get("averageRating") == 4.5

    def test_reviews_honest_empty_when_none(self, pg_factory, monkeypatch):
        from sqlalchemy.ext.asyncio import create_async_engine
        from sqlalchemy.pool import NullPool

        from engine_py.tools_registry import order_domain

        engine = pg_factory.kw["bind"]
        merchant_engine = create_async_engine(url=engine.url.render_as_string(hide_password=False), poolclass=NullPool)
        original = order_domain._merchant_reader_engine

        async def setup():
            async with merchant_engine.begin() as conn:
                await conn.execute(text(
                    "CREATE TABLE IF NOT EXISTS merchant_spus ("
                    " id UUID PRIMARY KEY, spu_code TEXT UNIQUE, title TEXT NOT NULL,"
                    " subtitle TEXT, description TEXT, category TEXT, main_image TEXT, specs JSONB DEFAULT '{}'::jsonb, status TEXT DEFAULT 'ON_SALE')"
                ))
                await conn.execute(text(
                    "INSERT INTO merchant_spus (id, spu_code, title) VALUES "
                    "(CAST(:sid AS uuid), 'SPU-R-2', '极光 双人双层露营帐篷') "
                    "ON CONFLICT (id) DO UPDATE SET title = EXCLUDED.title"
                ).bindparams(sid="11111111-1111-1111-1111-111111111111"))
                await conn.execute(text(
                    "CREATE TABLE IF NOT EXISTS merchant_product_reviews ("
                    " id UUID PRIMARY KEY DEFAULT gen_random_uuid(), spu_id UUID NOT NULL,"
                    " sku_code TEXT, customer_id TEXT, rating INT NOT NULL, content TEXT,"
                    " created_at TIMESTAMP DEFAULT NOW())"
                ))
                await conn.execute(text("TRUNCATE merchant_product_reviews"))

        asyncio.run(setup())
        order_domain._merchant_reader_engine = lambda: merchant_engine
        try:
            result = asyncio.run(MallDomainService.query_product_reviews({"productName": "露营帐篷"}))
        finally:
            order_domain._merchant_reader_engine = original
            asyncio.run(merchant_engine.dispose())

        assert result.get("success") is True
        assert result.get("reviews") == []
        assert "暂无" in (result.get("message") or ""), "无评价必须诚实说明"


# ── ②幻影入车:历史回溯候选在检索诉求句中禁用 ─────────────────────────────


class TestPhantomAddGuard:
    def test_ordinal_with_search_intent_ignores_history_candidates(self, monkeypatch):
        """「询评价好的短袖，并把第一个加入购物车」:本轮检索无果时,历史回溯
        候选(上一轮的慢跑裤)严禁充当「第一个」—— 必须诚实反问。"""
        from engine_py.skills.cart_manage_skill import CartManageSkill
        from engine_py.tools_registry.mall_domain import MallDomainService

        add_calls: list = []

        async def _fake_add(params: dict) -> dict:
            add_calls.append(params)
            return {"success": True, "message": "已加入", "cart": {"items": []}}

        async def _fake_summary(params: dict) -> dict:
            return {"cart": {"items": [], "totalQuantity": 0, "totalAmount": 0, "payableAmount": 0}}

        monkeypatch.setattr(MallDomainService, "add_to_cart", staticmethod(_fake_add))
        monkeypatch.setattr(MallDomainService, "get_cart_summary", staticmethod(_fake_summary))

        ctx = {
            "threadId": "phantom_t", "tenantId": "ecommerce", "userId": "CUST-8801",
            "input": "询评价好的短袖，并把第一个加入购物车",
            "slots": {},
            "extra": {
                "shortMemory": [
                    {"role": "assistant", "content": "为您精选了以下推荐商品：\n1. 【极光 420g重磅毛圈棉抽绳束脚慢跑裤】 ¥349"}
                ],
                "guideContext": {},  # 本轮导购检索为空,候选全靠历史回溯
            },
        }
        result = asyncio.run(CartManageSkill().execute(ctx))
        assert not add_calls, "检索诉求句中历史候选严禁充当加购目标(幻影入车)"
        assert "哪一款" in (result.get("output") or ""), "必须诚实反问"


# ── ③地址簿是顾客自有数据:跨租户可见 + 裸「地址列表」检出 ─────────────────


class TestAddressBookCustomerOwned:
    def test_address_book_reads_merchant_ledger(self, pg_factory, monkeypatch):
        """地址簿单账本:聊天读写商户侧 merchant_customers.addresses(与商城
        前端同一存储)—— 双库分裂曾致聊天新增在前端「我的地址」永不可见。"""
        from sqlalchemy.ext.asyncio import create_async_engine
        from sqlalchemy.pool import NullPool

        from engine_py.tools_registry import order_domain
        from engine_py.tools_registry.mall_domain import MallDomainService

        engine = pg_factory.kw["bind"]
        merchant_engine = create_async_engine(url=engine.url.render_as_string(hide_password=False), poolclass=NullPool)
        original = order_domain._merchant_reader_engine

        async def setup():
            async with merchant_engine.begin() as conn:
                await conn.execute(text(
                    "CREATE TABLE IF NOT EXISTS merchant_customers ("
                    " customer_id TEXT PRIMARY KEY, name TEXT, addresses JSONB DEFAULT '[]'::jsonb)"
                ))
                await conn.execute(text(
                    "INSERT INTO merchant_customers (customer_id, addresses) VALUES "
                    "('CUST-AB', CAST(:a AS jsonb)) "
                    "ON CONFLICT (customer_id) DO UPDATE SET addresses = EXCLUDED.addresses"
                ).bindparams(a='[{"id":"addr_x","recipientName":"张伟","phone":"13800138000",'
                                '"fullAddress":"北京市海淀区中关村南大街1号","isDefault":true}]'))

        asyncio.run(setup())
        order_domain._merchant_reader_engine = lambda: merchant_engine
        try:
            result = asyncio.run(MallDomainService.get_user_addresses("CUST-AB", "aurora", None))
        finally:
            order_domain._merchant_reader_engine = original
            asyncio.run(merchant_engine.dispose())

        addrs = result.get("addresses") or []
        assert result.get("total", 0) >= 1, f"必须读到商户账本地址: {result}"
        assert addrs[0].get("fullAddress") == "北京市海淀区中关村南大街1号"

    def test_bare_address_list_detected(self):
        """裸「地址列表」必须检出地址簿查询意图(曾落咨询 RAG 答改派政策)。"""
        from engine_py.triage.intent_triage_engine import detect_address_manage

        detected = detect_address_manage("地址列表")
        assert detected is not None and detected["mode"] == "list"




# ── 价格极值/对比/场景化推荐:快轨词表与价格排序(2026-09-14 T3 矩阵)──────


class TestPriceSuperlativeAndScenario:
    def test_guide_vocab_covers_superlative_and_scenario(self):
        """T3 矩阵:价格极值/对比/场景化问法必须进导购快轨词表 —— 落深规划
        曾 25~236s(转圈根因)。"""
        from engine_py.skills.guide_skills import ShoppingGuideSkill

        for text in (
            "最便宜的背包", "最贵的冲锋衣是哪款", "性价比最高的跑鞋", "问最便宜的背包",
            "有没有便宜点的短袖", "三合一冲锋衣和软壳冲锋衣哪个好", "背包和胸包怎么选",
            "极光的跑鞋和徒步鞋有什么区别", "我经常爬山，买哪种背包", "冬天露营该用什么睡袋",
            "日常通勤背什么包好", "周末去爬山需要准备什么装备", "跑鞋哪款性价比最高",
        ):
            assert ShoppingGuideSkill().can_handle({"input": text}), text

    def test_price_modifier_stripped_from_terms(self):
        """「最便宜的背包」词元=「背包」:价格极值词是排序修饰,严禁混入词元
        (曾把头巾/水壶按价格升序顶了真背包)。"""
        from engine_py.tools_registry.mall_domain import MallDomainService

        terms = MallDomainService._extract_query_terms("最便宜的背包")
        assert "背包" in terms
        assert all("便宜" not in t for t in terms)

    def test_search_supports_price_desc(self, pg_factory, monkeypatch):
        """「最贵的X」:检索支持 price_desc 排序(首条即最贵)。"""
        from sqlalchemy.ext.asyncio import create_async_engine
        from sqlalchemy.pool import NullPool

        from engine_py.tools_registry import order_domain

        engine = pg_factory.kw["bind"]
        merchant_engine = create_async_engine(url=engine.url.render_as_string(hide_password=False), poolclass=NullPool)
        original = order_domain._merchant_reader_engine

        async def setup():
            async with merchant_engine.begin() as conn:
                await conn.execute(text(
                    "CREATE TABLE IF NOT EXISTS merchant_spus ("
                    " id UUID PRIMARY KEY, spu_code TEXT UNIQUE, title TEXT NOT NULL,"
                    " subtitle TEXT, description TEXT, category TEXT, main_image TEXT,"
                    " specs JSONB DEFAULT '{}'::jsonb, status TEXT DEFAULT 'ON_SALE',"
                    " created_at TIMESTAMP NOT NULL DEFAULT NOW())"
                ))
                await conn.execute(text(
                    "CREATE TABLE IF NOT EXISTS merchant_skus ("
                    " id UUID PRIMARY KEY, spu_id UUID NOT NULL, sku_code TEXT UNIQUE,"
                    " sku_title TEXT, price NUMERIC(10,2) NOT NULL, stock INTEGER DEFAULT 0,"
                    " spec_attributes JSONB DEFAULT '{}'::jsonb, image_url TEXT,"
                    " cost_price NUMERIC(10,2) NOT NULL DEFAULT 0,"
                    " created_at TIMESTAMP NOT NULL DEFAULT NOW())"
                ))
                await conn.execute(text("TRUNCATE merchant_skus, merchant_spus"))
                for code, title in (("SPU-CHEAP", "极光 便宜背包"), ("SPU-PRICY", "极光 昂贵背包")):
                    await conn.execute(text(
                        "INSERT INTO merchant_spus (id, spu_code, title) VALUES "
                        "(CAST(:sid AS uuid), :c, :t)"
                    ).bindparams(sid=str(__import__("uuid").uuid5(__import__("uuid").NAMESPACE_URL, code)), c=code, t=title))
                await conn.execute(text(
                    "INSERT INTO merchant_skus (id, spu_id, sku_code, sku_title, price, stock) VALUES "
                    "(CAST(:i1 AS uuid), CAST(:s1 AS uuid), 'SPU-CHEAP-SKU-0', '基础款', 199.0, 10), "
                    "(CAST(:i2 AS uuid), CAST(:s2 AS uuid), 'SPU-PRICY-SKU-0', '旗舰款', 1899.0, 3)"
                ).bindparams(
                    i1=str(__import__("uuid").uuid5(__import__("uuid").NAMESPACE_URL, "cheap-sku")),
                    s1=str(__import__("uuid").uuid5(__import__("uuid").NAMESPACE_URL, "SPU-CHEAP")),
                    i2=str(__import__("uuid").uuid5(__import__("uuid").NAMESPACE_URL, "pricy-sku")),
                    s2=str(__import__("uuid").uuid5(__import__("uuid").NAMESPACE_URL, "SPU-PRICY")),
                ))

        asyncio.run(setup())
        order_domain._merchant_reader_engine = lambda: merchant_engine
        try:
            asc = asyncio.run(MallDomainService.search_products({"query": "背包", "limit": 2}))
            desc = asyncio.run(MallDomainService.search_products({"query": "背包", "sort": "price_desc", "limit": 2}))
        finally:
            order_domain._merchant_reader_engine = original
            asyncio.run(merchant_engine.dispose())
        asc_first = (asc.get("products") or [{}])[0].get("price")
        desc_first = (desc.get("products") or [{}])[0].get("price")
        assert asc_first == 199.0 and desc_first == 1899.0, (asc_first, desc_first)




# ── ③重复拦截数字指纹:槽位数字不同=不同请求 ─────────────────────────────


class TestDuplicateDigitFingerprint:
    def test_digit_runs_differ_means_not_duplicate(self):
        """「…1211室」vs「…1402室」:门牌数字不同,严禁语义重复重放
        (实弹:新地址保存被旧确认重放顶掉)。"""
        from engine_py.triage.intent_triage_engine import _digit_fingerprint

        assert _digit_fingerprint("新增地址 张伟 13800138000 北京市海淀区中关村南大街1号院8号楼1211室") != (
            _digit_fingerprint("新增地址 张伟 13800138000 北京市海淀区中关村南大街1号院8号楼1402室")
        )

    def test_same_digits_same_fingerprint(self):
        from engine_py.triage.intent_triage_engine import _digit_fingerprint as _df
        assert _df("退货政策是什么") == _df("退货策略是什么") == []




# ── 第四轮:守卫语境/否定推荐/JSON 泄漏 ──────────────────────────────────


class TestGuardContextAndLeaks:
    def test_order_query_mentioning_id_not_sanitized(self):
        """N3 实报:查不存在订单的诚实回复被守卫误伤(替换标记泄漏给用户)
        —— 守卫只应拦「下单/结算成功」类宣称,不得碰查单语境。"""
        from engine_py.graph.nodes.output_guard import sanitize_order_claims

        out = (
            "关于您查询的订单 AURORA-ORD-2026-9999，系统查询结果显示该订单不属于您名下，"
            "或不存在于系统中。建议您核对一下订单号是否输入正确。"
        )
        assert asyncio.run(sanitize_order_claims(out, None)) == out, "查单语境严禁被守卫改写"

    def test_raw_tool_json_dump_stripped(self):
        """N12 实报:finish 把工具 JSON 原样吐给用户 —— 必须剥离。"""
        from engine_py.graph.nodes.output_guard import sanitize_order_claims

        out = (
            "您好！您的请求已由 官方综合商城 客服系统处理。执行详情："
            '[{"toolExecuted": "listUserOrders", "output": {"orders": [1,2]}}]'
        )
        cleaned = asyncio.run(sanitize_order_claims(out, None))
        assert "toolExecuted" not in cleaned and "执行详情：[" not in cleaned

    def test_negative_purchase_intent_not_guided(self, monkeypatch):
        """N2 实报:「我不想买了，别给我推荐任何东西」仍被导购快轨搜索推荐
        —— 否定意向必须让位,不得强行推荐。"""
        from engine_py.skills.guide_skills import ShoppingGuideSkill

        skill = ShoppingGuideSkill()
        ctx = {"input": "我不想买了，别给我推荐任何东西"}
        assert skill.can_handle(ctx) is False, "否定意向不得进导购推荐"


# ── ③改单意图对下单/结算复合语境让位 ─────────────────────────────────────


class TestModifyAddressCompoundYield:
    def test_address_in_checkout_context_is_not_modify(self):
        """「地址是北京市…1201室，然后结算」:地址属于新订单,不得拆出
        order_modify_address 意图(旧单已发货被拿去改=撞墙噪音)。"""
        specs = SlotExtractor.extract_all("地址是北京市海淀区中关村南大街1号院8号楼1201室，然后结算")
        intents = {s["intentType"] for s in specs}
        assert "order_modify_address" not in intents, f"改单意图误检出: {intents}"
        assert "cart_manage" in intents, "结算半必须保留"


# ── ④checkoutCart 地址保真 ───────────────────────────────────────────────


class TestCheckoutAddressFidelity:
    def test_fast_path_extracts_stated_address(self):
        """深规划把顾客地址写进步骤描述后,快路径提取为 shippingAddress ——
        严禁静默回落地址簿默认地址。"""
        result = try_match_executor_fast_path(
            description=(
                "Call checkoutCart to place a real order from the customer's current cart items, "
                "shipping to 北京市海淀区中关村南大街1号院8号楼1201室"
            ),
            user_input="然后结算",
            allowed_tools=["checkoutCart"],
        )
        assert result is not None
        assert result["toolName"] == "checkoutCart"
        assert result["args"].get("shippingAddress") == "北京市海淀区中关村南大街1号院8号楼1201室"

    def test_cart_skill_checkout_branch_uses_stated_address(self, monkeypatch):
        """单意图结算路径:「地址是X,然后结算」显式地址必须传给结算服务。"""
        from engine_py.skills.cart_manage_skill import CartManageSkill
        from engine_py.tools_registry.mall_domain import MallDomainService

        calls: list = []

        async def _fake_checkout(params: dict) -> dict:
            calls.append(params)
            return {"success": True, "orderId": "T-1", "totalAmount": 1, "items": [], "shippingAddress": "X"}

        monkeypatch.setattr(MallDomainService, "checkout_user_cart", staticmethod(_fake_checkout))
        asyncio.run(CartManageSkill().execute({
            "threadId": "addr_t", "tenantId": "ecommerce", "userId": "CUST-8801",
            "input": "地址是北京市海淀区中关村南大街1号院8号楼1201室，然后结算",
            "slots": {}, "extra": {},
        }))
        assert calls and calls[0].get("shippingAddress") == "北京市海淀区中关村南大街1号院8号楼1201室"


if __name__ == "__main__":
    pytest.main([__file__])
