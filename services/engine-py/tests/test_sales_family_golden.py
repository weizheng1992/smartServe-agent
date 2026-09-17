"""销售族 golden SQL 冻结(18-D2:基准 SQL + 种子期望;迁移前后行为不变的证明)。

同一 merchant_pg 密封种子库上:
- 旧路径 OrderDomainService.query_product_ranking(现有行为 = 冻结基准)
- 新路径 MetricQueryEngine resolve→compile→execute(阶段② analytics 骨架)
两路径对同一指标的 rows(商品集合与量值)必须一致 —— 迁移即等价。

复用 test_product_ranking_merchant_source 的 merchant_pg 夹具(种子与清理协议
同源,严禁第二套种子漂移)。
"""

from __future__ import annotations

import asyncio

import pytest

from engine_py.analytics.engine import MetricQueryEngine
from engine_py.tools_registry.order_domain import OrderDomainService

try:  # 常规包导入
    from tests.test_product_ranking_merchant_source import merchant_pg
except ImportError:  # pytest rootdir=services/engine-py 无 tests 包时的平铺回退
    import importlib.util
    from pathlib import Path as _P

    _spec = importlib.util.spec_from_file_location(
        "_ranking_seed", _P(__file__).resolve().parent / "test_product_ranking_merchant_source.py"
    )
    _mod = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_mod)
    merchant_pg = _mod.merchant_pg


@pytest.fixture()
def engine(merchant_pg):
    """容器内执行:merchant_pg 已把 reader 指向密封容器(见其夹具)。"""
    return MetricQueryEngine(session_ctx={"business_id": "aurora", "role": "finance_owner"})


@pytest.mark.parametrize("metric,question", [
    ("gmv", "销售额最高的商品"),
    ("volume", "销量最高的商品"),
    ("gross_profit", "毛利最高的商品"),
    ("margin_rate", "毛利率最高的商品"),
])
def test_new_engine_matches_frozen_baseline(merchant_pg, engine, metric, question) -> None:
    """golden 冻结:新引擎 rows 集合与旧路径逐商品量值一致(gmv/volume/gross_profit/margin_rate)。"""
    baseline = asyncio.run(OrderDomainService.query_product_ranking({"rankingMetric": metric, "limit": 10}))
    intent = engine.resolve(question)
    compiled = engine.compile(intent)
    fresh = asyncio.run(engine.execute_async(compiled))

    assert fresh.rows, "种子库上新引擎不得诚实空(种子含有效成交)"
    base_map = {p["productId"]: p["metricScore"] for p in baseline["products"]}
    fresh_map = {r["productId"]: float(r["metricScore"]) for r in fresh.rows}
    assert set(base_map) == set(fresh_map), f"{metric}: 商品集合与基准不一致"
    for pid, score in base_map.items():
        assert fresh_map[pid] == pytest.approx(score, rel=1e-6), f"{metric}: {pid} 量值漂移"


def test_ranking_direction_semantics_match(merchant_pg, engine) -> None:
    """方向语义:gmv 榜首 = 量值最大;「卖得最差」ASC 榜首 = 量值最小。"""
    best = asyncio.run(OrderDomainService.query_product_ranking({"rankingMetric": "gmv", "limit": 10}))
    intent_best = engine.resolve("销售额最高的商品")
    rows_best = asyncio.run(engine.execute_async(engine.compile(intent_best)))
    intent_worst = engine.resolve("卖得最差的商品")
    rows_worst = asyncio.run(engine.execute_async(engine.compile(intent_worst)))

    assert rows_best.rows[0]["productId"] == best["products"][0]["productId"]
    assert rows_worst.rows[0]["metricScore"] <= min(float(r["metricScore"]) for r in rows_best.rows)


def test_refund_exclusion_caliber_note_present(merchant_pg, engine) -> None:
    """口径注记(呈现层诚实):QueryResult 必带排除退款/取消的口径说明。"""
    intent = engine.resolve("销售额最高的商品")
    result = asyncio.run(engine.execute_async(engine.compile(intent)))
    assert "退款" in result.caliber and "取消" in result.caliber
