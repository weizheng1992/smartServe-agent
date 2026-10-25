"""回归:查询改写档降级的品类词回退(2026-10-24 实弹「推荐当季热销机能外套」)。

根因链(诊断留档,gateway-nightly.log 08:10 轮):
1. 「机能外套」复合词 L1 词元 miss + L2 语义卡阈 —— 合法到达 L4 改写档;
2. L4 改写 LLM 撞 2s 超时(asyncio.TimeoutError 的 str 为空 = 日志
   `[MallDomain] 查询改写档降级空表(query=…): ` 冒号后空白),降级空表;
3. L4 空即链终点诚实空 → 导购道歉「未能找到现货商品」。LLM 延迟骑在
   超时线上,直调 search_products 复现 ~50%(run1 命中 4 件 / run2 空)。

修复契约:L4 降级不再终结 —— `_category_bigram_fallback` 品类词二元组
确定性回退(词表锚定,零 LLM,同守不跨目录补货红线);查询与品类名无
≥2 字重叠时仍诚实空。商户货架以桩密封(同 test_mall_search_terms 纪律,
不触环境商户库)。
"""

from __future__ import annotations

import asyncio

import pytest

from engine_py.tools_registry.mall_domain import MallDomainService

_SHELF = ["户外机能", "潮流T恤", "背包收纳", "露营装备", "配饰"]


@pytest.fixture(autouse=True)
def _sealed_shelf(monkeypatch):
    """货架桩:catalog_match 以「terms 命中品类词或类内词」仿真;词表固定;
    改写 LLM 默认抛 TimeoutError(实弹形态)。"""

    async def fake_fetch(terms, category, max_price, limit, sort=None, color=None):
        hit_words = tuple(terms or ()) + ((category,) if category else ())
        if any(any(w in t for t in hit_words) for w in ("机能", "户外", "冲锋衣", "外套")):
            return [
                {"id": "spu-001", "title": "极光 三合一户外硬壳冲锋衣", "price": 1299.0, "stock": 45, "category": "户外机能"},
            ]
        return []

    async def fake_overview():
        return [{"category": c} for c in _SHELF]

    async def boom_llm(_prompt: str):
        raise TimeoutError()

    monkeypatch.setattr(MallDomainService, "_fetch_merchant_catalog", staticmethod(fake_fetch))
    monkeypatch.setattr(MallDomainService, "get_shelf_overview", staticmethod(fake_overview))
    monkeypatch.setattr(MallDomainService, "_invoke_rewrite_llm", staticmethod(boom_llm))


def _search(query: str) -> dict:
    return asyncio.run(MallDomainService.search_products({"query": query, "limit": 4, "businessId": "aurora"}))


def test_rewrite_timeout_falls_back_to_category_bigram():
    """实弹症状串:改写超时后回退「户外机能」→ 命中在售商品(修前红:空)。"""
    result = _search("推荐当季热销机能外套")
    assert result["total"] >= 1
    assert "冲锋衣" in result["products"][0]["title"]


def test_unparseable_rewrite_also_falls_back(monkeypatch):
    """改写输出不可解析(非超时形态)同享回退。"""

    async def garbage_llm(_prompt: str):
        return "不是 JSON 的输出"

    monkeypatch.setattr(MallDomainService, "_invoke_rewrite_llm", staticmethod(garbage_llm))
    result = _search("来一件户外机能外套")
    assert result["total"] >= 1


def test_no_overlap_stays_honest_empty():
    """查询与货架词表零重叠:回退不产候选,诚实空保持(不跨目录补货红线)。"""
    result = _search("想要一台量子手机")
    assert result["total"] == 0 and result["products"] == []


def test_bigram_ranking_prefers_longest_overlap():
    """纯函数:按最长重叠排序,「背包收纳」双字重叠命中,无重叠品类不入选。"""
    assert MallDomainService._category_bigram_fallback("推荐一个收纳背包", _SHELF) == ["背包收纳"]
    assert MallDomainService._category_bigram_fallback("推荐当季热销机能外套", _SHELF) == ["户外机能"]
    assert MallDomainService._category_bigram_fallback("量子手机", _SHELF) == []
    assert MallDomainService._category_bigram_fallback("", _SHELF) == []
