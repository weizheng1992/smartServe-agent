"""结果缓存命中路不得预污染 chart ——「折线仅趋势族」仲裁单点保全(2026-09-28 夜审)。

实弹通路:AI_RESULT_CACHE_TTL>0 时,非趋势指标带 chart_hint='line' 的问句
第二次起走缓存命中,此前命中路 `chart=chart_hint or auto_chart` 把
result.chart 预污染成 'line',graph._effective_chart 的仲裁(非趋势不信
line 指令,落「缺省随指标语义」)读到被污染的 result.chart 透传 'line' ——
2026-09-25 折线事故(前端把「品类」文案画成 NaN 网)在缓存开启时复发。
本套钉死:命中路与执行路同公式,chart 只随指标语义,仲裁单点留给
_effective_chart。
"""

from __future__ import annotations

import time
import types

import pytest

from engine_py.analytics.engine import MetricQueryEngine
from engine_py.analytics.graph import _TREND_LINE_METRICS, _effective_chart

pytestmark = pytest.mark.usefixtures("pg_factory")


def _compiled(metric: str) -> types.SimpleNamespace:
    return types.SimpleNamespace(
        sql="SELECT 1", params={}, metric=metric, chart_hint="line", target_db="engine_db",
    )


def _prime_cache(monkeypatch, rows: list[dict]) -> None:
    from engine_py.analytics import result_cache

    async def _fake_get(key: str):
        return {"rows": rows, "ts": time.time()}

    monkeypatch.setattr(result_cache, "get", _fake_get)
    monkeypatch.setattr(result_cache, "set", _fake_set)


async def _fake_set(key: str, payload: dict, ttl: int) -> None:
    return None


@pytest.mark.parametrize("metric", sorted(_TREND_LINE_METRICS))
def test_cache_hit_trend_family_keeps_line(monkeypatch, metric):
    _prime_cache(monkeypatch, rows=[{"d": "2026-09-01", "v": 1.0}, {"d": "2026-09-02", "v": 2.0}])
    monkeypatch.setenv("AI_RESULT_CACHE_TTL", "60")
    engine = MetricQueryEngine(session_ctx={"business_id": "aurora"})
    result = __import__("asyncio").run(engine.execute_async(_compiled(metric)))
    assert result.chart == "line", "趋势指标缓存命中仍应随指标语义出折线"
    intent = types.SimpleNamespace(chart_hint="line", metric=metric)
    assert _effective_chart(intent, result) == "line"


@pytest.mark.parametrize("metric", ["spu_compare", "customer_orders"])
def test_cache_hit_nontrend_ignores_line_hint(monkeypatch, metric):
    """非趋势指标:命中路 chart 必须为 None(不预污染),仲裁落 None 而非透传 line。"""
    _prime_cache(monkeypatch, rows=[{"spu": "A", "qty": 3}, {"spu": "B", "qty": 1}])
    monkeypatch.setenv("AI_RESULT_CACHE_TTL", "60")
    engine = MetricQueryEngine(session_ctx={"business_id": "aurora"})
    result = __import__("asyncio").run(engine.execute_async(_compiled(metric)))
    assert result.chart is None, "命中路不得吃 chart_hint 预污染 result.chart"
    intent = types.SimpleNamespace(chart_hint="line", metric=metric)
    assert _effective_chart(intent, result) is None, (
        "仲裁单点读到干净 result.chart 后,非趋势指标的 line 指令必须落「缺省随指标语义」"
    )


def test_cache_hit_flags_from_cache(monkeypatch):
    """缓存命中是机器语义,走 QueryResult.from_cache 字段(2026-10-03);
    trace 归类不得再解析口径注记的「缓存读」词面 —— 文案与行为解耦。"""
    _prime_cache(monkeypatch, rows=[{"v": 1.0}])
    monkeypatch.setenv("AI_RESULT_CACHE_TTL", "60")
    engine = MetricQueryEngine(session_ctx={"business_id": "aurora"})
    result = __import__("asyncio").run(engine.execute_async(_compiled("gmv")))
    assert result.from_cache is True
    assert "缓存读" in result.caliber  # 口径注记原样保留(诚实呈现),仅不再被解析
