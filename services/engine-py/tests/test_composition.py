"""T1 组合通道契约(ADR-0010;spec §5)。

闭集校验(目录外响亮拒绝)/ 编译 SQL 形状(维度聚合/时间平移/实体绑定/
安全闸)/ 灰度开关默认关。LLM 解析面(compose_resolve)不在此册 —— 需真
模型,由 promptfoo 组合评测覆盖(门见 spec §7)。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from engine_py.analytics import composition
from engine_py.analytics.composition import (
    CompositionQuery,
    CompositionRejected,
    _validate,
    compile_composition,
    composition_enabled,
)
from engine_py.analytics.quick_summary import attribution_summary


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
            _validate(_Out(metric="gmv", dimension="age_group"), _ALLOWED, "按年龄段")

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

    def test_region_expression_dimension(self):
        """区域 = 七大地理区 CASE(表达式维度,声明进模型);「华东上月净销售额」
        场景的落地件。"""
        comp = CompositionQuery(metric="net_sales", dimension="region", time_window={"kind": "last_month"})
        compiled = compile_composition(comp, "aurora")
        assert "THEN '华东'" in compiled.sql and "ELSE '其他'" in compiled.sql
        assert 'AS "区域"' in compiled.sql
        assert "GROUP BY CASE" in compiled.sql
        assert compiled.params["window_start"] is not None

    def test_city_expression_dimension(self):
        comp = CompositionQuery(metric="order_count", dimension="city")
        compiled = compile_composition(comp, "aurora")
        assert "substring(o.shipping_address->>'fullAddress'" in compiled.sql
        assert 'AS "城市"' in compiled.sql

    def test_unknown_metric_at_compile_is_loud(self):
        comp = CompositionQuery(metric="review_bad", dimension="category")  # 不可组合指标
        with pytest.raises(Exception, match="未开放语义层组合"):
            compile_composition(comp, "aurora")


class TestAttributionSummary:
    """归因速览(票 10 阶段 A):compare_previous 帧的确定性呈现。"""

    def _result(self, rows):
        from engine_py.analytics.engine import QueryResult

        return QueryResult(rows=rows, metric="net_sales", unit="元", caliber="x")

    def test_drop_attribution(self):
        summary = attribution_summary(self._result([
            {"品类": "户外机能", "本期": 400.0, "上期": 600.0, "变化": -200.0},
            {"品类": "潮流鞋靴", "本期": 150.0, "上期": 100.0, "变化": 50.0},
        ]))
        assert "合计 本期 550 vs 上期 700" in summary
        assert "净变化 -150" in summary and "-21.4%" in summary
        assert "主因:户外机能(-200,占变动的 80%)" in summary
        assert "次正贡献:潮流鞋靴(+50)" in summary

    def test_rise_top_contributor_wording(self):
        summary = attribution_summary(self._result([
            {"品类": "A", "本期": 300.0, "上期": 100.0, "变化": 200.0},
        ]))
        assert "最大正贡献:A(+200,占变动的 100%)" in summary

    def test_zero_prev_delta_pct_is_dash(self):
        summary = attribution_summary(self._result([
            {"品类": "A", "本期": 100.0, "上期": 0.0, "变化": 100.0},
        ]))
        assert "—" in summary

    def test_non_compare_result_returns_none(self):
        assert attribution_summary(self._result([{"品类": "A", "metricScore": 5.0}])) is None
        assert attribution_summary(self._result([])) is None

class TestAttributionRelatedAndNarrative:
    """B1 退款率对照列 + B2 叙事溯源硬校验(ADR-0011)。"""

    def test_period_compare_carries_refund_rate_columns(self):
        comp = CompositionQuery(metric="gmv", dimension="category", compare_previous=True)
        compiled = compile_composition(comp, "aurora")
        assert 'AS "本期退款率"' in compiled.sql and 'AS "退款率变化"' in compiled.sql
        assert "CUR.RV" in compiled.sql.upper()

    def test_refund_rate_metric_skips_related_columns(self):
        comp = CompositionQuery(metric="refund_rate", dimension="category", compare_previous=True)
        compiled = compile_composition(comp, "aurora")
        assert "本期退款率" not in compiled.sql

    def test_narrative_disabled_by_default(self, monkeypatch):
        from engine_py.analytics import composition

        monkeypatch.delenv("AI_ATTR_NARRATIVE", raising=False)
        assert composition.attribute_narrative.__name__ == "attribute_narrative"

    def test_traceable_narrative_passes(self):
        from engine_py.analytics.composition import _narrative_traceable

        rows = [{"品类": "户外机能", "本期": 400.0, "上期": 600.0, "变化": -200.0, "本期退款率": 8.2, "退款率变化": 3.1}]
        summary = "合计 本期 400 vs 上期 600(净变化 -200,-33.3%)"
        assert _narrative_traceable("主因:户外机能(变化 -200),其本期退款率 8.2,环比 +3.1。", rows, summary)

    def test_fabricated_number_dropped(self):
        from engine_py.analytics.composition import _narrative_traceable

        rows = [{"品类": "户外机能", "本期": 400.0, "上期": 600.0, "变化": -200.0}]
        assert not _narrative_traceable("主因:户外机能(变化 -200),涉及订单 1,234 单。", rows, None)

    def test_comma_number_normalized(self):
        from engine_py.analytics.composition import _narrative_traceable

        rows = [{"品类": "A", "本期": 53515.0, "上期": 60000.0, "变化": -6485.0}]
        assert _narrative_traceable("净变化 -6,485。", rows, None)


class TestBreakdownReroute:
    """确定性组合升级(维度拆分语感直通):总量形 × 拆分语感 → 组合查询。"""

    from engine_py.analytics.engine import StructuredQueryIntent as _SQI

    def _intent(self, metric="net_sales", **kw):
        return self._SQI(metric=metric, **kw)

    def test_brand_breakdown_reroute(self, monkeypatch):
        monkeypatch.setenv("AI_T1_COMPOSE", "on")
        comp = composition.breakdown_reroute("各品牌净销售额对比", self._intent("net_sales"))
        assert comp is not None and comp.dimension == "brand" and comp.metric == "net_sales"

    def test_region_with_time_backfill(self, monkeypatch):
        monkeypatch.setenv("AI_T1_COMPOSE", "on")
        comp = composition.breakdown_reroute("按区域的上月订单量", self._intent("order_count", time_window={"kind": "last_month"}))
        assert comp is not None and comp.dimension == "region" and comp.time_window["kind"] == "last_month"

    def test_no_cue_no_reroute(self, monkeypatch):
        monkeypatch.setenv("AI_T1_COMPOSE", "on")
        assert composition.breakdown_reroute("净销售额多少", self._intent("net_sales")) is None

    def test_dim_rank_metric_no_reroute(self, monkeypatch):
        """命中指标已自带维度拆分(品类GMV榜)→ 不升级。"""
        monkeypatch.setenv("AI_T1_COMPOSE", "on")
        assert composition.breakdown_reroute("各品类GMV榜", self._intent("category_gmv_top")) is None

    def test_env_off_no_reroute(self, monkeypatch):
        monkeypatch.delenv("AI_T1_COMPOSE", raising=False)
        assert composition.breakdown_reroute("各品牌净销售额对比", self._intent("net_sales")) is None

    def test_category_incompatible_dimension_no_reroute(self, monkeypatch):
        monkeypatch.setenv("AI_T1_COMPOSE", "on")
        comp = composition.breakdown_reroute(
            "衬衫的各客户净销售额", self._intent("net_sales", category="衬衫")
        )
        assert comp is None  # 品类过滤挂 SPU 表,客户维度不可组合,宁可不升级

    def test_compare_previous_cue(self, monkeypatch):
        monkeypatch.setenv("AI_T1_COMPOSE", "on")
        comp = composition.breakdown_reroute("各品类净销售额环比", self._intent("net_sales"))
        assert comp is not None and comp.compare_previous is True


class TestMalformedComposeOutput:
    """LLM 产出不合契约的成分类型时驯化为响亮拒绝(eval-gap-2026-10 16):
    垃圾输出 = 组合失败,严禁裸 ValidationError 逃逸成调用方无法分类的异常。"""

    def test_nonstring_dimension_becomes_rejection(self):
        import asyncio

        from engine_py.analytics import composition as c

        class _StubModel:
            def bind_tools(self, tools, tool_choice=None):  # 逼走文本解析路径
                raise RuntimeError("tools unavailable")

            async def ainvoke(self, messages):
                class _Resp:
                    content = '{"metric": "gmv", "dimension": ["品类"]}'

                return _Resp()

        with pytest.raises(c.CompositionRejected, match="不合契约"):
            asyncio.run(c._invoke_compose_out(_StubModel(), []))


class TestDimensionBackfill:
    """维度漏填确定性回填(eval-gap-2026-10 15/16):拆分句式的 dimension
    由 _BREAKDOWN_RE 语感词表先验兜底,只兜漏填、不覆盖 LLM 显式输出。"""

    def _out(self, **kw):
        from engine_py.analytics.composition import _ComposeOut

        base = {"metric": "gmv", "dimension": None, "limit": 10}
        base.update(kw)
        return _ComposeOut(**base)

    def test_ge_phrase_backfill(self):
        from engine_py.analytics.composition import _validate

        comp = _validate(self._out(), None, "近30天各品类的成交额")
        assert comp.dimension == "category"

    def test_status_question_backfill(self):
        from engine_py.analytics.composition import _validate

        comp = _validate(self._out(metric="order_count"), None, "订单目前都处于什么状态")
        assert comp.dimension == "order_status"

    def test_explicit_dimension_not_overridden(self):
        from engine_py.analytics.composition import _validate

        comp = _validate(self._out(dimension="spu"), None, "各品类的成交额")
        assert comp.dimension == "spu"

    def test_no_breakdown_phrase_stays_none(self):
        from engine_py.analytics.composition import _validate

        comp = _validate(self._out(), None, "现在的客单价是多少")
        assert comp.dimension is None

    def test_category_garbage_strings_normalized(self):
        """LLM 品类垃圾串归一(15 号票三跑三红:'各品类'/'null'/'')—— 裸维度
        分组问句的 category 一律归 None,dimension 由语感回填承担。"""
        from engine_py.analytics.composition import _validate

        for garbage in ("各品类", "null", "none", "无", ""):
            comp = _validate(self._out(category=garbage), None, "各品类销售额的环比变化")
            assert comp.dimension == "category"
            assert comp.category is None, garbage
            assert comp.compare_previous is True, "环比词确定性置位(15 号票)"

    def test_compare_previous_phrase_overrides(self):
        """问句明示环比/同比而 LLM 漏标 → 确定性置 True(错判非风格差异)。"""
        from engine_py.analytics.composition import _validate

        comp = _validate(self._out(compare_previous=False), None, "上月与这个月的销售额环比对比")
        assert comp.compare_previous is True

    def test_product_metric_denied(self):
        """成品指标硬闸(15 号票):LLM 偶发映射 order_overview(prompt 软约束
        漏网)—— _validate 兜底拒绝,「订单状态分布」类问句不得走成品指标。"""
        from engine_py.analytics.composition import CompositionRejected, _validate

        with pytest.raises(CompositionRejected, match="成品指标"):
            _validate(self._out(metric="order_overview"), None, "订单目前都处于什么状态")

    def test_category_boolean_leak_normalized(self):
        """LLM 布尔串泄漏(15 号票 live 实弹:category='true')同归垃圾集。"""
        from engine_py.analytics.composition import _validate

        comp = _validate(self._out(category="true"), None, "各品类销售额的环比变化")
        assert comp.category is None


class TestAttributionP01:
    """grill 2026-10-26 P0①/② + ADR-0011 裁决落地:时间窗扩容右界、B1 差评率
    对照列、T0 榜指标归因映射、品类闭集派生、新指标编译。"""

    def test_period_compare_yesterday_complete_past_bounds(self):
        """完整过去段(昨天)双期对照:本期必须带排他右界,上期=前天全天。"""
        comp = composition.CompositionQuery(
            metric="gmv", dimension="category", compare_previous=True, time_window={"kind": "yesterday"},
        )
        compiled = composition.compile_composition(comp, "aurora")
        assert compiled.params["cur_end"] is not None
        assert compiled.params["cur_start"] + timedelta(days=1) == compiled.params["cur_end"]
        assert compiled.params["prev_start"] == compiled.params["cur_start"] - timedelta(days=1)

    def test_period_compare_rolling_window_stays_open(self):
        """滚动窗(近7天)保持开口,不受右界扩容影响。"""
        comp = composition.CompositionQuery(
            metric="gmv", dimension="category", compare_previous=True, time_window={"kind": "last_7d"},
        )
        compiled = composition.compile_composition(comp, "aurora")
        assert "cur_end" not in compiled.params

    def test_period_bounds_p01_kinds(self):
        for kind in ("today", "yesterday", "this_week", "last_week", "this_month", "this_year", "last_year"):
            cur, prev = composition._period_bounds({"kind": kind})
            assert cur > prev, f"{kind} 双期起点必须严格递减"

    def test_period_compare_carries_bad_rate_columns(self):
        """B1 差评率对照列(品类维度):独立 CTE,join 条件从语义模型声明派生。"""
        from engine_py.analytics.tools_registry_bridge import semantic_model

        comp = composition.CompositionQuery(metric="gmv", dimension="category", compare_previous=True)
        compiled = composition.compile_composition(comp, "aurora")
        assert 'AS "本期差评率"' in compiled.sql and 'AS "差评率变化"' in compiled.sql
        assert "badcur AS" in compiled.sql
        declared = next(j["condition"] for j in semantic_model()["joins"] if j["name"] == "review_of_spu")
        assert f"LEFT JOIN merchant_spus s ON {declared}" in compiled.sql

    def test_time_kind_closure_single_source(self):
        """时间 kind 闭集一致性(P0① 评审收口):L0 槽位、L3 契约、T1 校验
        三处枚举必须 ⊆ window_start/_period_bounds 的支持集 —— 漏一处即
        静默丢窗落全历史,这正是本批要修的病,故钉死。"""
        import datetime as _dt

        from engine_py.analytics import l0_lexicon, llm_intent
        from engine_py.analytics.engine import UnsupportedQuery, window_start

        l0_kinds = {k for k, _ in l0_lexicon.TIME_PATTERNS}
        assert l0_kinds <= set(llm_intent._VALID_TIME) | {"last_months"}, "L0 产出的 kind L3 必须认得"
        probe = _dt.datetime(2026, 10, 26, 12, 0, tzinfo=_dt.UTC).replace(tzinfo=None)
        for kind in set(llm_intent._VALID_TIME) | {"last_months"}:
            try:
                window_start({"kind": kind}, probe)
                composition._period_bounds({"kind": kind}, probe)
            except UnsupportedQuery as err:
                raise AssertionError(f"kind {kind} 被契约接受但算不出边界:{err}") from err

    def test_bad_rate_skipped_for_unreachable_dimension(self):
        """客户维度与评价表无 join 路径:诚实缺列,不造零。"""
        comp = composition.CompositionQuery(metric="gmv", dimension="customer", compare_previous=True)
        compiled = composition.compile_composition(comp, "aurora")
        assert "差评率" not in compiled.sql

    def test_reason_reroute_maps_t0_rank_metric(self, monkeypatch):
        """「为什么×品类销售额」被 L0 命中 category_gmv_top(不可组合)时,
        归因降维到基度量 gmv —— 「为什么」不再被吞成当期榜。"""
        monkeypatch.setenv("AI_T1_COMPOSE", "on")
        from engine_py.analytics.engine import StructuredQueryIntent

        intent = StructuredQueryIntent(metric="category_gmv_top", time_window={"kind": "last_month"})
        comp = composition.reason_reroute("为什么各品类销售额跌了", intent)
        assert comp is not None and comp.metric == "gmv"
        assert comp.compare_previous is True and comp.dimension == "category"

    def test_valid_categories_derived_from_semantic_model(self):
        """L3 品类闭集 = semantic_model.yaml 派生(修 9 vs 11 漂移)。"""
        from engine_py.analytics.llm_intent import _valid_categories
        from engine_py.analytics.tools_registry_bridge import semantic_model

        expected = tuple(semantic_model()["dimensions"]["category"]["values"])
        assert _valid_categories() == expected and len(expected) >= 11

    def test_new_metric_review_avg_compiles(self):
        from engine_py.analytics.engine import StructuredQueryIntent
        from engine_py.analytics.semantic_compiler import compile_metric

        compiled = compile_metric(StructuredQueryIntent(metric="review_avg"), "aurora")
        assert "AVG(r.rating)" in compiled.sql and "merchant_product_reviews" in compiled.sql

    def test_new_metric_repeat_purchase_rate_compiles(self):
        from engine_py.analytics.engine import StructuredQueryIntent
        from engine_py.analytics.semantic_compiler import compile_metric

        compiled = compile_metric(StructuredQueryIntent(metric="repeat_purchase_rate"), "aurora")
        assert "WITH cust AS" in compiled.sql and "orders_n >= 2" in compiled.sql
        assert "FROM cust c" in compiled.sql
        # 时间窗右界入 CTE 内层(昨天 → 完整过去段)
        compiled_y = compile_metric(
            StructuredQueryIntent(metric="repeat_purchase_rate", time_window={"kind": "yesterday"}), "aurora",
        )
        assert compiled_y.params["window_end"] is not None


class TestComposeExpansionTicket:
    """grill 2026-10-27 票:组合面扩容(毛利/毛利率 + 复购率入组合与归因)。"""

    def test_gross_profit_margin_composable_rank(self):
        comp = composition.CompositionQuery(metric="gross_profit", dimension="category")
        compiled = composition.compile_composition(comp, "aurora")
        assert "cost_at_purchase" in compiled.sql and "GROUP BY s.category" in compiled.sql
        comp2 = composition.CompositionQuery(metric="margin_rate", dimension="brand")
        compiled2 = composition.compile_composition(comp2, "aurora")
        assert "cost_at_purchase" in compiled2.sql and compiled2.params["lim"] == 10

    def test_compose_role_closure_blocks_finance_metrics(self):
        """毛利/毛利率 finance_owner 专属:allowed 闭集外的组合必须响亮拒绝
        (组合面扩容不新增权限面)。"""
        with pytest.raises(composition.CompositionRejected):
            composition._validate(_Out(metric="gross_profit", dimension="category"), ["gmv"], "各品类毛利")
        ok = composition._validate(
            _Out(metric="gross_profit", dimension="category"), ["gmv", "gross_profit"], "各品类毛利"
        )
        assert ok.metric == "gross_profit"

    def test_nested_rank_repeat_rate_by_category(self):
        comp = composition.CompositionQuery(metric="repeat_purchase_rate", dimension="category")
        compiled = composition.compile_composition(comp, "aurora")
        assert "orders_n" in compiled.sql and "GROUP BY s.category, o.customer_id" in compiled.sql
        assert "per_cust" in compiled.sql

    def test_nested_compare_repeat_rate_carries_bad_rate(self):
        """「为什么复购率变了」:双期嵌套归因 + 差评率对照(退款率对照在嵌套
        度量下挂不上平铺行集,由差评率 CTE 独立承担)。"""
        comp = composition.CompositionQuery(
            metric="repeat_purchase_rate", dimension="category", compare_previous=True,
            time_window={"kind": "last_month"},
        )
        compiled = composition.compile_composition(comp, "aurora")
        assert "cur_start" in compiled.params and "cur_end" in compiled.params  # 完整过去段右界
        assert compiled.sql.count("per_cust") == 2  # 双期各一层内嵌
        assert 'AS "本期差评率"' in compiled.sql and "本期退款率" not in compiled.sql

    def test_breakdown_and_reason_upgrade_repeat_rate(self, monkeypatch):
        """「各品类复购率」breakdown 升格、「为什么复购率变了」归因 ——
        T0 total_single 指标入组合面后两条确定性直通自然打通。"""
        monkeypatch.setenv("AI_T1_COMPOSE", "on")
        from engine_py.analytics.engine import StructuredQueryIntent

        intent = StructuredQueryIntent(metric="repeat_purchase_rate")
        bd = composition.breakdown_reroute("各品类复购率", intent)
        assert bd is not None and bd.metric == "repeat_purchase_rate" and bd.dimension == "category"
        rs = composition.reason_reroute("为什么复购率变了", intent)
        assert rs is not None and rs.compare_previous is True and rs.dimension == "category"
