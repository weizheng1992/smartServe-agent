"""导购颜色偏好零消费 + 衣族词元缺口回归(2026-10-01 实弹「我喜欢黑色,推荐
出去游玩的衣服和背包」)。

症状链(两族并存,同句双杀):
1. 颜色零消费:技能把「黑色」提取进偏好并宣称「已结合您的偏好:黑色」,但
   search_products 只吃 query/maxPrice —— 颜色从不参与检索。且颜色只活在
   merchant_skus.spec_attributes->>'颜色'(曜石黑/石墨黑),SPU 四列词面
   无「黑」,词元路径结构上永远看不见颜色:货架 14 款黑色在售,推荐 0 款,
   「推荐黑色的衣服」甚至诚实空(真货架 9 款衣族全带黑 SKU)。
2. 衣族词元缺口:「衣服」在货架零词法足迹(货架以 衬衫/T恤/夹克/冲锋衣/裤
   命名),_TERM_STEM_ALIASES 无「衣服」条目;多词元轮转里「衣服」脚空被
   静默丢弃,%背包% 一族独吞 limit(胸包凭品类列「背包收纳」、渔夫帽凭描述
   「收纳进背包侧袋」擦边挤位)—— 用户要「衣服和背包」,得 0 衣服 + 2 包。

钉死契约:
- 颜色是本轮实际说出的偏好时必须真折进检索(SKU spec 级 EXISTS 过滤),
  「已结合您的偏好」从此是真话;承接面旧颜色照旧严禁折入(对齐 0930 契约)。
- 「衣服」经词干别名展开落货架衣族词素,多词元轮转交错合并必须保两族在场。
"""

from __future__ import annotations

import asyncio
import json
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

# 密封货架:颜色只铺在 SKU spec_attributes(复刻真货架形态 —— SPU 四列
# 词面无「黑」);38L 背包只给日落橙、渔夫帽只给米白并带「背包」描述弱命中
# (复刻实弹挤位三兄弟),黑色 SKU 只在 冲锋衣/T恤/双肩包 三款上。
_SPUS = [
    # (spu_code, title, subtitle, category, description, [(price, stock, 颜色)])
    (
        "SPU-C-SHELL", "极光 三合一全天候户外硬壳冲锋衣", "GORE-TEX级 | 三合一", "户外机能",
        "全天候户外硬壳冲锋衣，适合徒步登山。",
        [(1299.0, 20, "曜石黑"), (1299.0, 10, "极夜绿")],
    ),
    (
        "SPU-C-TEE", "极光 320g重磅纯棉复古印花短袖T恤", "重磅精梳纯棉", "潮流T恤",
        "春夏款重磅纯棉T恤，复古印花。",
        [(199.0, 40, "曜石黑"), (199.0, 30, "雪山白")],
    ),
    (
        "SPU-C-SHIRT", "极光 UPF40+ 速干透气户外机能长袖衬衫", "UPF40+ | 速干", "衬衫",
        "户外机能长袖衬衫，速干透气。",
        [(259.0, 15, "雪山白"), (259.0, 12, "雾霾蓝")],
    ),
    (
        "SPU-B-TREK38", "极光 高山徒步轻量化背包 38L", "轻量承载 | 3D减压背负", "背包收纳",
        "高山徒步轻量化背包。",
        [(829.0, 20, "日落橙")],
    ),
    (
        "SPU-B-CITY", "极光 城市通勤防泼水双肩包", "通勤防泼水", "背包收纳",
        "城市通勤双肩包。",
        [(399.0, 25, "曜石黑")],
    ),
    (
        "SPU-A-HAT", "极光 UPF50+ 可折叠双面戴渔夫帽", "UPF50+ | 双面两戴", "配饰",
        "双面两戴一帽两色，收纳进背包侧袋毫无存在感。",
        [(129.0, 30, "米白")],
    ),
]

_BLACK_SPUS = {"SPU-C-SHELL", "SPU-C-TEE", "SPU-B-CITY"}
_CLOTHING_SPUS = {"SPU-C-SHELL", "SPU-C-TEE", "SPU-C-SHIRT"}

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


async def _setup_shelf(pg_factory):
    from engine_py.tools_registry import order_domain
    from engine_py.tools_registry.mall_domain import MallDomainService

    engine = pg_factory.kw["bind"]
    url = engine.url.render_as_string(hide_password=False)
    merchant_engine = create_async_engine(url, poolclass=NullPool)

    async with merchant_engine.begin() as conn:
        # 先 DROP 再建:session 级共享容器里 test_merchant_catalog_reach 会先
        # 建出无 spec_attributes/sku_title 的窄表,IF NOT EXISTS 会变 no-op。
        # 本表形状是其超集(新列全带默认值),对方册后跑照常插数。
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


SPU_CODE_BY_NAME = {
    "SPU-C-SHELL": "SPU-C-SHELL",
    "SPU-C-TEE": "SPU-C-TEE",
    "SPU-C-SHIRT": "SPU-C-SHIRT",
    "SPU-B-TREK38": "SPU-B-TREK38",
    "SPU-B-CITY": "SPU-B-CITY",
    "SPU-A-HAT": "SPU-A-HAT",
}


async def _teardown_shelf(merchant_engine, original, original_embeds, original_rewrite) -> None:
    from engine_py.tools_registry import order_domain
    from engine_py.tools_registry.mall_domain import MallDomainService

    order_domain._merchant_reader_engine = original
    MallDomainService._embed_query = original_embeds[0]
    MallDomainService._embed_texts = original_embeds[1]
    MallDomainService._invoke_rewrite_llm = original_rewrite
    MallDomainService._spu_embedding_cache.clear()
    async with merchant_engine.begin() as conn:
        await conn.execute(text("TRUNCATE merchant_skus, merchant_spus"))
    await merchant_engine.dispose()


class TestClothingFamilyAlias:
    def test_clothing_colloquial_term_expands_to_shelf_stems(self) -> None:
        """「衣服」必须展开出货架衣族词素 —— 货架四列词面无「衣服」子串,
        无别名则词元脚恒空,多词元轮转静默丢族(实弹:0 衣服 + 2 包)。"""
        from engine_py.tools_registry.mall_domain import MallDomainService

        expanded = MallDomainService._expand_stem_aliases(["衣服"])
        assert expanded[0] == "衣服", "原词元必须在前"
        for stem in ("衬衫", "T恤", "夹克", "冲锋衣", "羽绒", "裤"):
            assert stem in expanded, f"衣族词素 {stem} 缺席,展开面:{expanded}"


class TestColorFilterAtCatalog:
    def test_color_filter_keeps_only_black_sku_spus(self, pg_factory) -> None:
        """颜色过滤是 SKU spec 级:白/蓝衬衫四列词面无「黑」但也没黑 SKU,
        必须被排掉;黑色只在 曜石黑/石墨黑 族 SKU 上,LIKE 词素必须接得住。"""
        async def scenario():
            handle = await _setup_shelf(pg_factory)
            try:
                from engine_py.tools_registry.mall_domain import MallDomainService

                res = await MallDomainService.search_products(
                    {"query": "推荐黑色的衣服", "color": "黑色", "limit": 5, "businessId": "ecommerce"}
                )
                return [p["name"] for p in (res.get("products") or [])]
            finally:
                await _teardown_shelf(*handle)

        names = asyncio.run(scenario())
        assert names, "货架有带黑 SKU 的衣服,严禁诚实空(实弹症状)"
        for name in names:
            assert "衬衫" not in name, f"无黑 SKU 的衬衫被颜色过滤放行:{names}"
        assert any("冲锋衣" in n for n in names), f"黑色冲锋衣缺席:{names}"
        assert any("T恤" in n for n in names), f"黑色T恤缺席:{names}"

    def test_color_filter_drops_non_black_spu_even_when_term_matches(self, pg_factory) -> None:
        """38L 背包词元强命中(标题)但只有日落橙 SKU —— 颜色过滤必须压过
        词元命中,严禁「词面命中即放行」退回老路。"""
        async def scenario():
            handle = await _setup_shelf(pg_factory)
            try:
                from engine_py.tools_registry.mall_domain import MallDomainService

                res = await MallDomainService.search_products(
                    {"query": "推荐黑色的背包", "color": "黑色", "limit": 5, "businessId": "ecommerce"}
                )
                return [p["name"] for p in (res.get("products") or [])]
            finally:
                await _teardown_shelf(*handle)

        names = asyncio.run(scenario())
        assert any("双肩包" in n for n in names), f"黑色双肩包缺席:{names}"
        assert not any("38L" in n for n in names), f"日落橙 38L 被颜色过滤放行:{names}"
        assert not any("渔夫帽" in n for n in names), f"米白渔夫帽(描述弱命中)被放行:{names}"


class TestFamilyGapInterleave:
    def test_clothes_and_bags_request_keeps_both_families(self, pg_factory) -> None:
        """「推荐衣服和背包」:多词元轮转交错合并必须保两族在场,单族凭弱
        命中独吞 limit 即实弹症状(0 衣服 + 2 包)。"""
        async def scenario():
            handle = await _setup_shelf(pg_factory)
            try:
                from engine_py.tools_registry.mall_domain import MallDomainService

                res = await MallDomainService.search_products(
                    {"query": "推荐衣服和背包", "limit": 3, "businessId": "ecommerce"}
                )
                return [p["name"] for p in (res.get("products") or [])]
            finally:
                await _teardown_shelf(*handle)

        names = asyncio.run(scenario())
        has_clothing = any(n for n in names if any(s in n for s in ("衬衫", "T恤", "夹克", "冲锋衣", "羽绒", "裤")))
        has_bag = any("包" in n for n in names)
        assert has_clothing, f"衣族缺席(实弹症状):{names}"
        assert has_bag, f"包族缺席:{names}"
        bag_count = sum(1 for n in names if "包" in n)
        assert bag_count <= 2, f"包族独吞 limit:{names}"


class TestSkillColorWiring:
    @staticmethod
    def _run(capture: list[dict], user_input: str, guide_ctx: dict | None = None):
        from engine_py.skills.contract import SkillContext
        from engine_py.skills.guide_skills import ShoppingGuideSkill
        from engine_py.tools_registry.mall_domain import MallDomainService

        async def fake_search(params: dict) -> dict:
            capture.append(params)
            return {"total": 0, "products": []}

        original = MallDomainService.search_products
        MallDomainService.search_products = staticmethod(fake_search)
        try:
            res = asyncio.run(
                ShoppingGuideSkill().execute(
                    SkillContext(input=user_input, guide_context=guide_ctx, thread_id=None, tenant_id="ecommerce")
                )
            )
        finally:
            MallDomainService.search_products = staticmethod(original)
        return res

    def test_current_turn_color_folds_into_search(self) -> None:
        """本轮说出的颜色必须真传检索 —— 「已结合您的偏好:黑色」从此是真话。"""
        capture: list[dict] = []
        self._run(capture, "我喜欢黑色，推荐出去游玩的衣服和背包")
        assert capture, "技能路径必须发起检索"
        assert capture[0].get("color") == "黑色", f"颜色未折进检索参数:{capture[0]}"

    def test_carried_color_never_folds_into_search(self) -> None:
        """承接面旧颜色照旧严禁折入(对齐 2026-09-30 陈旧偏好契约)——
        承接只入库,不上展示句,更不折检索参数。"""
        capture: list[dict] = []
        self._run(
            capture,
            "推荐背包",
            guide_ctx={"extractedPreferences": {"color": "黑色"}, "clarificationRound": 2},
        )
        assert capture, "技能路径必须发起检索"
        assert capture[0].get("color") is None, f"承接颜色严禁折进检索:{capture[0]}"


class TestIncidentSentenceEndToEnd:
    def test_incident_sentence_recommends_black_across_families(self, pg_factory) -> None:
        """用户原句端到端:密封货架 × 真实检索链 × 技能,推荐必须
        全黑(有黑 SKU 的 SPU)且衣族在场、日落橙 38L/米白渔夫帽出局。"""
        async def scenario():
            handle = await _setup_shelf(pg_factory)
            try:
                from engine_py.skills.contract import SkillContext
                from engine_py.skills.guide_skills import ShoppingGuideSkill

                res = await ShoppingGuideSkill().execute(
                    SkillContext(
                        input="我喜欢黑色，推荐出去游玩的衣服和背包",
                        thread_id=None,
                        tenant_id="ecommerce",
                    )
                )
                cards = res.cards or []
                return [p["name"] for p in ((cards[0]["data"]["products"] if cards else []) or [])]
            finally:
                await _teardown_shelf(*handle)

        names = asyncio.run(scenario())
        code_by_title = {
            "极光 三合一全天候户外硬壳冲锋衣": "SPU-C-SHELL",
            "极光 320g重磅纯棉复古印花短袖T恤": "SPU-C-TEE",
            "极光 UPF40+ 速干透气户外机能长袖衬衫": "SPU-C-SHIRT",
            "极光 高山徒步轻量化背包 38L": "SPU-B-TREK38",
            "极光 城市通勤防泼水双肩包": "SPU-B-CITY",
            "极光 UPF50+ 可折叠双面戴渔夫帽": "SPU-A-HAT",
        }
        assert names, "端到端推荐不得为空"
        for name in names:
            code = code_by_title.get(name)
            assert code in _BLACK_SPUS, f"推荐含无黑 SKU 商品(实弹症状):{names}"
        assert any(code_by_title.get(n) in _CLOTHING_SPUS for n in names), f"衣族缺席(实弹症状):{names}"
        assert not any("渔夫帽" in n or "38L" in n for n in names), f"无黑弱命中挤位:{names}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
