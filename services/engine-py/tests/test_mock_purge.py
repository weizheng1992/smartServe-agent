"""mock 清零回归(2026-09-12,real-data-only/01)—— 欺骗性兜底拆除钉死。

事故面(全链路实测电池撞出):①SKU 查询查无/异常兜底 AJ1 假目录;②地址簿
兜底「张先生」假地址;③地址保存假成功 addr_mock_;④购物车摘要 `[] or 演示车`
falsy 陷阱(清空→查看必现幻影 AJ1);⑤加购无价兜底 899.0;⑥RAG PG 失败降级
假切片假相似度;⑦SKU 查询没接商户真货架(真店问规格答「没有参数」)。
原则:库可达但查无 → 诚实空;写入失败 → 真实失败;严禁任何硬编码目录/价格/
地址/切片顶替真实态。
"""

from __future__ import annotations

import asyncio
import json
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

# ------------------------------------------------- 密封商户货架(带 SKU 规格列)

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

# 会话级共享容器里,先跑的套件可能已用旧 DDL(无规格列)建过 merchant_skus:
# 三列 IF NOT EXISTS 自愈,本套件对表形态的假设不依赖文件名字典序。
_MERCHANT_SKUS_COLUMN_PATCHES = [
    "ALTER TABLE merchant_skus ADD COLUMN IF NOT EXISTS sku_title TEXT",
    "ALTER TABLE merchant_skus ADD COLUMN IF NOT EXISTS spec_attributes JSONB DEFAULT '{}'::jsonb",
    "ALTER TABLE merchant_skus ADD COLUMN IF NOT EXISTS image_url TEXT",
]

# (spu_code, title, category, status, [(sku_code, price, stock, spec_attrs)])
_SEED = [
    (
        "SPU-P-BAG",
        "极光 城市通勤双肩包",
        "背包收纳",
        "ON_SALE",
        [
            ("SPU-P-BAG-SKU-M", 499.0, 30, {"color": "曜石黑", "size": "15寸"}),
            ("SPU-P-BAG-SKU-L", 549.0, 12, {"color": "雾岩灰", "size": "17寸"}),
        ],
    ),
    ("SPU-P-OFF", "极光 下架款双肩包", "背包收纳", "OFF_SALE", [("SPU-P-OFF-SKU-0", 199.0, 3, {})]),
]


async def _setup_shelf(pg_factory):
    from engine_py.tools_registry import order_domain

    engine = pg_factory.kw["bind"]
    url = engine.url.render_as_string(hide_password=False)
    merchant_engine = create_async_engine(url, poolclass=NullPool)

    async with merchant_engine.begin() as conn:
        await conn.execute(text(_MERCHANT_SPUS_DDL))
        await conn.execute(text(_MERCHANT_SKUS_DDL))
        for patch in _MERCHANT_SKUS_COLUMN_PATCHES:
            await conn.execute(text(patch))
        await conn.execute(text("TRUNCATE merchant_skus, merchant_spus"))
        for spu_code, title, category, status, skus in _SEED:
            spu_id = uuid.uuid5(uuid.NAMESPACE_URL, spu_code)
            await conn.execute(
                text(
                    "INSERT INTO merchant_spus (id, spu_code, title, category, main_image, status) "
                    "VALUES (:id, :code, :title, :cat, :img, :status)"
                ).bindparams(
                    id=spu_id,
                    code=spu_code,
                    title=title,
                    cat=category,
                    img=f"https://img.test/{spu_code}.png",
                    status=status,
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
                        stitle=f"{title} 标准款",
                        attrs=json.dumps(attrs, ensure_ascii=False),
                        price=price,
                        stock=stock,
                    )
                )

    original_reader = order_domain._merchant_reader_engine
    order_domain._merchant_reader_engine = lambda: merchant_engine
    order_domain._merchant_writer_engine = lambda: merchant_engine
    return merchant_engine, original_reader


async def _teardown_shelf(merchant_engine, original_reader) -> None:
    from engine_py.tools_registry import order_domain

    order_domain._merchant_reader_engine = original_reader
    async with merchant_engine.begin() as conn:
        await conn.execute(text("TRUNCATE merchant_skus, merchant_spus"))
    await merchant_engine.dispose()


def _raise_session():
    def _boom():
        raise RuntimeError("db sealed in this test")

    return _boom


# ------------------------------------------------- SKU 查询:商户货架接线 + 诚实空


def test_sku_query_reads_merchant_shelf(pg_factory):
    """真店问规格:productId=spu_code 命中商户 SKU(此前只查 engine 本地表)。"""
    asyncio.run(_sku_merchant_scenario(pg_factory))


async def _sku_merchant_scenario(pg_factory) -> None:
    from engine_py.tools_registry.mall_domain import MallDomainService

    merchant_engine, original_reader = await _setup_shelf(pg_factory)
    try:
        res = await MallDomainService.query_product_skus({"productId": "SPU-P-BAG"})
        assert res["total"] == 2, f"应命中商户双 SKU,实际: {res}"
        codes = {s["skuCode"] for s in res["skus"]}
        assert codes == {"SPU-P-BAG-SKU-M", "SPU-P-BAG-SKU-L"}
        first = res["skus"][0]
        assert first["price"].startswith("¥"), f"价格应与既有路径同形,实际: {first['price']}"
        assert first["inStock"] is True
        assert isinstance(first["specs"], dict)
        # 按名称(非 code)也能解析 —— 导购候选名直达规格
        res2 = await MallDomainService.query_product_skus({"productId": "城市通勤双肩包"})
        assert res2["total"] == 2, f"按名称应解析到 SPU,实际: {res2}"
        # skuCode 精确查询
        res3 = await MallDomainService.query_product_skus({"skuCode": "SPU-P-BAG-SKU-L"})
        assert res3["total"] == 1 and res3["skus"][0]["skuCode"] == "SPU-P-BAG-SKU-L"
    finally:
        await _teardown_shelf(merchant_engine, original_reader)


def test_sku_query_off_sale_and_unknown_honest_empty(pg_factory):
    """OFF_SALE 不出规格;商户可达查无 → 诚实空,严禁 AJ1 假目录顶替。"""
    asyncio.run(_sku_honest_empty_scenario(pg_factory))


async def _sku_honest_empty_scenario(pg_factory) -> None:
    from engine_py.tools_registry.mall_domain import MallDomainService

    merchant_engine, original_reader = await _setup_shelf(pg_factory)
    try:
        res = await MallDomainService.query_product_skus({"productId": "SPU-P-OFF"})
        assert res == {"total": 0, "productId": "SPU-P-OFF", "skus": []}, f"OFF_SALE 应诚实空: {res}"
        res2 = await MallDomainService.query_product_skus({"productId": "SPU-P-NOPE"})
        assert res2["total"] == 0 and res2["skus"] == [], f"查无应诚实空: {res2}"
        assert not any("nike" in str(s).lower() or "jordan" in str(s).lower() for s in res2["skus"])
    finally:
        await _teardown_shelf(merchant_engine, original_reader)


def test_sku_query_all_db_down_honest_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    """商户库与本地库皆不可达 → 诚实空(旧兜底 AJ1 三件套在此回归)。"""
    from engine_py.tools_registry import mall_domain as md
    from engine_py.tools_registry import order_domain

    def _boom_reader():
        raise RuntimeError("merchant down")

    monkeypatch.setattr(order_domain, "_merchant_reader_engine", _boom_reader)
    monkeypatch.setattr(md, "get_session", _raise_session())

    async def _run():
        return await md.MallDomainService.query_product_skus({"productId": "SPU-X"})

    res = asyncio.run(_run())
    assert res["total"] == 0 and res["skus"] == [], f"双库不可达应诚实空: {res}"
    assert "sku_nike" not in json.dumps(res, ensure_ascii=False)


# ------------------------------------------------- 地址簿:无假地址


def test_user_addresses_db_down_honest_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    """地址簿查询库不可达 → total 0 空列表(旧兜底「张先生/中关村」假地址)。"""
    from engine_py.tools_registry import mall_domain as md

    monkeypatch.setattr(md, "get_session", _raise_session())

    async def _run():
        return await md.MallDomainService.get_user_addresses(user_id="u1", business_id="ecommerce")

    res = asyncio.run(_run())
    assert res["total"] == 0 and res["addresses"] == [], f"库不可达应诚实空: {res}"
    assert "张先生" not in json.dumps(res, ensure_ascii=False)
    assert "addr_default_home" not in json.dumps(res, ensure_ascii=False)


# ------------------------------------------------- 地址保存:失败必须真实失败


def test_save_address_db_failure_is_honest(monkeypatch: pytest.MonkeyPatch) -> None:
    """写地址库失败 → success=False 可读错误(旧兜底假成功 + addr_mock_ 假 ID)。"""
    from engine_py.tools_registry import mall_domain as md

    monkeypatch.setattr(md, "get_session", _raise_session())

    async def _run():
        return await md.MallDomainService.save_user_address(
            {
                "receiverName": "测先生",
                "receiverPhone": "13800000000",
                "province": "北京市",
                "city": "北京市",
                "district": "海淀区",
                "detailAddress": "测试路 1 号",
                "userId": "u1",
                "businessId": "ecommerce",
            }
        )

    res = asyncio.run(_run())
    assert res.get("success") is False, f"写库失败必须如实失败: {res}"
    assert "addr_mock" not in json.dumps(res, ensure_ascii=False)
    assert res.get("message"), "应带可读错误信息"


# ------------------------------------------------- 购物车:空车诚实空(拆演示车)


def test_cart_summary_empty_cart_no_demo(monkeypatch: pytest.MonkeyPatch) -> None:
    """无购物车 → 空车;清空后的 [] 不得 falsy 落进 AJ1 演示车。"""
    from engine_py.tools_registry import mall_domain as md

    # 密封:进程缓存清场 + Redis 不可达(_load_cart 降级 None)
    md.MallDomainService._cart_storage.pop("bat_empty_user", None)

    from engine_py import event_bus

    def _boom():
        raise RuntimeError("redis sealed")

    monkeypatch.setattr(event_bus, "get_client", _boom)

    async def _run():
        return await md.MallDomainService.get_cart_summary({"userId": "bat_empty_user"})

    res = asyncio.run(_run())
    cart = res["cart"]
    assert cart["itemCount"] == 0 and cart["items"] == [], f"空车必须诚实空: {res}"
    assert "nike" not in json.dumps(res, ensure_ascii=False).lower()
    assert "jordan" not in json.dumps(res, ensure_ascii=False).lower()


def test_cart_summary_clear_then_view_stays_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    """清空→查看全链:写 [] 再读,必须仍是空车(实测幻影 AJ1 的原始路径)。"""
    from engine_py.tools_registry import mall_domain as md

    md.MallDomainService._cart_storage["bat_clear_user"] = []  # 清空后的真实存储态

    async def _run():
        return await md.MallDomainService.get_cart_summary({"userId": "bat_clear_user"})

    try:
        res = asyncio.run(_run())
        assert res["cart"]["itemCount"] == 0 and res["cart"]["items"] == [], (
            f"清空后查看必须空车(进程缓存 [] 路径): {res}"
        )
    finally:
        md.MallDomainService._cart_storage.pop("bat_clear_user", None)


# ------------------------------------------------- 加购:无价不入车,严禁编造价格


def test_add_to_cart_without_price_refuses(monkeypatch: pytest.MonkeyPatch) -> None:
    """调用方缺价格 → 拒绝入车并如实说明(旧兜底 899.0 假价格)。"""
    from engine_py.tools_registry import mall_domain as md

    md.MallDomainService._cart_storage.pop("bat_noprice_user", None)

    async def _run():
        return await md.MallDomainService.add_to_cart(
            {"skuId": "SKU-X", "title": "某商品", "userId": "bat_noprice_user"}
        )

    res = asyncio.run(_run())
    assert res.get("success") is False, f"缺价必须拒绝入车: {res}"
    assert md.MallDomainService._cart_storage.get("bat_noprice_user") in (None, []), "拒绝时不得写入购物车"
    assert res.get("message"), "应带可读说明"
    md.MallDomainService._cart_storage.pop("bat_noprice_user", None)


# ------------------------------------------------- RAG:PG 失败诚实空(拆假切片)


def test_rag_db_failure_returns_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    """RAG 库查询失败 → 空列表(旧 `_search_local_fake_docs` 假切片假相似度)。"""
    from engine_py.rag import contextual_rag as cr

    async def _boom():
        raise RuntimeError("pg sealed")

    class _FakeSession:
        def __init__(self):
            raise RuntimeError("pg sealed")

    monkeypatch.setattr(cr, "get_session", _raise_session())
    svc = cr.ContextualRAG(business_id="ecommerce")

    class _FakeEmbed:
        async def aembed_query(self, _q):
            return [0.1, 0.2]

    monkeypatch.setattr(cr, "get_embedding_model", lambda: _FakeEmbed())
    res = asyncio.run(svc.search_relevant_docs("退货政策"))
    assert res == [], f"库失败应诚实空: {res}"
