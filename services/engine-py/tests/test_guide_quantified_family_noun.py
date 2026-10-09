"""导购量化词黏族名词死词元回归(2026-10-09 实弹「天气冷了,要外出游玩,
推荐一些衣服和装备」得了 0 衣服 + 3 件露营装备)。

症状链(与 0927 搭配补脚、1001 衣族别名两次实弹同族,第三种措辞形状):
1. 剥「推荐」后「一些」黏在族名词上成「一些衣服」—— _TERM_STEM_ALIASES
   精确键查不到(别名只在键完全相等时展开),ILIKE %一些衣服% 货架四列
   永真空,衣族整族词法隐身;
2. 「装备」ILIKE 命中品类列「露营装备」独吞 limit(咖啡套装/睡袋/帐篷);
3. 0927 的搭配补脚闸 OUTFIT_RE(搭配|一套|套装|一整套)不认本句形,保险
   永不触发。

修复契约:_expand_stem_aliases 升级为「精确键优先 + 最长键包含扫描」——
量化/修饰语黏在族名词前后(一些衣服/保暖裤子/来点衣服)同一族词素必须
仍然展开;原词元保持在最前,OR 匹配面只宽不窄。密封货架复刻真种子形态
(露营装备族 ×3 + 衣族 ×2),嵌入与改写 LLM 全密封 —— 词元路命中即不落
语义/L4,全链确定性。
"""

from __future__ import annotations

import asyncio
import json
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

# (spu_code, title, subtitle, category, description, [(price, stock, 颜色)])
_SPUS = [
    # 露营装备族:复刻实弹货架 —— 「装备」凭品类列子串独吞 limit 的三兄弟
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
_EQUIPMENT_SPUS = {"SPU-CAMP-CD", "SPU-CAMP-SB", "SPU-CAMP-TT"}
_CLOTHING_SPUS = {"SPU-WEAR-SHELL", "SPU-WEAR-TEE"}

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
    from engine_py.tools_registry.mall_domain import MallDomainService

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


class TestQuantifiedFamilyNounAliases:
    def test_quantifier_glued_noun_still_expands_family_stems(self) -> None:
        """量化词黏族名词:「一些衣服」含别名键「衣服」→ 全族词素必须展开。

        实弹:「推荐一些衣服和装备」词元成「一些衣服」,精确键查不到、
        ILIKE 永真空,衣族整族隐身致 0 衣服 + 3 露营装备。"""
        from engine_py.tools_registry.mall_domain import MallDomainService

        expanded = MallDomainService._expand_stem_aliases(["一些衣服"])
        assert expanded[0] == "一些衣服", "原词元必须在前"
        for stem in _CLOTHING_STEMS:
            assert stem in expanded, f"黏词后族词素 {stem} 缺席,展开面:{expanded}"

    @pytest.mark.parametrize(
        "glued",
        ["保暖衣服", "来点衣服", "些衣服", "一件保暖的衣服", "防水冲锋衣"],
    )
    def test_modifier_glued_variants_all_expand(self, glued: str) -> None:
        """反复发病的措辞形状一次收口:任意修饰/量化语黏在族名词上,
        族词素都必须仍然展开(「解决过好几次」的 whack-a-mole 根治)。"""
        from engine_py.tools_registry.mall_domain import MallDomainService

        expanded = MallDomainService._expand_stem_aliases([glued])
        assert any(stem in expanded for stem in _CLOTHING_STEMS), f"{glued!r} 族词素缺席:{expanded}"

    def test_incident_sentence_terms_include_clothing_stems(self) -> None:
        """实弹原句检索词元面:展开后必须含衣族词素(轮转按原词元分脚,
        「一些衣服」脚靠词素接住衣族)。"""
        from engine_py.tools_registry.mall_domain import MallDomainService

        terms = MallDomainService.search_terms("天气冷了，要外出游玩，推荐一些衣服和装备")
        assert "装备" in terms, f"装备词元缺席:{terms}"
        assert any(stem in terms for stem in _CLOTHING_STEMS), f"衣族词素缺席:{terms}"


class TestIncidentSentenceEndToEnd:
    def test_clothes_and_equipment_request_keeps_both_families(self, pg_factory) -> None:
        """实弹原句端到端:密封货架 × 真实检索链 × 技能,推荐必须两族在场,
        单族凭品类列子串独吞 limit 即实弹症状(0 衣服 + 3 露营装备)。"""
        async def scenario():
            handle = await _setup_shelf(pg_factory)
            try:
                from engine_py.skills.contract import SkillContext
                from engine_py.skills.guide_skills import ShoppingGuideSkill

                res = await ShoppingGuideSkill().execute(
                    SkillContext(
                        input="天气冷了，要外出游玩，推荐一些衣服和装备",
                        thread_id=None,
                        tenant_id="ecommerce",
                    )
                )
                cards = res.cards or []
                return [p["name"] for p in ((cards[0]["data"]["products"] if cards else []) or [])]
            finally:
                await _teardown_shelf(*handle)

        names = asyncio.run(scenario())
        assert names, "端到端推荐不得为空"
        assert any(_is_clothing(n) for n in names), f"衣族缺席(实弹症状):{names}"
        assert len(names) < len(_EQUIPMENT_SPUS) + 1 or any(
            n for n in names if not _is_clothing(n)
        ), f"装备族缺席:{names}"

    def test_retrieval_seam_interleaves_both_families(self, pg_factory) -> None:
        """检索缝单点:多词元轮转必须把「一些衣服」脚(词素展开后)与
        「装备」脚交错合并 —— 红色时正是装备族独吞 limit 的实弹形状。"""
        async def scenario():
            handle = await _setup_shelf(pg_factory)
            try:
                from engine_py.tools_registry.mall_domain import MallDomainService

                res = await MallDomainService.search_products(
                    {"query": "推荐一些衣服和装备", "limit": 3, "businessId": "ecommerce"}
                )
                return [p["name"] for p in (res.get("products") or [])]
            finally:
                await _teardown_shelf(*handle)

        names = asyncio.run(scenario())
        assert names, "货架两族都有货,严禁诚实空"
        assert any(_is_clothing(n) for n in names), f"衣族缺席(实弹症状):{names}"
        camping = sum(1 for n in names if "露营" in n or "帐篷" in n or "睡袋" in n or "咖啡" in n)
        assert camping < 3, f"露营装备族独吞 limit(实弹症状):{names}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
