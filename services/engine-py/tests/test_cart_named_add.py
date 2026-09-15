"""点名加购直配回归(2026-09-14 用户实报:让 AI 加购「极光三合一冲锋衣
曜石黑 M码」,入车的却是别的商品)。

根因:加购链只有 序数 → 全量 → 模糊 → candidate[0] 静默兜底,**从未实现
按名解析** —— 用户点名的商品被整句忽略后静默替成候选第一款。此前拆除的
是「假商品兜底」(硬编码 Nike),「真商品错替」这半一直都在,同族症状。

钉死契约:
- 点名+规格 → 商户真货架按描述直配到确切 SKU(真 sku_code/真价),候选
  顺序无关;
- 点名但货架配不中/歧义 → 诚实反问列候选,严禁静默替他款;
- 裸动词加购(剥动作词后无实质内容)→ 维持 candidate[0] 既有契约不变。
"""

from __future__ import annotations

import asyncio
import json
import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

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

# 真实货架形态微缩:冲锋衣三规格(曜石黑M/L、冰川白M)+ POLO 两规格(曜石黑M、雾岩灰L)
_SEED = [
    (
        "SPU-N-COAT",
        "极光三合一全天候户外硬壳冲锋衣 (2026款旗舰版)",
        [
            ("SKU-N-COAT-BLACK-M", 1299.0, 8, {"颜色": "曜石黑", "尺码": "M"}),
            ("SKU-N-COAT-BLACK-L", 1299.0, 5, {"颜色": "曜石黑", "尺码": "L"}),
            ("SKU-N-COAT-WHITE-M", 1299.0, 3, {"颜色": "冰川白", "尺码": "M"}),
        ],
    ),
    (
        "SPU-N-POLO",
        "极光 凉感抗菌速干机能POLO衫",
        [
            ("SKU-N-POLO-BLACK-M", 329.0, 20, {"颜色": "曜石黑", "尺码": "M"}),
            ("SKU-N-POLO-GREY-L", 329.0, 15, {"颜色": "雾岩灰", "尺码": "L"}),
        ],
    ),
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
        for spu_code, title, skus in _SEED:
            spu_id = uuid.uuid5(uuid.NAMESPACE_URL, spu_code)
            await conn.execute(
                text(
                    "INSERT INTO merchant_spus (id, spu_code, title, category, main_image, status) "
                    "VALUES (:id, :code, :title, :cat, :img, 'ON_SALE')"
                ).bindparams(
                    id=spu_id, code=spu_code, title=title, cat="户外机能", img=f"https://img.test/{spu_code}.png"
                )
            )
            for sku_code, price, stock, attrs in skus:
                await conn.execute(
                    text(
                        "INSERT INTO merchant_skus (id, spu_id, sku_code, sku_title, spec_attributes, price, stock) "
                        "VALUES (:id, :sid, :code, :stitle, CAST(:attrs AS jsonb), :price, :stock)"
                    ).bindparams(
                        id=uuid.uuid5(uuid.NAMESPACE_URL, sku_code),
                        sid=spu_id,
                        code=sku_code,
                        stitle=f"{title} {attrs.get('颜色', '')}{attrs.get('尺码', '')}",
                        attrs=json.dumps(attrs, ensure_ascii=False),
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


# 候选顺序刻意 POLO 在前:candidate[0] 是「错替」的现行犯
_GUIDE_CONTEXT = {
    "candidateProductIds": ["SPU-N-POLO", "SPU-N-COAT"],
    "candidateProducts": [
        {"id": "SPU-N-POLO", "name": "极光 凉感抗菌速干机能POLO衫", "price": 329.0},
        {"id": "SPU-N-COAT", "name": "极光三合一全天候户外硬壳冲锋衣 (2026款旗舰版)", "price": 1299.0},
    ],
}


def _named_add_context(user_input: str) -> dict:
    return {
        "input": user_input,
        "userId": "CUST-NAMED-01",
        "tenantId": "aurora",
        "slots": {},
        "extra": {"guideContext": _GUIDE_CONTEXT},
    }


def test_named_product_with_spec_lands_exact_sku(pg_factory):
    """点名「冲锋衣 曜石黑 M码」必须入确切 SKU,严禁替成候选第一款 POLO。"""
    asyncio.run(_named_spec_scenario(pg_factory))


async def _named_spec_scenario(pg_factory) -> None:
    from engine_py.skills.cart_manage_skill import CartManageSkill
    from engine_py.tools_registry.mall_domain import MallDomainService

    merchant_engine, original_reader = await _setup_shelf(pg_factory)
    try:
        result = await CartManageSkill().execute(
            _named_add_context("极光三合一冲锋衣 曜石黑 M码 加入购物车")
        )
        assert result["success"] is True
        items = (await MallDomainService._load_cart("CUST-NAMED-01")) or []
        assert [i["skuId"] for i in items] == ["SPU-N-COAT"], (
            f"车行主键必须维持 SPU 粒度契约(skuId=spu_code),实际: {[i['skuId'] for i in items]}"
        )
        # 用户点名的确切规格钉在 skuCode 上(结算 sku_code 直配优先不换规格)
        assert items[0]["skuCode"] == "SKU-N-COAT-BLACK-M"
        assert items[0]["spuId"] == "SPU-N-COAT"
        # 标题是干净 SPU 标题,不得拼接 SKU 标题致信息重复错乱
        assert items[0]["title"] == "极光三合一全天候户外硬壳冲锋衣 (2026款旗舰版)"
        assert items[0]["price"] == 1299.0
        assert "冲锋衣" in result["output"]
    finally:
        await _teardown_shelf(merchant_engine, original_reader)


def test_named_off_shelf_product_asks_not_substitutes(pg_factory):
    """点名货架没有的商品 → 诚实反问列候选,严禁静默替成 candidate[0]。"""
    asyncio.run(_named_off_shelf_scenario(pg_factory))


async def _named_off_shelf_scenario(pg_factory) -> None:
    from engine_py.skills.cart_manage_skill import CartManageSkill
    from engine_py.tools_registry.mall_domain import MallDomainService

    merchant_engine, original_reader = await _setup_shelf(pg_factory)
    try:
        result = await CartManageSkill().execute(_named_add_context("滑雪板 加入购物车"))
        assert result["success"] is True
        assert "哪一款" in result["output"], f"配不中必须反问而非错替,实际: {result['output'][:80]}"
        items = (await MallDomainService._load_cart("CUST-NAMED-01")) or []
        assert items == [], f"配不中严禁入车,实际: {items}"
    finally:
        await _teardown_shelf(merchant_engine, original_reader)


def test_bare_add_still_takes_first_candidate(pg_factory):
    """裸动词加购(剥动作词后无实质内容)维持 candidate[0] 既有契约。"""
    asyncio.run(_bare_add_scenario(pg_factory))


async def _bare_add_scenario(pg_factory) -> None:
    from engine_py.skills.cart_manage_skill import CartManageSkill
    from engine_py.tools_registry.mall_domain import MallDomainService

    merchant_engine, original_reader = await _setup_shelf(pg_factory)
    try:
        result = await CartManageSkill().execute(_named_add_context("加入购物车"))
        assert result["success"] is True
        items = (await MallDomainService._load_cart("CUST-NAMED-01")) or []
        assert [i["skuId"] for i in items] == ["SPU-N-POLO"], (
            f"裸加购维持候选第一款契约,实际: {[i['skuId'] for i in items]}"
        )
    finally:
        await _teardown_shelf(merchant_engine, original_reader)
