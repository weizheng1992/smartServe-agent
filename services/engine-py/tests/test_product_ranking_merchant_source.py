"""回归:商品排行换商户库真源(ADR-0002 Q3/Q4,spec .scratch/aftersale-evidence-real-sales)。

症状根源:queryProductRanking 查 engine 本地 5 行演示表且按 manager_id 过滤
(种子无 manager_id)→ 恒诚实空 items=0;「热销/排行」永远空手而归。

契约(ADR-0002):
- 数据源 = 商户真订单明细:merchant_order_items × merchant_orders,
  **排除 REFUNDED/CANCELLED**——退款单不产生真实成交;
- 在售过滤 status='ON_SALE'(下架款不进榜),展示价 = MIN(sku.price),
  库存 = SUM(sku.stock)(与网关/检索链同源);
- gmv/volume 只收真实卖出 ≥1 件的 SPU(零销量热销榜 = 误导);
- **gross_profit / margin_rate 指标整体移除**:商户库无成本价列,算不了就
  不提供——被移除指标诚实报错,严禁静默回退;
- manager_id / businessId 过滤摘除(单商户现实,全租户统一路由先例);
- 条目无 costPrice/grossProfit/marginRate(前端 2.6.12 起可选渲染,零改动)。
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from engine_py.tools_registry.order_domain import OrderDomainService

# 行内最小 DDL(镜像 merchant_db.py 形态,asyncpg 每块一条)
_DDL = [
    """
    CREATE TABLE IF NOT EXISTS merchant_spus (
      id UUID PRIMARY KEY, spu_code TEXT NOT NULL UNIQUE, title TEXT NOT NULL,
      category TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'ON_SALE'
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS merchant_skus (
      id UUID PRIMARY KEY, spu_id UUID NOT NULL REFERENCES merchant_spus(id),
      sku_code TEXT NOT NULL UNIQUE, price NUMERIC(10,2) NOT NULL, stock INTEGER NOT NULL DEFAULT 0
    )
    """,
    # merchant_orders 形状必须与 test_double_refund_replay.py 一致(order_id
    # 主键、无 id 列)——共享密封容器,IF NOT EXISTS 不会纠偏异形表。
    """
    CREATE TABLE IF NOT EXISTS merchant_orders (
      order_id TEXT PRIMARY KEY, customer_id TEXT,
      status TEXT NOT NULL DEFAULT 'PAID', total_amount NUMERIC(10,2)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS merchant_order_items (
      id UUID PRIMARY KEY, order_id TEXT NOT NULL,
      spu_id TEXT, sku_code TEXT, title TEXT, quantity INTEGER NOT NULL DEFAULT 1, price NUMERIC(10,2)
    )
    """,
]

# (code, title, category, status, price, stock, [(order_id, order_status, qty)])
_SEED = [
    # A:2+1 件真实成交 + 4 件退款(必须被排除)→ 净 3 件 / GMV 3×829=2487
    # 双 SKU:库存 10+7=17 且严禁 JOIN 扇出(2026-09-12 实弹抓出:多 SKU SPU
    # 的明细行被 SKU 行数放大,5 件卖成 30 件)
    ("SPU-A", "极光 高山徒步轻量化背包 38L", "背包收纳", "ON_SALE", 829.0, 10,
     [("O1", "PAID", 2), ("O2", "SHIPPED", 1), ("O3", "REFUNDED", 4)]),
    ("SPU-B", "极光 冷山双人隧道帐篷", "露营装备", "ON_SALE", 1299.0, 3,
     [("O1", "PAID", 1)]),
    ("SPU-C", "极光 零销量旗舰硬壳冲锋衣", "户外机能", "ON_SALE", 999.0, 1, []),
    # D:有销量但已下架 → 不进榜
    ("SPU-D", "极光 下架联名背包", "背包收纳", "OFF_SALE", 1999.0, 2,
     [("O2", "SHIPPED", 9)]),
]


@pytest.fixture()
def merchant_pg(pg_factory):
    """密封容器内铺商户四表 + reader 引擎指向容器(带恢复/清场,严禁泄漏
    到后续测试——共享容器里 TRUNCATE 被 FK 卡死 / patch 泄漏都会炸别人)。"""
    from engine_py.tools_registry import order_domain

    engine = pg_factory.kw["bind"]
    url = engine.url.render_as_string(hide_password=False)
    original_reader = order_domain._merchant_reader_engine

    async def _seed():
        merchant_engine = create_async_engine(url, poolclass=NullPool)
        async with merchant_engine.begin() as conn:
            for ddl in _DDL:
                await conn.execute(text(ddl))
            await conn.execute(text("TRUNCATE merchant_order_items, merchant_orders, merchant_skus, merchant_spus"))
            # ① 目录:SPU + SKU(SKU-2 仅 SPU-A,钉双 SKU 无扇出)
            for code, title, category, status, price, stock, sales in _SEED:
                spu_id = uuid.uuid5(uuid.NAMESPACE_URL, code)
                await conn.execute(
                    text("INSERT INTO merchant_spus (id, spu_code, title, category, status) "
                         "VALUES (:id, :code, :title, :cat, :status)").bindparams(
                        id=spu_id, code=code, title=title, cat=category, status=status)
                )
                await conn.execute(
                    text("INSERT INTO merchant_skus (id, spu_id, sku_code, price, stock) "
                         "VALUES (:id, :spu, :code, :price, :stock)").bindparams(
                        id=uuid.uuid5(uuid.NAMESPACE_URL, code + "-SKU"), spu=spu_id,
                        code=code + "-SKU-1", price=price, stock=stock)
                )
                if code == "SPU-A":
                    await conn.execute(
                        text("INSERT INTO merchant_skus (id, spu_id, sku_code, price, stock) "
                             "VALUES (:id, :spu, :code, :price, :stock)").bindparams(
                            id=uuid.uuid5(uuid.NAMESPACE_URL, code + "-SKU-2"), spu=spu_id,
                            code=code + "-SKU-2", price=price, stock=7)
                    )
            # ② 订单 + 明细(单遍;价格取各 SPU 真值)
            item_prices = {"SPU-A": 829.0, "SPU-B": 1299.0, "SPU-C": 999.0, "SPU-D": 1999.0}
            seen_orders: set[str] = set()
            for code, *_, sales in _SEED:
                for oid, ostatus, qty in sales:
                    if oid not in seen_orders:
                        seen_orders.add(oid)
                        await conn.execute(
                            text("INSERT INTO merchant_orders (order_id, customer_id, status, total_amount) "
                                 "VALUES (:oid, :cust, :st, :amt)").bindparams(
                                oid=oid, cust="CUST-8801", st=ostatus, amt=0)
                        )
                    await conn.execute(
                        text("INSERT INTO merchant_order_items (id, order_id, spu_id, sku_code, title, quantity, price) "
                             "VALUES (:id, :oid, :spu, :sku, :title, :qty, :price)").bindparams(
                            id=uuid.uuid4(), oid=oid, spu=code, sku=code + "-SKU-1",
                            title=f"{code} 商品", qty=qty, price=item_prices[code])
                    )
        await merchant_engine.dispose()

    asyncio.run(_seed())

    merchant_engine = create_async_engine(url, poolclass=NullPool)
    order_domain._merchant_reader_engine = lambda: merchant_engine
    yield merchant_engine
    order_domain._merchant_reader_engine = original_reader

    async def _cleanup():
        async with merchant_engine.begin() as conn:
            await conn.execute(text(
                "TRUNCATE merchant_order_items, merchant_orders, merchant_skus, merchant_spus"
            ))
        await merchant_engine.dispose()

    asyncio.run(_cleanup())


def test_gmv_excludes_refunded_and_sums(merchant_pg) -> None:
    result = asyncio.run(OrderDomainService.query_product_ranking({"rankingMetric": "gmv", "limit": 10}))

    assert result["success"] is True
    assert result["metricLabel"] == "总销售额 (GMV)"
    items = result["products"]
    assert [i["productId"] for i in items[:2]] == [
        _spu_id("SPU-A"), _spu_id("SPU-B"),
    ], "退款的 4 件必须被排除:SPU-A 净 3 件居首,零销量/下架款不进榜"
    a = items[0]
    assert a["totalVolume"] == 3, "SPU-A 净销量 = 2+1-4(退款排除)"
    assert a["totalGmv"] == pytest.approx(3 * 829.0)
    assert a["totalGmv"] == pytest.approx(a["metricScore"])
    assert items[1]["totalGmv"] == pytest.approx(1299.0)


def _spu_id(code: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, code))


def test_volume_metric_ranks_by_units(merchant_pg) -> None:
    result = asyncio.run(OrderDomainService.query_product_ranking({"rankingMetric": "volume", "limit": 10}))

    assert result["metricUnit"] == "件"
    assert [i["totalVolume"] for i in result["products"]] == [3, 1], "SPU-A 3 件 > SPU-B 1 件"


def test_stock_risk_uses_real_stock_ascending(merchant_pg) -> None:
    result = asyncio.run(OrderDomainService.query_product_ranking({"rankingMetric": "stock_risk", "limit": 10}))

    stocks = [i["stock"] for i in result["products"]]
    assert stocks == sorted(stocks), "滞销风险按真实在库升序"
    assert _spu_id("SPU-C") in [i["productId"] for i in result["products"]], "零销量款也参与库存风险盘点"


def test_multi_sku_spu_no_join_fanout(merchant_pg) -> None:
    """双 SKU SPU 的明细/库存严禁被 SKU 行数放大(2026-09-12 实弹实伤)。"""
    result = asyncio.run(OrderDomainService.query_product_ranking({"rankingMetric": "volume", "limit": 10}))

    a = next(i for i in result["products"] if i["productId"] == _spu_id("SPU-A"))
    assert a["totalVolume"] == 3, "双 SKU SPU 净销量必须仍是 3(2+1-4退款),不得被放大"
    b = next(i for i in result["products"] if i["productId"] == _spu_id("SPU-B"))
    assert b["totalVolume"] == 1

    gmv_result = asyncio.run(OrderDomainService.query_product_ranking({"rankingMetric": "gmv", "limit": 10}))
    a_gmv = next(i for i in gmv_result["products"] if i["productId"] == _spu_id("SPU-A"))
    assert a_gmv["totalGmv"] == pytest.approx(3 * 829.0), "GMV 同样不得扇出放大"

    risk = asyncio.run(OrderDomainService.query_product_ranking({"rankingMetric": "stock_risk", "limit": 10}))
    a_stock = next(i for i in risk["products"] if i["productId"] == _spu_id("SPU-A"))
    assert a_stock["stock"] == 17, "库存 = SUM(sku.stock)(10+7),不得被明细行放大"


def test_items_have_no_cost_fields(merchant_pg) -> None:
    """商户库无成本价 → 条目严禁出现毛利字段(前端可选渲染,缺省降级)。"""
    result = asyncio.run(OrderDomainService.query_product_ranking({"rankingMetric": "gmv", "limit": 10}))

    for item in result["products"]:
        assert "costPrice" not in item
        assert "grossProfit" not in item
        assert "marginRate" not in item


def test_removed_metrics_error_honestly(merchant_pg) -> None:
    """gross_profit/margin_rate 已移除:诚实报错,严禁静默回退 gmv 假装成功。"""
    for metric in ("gross_profit", "margin_rate"):
        result = asyncio.run(OrderDomainService.query_product_ranking({"rankingMetric": metric}))
        assert "error" in result, f"{metric} 必须诚实报错"
        assert "products" not in result


def test_unknown_metric_falls_back_to_gmv(merchant_pg) -> None:
    """无意义输入(LLM 噪声)回退默认口径 gmv,不炸。"""
    result = asyncio.run(OrderDomainService.query_product_ranking({"rankingMetric": "随便说说", "limit": 5}))
    assert result["success"] is True
    assert result["rankingMetric"] == "gmv"


def test_top_n_limit_parsed(merchant_pg) -> None:
    result = asyncio.run(OrderDomainService.query_product_ranking({"query": "按销量 top 1 查询商品"}))
    assert len(result["products"]) == 1
    assert result["products"][0]["totalVolume"] == 3
