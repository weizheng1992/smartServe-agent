"""商户真货架检索回归(L3,2026-09-11)—— 聊天商品检索主目录接 agent_merchant。

症状源头(2026-09-11 20:17):「推荐背包热销」推荐了 Nike 跑鞋。B 档修复了
整句匹配落空与 mock 全量兜底两层;L3 把主目录换成商户真货架
(agent_merchant.merchant_spus/skus,单商户现实下全租户统一路由,含 ecommerce),
engine 本地 products 表降为商户库不可达时的兜底,降级链终点诚实空
(MOCK_PRODUCTS 假目录已整体拆除)。

沿 test_spi_client_thread_context.py 套路:密封 PG 同容器第二引擎(NullPool,
asyncio.run 每测试独立事件循环)+ 行内最小 DDL + 整体替换
order_domain._merchant_reader_engine(绕过 lru_cache,运行时模块属性查表)。
"""

from __future__ import annotations

import asyncio
import json
import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

# asyncpg 不接受多命令 prepared statement,每块只放一条 DDL
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
  price NUMERIC(10,2) NOT NULL,
  stock INTEGER NOT NULL DEFAULT 0
)
"""

# 种子矩阵:背包/帐篷/跑鞋/Pegasus/P41 在售;联名背包 OFF_SALE(钉 status
# 过滤);旗舰冲锋衣高客单(maxPrice HAVING 排除用);背包双 SKU 价差(钉
# maxPrice 基准是 MIN(sku.price) 而非任意 SKU 价)。
_SPUS = [
    # (spu_code, title, subtitle, category, status, [(price, stock), ...])
    ("SPU-T-BAG", "极光 高山徒步轻量化背包 38L", "轻量承载 | 防泼水 | 3D减压背负", "背包收纳", "ON_SALE", [(829.0, 20), (899.0, 10)]),
    ("SPU-T-TENT", "极光 冷山双人隧道帐篷", "双层防凝露 | 3000mm 防水", "露营装备", "ON_SALE", [(1299.0, 5)]),
    ("SPU-T-SHOE", "极光 轻量越野跑鞋", "湿地抓地大底", "潮流鞋靴", "ON_SALE", [(899.0, 8)]),
    ("SPU-T-OFF", "极光 限量联名背包", "联名配色", "背包收纳", "OFF_SALE", [(999.0, 5)]),
    ("SPU-T-RICH", "极光 旗舰硬壳冲锋衣", "GORE-TEX 级面料", "户外机能", "ON_SALE", [(1299.0, 3)]),
    ("SPU-T-P41", "极光 Pegasus 41 城市越野跑鞋", "多词元 OR 契约钉死用", "潮流鞋靴", "ON_SALE", [(799.0, 6)]),
]

_ON_SALE_CODES = {row[0] for row in _SPUS if row[4] == "ON_SALE"}


async def _setup_shelf(pg_factory):
    """密封 PG + 同容器商户镜像表铺数 + reader/嵌入 patch。返回 teardown 句柄。"""
    from engine_py.tools_registry import order_domain
    from engine_py.tools_registry.mall_domain import MallDomainService

    engine = pg_factory.kw["bind"]
    url = engine.url.render_as_string(hide_password=False)
    merchant_engine = create_async_engine(url, poolclass=NullPool)

    async with merchant_engine.begin() as conn:
        await conn.execute(text(_MERCHANT_SPUS_DDL))
        await conn.execute(text(_MERCHANT_SKUS_DDL))
        await conn.execute(text("TRUNCATE merchant_skus, merchant_spus"))
        for spu_code, title, subtitle, category, status, skus in _SPUS:
            spu_id = uuid.uuid5(uuid.NAMESPACE_URL, spu_code)
            await conn.execute(
                text(
                    "INSERT INTO merchant_spus (id, spu_code, title, subtitle, description, "
                    "category, main_image, specs, status) VALUES ("
                    ":id, :code, :title, :sub, :desc, :cat, :img, CAST(:specs AS jsonb), :status)"
                ).bindparams(
                    id=spu_id,
                    code=spu_code,
                    title=title,
                    sub=subtitle,
                    desc=f"{title} 的长文案描述(L3 测试铺数)",
                    cat=category,
                    img=f"https://img.test/{spu_code}.png",
                    specs=json.dumps({"容量": "38L", "场景": "徒步"}, ensure_ascii=False),
                    status=status,
                )
            )
            for idx, (price, stock) in enumerate(skus):
                await conn.execute(
                    text(
                        "INSERT INTO merchant_skus (id, spu_id, sku_code, price, stock) "
                        "VALUES (:id, :sid, :code, :price, :stock)"
                    ).bindparams(
                        id=uuid.uuid5(uuid.NAMESPACE_URL, f"{spu_code}-{idx}"),
                        sid=spu_id,
                        code=f"{spu_code}-SKU-{idx}",
                        price=price,
                        stock=stock,
                    )
                )

    original = order_domain._merchant_reader_engine
    order_domain._merchant_reader_engine = lambda: merchant_engine

    # 嵌入默认密封:意外走到语义路径的用例得到「嵌入不可用 → 降级诚实空」,
    # 不加载真 bge 模型(密封测试零外部依赖、确定性)。语义用例显式覆盖
    # _embed_query/_embed_texts 为向量桩;嵌入故障降级用例恰好消费本桩。
    async def _sealed_embed(*_args, **_kwargs):
        raise RuntimeError("embedding sealed in this suite")

    original_embeds = (
        MallDomainService.__dict__["_embed_query"],
        MallDomainService.__dict__["_embed_texts"],
    )
    MallDomainService._embed_query = staticmethod(_sealed_embed)
    MallDomainService._embed_texts = staticmethod(_sealed_embed)
    return engine, merchant_engine, original, original_embeds


async def _teardown_shelf(engine, merchant_engine, original, original_embeds) -> None:
    from engine_py.tools_registry import order_domain
    from engine_py.tools_registry.mall_domain import MallDomainService

    order_domain._merchant_reader_engine = original
    MallDomainService._embed_query = original_embeds[0]
    MallDomainService._embed_texts = original_embeds[1]
    MallDomainService._spu_embedding_cache.clear()
    async with merchant_engine.begin() as conn:
        await conn.execute(text("TRUNCATE merchant_skus, merchant_spus"))
    await merchant_engine.dispose()


async def _search(query: str, **overrides) -> dict:
    from engine_py.tools_registry.mall_domain import MallDomainService

    params = {"query": query, "limit": 10, "businessId": "ecommerce", **overrides}
    return await MallDomainService.search_products(params)


def test_symptom_backpack_query_returns_only_backpack(pg_factory):
    """用户症状钉死(真货架版):「推荐背包热销」只回背包,跑鞋不混入。"""
    asyncio.run(_symptom_scenario(pg_factory))


async def _symptom_scenario(pg_factory) -> None:
    _engine, merchant_engine, original, embeds = await _setup_shelf(pg_factory)
    try:
        res = await _search("推荐背包热销")
        assert res["total"] == 1, f"应只命中背包 SPU,实际: {[p['id'] for p in res['products']]}"
        product = res["products"][0]
        assert product["id"] == "SPU-T-BAG"
        assert "背包" in product["name"]
        # 出参形状与 engine 分支同键集,技能/卡片可直接消费
        assert set(product) == {
            "id", "name", "price", "stock", "description", "category", "specs", "imageUrl",
        }
        assert isinstance(product["price"], float) and product["price"] == 829.0
        assert isinstance(product["stock"], int) and product["stock"] == 30
        assert product["description"] == "轻量承载 | 防泼水 | 3D减压背负"  # subtitle 优先
        assert isinstance(product["specs"], dict)
        assert product["imageUrl"] == "https://img.test/SPU-T-BAG.png"
    finally:
        await _teardown_shelf(_engine, merchant_engine, original, embeds)


def test_l1_modifier_family_routes_to_tent(pg_factory):
    """L1 修饰词族端到端:「有什么卖的好的帐篷」「比较好的帐篷」都只回帐篷。"""
    asyncio.run(_l1_scenario(pg_factory))


async def _l1_scenario(pg_factory) -> None:
    _engine, merchant_engine, original, embeds = await _setup_shelf(pg_factory)
    try:
        for query in ("有什么卖的好的帐篷", "比较好的帐篷"):
            res = await _search(query)
            assert [p["id"] for p in res["products"]] == ["SPU-T-TENT"], (
                f"{query!r} 应剥修饰词后仅命中帐篷,实际: {[p['id'] for p in res['products']]}"
            )
    finally:
        await _teardown_shelf(_engine, merchant_engine, original, embeds)


def test_off_sale_filtered(pg_factory):
    """OFF_SALE 行不得进检索结果(status 过滤)。"""
    asyncio.run(_off_sale_scenario(pg_factory))


async def _off_sale_scenario(pg_factory) -> None:
    _engine, merchant_engine, original, embeds = await _setup_shelf(pg_factory)
    try:
        res = await _search("联名背包")  # 只命中 OFF_SALE 行
        assert res == {"total": 0, "products": []}
    finally:
        await _teardown_shelf(_engine, merchant_engine, original, embeds)


def test_max_price_filters_on_min_sku_price(pg_factory):
    """maxPrice 基准是 SPU 展示价 MIN(sku.price),非任意 SKU 价。"""
    asyncio.run(_max_price_scenario(pg_factory))


async def _max_price_scenario(pg_factory) -> None:
    _engine, merchant_engine, original, embeds = await _setup_shelf(pg_factory)
    try:
        res = await _search("背包", maxPrice=850)
        # 背包双 SKU 829/899:min=829 过阈,高价位 SKU 不得拖杀整个 SPU
        assert [p["id"] for p in res["products"]] == ["SPU-T-BAG"]
        assert await _search("背包", maxPrice=800) == {"total": 0, "products": []}
        assert await _search("冲锋衣", maxPrice=1000) == {"total": 0, "products": []}
        assert [p["id"] for p in (await _search("冲锋衣"))["products"]] == ["SPU-T-RICH"]
    finally:
        await _teardown_shelf(_engine, merchant_engine, original, embeds)


def test_reader_failure_degrades_to_engine_chain(pg_factory):
    """商户库不可达 → 降级 engine 本地表;engine 也查无 → 诚实空(mock 已拆)。"""
    asyncio.run(_degrade_scenario(pg_factory))


async def _degrade_scenario(pg_factory) -> None:
    from engine_py.db import get_session
    from engine_py.tools_registry import order_domain

    _engine, merchant_engine, original, embeds = await _setup_shelf(pg_factory)
    try:
        def _boom():
            raise RuntimeError("merchant shelf down")

        order_domain._merchant_reader_engine = _boom
        async with get_session() as session:
            await session.execute(
                text(
                    "INSERT INTO products (id, business_id, name, category, description, price, stock) "
                    "VALUES ('pytest_l3_degrade', 'pytest_l3', '引擎兜位测试独木舟', 'misc', '降级链测试行', 199.0, 7)"
                )
            )
            await session.commit()

        res = await _search("独木舟")
        assert res["total"] == 1 and res["products"][0]["name"] == "引擎兜位测试独木舟"

        async with get_session() as session:
            await session.execute(text("DELETE FROM products WHERE business_id = 'pytest_l3'"))
            await session.commit()
        # engine 也查无 → 诚实空,不再落 Nike 假目录
        assert await _search("独木舟") == {"total": 0, "products": []}
    finally:
        await _teardown_shelf(_engine, merchant_engine, original, embeds)


def test_shopping_guide_skill_consumes_merchant_shape(pg_factory):
    """ShoppingGuideSkill 端到端不打桩:卡片与候选上下文直接消费商户出参。"""
    asyncio.run(_skill_scenario(pg_factory))


async def _skill_scenario(pg_factory) -> None:
    from engine_py.skills.guide_skills import ShoppingGuideSkill

    _engine, merchant_engine, original, embeds = await _setup_shelf(pg_factory)
    try:
        result = await ShoppingGuideSkill().execute({"input": "推荐背包热销", "tenantId": "ecommerce"})
        assert result["success"] is True
        card = result["cards"][0]
        assert card["type"] == "product_ranking"
        assert [p["productId"] for p in card["data"]["products"]] == ["SPU-T-BAG"]
        assert isinstance(card["data"]["products"][0]["price"], float)
        assert isinstance(card["data"]["products"][0]["stock"], int)

        candidate = result["extra"]["guideContext"]["candidateProducts"][0]
        assert candidate["id"] == "SPU-T-BAG"
        assert candidate["description"] == "轻量承载 | 防泼水 | 3D减压背负"
        assert isinstance(candidate["specs"], dict)
        assert candidate["imageUrl"].startswith("https://img.test/")
    finally:
        await _teardown_shelf(_engine, merchant_engine, original, embeds)


def test_spi_adapter_routes_merchant_shelf(pg_factory):
    """LocalDbSpiAdapter 改道统一检索链,SPI 出参契约零漂移。"""
    asyncio.run(_spi_scenario(pg_factory))


async def _spi_scenario(pg_factory) -> None:
    from engine_py.skills.spi_client import LocalDbSpiAdapter

    _engine, merchant_engine, original, embeds = await _setup_shelf(pg_factory)
    try:
        rows = await LocalDbSpiAdapter().search_products(
            {"query": "背包", "tenantId": "ecommerce", "limit": 5}
        )
        assert [r["productId"] for r in rows] == ["SPU-T-BAG"]
        row = rows[0]
        assert set(row) == {
            "productId", "title", "description", "price", "stock", "category", "isAvailable",
        }
        assert row["title"].startswith("极光 高山徒步")
        assert row["isAvailable"] is True
        assert isinstance(row["price"], float)
    finally:
        await _teardown_shelf(_engine, merchant_engine, original, embeds)


def test_honest_empty_no_cross_catalog(pg_factory):
    """商户可达但查无 → 诚实空,不跨目录补货(用户裁决钉死)。"""
    asyncio.run(_honest_empty_scenario(pg_factory))


async def _honest_empty_scenario(pg_factory) -> None:
    _engine, merchant_engine, original, embeds = await _setup_shelf(pg_factory)
    try:
        assert await _search("滑雪板") == {"total": 0, "products": []}
    finally:
        await _teardown_shelf(_engine, merchant_engine, original, embeds)


def test_browse_form_lists_all_on_sale(pg_factory):
    """纯浏览形输入(修饰词剥完为空)回全量在售货架,OFF_SALE 不入列。"""
    asyncio.run(_browse_scenario(pg_factory))


async def _browse_scenario(pg_factory) -> None:
    _engine, merchant_engine, original, embeds = await _setup_shelf(pg_factory)
    try:
        res = await _search("最近热销的商品")
        ids = {p["id"] for p in res["products"]}
        assert ids == _ON_SALE_CODES, f"浏览形应回全部在售 SPU,实际: {ids}"
        assert "SPU-T-OFF" not in ids
        prices = [p["price"] for p in res["products"]]
        assert prices == sorted(prices), f"应按展示价 ASC 排序,实际: {prices}"
    finally:
        await _teardown_shelf(_engine, merchant_engine, original, embeds)


def test_multi_term_latin_or(pg_factory):
    """裸多词元 OR 契约不变:「Pegasus 41」按词元命中,非整句子串。"""
    asyncio.run(_latin_scenario(pg_factory))


async def _latin_scenario(pg_factory) -> None:
    _engine, merchant_engine, original, embeds = await _setup_shelf(pg_factory)
    try:
        res = await _search("Pegasus 41")
        assert [p["id"] for p in res["products"]] == ["SPU-T-P41"]
    finally:
        await _teardown_shelf(_engine, merchant_engine, original, embeds)


# ------------------------------------------------- L2 语义召回(桩嵌入密封)


def _vec_for_text(embed_text: str) -> list[float]:
    """确定性语义桩:按品类词定向,词元查空的口语措辞经余弦补位可测。"""
    if "帐篷" in embed_text:
        return [1.0, 0.0, 0.0]
    if "背包" in embed_text:
        return [0.0, 1.0, 0.0]
    if "冲锋衣" in embed_text:
        return [0.0, 1.0, 1.0]
    return [0.0, 0.0, 1.0]


def test_semantic_recall_fills_token_miss(pg_factory):
    """L2 补位:词元查空的口语措辞(「野外露营睡觉用的」)经语义召回帐篷。"""
    asyncio.run(_semantic_fill_scenario(pg_factory))


async def _semantic_fill_scenario(pg_factory) -> None:
    from engine_py.tools_registry.mall_domain import MallDomainService

    _engine, merchant_engine, original, embeds = await _setup_shelf(pg_factory)

    async def _camping_query(_q: str) -> list[float]:
        return [1.0, 0.0, 0.0]

    async def _stubby_texts(texts: list[str]) -> list[list[float]]:
        return [_vec_for_text(t) for t in texts]

    MallDomainService._embed_query = staticmethod(_camping_query)
    MallDomainService._embed_texts = staticmethod(_stubby_texts)
    try:
        res = await _search("野外露营睡觉用的")  # 词元不命中任何种子文案
        assert [p["id"] for p in res["products"]] == ["SPU-T-TENT"], (
            f"语义补位应召回帐篷,实际: {[p['id'] for p in res['products']]}"
        )
    finally:
        await _teardown_shelf(_engine, merchant_engine, original, embeds)


def test_semantic_below_threshold_honest_empty(pg_factory):
    """全部候选余弦低于阈值(默认 0.55,真 bge 实测定标)→ 语义也无命中 → 诚实空。"""
    asyncio.run(_semantic_threshold_scenario(pg_factory))


async def _semantic_threshold_scenario(pg_factory) -> None:
    from engine_py.tools_registry.mall_domain import MallDomainService

    _engine, merchant_engine, original, embeds = await _setup_shelf(pg_factory)

    async def _diagonal_query(_q: str) -> list[float]:
        return [0.5, 0.5, 0.7071]  # 与任何基向量余弦恒 0.5 < 0.6

    async def _uniform_texts(texts: list[str]) -> list[list[float]]:
        return [[1.0, 0.0, 0.0] for _ in texts]

    MallDomainService._embed_query = staticmethod(_diagonal_query)
    MallDomainService._embed_texts = staticmethod(_uniform_texts)
    try:
        assert await _search("野外露营睡觉用的") == {"total": 0, "products": []}
    finally:
        await _teardown_shelf(_engine, merchant_engine, original, embeds)


def test_semantic_cache_invalidation_on_text_change(pg_factory):
    """SPU 嵌入缓存按文案哈希失效:文案未变零重嵌,变更仅重嵌该 SPU。"""
    asyncio.run(_semantic_cache_scenario(pg_factory))


async def _semantic_cache_scenario(pg_factory) -> None:
    from engine_py.tools_registry.mall_domain import MallDomainService

    _engine, merchant_engine, original, embeds = await _setup_shelf(pg_factory)
    embed_calls: list[list[str]] = []

    async def _counting_texts(texts: list[str]) -> list[list[float]]:
        embed_calls.append(list(texts))
        return [_vec_for_text(t) for t in texts]

    async def _camping_query(_q: str) -> list[float]:
        return [1.0, 0.0, 0.0]

    MallDomainService._embed_texts = staticmethod(_counting_texts)
    MallDomainService._embed_query = staticmethod(_camping_query)
    try:
        await _search("野外露营睡觉用的")
        assert len(embed_calls) == 1 and len(embed_calls[0]) == 5, "首轮应批量嵌入 5 个在售 SPU"

        await _search("野外露营睡觉用的")
        assert len(embed_calls) == 1, "文案未变,缓存命中不得重嵌"

        async with merchant_engine.begin() as conn:
            await conn.execute(
                text("UPDATE merchant_spus SET subtitle = 'updated camping copy' WHERE spu_code = 'SPU-T-TENT'")
            )
        await _search("野外露营睡觉用的")
        assert len(embed_calls) == 2 and len(embed_calls[1]) == 1, "仅文案变更的 SPU 重嵌"
    finally:
        await _teardown_shelf(_engine, merchant_engine, original, embeds)


def test_semantic_embedding_failure_degrades_to_honest_empty(pg_factory):
    """嵌入不可用(默认密封桩即 raise)→ 语义降级,检索不炸、落诚实空。"""
    asyncio.run(_semantic_failure_scenario(pg_factory))


async def _semantic_failure_scenario(pg_factory) -> None:
    _engine, merchant_engine, original, embeds = await _setup_shelf(pg_factory)
    try:
        res = await _search("野外露营睡觉用的")  # 词元空 → 语义 → 嵌入 raise → 降级
        assert res == {"total": 0, "products": []}
    finally:
        await _teardown_shelf(_engine, merchant_engine, original, embeds)


def test_semantic_disabled_by_flag(pg_factory):
    """AI_MALL_SEMANTIC_ENABLED=0:词元空直接诚实空,零嵌入调用。"""
    asyncio.run(_semantic_disabled_scenario(pg_factory))


async def _semantic_disabled_scenario(pg_factory) -> None:
    from engine_py.config import settings
    from engine_py.tools_registry.mall_domain import MallDomainService

    _engine, merchant_engine, original, embeds = await _setup_shelf(pg_factory)
    query_calls: list[str] = []

    async def _spy_query(q: str) -> list[float]:
        query_calls.append(q)
        return [1.0, 0.0, 0.0]

    MallDomainService._embed_query = staticmethod(_spy_query)
    # settings 是 frozen dataclass,测试覆写走 object.__setattr__
    # (先例:test_cart_persistence_regression.py 的 redis_url 覆写)
    previous = settings.mall_semantic_enabled
    object.__setattr__(settings, "mall_semantic_enabled", False)
    try:
        assert await _search("野外露营睡觉用的") == {"total": 0, "products": []}
        assert query_calls == [], "开关关闭不得触达嵌入"
    finally:
        object.__setattr__(settings, "mall_semantic_enabled", previous)
        await _teardown_shelf(_engine, merchant_engine, original, embeds)


def test_semantic_respects_hard_filters(pg_factory):
    """语义候选池吃满硬过滤:maxPrice 先于语义把高价 SPU 挤出池。"""
    asyncio.run(_semantic_hard_filter_scenario(pg_factory))


async def _semantic_hard_filter_scenario(pg_factory) -> None:
    from engine_py.tools_registry.mall_domain import MallDomainService

    _engine, merchant_engine, original, embeds = await _setup_shelf(pg_factory)

    # 偏「冲锋衣/鞋」维度:与冲锋衣 [0,1,1] 余弦≈0.77、跑鞋 [0,0,1]≈0.995
    # 均过阈,与背包/帐篷正交 —— 断言只钉硬过滤挤出的 RICH 在/不在。
    async def _outdoor_query(_q: str) -> list[float]:
        return [0.0, 0.1, 1.0]

    async def _stubby_texts(texts: list[str]) -> list[list[float]]:
        return [_vec_for_text(t) for t in texts]

    MallDomainService._embed_query = staticmethod(_outdoor_query)
    MallDomainService._embed_texts = staticmethod(_stubby_texts)
    try:
        res = await _search("野外防晒防雨的外套")  # 词元不命中种子文案
        assert "SPU-T-RICH" in {p["id"] for p in res["products"]}

        filtered = await _search("野外防晒防雨的外套", maxPrice=1000)  # RICH 1299 出池
        assert "SPU-T-RICH" not in {p["id"] for p in filtered["products"]}
    finally:
        await _teardown_shelf(_engine, merchant_engine, original, embeds)
