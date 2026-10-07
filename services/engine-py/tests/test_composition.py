"""T1 组合通道契约(ADR-0010;spec §5)。

闭集校验(目录外响亮拒绝)/ 编译 SQL 形状(维度聚合/时间平移/实体绑定/
安全闸)/ 灰度开关默认关。LLM 解析面(compose_resolve)不在此册 —— 需真
模型,由 promptfoo 组合评测覆盖(门见 spec §7)。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from engine_py.analytics.composition import (
    CompositionQuery,
    CompositionRejected,
    _validate,
    compile_composition,
    composition_enabled,
)


class _Out:
    """compose_resolve 的 LLM 输出形(pydantic 模型的鸭子替身)。"""

    def __init__(self, **kw):
        self.metric = kw.get("metric", "gmv")
        self.dimension = kw.get("dimension")
        self.direction = kw.get("direction", "DESC")
        self.limit = kw.get("limit", 10)
        self.time_kind = kw.get("time_kind")
        self.time_n = kw.get("time_n")
        self.compare_previous = kw.get("compare_previous", False)
        self.category = kw.get("category")
        self.entity_kind = kw.get("entity_kind")
        self.entity_mention = kw.get("entity_mention")


_ALLOWED = ["gmv", "volume", "order_count", "aov", "refund_rate", "review_bad"]


class TestCompositionGate:
    def test_default_off(self, monkeypatch):
        monkeypatch.delenv("AI_T1_COMPOSE", raising=False)
        assert composition_enabled() is False

    def test_env_on(self, monkeypatch):
        monkeypatch.setenv("AI_T1_COMPOSE", "on")
        assert composition_enabled() is True


class TestCompositionValidate:
    def test_valid_composition(self):
        comp = _validate(_Out(metric="gmv", dimension="category", limit=8), _ALLOWED, "各品类卖多少")
        assert comp.metric == "gmv" and comp.dimension == "category" and comp.limit == 8
        assert comp.source_question == "各品类卖多少"

    def test_unknown_metric_rejected(self):
        with pytest.raises(CompositionRejected, match="不在语义层目录"):
            _validate(_Out(metric="revenue_2026"), _ALLOWED, "revenue?")

    def test_sentinel_unsupported_rejected(self):
        with pytest.raises(CompositionRejected):
            _validate(_Out(metric="__unsupported__"), _ALLOWED, "随便聊聊")

    def test_metric_outside_role_rejected(self):
        with pytest.raises(CompositionRejected, match="无权"):
            _validate(_Out(metric="gross_profit"), _ALLOWED, "毛利按品类")  # 不在 allowed

    def test_unknown_dimension_rejected(self):
        with pytest.raises(CompositionRejected, match="不在语义层目录"):
            _validate(_Out(metric="gmv", dimension="region"), _ALLOWED, "按区域")

    def test_category_filter_incompatible_dimension_rejected(self):
        """品类过滤挂在 SPU 表:客户/活动/订单状态维度不可组合(宁可响亮)。"""
        with pytest.raises(CompositionRejected, match="不可组合"):
            _validate(_Out(metric="gmv", dimension="customer", category="衬衫"), _ALLOWED, "x")

    def test_unknown_entity_kind_rejected(self):
        with pytest.raises(CompositionRejected, match="实体种类"):
            _validate(_Out(metric="gmv", entity_kind="warehouse"), _ALLOWED, "x")

    def test_time_window_clamped(self):
        comp = _validate(
            _Out(metric="gmv", time_kind="last_months", time_n=99), _ALLOWED, "近 99 个月"
        )
        assert comp.time_window == {"kind": "last_months", "n": 24}


class TestCompositionCompile:
    def test_rank_by_category(self):
        comp = CompositionQuery(metric="gmv", dimension="category", limit=9)
        compiled = compile_composition(comp, "aurora")
        assert 'GROUP BY s.category ORDER BY "metricScore" DESC LIMIT :lim' in compiled.sql
        assert "LEFT JOIN merchant_spus s ON s.spu_code = oi.spu_id" in compiled.sql
        assert "NOT IN ('REFUNDED', 'CANCELLED')" in compiled.sql
        assert compiled.params["lim"] == 9
        assert compiled.target_db == "merchant_db"

    def test_entity_binding_goes_to_params(self):
        comp = CompositionQuery(metric="gmv", dimension="spu", entity_kind="spu")
        compiled = compile_composition(comp, "aurora", entity_ids=["SPU-1", "SPU-2"])
        assert "oi.spu_id = ANY(:entities)" in compiled.sql
        assert compiled.params["entities"] == ["SPU-1", "SPU-2"]

    def test_customer_dimension_joins_customers(self):
        comp = CompositionQuery(metric="volume", dimension="customer")
        compiled = compile_composition(comp, "aurora")
        assert "LEFT JOIN merchant_customers c ON c.customer_id = o.customer_id" in compiled.sql
        assert 'GROUP BY c.name' in compiled.sql

    def test_order_status_dimension_needs_no_join(self):
        comp = CompositionQuery(metric="order_count", dimension="order_status")
        compiled = compile_composition(comp, "aurora")
        assert "o.status AS \"订单状态\"" in compiled.sql
        assert "merchant_customers" not in compiled.sql

    def test_time_window_binds_window_start(self):
        comp = CompositionQuery(metric="gmv", dimension="category", time_window={"kind": "last_30d"})
        compiled = compile_composition(comp, "aurora")
        assert "o.created_at >= :window_start" in compiled.sql
        assert "window_start" in compiled.params

    def test_period_compare_emits_two_phase_cte(self):
        comp = CompositionQuery(metric="gmv", dimension="category", compare_previous=True)
        compiled = compile_composition(comp, "aurora")
        assert "WITH cur AS" in compiled.sql and "prev AS" in compiled.sql
        assert "FULL OUTER JOIN prev ON prev.dim = cur.dim" in compiled.sql
        assert compiled.params["cur_start"] > compiled.params["prev_start"]

    def test_period_compare_month_semantics(self):
        """缺省时间窗 = 本月 vs 上月(gmv_mom 语义收编的机制化偿还)。"""
        comp = CompositionQuery(metric="volume", dimension="category", compare_previous=True)
        compiled = compile_composition(comp, "aurora")
        now = datetime.now(UTC).replace(tzinfo=None)
        first = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        assert compiled.params["cur_start"] == first
        assert compiled.params["prev_start"] == (first - timedelta(days=1)).replace(day=1)

    def test_total_with_category_joins_spu(self):
        comp = CompositionQuery(metric="aov", category="衬衫")
        compiled = compile_composition(comp, "aurora")
        assert "LEFT JOIN merchant_spus s" in compiled.sql
        assert "LIMIT 1" in compiled.sql
        assert compiled.params["cat"] == "衬衫"

    def test_brand_column_dimension(self):
        """品牌 = 开放列维度(kind=column,无闭集取值);T1 组合即得「按品牌」。"""
        comp = CompositionQuery(metric="gmv", dimension="brand")
        compiled = compile_composition(comp, "aurora")
        assert 'GROUP BY s.brand ORDER BY "metricScore" DESC LIMIT :lim' in compiled.sql

    def test_net_sales_composable(self):
        comp = CompositionQuery(metric="net_sales", dimension="category")
        compiled = compile_composition(comp, "aurora")
        assert "SUM(o.total_amount)" in compiled.sql

    def test_unknown_metric_at_compile_is_loud(self):
        comp = CompositionQuery(metric="review_bad", dimension="category")  # 不可组合指标
        with pytest.raises(Exception, match="未开放语义层组合"):
            compile_composition(comp, "aurora")
