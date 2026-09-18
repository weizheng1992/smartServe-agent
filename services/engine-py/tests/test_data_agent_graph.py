"""data agent 轻图全链路(graph.ask;阶段④;L3 兜底前的编排面)。

不依赖 DB 的编排分支:clarify 反问透传 / 越权指标拒绝(角色闭集)/
unsupported 诚实 / PageContext 选中实体进 intent / 响应形状。
DB 执行分支由 golden/契约套件覆盖,此处 monkeypatch execute_async 桩测编排。
"""

from __future__ import annotations

import asyncio

import pytest

from engine_py.analytics import graph
from engine_py.analytics.engine import QueryResult


@pytest.fixture()
def stub_execute(monkeypatch):
    """桩掉执行层,回可断言的 QueryResult;捕获传入的 intent。"""
    captured: dict = {}

    async def _fake(self, compiled, session_ctx=None):
        captured["sql"] = compiled.sql
        captured["params"] = compiled.params
        return QueryResult(
            rows=[{"productId": "SPU-A", "metricScore": 1.0}],
            metric=compiled.metric, unit=compiled.unit, caliber="测试口径",
        )

    monkeypatch.setattr(graph.MetricQueryEngine, "execute_async", _fake)
    return captured


class TestGraphAsk:
    def test_unsupported_honest(self):
        out = asyncio.run(graph.ask("今天心情如何", {"business_id": "aurora", "role": "finance_owner"}))
        assert out["type"] == "unsupported" and "暂不支持" in out["message"]

    def test_clarify_passthrough(self):
        out = asyncio.run(graph.ask("卖得最好的商品", {"business_id": "aurora", "role": "finance_owner"}))
        assert out["type"] == "clarify" and len(out["options"]) >= 2

    def test_result_produces_table_card(self, stub_execute):
        out = asyncio.run(graph.ask("销售额最高的商品", {"business_id": "aurora", "role": "finance_owner"}))
        assert out["type"] == "result"
        card = out["cards"][0]
        assert card["type"] == "table" and card["caliber"] == "测试口径"
        assert card["rows"][0]["productId"] == "SPU-A"

    def test_honest_empty_card(self, stub_execute, monkeypatch):
        async def _empty(self, compiled, session_ctx=None):
            return QueryResult(rows=[], metric=compiled.metric, unit=compiled.unit, caliber="测试口径")

        monkeypatch.setattr(graph.MetricQueryEngine, "execute_async", _empty)
        out = asyncio.run(graph.ask("销售额最高的商品", {"business_id": "aurora", "role": "finance_owner"}))
        assert out["cards"][0]["type"] == "text" and "诚实空" in out["cards"][0]["text"]

    def test_role_blocked_metric(self, stub_execute, monkeypatch):
        """sales_viewer 问毛利 → 越权兜底拒绝(13-D4;反问选项集过滤之外的第二道)。

        0013 起指标闭集经 rbac 动态派生(DB);本套件保持无 DB,桩掉派生层
        返回空集(未持任何 metric: 权限点 → 回落内置闭集路径不在此覆盖,
        gateway 契约测试有真实 DB 的对应用例)。"""
        async def _no_metric_perms(role):
            return []

        monkeypatch.setattr("engine_py.analytics.rbac.allowed_metrics_for_role", _no_metric_perms)
        out = asyncio.run(graph.ask("毛利最高的商品", {"business_id": "aurora", "role": "sales_viewer"}))
        assert out["type"] == "unsupported" and "无权" in out["message"]

    def test_page_context_selection_flows_into_params(self, stub_execute):
        """PageContext(19-D3):选中实体进编译参数(IN 绑定),不进 SQL 文本。"""
        out = asyncio.run(graph.ask(
            "销售额排行", {"business_id": "aurora", "role": "finance_owner"},
            {"route": "/products", "selection": ["SPU-A", "SPU-B"]},
        ))
        assert out["type"] == "result"
        assert "entities" in stub_execute["params"]
        assert stub_execute["params"]["entities"] == ["SPU-A", "SPU-B"]
        assert ":entities" in stub_execute["sql"]

    def test_execution_error_reported_not_fabricated(self, monkeypatch):
        async def _boom(self, compiled, session_ctx=None):
            raise RuntimeError("db down")

        monkeypatch.setattr(graph.MetricQueryEngine, "execute_async", _boom)
        out = asyncio.run(graph.ask("销售额最高的商品", {"business_id": "aurora", "role": "finance_owner"}))
        assert out["type"] == "error" and "如实" in out["message"]
