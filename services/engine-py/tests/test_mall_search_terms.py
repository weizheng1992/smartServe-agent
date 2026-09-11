"""回归:商品检索词元语义 —— 2026-09-11 用户症状「推荐背包热销」推荐了跑鞋。

根因链(诊断留档):
1. search_products 以整句做子串匹配(`name ILIKE '%推荐背包热销%'`),
   NL 措辞永远命中不了任何商品字段;
2. 查无结果时 mock 兜底 `filtered or MOCK_PRODUCTS` 把整个目录冒充
   「热销推荐」全量返回 —— 用户要背包,得到 3 件 Nike 跑鞋。

修复契约(B 档 + L3,2026-09-11):
- 剥导购 wrapper 词(推荐/热销/有什么/比较好…,与 slot_extractor
  SHOPPING_GUIDE 规则、ShoppingGuideSkill._FALLBACK_RE 两处意图词表同族
  维护)后按词元 OR 匹配;
- 检索降级链 = 商户真货架(agent_merchant)→ engine 本地 products 表 →
  诚实空;MOCK_PRODUCTS 假目录已整体拆除,严禁任何目录兜底冒充推荐;
- 纯浏览形输入(wrapper 剥完为空)保持无关键词全量浏览。

本文件覆盖词元提取纯单测 + engine 降级分支(商户 reader 以抛异常桩密封,
不依赖环境 MERCHANT_DATABASE_URL 是否导出)。商户主目录的端到端行为由
test_merchant_catalog_reach.py(密封商户库)钉死。
"""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import text as sql_text

from engine_py.tools_registry.mall_domain import MallDomainService


@pytest.fixture(autouse=True)
def _sealed_merchant_reader():
    """商户 reader 以抛异常桩密封:本文件全部用例固定走 engine 降级分支。

    conftest 冻结 DATABASE_URL 但不清 MERCHANT_DATABASE_URL —— dev shell
    若导出过该变量,未密封用例会对宿主 5432 真实商户库发起 TCP 认证往返,
    引入环境相关非决定性。
    """
    from engine_py.tools_registry import order_domain

    def _boom():
        raise RuntimeError("merchant reader sealed for engine-branch tests")

    original = order_domain._merchant_reader_engine
    order_domain._merchant_reader_engine = _boom
    yield
    order_domain._merchant_reader_engine = original


def _search(query: str | None, **overrides) -> dict:
    params = {"query": query, "limit": 3, "businessId": "ecommerce", **overrides}
    return asyncio.run(MallDomainService.search_products(params))


# ------------------------------------------------- _extract_query_terms 单测


def test_terms_symptom_string_strips_to_backpack() -> None:
    """症状串钉死:「推荐背包热销」剥掉 wrapper 后只剩「背包」。"""
    assert MallDomainService._extract_query_terms("推荐背包热销") == ["背包"]


def test_terms_browse_only_input_empties() -> None:
    """纯浏览形输入(2026-09-08 购物车事故同款措辞)剥完为空。"""
    assert MallDomainService._extract_query_terms("最近热销的商品") == []


def test_terms_l1_browse_family_empties() -> None:
    """L1 词族浏览形:「有什么卖的好的商品」须剥空(词表曾只有「有没有」)。"""
    assert MallDomainService._extract_query_terms("有什么卖的好的商品") == []


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("比较好的帐篷", ["帐篷"]),
        ("人气高的背包", ["背包"]),
        ("性价比高的冲锋衣", ["冲锋衣"]),
        ("口碑不错的T恤", ["T恤"]),
    ],
)
def test_terms_l1_modifier_families_leave_clean_noun(query: str, expected: list[str]) -> None:
    """L1 短语形修饰词族:剥完不得残留「好/高」残字(OR 会拉入无关商品)。"""
    assert MallDomainService._extract_query_terms(query) == expected


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("高帮鞋", ["高帮鞋"]),  # 「高」不在词表,不得误伤
        # 「好评」整词不在词表(词表只收评价侧 wrapper,好评是检索语义),
        # 如潮亦不剥 —— 误伤面为零
        ("好评如潮的跑鞋", ["好评如潮", "跑鞋"]),
        ("Pegasus 41", ["Pegasus", "41"]),  # 裸拉丁词元/数字不剥
        (None, []),
        ("", []),
    ],
)
def test_terms_existing_contracts_unchanged(query: str | None, expected: list[str]) -> None:
    """既有提取契约不变:误伤面为零。"""
    assert MallDomainService._extract_query_terms(query) == expected


# ------------------------------------------------- engine 降级分支(密封 PG)

_DB_ROWS = [
    ("pytest_bp_38l", "极光 高山徒步轻量化背包 38L", "背包收纳", "轻量化徒步背包", 829.0, 20),
    ("pytest_shoe", "Nike Pegasus Trail 5 越野跑鞋", "running_shoes", "越野跑鞋", 899.0, 5),
]


@pytest.fixture()
def seeded_products(pg_factory):
    """密封 PG 自铺两行(背包/跑鞋),逐测试清场。"""

    async def _run(statements: list[tuple[str, dict]]) -> None:
        from engine_py.db import get_session

        async with get_session() as session:
            for stmt, params in statements:
                await session.execute(sql_text(stmt), params)
            await session.commit()

    inserts = [
        (
            (
                "INSERT INTO products (id, business_id, name, category, description, price, stock) "
                "VALUES (:id, 'pytest_search', :name, :category, :description, :price, :stock)"
            ),
            dict(zip(("id", "name", "category", "description", "price", "stock"), row, strict=True)),
        )
        for row in _DB_ROWS
    ]
    deletes = [("DELETE FROM products WHERE business_id = 'pytest_search'", {})]
    asyncio.run(_run(deletes))
    asyncio.run(_run(inserts))
    yield
    asyncio.run(_run(deletes))


def test_engine_branch_wrapper_stripped_term(seeded_products) -> None:
    """商户库不可达降级 engine 表:整句 NL 措辞仍须以词元命中背包行。"""
    res = _search("推荐背包热销")
    names = [p["name"] for p in res["products"]]
    assert names == ["极光 高山徒步轻量化背包 38L"], names


def test_engine_branch_multi_term_or(seeded_products) -> None:
    """多词元 OR:「Nike 背包」两边都须召回。"""
    res = _search("Nike 背包")
    names = {p["name"] for p in res["products"]}
    assert any("背包" in n for n in names), names
    assert any("跑鞋" in n for n in names), names


def test_engine_branch_honest_empty(seeded_products) -> None:
    """engine 查无 = 降级链终点诚实空,不落任何目录兜底(mock 已拆)。"""
    res = _search("推荐滑雪板")
    assert res["total"] == 0
    assert res["products"] == []


def test_engine_branch_browse_form_full_catalog(seeded_products) -> None:
    """纯浏览形输入在 engine 分支保持无关键词全量浏览。"""
    res = _search("最近热销的商品")
    names = {p["name"] for p in res["products"]}
    assert names == {row[1] for row in _DB_ROWS}, names
