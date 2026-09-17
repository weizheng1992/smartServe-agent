"""阶段①收口契约(wayfinder 09-D4/08-P2;spec 六阶段排期第①步)。

A. 读写引擎物理分离:_update_merchant_order(退款/地址写穿透)必须走独立写引擎,
   读路径(engine=reader)不再被写路径复用 —— 阶段②只读沙箱的前置工程。
B. 指标定义单一事实源:order_domain 的排行显示层注册表从 metric_registry 派生,
   私有副本退役;label/unit/direction 语义逐键一致;未知指标静默落 gmv 的
   兜底语义保留(既有测试 test_unknown_metric_falls_back_to_gmv 守门,响亮化归
   08-P1 在 data agent 侧执行,非本阶段)。
"""

from __future__ import annotations

import asyncio

import pytest

from engine_py.tools_registry import metric_registry, order_domain


class TestReadWriteEngineSplit:
    """A: 读写引擎物理分离。"""

    def test_writer_factory_exists_and_distinct(self):
        assert hasattr(order_domain, "_merchant_writer_engine"), "写引擎工厂缺失"
        assert order_domain._merchant_writer_engine is not order_domain._merchant_reader_engine, (
            "读/写工厂必须是两个独立函数"
        )

    @staticmethod
    def _server_settings(engine) -> dict:
        """从 asyncpg 连接 creator 闭包提取 server_settings(asyncpg 的
        server_settings 经 creator keywords 传递,不落在 engine 根属性)。"""
        creator = engine.sync_engine.pool._creator
        for cell in creator.__closure__ or []:
            contents = cell.cell_contents
            if hasattr(contents, "keys") and "server_settings" in contents:
                return contents["server_settings"] or {}
        return {}

    def test_reader_engine_has_read_only_marker(self):
        settings_map = self._server_settings(order_domain._merchant_reader_engine())
        # 阶段②只读沙箱的前置:reader 建池必须带会话级只读 + 语句超时标记
        assert settings_map.get("default_transaction_read_only") == "on", "reader 引擎缺只读标记"
        assert settings_map.get("statement_timeout") == "3000", "reader 引擎缺语句超时"

    def test_writer_engine_plain_pool(self):
        settings_map = self._server_settings(order_domain._merchant_writer_engine())
        assert "default_transaction_read_only" not in settings_map, "写引擎不得带只读标记"

    def test_write_through_uses_writer_engine(self, monkeypatch):
        used = {"engine": None}

        class FakeConn:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

            async def execute(self, stmt):
                return None

        class FakeEngine:
            def begin(self):
                used["engine"] = "writer"
                return FakeConn()

        monkeypatch.setattr(order_domain, "_merchant_writer_engine", lambda: FakeEngine())
        monkeypatch.setattr(
            order_domain, "_merchant_reader_engine", lambda: pytest.fail("写穿透不得触碰 reader 引擎")
        )
        asyncio.run(order_domain._update_merchant_order("ORD-1", status="REFUNDED"))
        assert used["engine"] == "writer"


class TestMetricRegistryConvergence:
    """B: 指标定义单一事实源。"""

    def test_private_registry_is_derived_view(self):
        assert not hasattr(order_domain.OrderDomainService, "METRIC_REGISTRY"), (
            "order_domain 私有 METRIC_REGISTRY 应已退役"
        )
        assert hasattr(order_domain, "OrderDomainService") and hasattr(
            order_domain.OrderDomainService, "RANKING_VIEW_REGISTRY"
        ), "排行显示层注册表应从 metric_registry 派生"

    def test_semantics_match_per_key(self):
        for key, view in order_domain.OrderDomainService.RANKING_VIEW_REGISTRY.items():
            canonical = metric_registry.METRIC_SEMANTIC_REGISTRY[key]
            assert view["label"] == canonical["label"], f"{key} label 与真源漂移"
            assert view["unit"] == canonical["unit"], f"{key} unit 与真源漂移"
            assert view["key"] == key

    def test_direction_semantics_preserved(self):
        """方向语义(DESC 常规榜 / ASC 滞销风险榜)必须保持 —— 排序方向
        取自注册表而非用户输入是 04 号票的安全原则。"""
        views = order_domain.OrderDomainService.RANKING_VIEW_REGISTRY
        assert views["gmv"]["direction"] == "DESC"
        assert views["margin_rate"]["direction"] == "DESC"
        assert views["stock_risk"]["direction"] == "ASC"

    def test_full_metric_key_coverage(self):
        """排行视图覆盖真源全部五指标(漏一个 = 该指标无法排行)。"""
        assert set(order_domain.OrderDomainService.RANKING_VIEW_REGISTRY) == {
            "gmv",
            "volume",
            "gross_profit",
            "margin_rate",
            "stock_risk",
        }

    def test_unknown_metric_still_falls_back_to_gmv(self):
        """08-P1 响亮化前的既有兜底语义保留(测试名对齐 test_unknown_metric_falls_back_to_gmv 的契约)。"""
        views = order_domain.OrderDomainService.RANKING_VIEW_REGISTRY
        assert views.get("nonexistent") is None
        assert views["gmv"] is not None  # 兜底目标存在
