"""SPI 商品检索词元收敛契约(A8)。

``merchant_domain.search_products`` 此前整句 ILIKE —— 「推荐几款双肩包」整句
对 title 永远空手而归(engine 导购链 2026-09-11 同症状,当时只修了 engine
侧)。收敛后词元切分与 WHERE 匹配子句与 engine 导购链同源
(``MallDomainService.search_terms`` / ``catalog_match`` 单一实现);行形状 /
SKU 分组 / created_at 排序仍是网关门户契约不动。本契约钉死:口语措辞可
检索、有 query 提不出词元诚实空、类别过滤、行形状不变。
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.usefixtures("seeded")


@pytest.fixture()
async def catalog():
    from gateway_py.merchant_seed import seed_merchant_data

    await seed_merchant_data()


class TestSpiProductSearchTerms:
    async def test_colloquial_phrase_finds_backpack(self, catalog):
        """「推荐几款双肩包」:整句 ILIKE 命不中「极光 城市通勤防泼水双肩包」,
        词元切分(剥「推荐几款」)后必须命中。"""
        from gateway_py import merchant_domain as mds

        products = await mds.search_products(query="推荐几款双肩包")
        assert products, "词元路径必须命中货架双肩包"
        assert any("双肩包" in p["title"] for p in products)

    async def test_unextractable_query_is_honest_empty(self, catalog):
        """有 query 却提不出词元(纯语气/符号)= 无命中,严禁变相浏览全货架。"""
        from gateway_py import merchant_domain as mds

        assert await mds.search_products(query="!!!") == []

    async def test_category_filter_still_applies(self, catalog):
        """类别过滤与词元 AND 共存(收敛不丢过滤语义)。"""
        from gateway_py import merchant_domain as mds

        products = await mds.search_products(query="双肩包", category="背包收纳")
        assert products
        assert all(p["category"] == "背包收纳" for p in products)

    async def test_product_shape_unchanged(self, catalog):
        """行形状仍是门户契约:productId/skus 分组/price 账本字段齐全。"""
        from gateway_py import merchant_domain as mds

        products = await mds.search_products(query="冲锋衣")
        assert products
        p = products[0]
        for key in ("productId", "spuId", "title", "price", "stock", "category", "skus"):
            assert key in p, f"门户行形状缺 {key}"
        assert p["skus"], "SKU 分组不得丢"

    async def test_terms_facade_shared_with_engine(self):
        """词元管道单一实现:网关消费的就是 engine 门面(防再各自养一份)。"""
        from engine_py.tools_registry.mall_domain import MallDomainService

        terms = MallDomainService.search_terms("推荐几款双肩包")
        assert terms, "wrapper 词剥除后必须剩词元"
        assert any("双肩包" in t or t == "背包" for t in terms)
