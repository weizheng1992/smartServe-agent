"""回归:多品类连词检索(2026-09-12 用户实报)。

用户原话:「我想买几件裤子和 衬衫推荐一下」→ 只回了衬衫 3 款,裤子被吞。

根因(代码读 + 红灯实证):
1. 词元切分分隔符类不含连词「和/与」——「几件裤子和 衬衫」切成
   「几件裤子和」+「衬衫」,前者 ILIKE 永远落空,只剩衬衫命中;
2. 数量前缀「几件/N件」不剥——「几件裤子」整块无命中;
3. ShoppingGuideSkill limit 硬编码 3,「我要2个商品」数量语义被无视。
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from engine_py.skills.contract import SkillContext
from engine_py.skills.guide_skills import ShoppingGuideSkill
from engine_py.tools_registry import order_domain
from engine_py.tools_registry.mall_domain import MallDomainService

# ── 纯函数缝:词元切分 ────────────────────────────────────────────────────


def test_conjunction_and_quantity_split() -> None:
    """连词「和/与」切开、数量前缀剥除:词元必须是干净品类词。
    「几件裤子和」这类死词元 ILIKE 永远落空(实报症状的直接根因)。"""
    terms = MallDomainService._extract_query_terms("我想买几件裤子和 衬衫推荐一下")
    assert terms == ["裤子", "衬衫"], f"词元不干净: {terms}"


def test_stem_alias_expands_kuzi() -> None:
    """「裤子」→ 追加词素「裤」:品类列「下装裤类」才是命中面。"""
    expanded = MallDomainService._expand_stem_aliases(["裤子", "衬衫"])
    assert "裤" in expanded and expanded.index("裤子") < expanded.index("裤")


def test_quantity_prefix_stripped_per_chunk() -> None:
    assert MallDomainService._extract_query_terms("推荐2个商品 裤子") == ["裤子"]
    assert "几件帐篷" not in MallDomainService._extract_query_terms("来几件帐篷")


def test_no_false_split_inside_product_words() -> None:
    """「跟」不进分隔符(高跟鞋/跟妆会被劈开);「三合一」不被数量前缀误剥。"""
    terms = MallDomainService._extract_query_terms("高跟鞋")
    assert any("高跟鞋" in t for t in terms)
    terms2 = MallDomainService._extract_query_terms("三合一冲锋衣")
    assert any("三合一" in t for t in terms2)


# ── 集成缝:密封商户货架,用户原句端到端 ─────────────────────────────────

_DDL = [
    """
    CREATE TABLE IF NOT EXISTS merchant_spus (
      id UUID PRIMARY KEY, spu_code TEXT NOT NULL UNIQUE, title TEXT NOT NULL,
      subtitle TEXT, description TEXT, category TEXT NOT NULL,
      main_image TEXT, specs JSONB DEFAULT '{}'::jsonb,
      status TEXT NOT NULL DEFAULT 'ON_SALE'
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS merchant_skus (
      id UUID PRIMARY KEY, spu_id UUID NOT NULL REFERENCES merchant_spus(id),
      sku_code TEXT NOT NULL UNIQUE, price NUMERIC(10,2) NOT NULL, stock INTEGER NOT NULL DEFAULT 0
    )
    """,
]

# 裤子与衬衫各 2 款,价格交错(价格排序不得再偏向单品类)
_CATALOG = [
    ("SPU-PANTS-1", "极光 Cordura耐磨多袋机能工装裤", "下装裤类", 589.0, 12),
    ("SPU-PANTS-2", "极光 420g重磅毛圈棉抽绳束脚慢跑裤", "下装裤类", 499.0, 20),
    ("SPU-SHIRT-1", "极光 UPF40+ 速干透气户外机能长袖衬衫", "衬衫", 399.0, 153),
    ("SPU-SHIRT-2", "极光 法兰绒保暖格纹长袖衬衫", "衬衫", 459.0, 30),
]


@pytest.fixture()
def merchant_pg(pg_factory):

    engine = pg_factory.kw["bind"]
    url = engine.url.render_as_string(hide_password=False)
    original_reader = order_domain._merchant_reader_engine

    async def _seed():
        merchant_engine = create_async_engine(url, poolclass=NullPool)
        async with merchant_engine.begin() as conn:
            for ddl in _DDL:
                await conn.execute(text(ddl))
            await conn.execute(text("TRUNCATE merchant_skus, merchant_spus"))
            for code, title, category, price, stock in _CATALOG:
                spu_id = uuid.uuid5(uuid.NAMESPACE_URL, code)
                await conn.execute(
                    text("INSERT INTO merchant_spus (id, spu_code, title, category, status) "
                         "VALUES (:id, :code, :title, :cat, 'ON_SALE')").bindparams(
                        id=spu_id, code=code, title=title, cat=category)
                )
                await conn.execute(
                    text("INSERT INTO merchant_skus (id, spu_id, sku_code, price, stock) "
                         "VALUES (:id, :spu, :code, :price, :stock)").bindparams(
                        id=uuid.uuid5(uuid.NAMESPACE_URL, code + "-SKU"), spu=spu_id,
                        code=code + "-SKU-1", price=price, stock=stock)
                )
        await merchant_engine.dispose()

    asyncio.run(_seed())
    merchant_engine = create_async_engine(url, poolclass=NullPool)
    order_domain._merchant_reader_engine = lambda: merchant_engine
    yield merchant_engine
    order_domain._merchant_reader_engine = original_reader

    async def _cleanup():
        async with merchant_engine.begin() as conn:
            await conn.execute(text("TRUNCATE merchant_skus, merchant_spus"))
        await merchant_engine.dispose()

    asyncio.run(_cleanup())


def test_user_exact_sentence_returns_both_categories(merchant_pg) -> None:
    """用户原句端到端:裤子和衬衫都必须出现在检索结果里。"""
    result = asyncio.run(
        MallDomainService.search_products({"query": "我想买几件裤子和 衬衫推荐一下", "limit": 5})
    )
    names = " ".join(p["name"] for p in result["products"])
    assert "裤" in names, f"裤子品类被吞: {names}"
    assert "衬衫" in names, f"衬衫品类丢失: {names}"


# ── 技能缝:数量语义(「2个商品」)─────────────────────────────────────────


def test_guide_skill_honors_requested_count(merchant_pg) -> None:
    """「我要2个商品」→ 推荐 2 款,不是硬编码 3。"""
    context = SkillContext(
        thread_id="t_qty",
        tenant_id="ecommerce",
        user_id="CUST-8801",
        input="我要2个商品,裤子和衬衫都推荐一下",
        slots={"activeIntent": "shopping_guide"},
        guide_context={},
        cart_context={},
    )
    result = asyncio.run(ShoppingGuideSkill().execute(context)).to_dict()
    count = result["output"].count("【")
    assert count == 2, f"用户要 2 个商品,实际推荐 {count} 个"
    names = result["output"]
    assert ("裤" in names) and ("衬衫" in names), "双品类语义必须都体现"


def test_multi_term_interleave_gives_each_category_a_seat(merchant_pg) -> None:
    """limit=2 + 价格序会让贵品类全灭;多词元时按词元轮转配额,品类公平。"""
    result = asyncio.run(
        MallDomainService.search_products({"query": "裤子和衬衫", "limit": 2})
    )
    names = " ".join(p["name"] for p in result["products"])
    assert "裤" in names and "衬衫" in names, f"limit=2 双品类必须各有席位: {names}"


def test_chinese_numeral_count_honored(merchant_pg) -> None:
    """「我要三个商品」→ 3 款(中文数字不得静默丢弃)。"""
    context = SkillContext(
        thread_id="t_qty3",
        tenant_id="ecommerce",
        user_id="CUST-8801",
        input="我要四个商品,推荐一下",
        slots={"activeIntent": "shopping_guide"},
        guide_context={},
        cart_context={},
    )
    result = asyncio.run(ShoppingGuideSkill().execute(context)).to_dict()
    assert result["output"].count("【") == 4


def test_product_words_with_he_du_not_split() -> None:
    """「和牛/成都」类商品词不得被连词切分/尾缀剥除误伤:
    和切分保留(货架无和牛,可接受),但两字尾「都」不剥。"""
    assert MallDomainService._extract_query_terms("成都限定款裤子") == ["成都限定款裤子"] or any(
        "成都" in t for t in MallDomainService._extract_query_terms("成都限定款裤子")
    )
    terms = MallDomainService._extract_query_terms("衬衫和裤子都要")
    assert "衬衫" in terms and "裤子" in terms, f"{terms}"


def test_unreachable_db_single_fallback_fetch(monkeypatch: pytest.MonkeyPatch) -> None:
    """库不可达时多词元路径立即中断交给降级链,严禁 N 个词元 N 次失败连接。"""
    calls = []

    async def fake_fetch(terms, category, max_price, limit):
        calls.append(terms)

    monkeypatch.setattr(MallDomainService, "_fetch_merchant_catalog", staticmethod(fake_fetch))
    result = asyncio.run(MallDomainService.search_products({"query": "裤子和衬衫", "limit": 3}))
    assert len(calls) == 1, f"首次不可达即中断,实际查了 {len(calls)} 次"
    assert result is not None
