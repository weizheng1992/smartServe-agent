"""实弹冒烟固化(原手动脚本进 CI;18 号评测面的常驻回归面)。

八句真实口语逐一走 resolve→compile 断言关键形状;六胶囊契约在
test_new_metric_families.TestCapsuleContract。二者合起来 =「界面上与
口语中出现的每个问题都有确定性答案或诚实拒绝」。
"""

from __future__ import annotations

import pytest

from engine_py.analytics.engine import MetricQueryEngine, UnsupportedQuery

SMOKE_CASES = [
    ("本月销量 Top10", "volume", "DESC"),
    ("卖得最差的商品", "gmv", "ASC"),
    ("差评最多的 SKU", "review_bad", "DESC"),
    ("近 30 天退款率", "refund_rate", "DESC"),
    ("上个月 GMV 最高的商品", "gmv", "DESC"),
    ("压货最严重的商品", "stock_risk", "DESC"),
    ("销售额最高的商品 Top 20", "gmv", "DESC"),
]


@pytest.fixture(scope="module")
def engine():
    return MetricQueryEngine(session_ctx={"business_id": "aurora", "role": "finance_owner"})


@pytest.mark.parametrize("question,metric,direction", SMOKE_CASES)
def test_smoke_chain(engine, question, metric, direction):
    intent = engine.resolve(question)
    assert intent.metric == metric and intent.direction == direction
    compiled = engine.compile(intent)
    assert ":lim" in compiled.sql or intent.metric in ("review_bad", "refund_rate", "session_volume", "ai_resolution_rate", "after_sale_overview")


def test_smoke_honest_reject(engine):
    with pytest.raises(UnsupportedQuery):
        engine.resolve("今天心情如何")
