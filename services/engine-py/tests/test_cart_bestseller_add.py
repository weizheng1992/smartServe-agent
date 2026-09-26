"""销量最好加购回归(2026-09-26 用户实报症状③)。

症状:「把销量最好的裤子放到购物车，买2件」→ 店内货架下装裤类明明在售
3 款,机器人却答「未能找到符合您要求的裤子商品」。

根因双缝(全管线探针 + 纯函数缝环实锤):
- 缝A executor fallback 选工具只给工具名,无 schema、无用户原话 → LLM 发明
  schema 外实参(productType/bestSelling),search_products 静默丢弃后退化成
  无过滤全货架检索,垃圾测试品混入候选池;
- 缝B cart resolver `_SEARCH_INTENT_RE` 词表缺「销量最好/畅销/卖得好」族,
  `_ADD_ACTION_STRIP_RE` 不剥「放到」→「销量最好的裤子放到」被当字面商品名
  去货架直配,必然 miss → 诚实措辞包着错误事实(「店内没有」)。

钉死契约:
- 「销量最好的X放购物车」= 检索半,严禁当商品名直配、严禁静默加候选[0]
  (幻影守卫);货架有 X 时必须列出真货并请用户挑款;
- 列出的候选写回 guideContext,后续「把第1件加入购物车」用真货不落空;
- 货架查无时落既有诚实反问,不编造。
"""

from __future__ import annotations

import asyncio
import json
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from engine_py.skills.cart import CartManageSkill
from engine_py.skills.cart import resolver as R
from engine_py.skills.contract import SkillContext

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
  sku_title TEXT,
  spec_attributes JSONB DEFAULT '{}'::jsonb,
  price NUMERIC(10,2) NOT NULL,
  stock INTEGER NOT NULL DEFAULT 0,
  image_url TEXT
)
"""

_COLUMN_PATCHES = [
    "ALTER TABLE merchant_skus ADD COLUMN IF NOT EXISTS sku_title TEXT",
    "ALTER TABLE merchant_skus ADD COLUMN IF NOT EXISTS spec_attributes JSONB DEFAULT '{}'::jsonb",
    "ALTER TABLE merchant_skus ADD COLUMN IF NOT EXISTS image_url TEXT",
]

# 微缩货架镜像实弹:下装裤类 2 款(全零销量)+ 配饰 1 款(干扰项)
_SEED = [
    ("SPU-P-JOGGER", "极光 420g重磅毛圈棉抽绳束脚慢跑裤", "下装裤类", 399.0, 10),
    ("SPU-P-CARGO", "极光 Cordura考杜拉耐磨多袋机能工装裤", "下装裤类", 459.0, 8),
    ("SPU-J-BAND", "极光 速干无缝多功能魔术头巾围脖", "配饰", 59.0, 30),
]


async def _setup_shelf(pg_factory):
    from engine_py.tools_registry import order_domain

    engine = pg_factory.kw["bind"]
    url = engine.url.render_as_string(hide_password=False)
    merchant_engine = create_async_engine(url, poolclass=NullPool)

    async with merchant_engine.begin() as conn:
        await conn.execute(text(_MERCHANT_SPUS_DDL))
        await conn.execute(text(_MERCHANT_SKUS_DDL))
        for patch in _COLUMN_PATCHES:
            await conn.execute(text(patch))
        await conn.execute(text("TRUNCATE merchant_skus, merchant_spus"))
        for spu_code, title, category, price, stock in _SEED:
            spu_id = uuid.uuid5(uuid.NAMESPACE_URL, spu_code)
            await conn.execute(
                text(
                    "INSERT INTO merchant_spus (id, spu_code, title, category, main_image, status) "
                    "VALUES (:id, :code, :title, :cat, :img, 'ON_SALE')"
                ).bindparams(id=spu_id, code=spu_code, title=title, cat=category, img=f"https://img.test/{spu_code}.png")
            )
            await conn.execute(
                text(
                    "INSERT INTO merchant_skus (id, spu_id, sku_code, sku_title, spec_attributes, price, stock) "
                    "VALUES (:id, :sid, :code, :stitle, CAST(:attrs AS jsonb), :price, :stock)"
                ).bindparams(
                    id=uuid.uuid5(uuid.NAMESPACE_URL, f"{spu_code}-SKU"),
                    sid=spu_id,
                    code=f"{spu_code}-SKU",
                    stitle=title,
                    attrs=json.dumps({"颜色": "曜石黑", "尺码": "M"}, ensure_ascii=False),
                    price=price,
                    stock=stock,
                )
            )

    original_reader = order_domain._merchant_reader_engine
    order_domain._merchant_reader_engine = lambda: merchant_engine
    return merchant_engine, original_reader


async def _teardown_shelf(merchant_engine, original_reader) -> None:
    from engine_py.tools_registry import order_domain

    order_domain._merchant_reader_engine = original_reader
    async with merchant_engine.begin() as conn:
        await conn.execute(text("TRUNCATE merchant_skus, merchant_spus"))
    await merchant_engine.dispose()


# 事故形态:候选池被上游 schema 幻觉搜索污染成配饰垃圾(实证用-新增商品)
_JUNK_GUIDE_CONTEXT = {
    "candidateProductIds": ["SPU-JUNK-1", "SPU-JUNK-2"],
    "candidateProducts": [
        {"id": "SPU-JUNK-1", "name": "实证用-新增商品", "price": 9.9},
        {"id": "SPU-JUNK-2", "name": "进程内实证款", "price": 9.9},
    ],
}


def _ctx(user_input: str, guide_context: dict) -> SkillContext:
    return SkillContext(
        input=user_input,
        user_id="CUST-BEST-01",
        tenant_id="aurora",
        guide_context=guide_context,
    )


class TestResolverVocab:
    def test_bestseller_phrase_is_search_intent(self):
        """「销量最好/畅销/卖得好」必须命中检索意图正则 —— 否则被当字面商品名。"""
        for phrase in ("销量最好的裤子", "把畅销的帐篷加入购物车", "卖得好的冲锋衣", "热卖款"):
            assert R._SEARCH_INTENT_RE.search(phrase), f"检索意图正则漏判: {phrase}"

    def test_verb_zhidao_stripped_from_remainder(self):
        """「放到」必须从点名残词中剥除 —— 「冲锋裤放到」当名字查货架必 miss。"""
        assert R.named_query_remainder("把冲锋裤放到购物车") == "冲锋裤"
        assert R.named_query_remainder("把冲锋裤放进购物车") == "冲锋裤"


class TestBestsellerAddBehavior:
    def test_bestseller_pants_lists_real_goods_never_junk_add(self, pg_factory):
        """事故句重放:列真裤子、零入车、垃圾候选不得入车或出现在回复里。"""
        asyncio.run(_bestseller_scenario(pg_factory))

    def test_bestseller_no_hit_falls_to_honest_ask(self, pg_factory):
        """查无此类(货架无帐篷)→ 诚实反问,不编造不误加。"""
        asyncio.run(_no_hit_scenario(pg_factory))


async def _bestseller_scenario(pg_factory) -> None:
    merchant_engine, original_reader = await _setup_shelf(pg_factory)
    try:
        result = (await CartManageSkill().execute(
            _ctx("把销量最好的裤子放到购物车，买2件", _JUNK_GUIDE_CONTEXT)
        )).to_dict()
        assert result["success"] is True
        output = result["output"]
        # 不得谎称店内没有裤子(事故原话形)
        assert "没有在店内找到" not in output, f"事故措辞在场: {output}"
        assert "未能找到" not in output, f"事故措辞在场: {output}"
        # 必须列出货架真裤子(慢跑裤/工装裤任一)
        assert ("慢跑裤" in output) or ("工装裤" in output), f"未列出真裤子: {output}"
        # 垃圾候选严禁入车、严禁出现在回复里
        assert "实证用-新增商品" not in output and "进程内实证款" not in output
        # 请用户挑款的诚实反问形
        assert ("第1件" in output) or ("哪一款" in output) or ("哪款" in output)
        # 零入车:让用户挑款而非静默替他加
        items = await _load_cart("CUST-BEST-01")
        assert items == [], f"挑款反问前严禁静默入车: {items}"
        # 检索真货写回 guideContext —— 后续「把第1件加入购物车」落真货不落空
        guide = (result.get("extra") or {}).get("guideContext") or {}
        cands = guide.get("candidateProducts") or []
        assert cands and any("裤" in str(c.get("name", "")) for c in cands), f"候选未写回真裤子: {cands}"
    finally:
        await _teardown_shelf(merchant_engine, original_reader)


async def _no_hit_scenario(pg_factory) -> None:
    merchant_engine, original_reader = await _setup_shelf(pg_factory)
    try:
        result = (await CartManageSkill().execute(
            _ctx("把销量最好的帐篷放到购物车，买2件", {})
        )).to_dict()
        assert result["success"] is True
        output = result["output"]
        # 查无此类 → 诚实反问/告知,不编造帐篷、不误加干扰品
        assert (await _load_cart("CUST-BEST-01")) == [], f"查无时严禁入车: {await _load_cart('CUST-BEST-01')}"
        assert "魔术头巾" not in output, f"干扰品不得出场: {output}"
    finally:
        await _teardown_shelf(merchant_engine, original_reader)


async def _load_cart(user_id: str) -> list[dict]:
    from engine_py.tools_registry.mall_domain import MallDomainService

    return await MallDomainService._load_cart(user_id) or []


def _shelf_titles() -> list[str]:
    return [title for _, title, _, _, _ in _SEED]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
