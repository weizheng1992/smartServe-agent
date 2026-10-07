"""语义编译器契约(ADR-0010 分层信任架构;spec .scratch/data-agent-tiered-trust)。

T0-a 差分对拍:销售族 5 指标在「声明编译」与 legacy 模板两条路径下,
同意图产物必须 **SQL 逐字一致 + params 一致** —— 差分绿了才准切 engine.compile。
时间窗下界以 monkeypatch 冻结,杜绝月界翻转竞态。
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from engine_py.analytics.engine import MetricQueryEngine, StructuredQueryIntent
from engine_py.analytics.semantic_compiler import can_compile, compile_metric
from engine_py.analytics.tools_registry_bridge import semantic_model
from engine_py.tools_registry.metric_registry import METRIC_SEMANTIC_REGISTRY

_FIXED_NOW = datetime(2026, 10, 7, 12, 0, 0, tzinfo=UTC).replace(tzinfo=None)  # naive UTC(与 window_start 同源)


@pytest.fixture()
def engine() -> MetricQueryEngine:
    return MetricQueryEngine(session_ctx={"business_id": "aurora", "role": "finance_owner"})


@pytest.fixture()
def frozen_window(monkeypatch):
    """两侧 window_start 同源冻结:legacy 路模块内全局查找、编译器惰性 import
    都落在 engine 模块属性上,单点 patch 双路生效。"""
    monkeypatch.setattr(
        "engine_py.analytics.engine.window_start", lambda window, now=None: _FIXED_NOW
    )


class TestSemanticModel:
    def test_model_loads_with_expected_shape(self):
        model = semantic_model()
        assert model["version"] == 1
        assert len(model["entities"]) == 12
        assert len(model["joins"]) == 9
        assert model["dimensions"]["category"]["values"][0] == "户外机能"

    def test_category_enum_covers_l0_regex_vocabulary(self):
        """模型枚举即品类词表真源(正则退役的前置断言)。"""
        values = set(semantic_model()["dimensions"]["category"]["values"])
        assert values == {
            "户外机能", "潮流T恤", "下装裤类", "潮流鞋靴", "背包收纳",
            "露营装备", "衬衫", "配饰", "运动配件",
        }

    def test_bespoke_debt_metrics_all_in_registry(self):
        for debt in semantic_model()["bespoke_debt"]:
            assert debt["metric"] in METRIC_SEMANTIC_REGISTRY
            assert debt["reason"] and debt["plan"]

    def test_model_entities_subset_of_schema_card(self):
        from engine_py.analytics.schema_cards import compile_safe_schema_card

        card_tables = set(compile_safe_schema_card()["tables"])
        assert set(semantic_model()["entities"]) <= card_tables


class TestSalesFamilyParity:
    """差分对拍:声明编译 vs legacy 模板,同意图产物逐字一致(ADR-0010 迁移纪律)。"""

    SALES_METRICS = ("gmv", "volume", "gross_profit", "margin_rate", "stock_risk")

    INTENT_VARIANTS = (
        {},
        {"time_window": {"kind": "last_7d"}},
        {"time_window": {"kind": "last_months", "n": 3}},
        {"category": "露营装备"},
        {"entity_slot": {"spu": ["SPU-PARITY-1", "SPU-PARITY-2"]}},
        {"direction": "ASC", "time_window": {"kind": "last_month"}, "category": "衬衫"},
        {"limit": 13, "time_window": {"kind": "last_30d"}, "category": "潮流鞋靴",
         "entity_slot": {"spu": ["SPU-PARITY-3"]}},
    )

    def test_sales_family_registered_for_compiler(self):
        for metric in self.SALES_METRICS:
            assert can_compile(metric), f"{metric} 缺 compile 块"

    def test_compiled_out_metrics_have_no_compile_block(self):
        """债务族(bespoke_debt)与场景包不入编译器;真源 = 模型债务清单。"""
        debt_metrics = {d["metric"] for d in semantic_model()["bespoke_debt"]}
        assert "gmv_mom" in debt_metrics and "zero_sales" in debt_metrics
        assert not can_compile("gmv_mom") and not can_compile("zero_sales")

    @pytest.mark.parametrize("metric", SALES_METRICS)
    @pytest.mark.parametrize("variant", INTENT_VARIANTS)
    def test_parity_with_legacy_template(self, engine, frozen_window, metric, variant):
        intent = StructuredQueryIntent(metric=metric, **variant)
        legacy = engine.compile(intent)
        compiled = compile_metric(intent, "aurora")
        assert compiled.sql == legacy.sql, (
            f"{metric} {variant}: 声明编译产物与 legacy 模板不一致\n"
            f"--- compiler ---\n{compiled.sql}\n--- legacy ---\n{legacy.sql}"
        )
        assert compiled.params == legacy.params
        assert compiled.unit == legacy.unit
        assert compiled.target_db == legacy.target_db == "merchant_db"

    def test_unknown_shape_is_loud(self, engine):
        intent = StructuredQueryIntent(metric="gmv")
        blocks = dict(semantic_model())  # 不改真模型;直接构造坏块走编译器内部分派
        from engine_py.analytics import semantic_compiler

        original = semantic_compiler._compile_blocks
        monkey_blocks = lambda: {"gmv": {"shape": "no_such_shape"}}
        semantic_compiler._compile_blocks = monkey_blocks
        try:
            with pytest.raises(Exception, match="未知编译形状"):
                compile_metric(intent, "aurora")
        finally:
            semantic_compiler._compile_blocks = original
        assert blocks["version"] == 1  # 模型未被触碰


class TestSweptFamilyShapes:
    """迁移后形状契约(删 legacy 臂后长青):口径过滤/租户谓词/行数兜底逐族钉死。"""

    @pytest.mark.parametrize(
        "metric,needle",
        (
            ("review_bad", "r.rating <= 2"),
            ("review_good", "r.rating >= 4"),
            ("refund_rate", "o.status <> 'CANCELLED'"),
            ("category_gmv_top", "o.status NOT IN ('REFUNDED', 'CANCELLED')"),
            ("category_gmv_top", "s.status = 'ON_SALE'"),
            ("customer_spend_top", "NOT IN ('REFUNDED', 'CANCELLED')"),
            ("stock_value", "k.stock * k.price"),
            ("promo_gmv_total", "GROUP BY p.name, p.id"),
            ("promo_orders", "COUNT(DISTINCT rd.order_id)"),
        ),
    )
    def test_caliber_filter_declared(self, engine, metric, needle):
        assert needle in engine.compile(StructuredQueryIntent(metric=metric)).sql

    @pytest.mark.parametrize("metric", ("session_volume", "after_sale_overview", "ai_resolution_rate"))
    def test_engine_db_carries_tenant_param(self, engine, metric):
        compiled = engine.compile(StructuredQueryIntent(metric=metric))
        assert compiled.target_db == "engine_db"
        assert compiled.params["business_id"] == "aurora"
        assert "business_id" in compiled.sql

    @pytest.mark.parametrize("metric", ("aov", "order_count"))
    def test_single_row_literal_limit(self, engine, metric):
        compiled = engine.compile(StructuredQueryIntent(metric=metric))
        assert "LIMIT 1" in compiled.sql
        assert "lim" not in compiled.params

    def test_trend_day_and_month_granularity(self, engine):
        day = engine.compile(StructuredQueryIntent(metric="gmv_trend"))
        assert "generate_series" in day.sql and "MM-DD" in day.sql and "LIMIT 50" in day.sql
        month = engine.compile(
            StructuredQueryIntent(metric="gmv_trend", time_window={"kind": "last_months", "n": 3})
        )
        assert "YYYY-MM" in month.sql and "INTERVAL '2 months'" in month.sql

    def test_trend_entity_filter_lands_in_join_on(self, engine):
        compiled = engine.compile(
            StructuredQueryIntent(metric="volume_trend", entity_slot={"spu": ["SPU-T1"]})
        )
        assert "AND oi.spu_id = ANY(:spu_ids)" in compiled.sql
        assert compiled.params["spu_ids"] == ["SPU-T1"]
