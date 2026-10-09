"""货架词典解析器册(ADR-0012,2026-10-09):检索词产出从「分块偶然切分」
升格为「块内结构化解析」。

钉死契约:
- 块内词典最长匹配:词素在块不在句,分块边界不再决定词素命运 —— 实弹三连
  (0927 搭配补脚 / 1001 衣族别名 / 1009 黏词兜底)之后的第四种措辞形状在
  解析层结构性接住;
- 修饰/场景词只剥不扬:进 modifiers 槽,不进检索、不参与排序(排序议题
  留缝);死词元不再发查询(轮转 SQL 只对活脚发射);
- 不在册残留词保留为脚(recall 不缩,「装备」靠品类列 ILIKE 子串命中);
- 接线三态:off / 解析异常 / 零产出 → 逐字节回退旧词元路(零产出整句回退,
  严禁部分混搭);品类词典动态跟库(密封货架的品类列即词典)。
"""

from __future__ import annotations

import asyncio
import json
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from engine_py.tools_registry.mall.query_parser import parse_shelf_query
from engine_py.tools_registry.mall_domain import MallDomainService

# (spu_code, title, subtitle, category, description, [(price, stock, 颜色)])
_SPUS = [
    # 露营装备族:「装备」凭品类列子串命中、且可凭品类词典「露营装备」直接
    # 命中的三兄弟(实弹独吞 limit 事故的原班人马)
    (
        "SPU-CAMP-CD", "极光 户外便携手冲咖啡套装 (耐热玻璃分享壶)",
        "高硼硅玻璃分享壶 | 陶瓷扇形滤杯 | 钛合金保温壶", "露营装备",
        "玻璃制品，运输需加固防护，适用场景露营/居家手冲。",
        [(329.0, 123, "原木色")],
    ),
    (
        "SPU-CAMP-SB", "极光 700蓬鹅绒木乃伊睡袋 (舒适温标-5℃)",
        "700蓬RDS鹅绒 | 15D防绒尼龙 | 1.1kg轻量", "露营装备",
        "15D 防绒尼龙面料，舒适温标 0℃ / -5℃ 两档。",
        [(899.0, 78, "极夜绿")],
    ),
    (
        "SPU-CAMP-TT", "极光 轻量化双人双层露营帐篷",
        "20D硅涂尼龙 | 防水3000mm | 3分钟快搭", "露营装备",
        "3分钟快搭，双层交叉杆自立帐。",
        [(1299.0, 73, "军绿色")],
    ),
    # 衣族:货架以具体品名命名,四列词面无「衣服」子串(别名展开的目标族)
    (
        "SPU-WEAR-SHELL", "极光 三合一全天候户外硬壳冲锋衣",
        "GORE-TEX级 | 三合一", "户外机能",
        "全天候户外硬壳冲锋衣，适合徒步登山防风保暖。",
        [(1299.0, 20, "曜石黑")],
    ),
    (
        "SPU-WEAR-TEE", "极光 320g重磅纯棉复古印花短袖T恤",
        "重磅精梳纯棉", "潮流T恤",
        "重磅精梳纯棉T恤，复古印花。",
        [(199.0, 40, "雪山白")],
    ),
]

_CLOTHING_STEMS = ("衬衫", "T恤", "夹克", "冲锋衣", "羽绒", "裤", "POLO")

_MERCHANT_SPUS_DDL = """
CREATE TABLE IF NOT EXISTS merchant_spus (
  id UUID PRIMARY KEY,
  spu_code TEXT NOT NULL UNIQUE,
  title TEXT NOT NULL,
  subtitle TEXT,
  description TEXT,
  category TEXT NOT NULL DEFAULT '服装鞋包',
  main_image TEXT,
  specs JSONB DEFAULT '{}'::jsonb,
  status TEXT NOT NULL DEFAULT 'ON_SALE',
  created_at TIMESTAMP NOT NULL DEFAULT NOW()
)
"""

_MERCHANT_SKUS_DDL = """
CREATE TABLE IF NOT EXISTS merchant_skus (
  id UUID PRIMARY KEY,
  spu_id UUID NOT NULL REFERENCES merchant_spus(id) ON DELETE CASCADE,
  sku_code TEXT NOT NULL UNIQUE,
  sku_title TEXT NOT NULL DEFAULT '',
  spec_attributes JSONB NOT NULL DEFAULT '{}'::jsonb,
  price NUMERIC(10,2) NOT NULL,
  stock INTEGER NOT NULL DEFAULT 0
)
"""


def _parse(query: str, categories: tuple[str, ...] = ()) -> object:
    """纯函数入口:注入 MallDomainService 真实词典与文本基元(单一事实源)。"""
    return parse_shelf_query(
        query,
        wrapper_terms=MallDomainService._GUIDE_WRAPPER_TERMS,
        stem_aliases=MallDomainService._TERM_STEM_ALIASES,
        modifier_terms=MallDomainService._SCENE_MODIFIER_TERMS,
        categories=categories,
        split_chunks=MallDomainService._CHUNK_SEPARATOR_RE.split,
        clean_chunk=MallDomainService._clean_chunk,
    )


# ------------------------------------------------------- 块内解析纯单测


class TestParseShelfQuery:
    def test_incident_sentence_slots(self) -> None:
        """实弹原句:legs 只剩两族活脚,三段修饰全部进槽(死词元不再发查询)。"""
        parsed = _parse("天气冷了，要外出游玩，推荐一些衣服和装备")
        assert parsed.legs == ("衣服", "装备"), f"legs 形状:{parsed.legs}"
        for mod in ("天气冷了", "外出游玩", "一些"):
            assert mod in parsed.modifiers, f"修饰 {mod} 缺席:{parsed.modifiers}"

    @pytest.mark.parametrize(
        ("query", "leg"),
        [
            ("推荐一些衣服和装备", "衣服"),
            ("帮我挑保暖的裤子", "裤子"),
            ("来点防水冲锋衣", "冲锋衣"),
            ("推荐两件衣服", "衣服"),
        ],
    )
    def test_glued_variants_resolve_to_dictionary_leg(self, query: str, leg: str) -> None:
        """黏词变体族:量化/修饰语黏在族名词前后,解析层直接落词典键。"""
        parsed = _parse(query)
        assert leg in parsed.legs, f"{query!r} → {parsed.legs},缺 {leg}"

    def test_longest_match_wins_whole_word(self) -> None:
        """最长匹配不重叠消费:「登山包」整体命中,「登山」「背包」让位。"""
        parsed = _parse("推荐登山包")
        assert parsed.legs == ("登山包",), f"最长匹配失守:{parsed.legs}"

    def test_scene_chunk_goes_modifier_not_leg(self) -> None:
        """场景句整块进修饰槽:legs 为空(接线层据此整句回退旧路)。"""
        parsed = _parse("天气冷了")
        assert parsed.legs == ()
        assert parsed.modifiers == ("天气冷了",)

    def test_dynamic_categories_become_dictionary_keys(self) -> None:
        """品类词典动态跟库:货架品类列值注入即键,「露营装备」直接命中。"""
        parsed = _parse("推荐露营装备", categories=("露营装备", "户外机能"))
        assert parsed.legs == ("露营装备",), f"品类键失守:{parsed.legs}"

    def test_unbooked_residual_stays_leg(self) -> None:
        """不在册残留保留为脚(recall 不缩):「装备」无词典命中仍是 leg。"""
        parsed = _parse("推荐装备")
        assert parsed.legs == ("装备",), f"残留词被误剥:{parsed.legs}"

    def test_glue_leftover_goes_modifier(self) -> None:
        """命中块内的黏词胶水只剥不扬:「防水冲锋衣」→ leg 冲锋衣 + 胶水防水。"""
        parsed = _parse("来点防水冲锋衣")
        assert parsed.legs == ("冲锋衣",)
        assert any("防水" in m for m in parsed.modifiers), f"胶水去向:{parsed.modifiers}"

    def test_browse_shape_returns_empty(self) -> None:
        """纯浏览形(全剥空)与今日词元路同形:空 legs。"""
        parsed = _parse("有什么好看的")
        assert parsed.legs == ()


# ------------------------------------------------------- 接线行为(密封货架)


async def _setup_shelf(pg_factory):
    from engine_py.tools_registry import order_domain

    engine = pg_factory.kw["bind"]
    url = engine.url.render_as_string(hide_password=False)
    merchant_engine = create_async_engine(url, poolclass=NullPool)

    async with merchant_engine.begin() as conn:
        await conn.execute(text("DROP TABLE IF EXISTS merchant_skus CASCADE"))
        await conn.execute(text("DROP TABLE IF EXISTS merchant_spus CASCADE"))
        await conn.execute(text(_MERCHANT_SPUS_DDL))
        await conn.execute(text(_MERCHANT_SKUS_DDL))
        await conn.execute(text("TRUNCATE merchant_skus, merchant_spus"))
        for spu_code, title, subtitle, category, description, skus in _SPUS:
            spu_id = uuid.uuid5(uuid.NAMESPACE_URL, spu_code)
            await conn.execute(
                text(
                    "INSERT INTO merchant_spus (id, spu_code, title, subtitle, description, "
                    "category, main_image, specs, status) VALUES ("
                    ":id, :code, :title, :sub, :desc, :cat, :img, CAST(:specs AS jsonb), 'ON_SALE')"
                ).bindparams(
                    id=spu_id,
                    code=spu_code,
                    title=title,
                    sub=subtitle,
                    desc=description,
                    cat=category,
                    img=f"https://img.test/{spu_code}.png",
                    specs=json.dumps({"场景": "户外"}, ensure_ascii=False),
                )
            )
            for idx, (price, stock, color) in enumerate(skus):
                await conn.execute(
                    text(
                        "INSERT INTO merchant_skus (id, spu_id, sku_code, sku_title, "
                        "spec_attributes, price, stock) VALUES "
                        "(:id, :sid, :code, :stitle, CAST(:attrs AS jsonb), :price, :stock)"
                    ).bindparams(
                        id=uuid.uuid5(uuid.NAMESPACE_URL, f"{spu_code}-{idx}"),
                        sid=spu_id,
                        code=f"{spu_code}-SKU-{idx}",
                        stitle=f"{title} {color}",
                        attrs=json.dumps({"颜色": color}, ensure_ascii=False),
                        price=price,
                        stock=stock,
                    )
                )

    original = order_domain._merchant_reader_engine
    order_domain._merchant_reader_engine = lambda: merchant_engine

    async def _sealed_embed(*_args, **_kwargs):
        raise RuntimeError("embedding sealed in this suite")

    async def _sealed_rewrite(_prompt):
        raise RuntimeError("rewrite llm sealed in this suite")

    original_embeds = (
        MallDomainService.__dict__["_embed_query"],
        MallDomainService.__dict__["_embed_texts"],
    )
    original_rewrite = MallDomainService.__dict__["_invoke_rewrite_llm"]
    MallDomainService._embed_query = staticmethod(_sealed_embed)
    MallDomainService._embed_texts = staticmethod(_sealed_embed)
    MallDomainService._invoke_rewrite_llm = staticmethod(_sealed_rewrite)
    return merchant_engine, original, original_embeds, original_rewrite


async def _teardown_shelf(merchant_engine, original, original_embeds, original_rewrite) -> None:
    from engine_py.tools_registry import order_domain

    order_domain._merchant_reader_engine = original
    MallDomainService._embed_query = original_embeds[0]
    MallDomainService._embed_texts = original_embeds[1]
    MallDomainService._invoke_rewrite_llm = original_rewrite
    MallDomainService._spu_embedding_cache.clear()
    async with merchant_engine.begin() as conn:
        await conn.execute(text("TRUNCATE merchant_skus, merchant_spus"))
    await merchant_engine.dispose()


def _is_clothing(name: str) -> bool:
    return any(stem in name for stem in _CLOTHING_STEMS)


class TestParserWiring:
    def test_incident_sentence_keeps_both_families(self, pg_factory) -> None:
        """实弹原句端到端(解析器默认 on):两族在场。"""
        async def scenario():
            handle = await _setup_shelf(pg_factory)
            try:
                res = await MallDomainService.search_products(
                    {"query": "天气冷了，要外出游玩，推荐一些衣服和装备", "limit": 3, "businessId": "ecommerce"}
                )
                return [p["name"] for p in (res.get("products") or [])]
            finally:
                await _teardown_shelf(*handle)

        names = asyncio.run(scenario())
        assert any(_is_clothing(n) for n in names), f"衣族缺席:{names}"
        assert any(not _is_clothing(n) for n in names), f"装备族缺席:{names}"

    def test_dead_terms_no_longer_fire_queries(self, pg_factory) -> None:
        """轮转 SQL 只对活脚发射:实弹原句 2 脚 2 查(旧路 4 词元 4 查)。"""
        async def scenario():
            handle = await _setup_shelf(pg_factory)
            try:
                original = MallDomainService.__dict__["_fetch_merchant_catalog"]
                calls = {"n": 0}

                async def counting(terms, category, max_price, limit, sort=None, color=None):
                    calls["n"] += 1
                    return await original(terms, category, max_price, limit, sort=sort, color=color)

                MallDomainService._fetch_merchant_catalog = staticmethod(counting)
                try:
                    await MallDomainService.search_products(
                        {"query": "天气冷了，要外出游玩，推荐一些衣服和装备", "limit": 3, "businessId": "ecommerce"}
                    )
                finally:
                    MallDomainService._fetch_merchant_catalog = original
                return calls["n"]
            finally:
                await _teardown_shelf(*handle)

        # 轮转 2 脚(衣服/装备)+ 品类词典来自 get_shelf_overview(不走本函数)
        assert asyncio.run(scenario()) == 2

    def test_off_switch_reverts_to_legacy_terms(self, pg_factory, monkeypatch) -> None:
        """AI_GUIDE_PARSER=0 逃生门:回退 = **含 1009 黏词兜底**的旧词元路
        (别名包含式修复属旧路资产,off 只撤解析器,不撤 1009)。行为钉面:
        旧路 4 词元发 4 查(两个死词元照发)+ 两族在场;与 on 态的 2 活脚
        2 查互证开关真的在切换。"""
        monkeypatch.setenv("AI_GUIDE_PARSER", "0")

        async def scenario():
            handle = await _setup_shelf(pg_factory)
            try:
                original = MallDomainService.__dict__["_fetch_merchant_catalog"]
                calls = {"n": 0}

                async def counting(terms, category, max_price, limit, sort=None, color=None):
                    calls["n"] += 1
                    return await original(terms, category, max_price, limit, sort=sort, color=color)

                MallDomainService._fetch_merchant_catalog = staticmethod(counting)
                try:
                    res = await MallDomainService.search_products(
                        {"query": "天气冷了，要外出游玩，推荐一些衣服和装备", "limit": 3, "businessId": "ecommerce"}
                    )
                finally:
                    MallDomainService._fetch_merchant_catalog = original
                return calls["n"], [p["name"] for p in (res.get("products") or [])]
            finally:
                await _teardown_shelf(*handle)

        calls, names = asyncio.run(scenario())
        assert calls == 4, f"off 态应按旧路 4 词元发 4 查,实发 {calls}"
        assert names, "旧路在密封货架必须命中"
        assert any(_is_clothing(n) for n in names), f"off 态(含 1009 兜底的旧路)应两族在场:{names}"

    def test_zero_parse_falls_back_to_legacy_whole_sentence(self, pg_factory) -> None:
        """零产出整句回退(严禁部分混搭):「天气冷了」解析进槽 → 旧死词元
        照发 → 诚实空(而非浏览全量)—— L2/L4 对死词元的既有兜底语义保持。"""
        async def scenario():
            handle = await _setup_shelf(pg_factory)
            try:
                res = await MallDomainService.search_products(
                    {"query": "天气冷了", "limit": 3, "businessId": "ecommerce"}
                )
                return [p["name"] for p in (res.get("products") or [])]
            finally:
                await _teardown_shelf(*handle)

        assert asyncio.run(scenario()) == [], "零产出口必须回退旧死词元路(诚实空),不得变浏览"

    def test_dynamic_category_dictionary_hits_sealed_shelf(self, pg_factory) -> None:
        """品类词典 = 密封货架品类列:问「露营装备」命中整族三兄弟。"""
        async def scenario():
            handle = await _setup_shelf(pg_factory)
            try:
                res = await MallDomainService.search_products(
                    {"query": "推荐露营装备", "limit": 3, "businessId": "ecommerce"}
                )
                return [p["name"] for p in (res.get("products") or [])]
            finally:
                await _teardown_shelf(*handle)

        names = asyncio.run(scenario())
        assert len(names) == 3, f"品类词典脚应命中整族:{names}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
