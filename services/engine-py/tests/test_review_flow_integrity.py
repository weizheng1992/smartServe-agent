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
                    " subtitle TEXT, description TEXT, category TEXT, status TEXT DEFAULT 'ON_SALE')"
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
                    " subtitle TEXT, description TEXT, category TEXT, status TEXT DEFAULT 'ON_SALE')"
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
