"""special-family 安全闸 + LIMIT 双保险 + 角色闭集(code review 修复回归)。

- 08-D4:两条编译路径必须同闸 —— special-family 模板未经 AST 白名单/危险函数
  断言不得出编译器(此前该族跳过 assert_safe_select,模板漂移即带病执行);
- 50 行双保险:无 :lim 槽位的模板(gmv_trend/order_overview)必须显式 LIMIT;
- 13-D2:sales_viewer 闭集含 order_overview/gmv_trend(运营问订单对比不误拒)。
"""

from __future__ import annotations

import pytest

from engine_py.analytics.engine import MetricQueryEngine, UnsupportedQuery
from engine_py.analytics.rbac import ROLE_METRIC_PERMISSIONS
from engine_py.analytics.schema_cards import compile_safe_schema_card
from engine_py.analytics.sql_guard import UnsafeSqlError, reject_unsafe

# special-family 全闭集:每个模板都必须过闸(缺一即漂移未登记)
_SPECIAL_METRICS: list[tuple[str, dict]] = [
    ("review_bad", {}),
    ("refund_rate", {}),
    ("session_volume", {}),
    ("ai_resolution_rate", {}),
    ("promo_orders", {}),
    ("promo_discount_total", {}),
    ("after_sale_overview", {}),
    ("gmv_trend", {}),
    ("order_overview", {"entity_ids": ["ORD-1"]}),
    ("promo_effect", {"entity_slot": {"promotion": ["P1"]}}),
    ("promo_sku_compare", {"entity_slot": {"promotion": ["P1"], "spu": ["S1"]}}),
    ("promo_compare", {"entity_slot": {"promotion": ["P1", "P2"]}}),
    ("customer_orders", {"entity_slot": {"customer": ["C1"]}}),
    # 归因族(确定性环比分解)
    ("attribution_refund", {}),
    ("attribution_sales", {}),
    # 阶段⑥对话出口族
    ("aov", {}),
    ("order_count", {}),
    ("review_good", {}),
    ("zero_sales", {}),
    ("category_gmv_top", {}),
    ("customer_spend_top", {}),
    # 阶段⑦客户族/环比/走势/货值(场景包 biz_overview/customer_panorama 由编排层展开,不经编译器)
    ("orders_trend", {}),
    ("stock_value", {}),
    ("gmv_mom", {}),
    ("customer_spend_stats", {"entity_slot": {"customer": ["C1"]}}),
    ("customer_coupons", {"entity_slot": {"customer": ["C1"]}}),
    ("customer_profile", {"entity_slot": {"customer": ["C1"]}}),
]


@pytest.fixture()
def engine() -> MetricQueryEngine:
    return MetricQueryEngine(session_ctx={"business_id": "aurora", "role": "finance_owner"})


class TestSpecialFamilyGate:
    @pytest.mark.parametrize(("metric", "slots"), _SPECIAL_METRICS)
    def test_every_template_passes_sql_guard(self, engine, metric, slots):
        """闭集内每个模板出编译器前必过 AST 安全闸(联合卡表单点白名单)。"""
        from engine_py.analytics.engine import StructuredQueryIntent

        intent = StructuredQueryIntent(metric=metric, **slots)
        compiled = engine.compile(intent)
        assert compiled.sql
        assert compiled.ast is not None

    def test_hallucinated_table_rejected_on_union_card(self):
        """联合卡白名单是活的:卡外表即使写进模板也响亮拒绝。"""
        with pytest.raises(UnsafeSqlError):
            reject_unsafe(
                "SELECT 1 FROM evil_shadow_table",
                schema=compile_safe_schema_card(),
            )

    def test_engine_local_tables_registered(self):
        """engine 本地库两表(session/售后)必须已登记事实源,否则会话族全灭。"""
        tables = compile_safe_schema_card()["tables"]
        for table in ("session_metrics", "after_sale_tickets", "promotions", "promotion_redemptions"):
            assert table in tables


class TestLimitDoubleInsurance:
    def test_gmv_trend_explicit_limit(self, engine):
        from engine_py.analytics.engine import StructuredQueryIntent

        compiled = engine.compile(StructuredQueryIntent(metric="gmv_trend"))
        assert compiled.sql.rstrip().endswith("LIMIT 50")

    def test_order_overview_explicit_limit(self, engine):
        from engine_py.analytics.engine import StructuredQueryIntent

        compiled = engine.compile(StructuredQueryIntent(metric="order_overview", entity_ids=[f"ORD-{i}" for i in range(60)]))
        assert compiled.sql.rstrip().endswith("LIMIT 50")
        assert len(compiled.params["entities"]) == 60  # 参数面不限行,SQL 面兜底截断

    def test_order_overview_requires_entities(self, engine):
        from engine_py.analytics.engine import StructuredQueryIntent

        with pytest.raises(UnsupportedQuery):
            engine.compile(StructuredQueryIntent(metric="order_overview"))


class TestSalesViewerClosedSet:
    def test_sales_viewer_can_ask_order_overview_and_gmv_trend(self):
        """运营问「勾选订单对比/近 30 天 GMV 走势」不误拒(review 修复点)。"""
        allowed = ROLE_METRIC_PERMISSIONS["sales_viewer"]
        assert "order_overview" in allowed
        assert "gmv_trend" in allowed

    def test_exit_family_open_to_sales_viewer(self):
        """阶段⑥出口族对运营开放(客单价/订单量/好评/滞销/品类/客户消费)。"""
        allowed = ROLE_METRIC_PERMISSIONS["sales_viewer"]
        assert {"aov", "order_count", "review_good", "zero_sales", "category_gmv_top", "customer_spend_top"} <= set(allowed)


class TestExitFamilyResolve:
    """阶段⑥对话出口族:L0 词面 → 闭集意图(解析即契约)。"""

    @pytest.mark.parametrize(("question", "metric"), [
        ("本月客单价多少", "aov"),
        ("本月订单量多少", "order_count"),
        ("好评最多的商品 Top 3", "review_good"),
        ("零销量商品有哪些", "zero_sales"),
        ("品类GMV排行", "category_gmv_top"),
        ("消费最高的客户 Top 3", "customer_spend_top"),
        ("张伟的消费统计", "customer_spend_stats"),
        ("张伟的优惠券", "customer_coupons"),
        ("张伟的用户画像", "customer_profile"),
        ("经营概览", "biz_overview"),
        ("GMV环比", "gmv_mom"),
        ("每日订单量走势", "orders_trend"),
        ("库存价值排行", "stock_value"),
    ])
    def test_exit_family_routes(self, engine, question, metric):
        intent = engine.resolve(question)
        assert intent.metric == metric


class TestMonthlyTrendRouting:
    """跨月销量折线(用户实弹诉求):「近 N 个月/几个月的销量」月粒度趋势。"""

    @pytest.mark.parametrize(("question", "metric"), [
        ("近3个月的销量", "volume_trend"),
        ("几个月的销量怎么样", "volume_trend"),
        ("每月销量趋势", "volume_trend"),
        ("按月统计销量", "volume_trend"),
        ("近30天GMV趋势", "gmv_trend"),
    ])
    def test_trend_routes(self, engine, question, metric):
        intent = engine.resolve(question)
        assert intent.metric == metric

    def test_last_month_window_n_parsed(self, engine):
        intent = engine.resolve("近3个月的销量")
        assert intent.time_window == {"kind": "last_months", "n": 3}

    @pytest.mark.parametrize(("question", "metric"), [
        ("销量 折线图", "volume_trend"),
        ("GMV 折线图", "gmv_trend"),
        ("销量榜 折线图", "volume"),
    ])
    def test_line_hint_upgrades_to_trend(self, engine, question, metric):
        """「XX 折线图」= 随时间的线 → 升级趋势族;榜单语义优先不升级。"""
        intent = engine.resolve(question)
        assert intent.metric == metric

    def test_trend_template_filters_by_selected_spu(self, engine):
        """勾选商品的趋势:模板按勾选的 spu 过滤(勾哪款出哪款的线)。"""
        from engine_py.analytics.engine import StructuredQueryIntent

        compiled = engine.compile(StructuredQueryIntent(
            metric="volume_trend", entity_slot={"spu": ["SPU-AURORA-001"]},
        ))
        assert "oi.spu_id = ANY(:spu_ids)" in compiled.sql

    def test_ranking_semantics_outrank_trend(self, engine):
        """「上个月的销量排行」问的是榜单不是折线:降回 volume,时间窗保留。"""
        intent = engine.resolve("上个月的销量排行")
        assert intent.metric == "volume"
        assert intent.time_window == {"kind": "last_month"}

    def test_monthly_template_compiles_with_month_granularity(self, engine):
        from engine_py.analytics.engine import StructuredQueryIntent

        compiled = engine.compile(StructuredQueryIntent(
            metric="volume_trend", time_window={"kind": "last_months", "n": 6},
        ))
        assert "date_trunc('month'" in compiled.sql
        assert "销量" in compiled.sql

    def test_daily_trend_template_unchanged(self, engine):
        from engine_py.analytics.engine import StructuredQueryIntent

        compiled = engine.compile(StructuredQueryIntent(metric="volume_trend"))
        assert compiled.sql.rstrip().endswith("LIMIT 50")
        assert "date_trunc" not in compiled.sql
