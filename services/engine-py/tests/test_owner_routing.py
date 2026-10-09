"""「该找谁」责任人路由(spec .scratch/owner-routing)—— 解析器/快轨/归因附列离线册。

不依赖 DB:商户库 reader 与 engine 会话全桩;语义注册表(YAML)取真。
桩面 = owner_routing 的两个 IO 口(_mapped_staff_ids / get_session / reader_engine),
编排断言与 live 行为同形(live 冒烟 2026-10-08 已过五问句)。
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from engine_py.analytics import graph, owner_routing
from engine_py.analytics.composition import CompositionQuery
from engine_py.analytics.engine import QueryResult
from engine_py.analytics.quick_summary import attribution_summary

# ---------- 桩基建 ----------


class _FakeRows:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _FakeConn:
    def __init__(self, results):
        self._results = results

    async def execute(self, query, params=None):
        sql = str(query)
        for marker, rows in self._results.items():
            if marker in sql:
                return _FakeRows(rows)
        return _FakeRows([])

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _FakeEngine:
    def __init__(self, results):
        self._results = results

    def connect(self):
        return _FakeConn(self._results)


def _staff(sid, display, dept=None, level=None, email="", role="sales_viewer", enabled=True):
    return SimpleNamespace(
        id=sid, display_name=display, dept=dept, level=level, email=email or f"{sid}@aurora",
        role=role, status="enabled" if enabled else "disabled", business_id="aurora",
    )


class _FakeScalars:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _FakeSessionResult:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return _FakeScalars(self._rows)


class _FakeSession:
    def __init__(self, staff_rows):
        self._staff_rows = staff_rows

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def execute(self, query):
        return _FakeSessionResult(self._staff_rows)


@pytest.fixture()
def patch_owner_io(monkeypatch):
    """桩掉 owner_routing 的商户库与员工会话;返回可改的桩数据容器。"""
    state = {
        "mappings": [],  # owner_mappings 行 (map_value, staff_id)
        "spus": [],  # (spu_code, title) —— find_owner_target 词面扫描用
        "spu_owner_rows": [],  # (id, owner_id) —— T0 附列按 UUID 解析用
        "promotions": [],  # (name,)
        "spu_owner": {},  # spu_code -> staff_id(owner_id 列)
        "promo_creator": {},  # name -> staff_id(created_by 列)
        "staff": [],  # StaffMember 形行
    }

    async def _fake_mapped(map_type, values):
        if map_type == owner_routing.MAP_SPU:
            return {v: state["spu_owner"].get(v) for v in values}
        if map_type == owner_routing.MAP_PROMOTION:
            return {v: state["promo_creator"].get(v) for v in values}
        return {v: next((sid for mv, sid in state["mappings"] if mv == v), None) for v in values}

    monkeypatch.setattr(owner_routing, "_mapped_staff_ids", _fake_mapped)
    monkeypatch.setattr(owner_routing, "reader_engine", lambda: _FakeEngine({
        "SELECT spu_code, title": list(state["spus"]),
        "SELECT id::text, owner_id": list(state["spu_owner_rows"]),
        "FROM promotions": [(name,) for name in state["promotions"]],
    }))
    monkeypatch.setattr(owner_routing, "get_session", lambda: _FakeSession(state["staff"]))
    return state


# ---------- format_name(Q10 展示形) ----------


class TestFormatName:
    def test_full(self):
        info = owner_routing.OwnerInfo("s1", "陈锋", "销售部", "主管", "x@aurora", "sales_viewer")
        assert owner_routing.format_name(info) == "陈锋(销售部·主管)"

    def test_dept_only(self):
        info = owner_routing.OwnerInfo("s1", "李芸", "销售部", None, "x@aurora", "sales_viewer")
        assert owner_routing.format_name(info) == "李芸(销售部)"

    def test_bare(self):
        info = owner_routing.OwnerInfo("s1", "赵磊", None, None, "x@aurora", "sales_viewer")
        assert owner_routing.format_name(info) == "赵磊"


# ---------- resolve_owners(来源路由 + 诚实降级) ----------


class TestResolveOwners:
    def test_category_via_registry(self, patch_owner_io):
        patch_owner_io["mappings"] = [("户外机能", "staff_sales_1")]
        patch_owner_io["staff"] = [_staff("staff_sales_1", "李芸", "销售部", "专员")]
        out = asyncio.run(owner_routing.resolve_owners("aurora", "category", ["户外机能"]))
        assert out["户外机能"] is not None and out["户外机能"].display == "李芸"

    def test_spu_via_owner_id_column(self, patch_owner_io):
        """Q15 数据原生:SPU 走 merchant_spus.owner_id,不走注册表。"""
        patch_owner_io["spu_owner"] = {"SPU-1": "staff_sales_2"}
        patch_owner_io["staff"] = [_staff("staff_sales_2", "赵磊", "销售部", "专员")]
        out = asyncio.run(owner_routing.resolve_owners("aurora", "spu", ["SPU-1"]))
        assert out["SPU-1"].display == "赵磊"

    def test_promotion_via_created_by(self, patch_owner_io):
        """Q14 数据原生:活动走 promotions.created_by。"""
        patch_owner_io["promo_creator"] = {"国庆户外机能节": "staff_ops_lead"}
        patch_owner_io["staff"] = [_staff("staff_ops_lead", "周婷", "运营部", "主管")]
        out = asyncio.run(owner_routing.resolve_owners("aurora", "promotion", ["国庆户外机能节"]))
        assert out["国庆户外机能节"].dept == "运营部"

    def test_unmapped_is_none(self, patch_owner_io):
        out = asyncio.run(owner_routing.resolve_owners("aurora", "category", ["衬衫"]))
        assert out["衬衫"] is None

    def test_disabled_staff_is_none(self, patch_owner_io):
        """员工停用与未登记同归 None(呈现层统一诚实,不区分暴露)。"""
        patch_owner_io["mappings"] = [("户外机能", "staff_gone")]
        patch_owner_io["staff"] = []  # 查无/停用都不在返回集
        out = asyncio.run(owner_routing.resolve_owners("aurora", "category", ["户外机能"]))
        assert out["户外机能"] is None


# ---------- find_owner_target(具体专名优先) ----------


class TestFindOwnerTarget:
    def test_promotion_base_beats_category(self, patch_owner_io):
        """活动名内嵌品类词:泛类后置,「国庆户外机能节」必须答活动不是品类。"""
        patch_owner_io["promotions"] = ["国庆户外机能节·满500减80"]
        target = asyncio.run(owner_routing.find_owner_target("国庆户外机能节该找谁"))
        assert target is not None and target.map_type == owner_routing.MAP_PROMOTION

    def test_spu_code_first(self, patch_owner_io):
        patch_owner_io["spus"] = [("SPU-AURORA-001", "极光三合一全天候户外硬壳冲锋衣 (2026款旗舰版)")]
        target = asyncio.run(owner_routing.find_owner_target("SPU-AURORA-001 该找谁"))
        assert target.map_type == owner_routing.MAP_SPU and target.map_value == "SPU-AURORA-001"

    def test_spu_title_base_unique(self, patch_owner_io):
        """标题前段匹配(问句不带「(2026款旗舰版)」后缀);多命中放弃。"""
        patch_owner_io["spus"] = [("SPU-1", "极光三合一全天候户外硬壳冲锋衣 (2026款旗舰版)")]
        target = asyncio.run(owner_routing.find_owner_target("极光三合一全天候户外硬壳冲锋衣该找谁"))
        assert target is not None and target.map_value == "SPU-1"
        patch_owner_io["spus"].append(("SPU-2", "极光三合一全天候户外硬壳冲锋衣 (2025款)"))
        assert asyncio.run(owner_routing.find_owner_target("极光三合一全天候户外硬壳冲锋衣该找谁")) is None

    def test_category_then_metric_wordface(self, patch_owner_io):
        target = asyncio.run(owner_routing.find_owner_target("户外机能品类该找谁"))
        assert target.map_type == owner_routing.MAP_CATEGORY
        target = asyncio.run(owner_routing.find_owner_target("退款率谁负责"))
        assert target.map_type == owner_routing.MAP_METRIC

    def test_long_metric_wordface_wins(self, patch_owner_io):
        """「总销售额」必须压过同义词「销售额」(长词面优先)。"""
        target = asyncio.run(owner_routing.find_owner_target("总销售额该找谁"))
        assert target.map_value == "gmv"

    def test_no_target_returns_none(self, patch_owner_io):
        assert asyncio.run(owner_routing.find_owner_target("蓝鲸品类该找谁")) is None

    def test_bare_refund_wordface(self, patch_owner_io):
        """「退款」裸词 ∈ refund_rate 同义词册(2026-10-08 实弹:「为什么退款这么多」
        落 unsupported 的词面债)。"""
        target = asyncio.run(owner_routing.find_owner_target("退款该找谁"))
        assert target is not None and target.map_value == "refund_rate"

    def test_colloquial_performance_wordfaces(self, patch_owner_io):
        """口语绩效词族(2026-10-08 实弹:「热销商品该找谁」「为什么卖得这么差,该找谁」
        曾 unsupported):热销/畅销/好卖/卖得 → volume;卖得好 → gmv(长词面优先)。"""
        for word in ("热销商品该找谁", "畅销款谁负责", "好卖的商品该找谁", "为什么卖得这么差,该找谁"):
            target = asyncio.run(owner_routing.find_owner_target(word))
            assert target is not None and target.map_value == "volume", f"{word} → volume"
        target = asyncio.run(owner_routing.find_owner_target("为什么卖得好,该找谁"))
        assert target is not None and target.map_value == "gmv"

    def test_wordfaces_deduped(self):
        faces = owner_routing._metric_wordfaces()
        assert len(faces) == len(set(faces)), "label/去括号/synonyms 三源同文应去重"


# ---------- graph 快轨接线 ----------


class TestGraphOwnerRoute:
    def test_owner_frame_hit(self, patch_owner_io):
        patch_owner_io["mappings"] = [("户外机能", "staff_sales_1")]
        patch_owner_io["staff"] = [_staff("staff_sales_1", "李芸", "销售部", "专员")]
        out = asyncio.run(graph.ask("户外机能品类该找谁", {"business_id": "aurora", "role": "finance_owner"}))
        assert out["type"] == "result" and out["trust"] == "verified"
        assert "责任人注册表" in out["caliber"]
        row = out["rows"][0]
        assert row["负责人"] == "李芸" and row["部门"] == "销售部" and row["负责范围"] == "户外机能"
        assert out["summary"].startswith("「户外机能」的负责人是")

    def test_owner_frame_unregistered(self, patch_owner_io):
        """目标已识别但未登记 → 诚实引导帧(Q12),不是 unsupported。"""
        out = asyncio.run(graph.ask("衬衫品类该找谁", {"business_id": "aurora", "role": "finance_owner"}))
        assert out["type"] == "result" and out["rows"] == []
        assert "暂未登记负责人" in out["summary"] and "责任人维护" in out["summary"]

    def test_non_owner_question_passes_through(self, monkeypatch):
        """无找谁词面 → 快轨零感知,原管线照常(clarify 反问是既有行为)。"""
        async def _fake(self, compiled, session_ctx=None):
            return QueryResult(rows=[{"productId": "SPU-A", "metricScore": 1.0}],
                               metric=compiled.metric, unit=compiled.unit, caliber="测试口径")

        monkeypatch.setattr(graph.MetricQueryEngine, "execute_async", _fake)
        out = asyncio.run(graph.ask("卖得最好的商品", {"business_id": "aurora", "role": "finance_owner"}))
        assert out["type"] == "clarify"  # 原管线行为不变


class TestReasonAttributionUpgrade:
    """原因语感升格(2026-10-08 实弹):「为什么退款这么多,什么原因,该找谁」
    曾落 unsupported —— 找谁 × 指标 × 原因语感 → 确定性升格归因组合,一卡答两问。"""

    def _ask_compound(self, patch_owner_io, monkeypatch):
        # 收敛后复合句走主管线:L0 同义词(退款→refund_rate)→ reason_reroute
        # (T1 闸)→ 归因组合;快轨只负责放行。
        monkeypatch.setenv("AI_T1_COMPOSE", "on")
        rows = [
            {"品类": "潮流鞋靴", "本期": 20.0, "上期": 5.0, "变化": 15.0},
            {"品类": "户外机能", "本期": 2.0, "上期": 8.0, "变化": -6.0},
        ]

        async def _fake(self, compiled, session_ctx=None):
            return QueryResult(rows=rows, metric=compiled.metric, unit="%", caliber="组合口径")

        monkeypatch.setattr(graph.MetricQueryEngine, "execute_async", _fake)
        patch_owner_io["mappings"] = [("潮流鞋靴", "staff_sales_lead"), ("户外机能", "staff_sales_1")]
        patch_owner_io["staff"] = [
            _staff("staff_sales_lead", "陈锋", "销售部", "主管"),
            _staff("staff_sales_1", "李芸", "销售部", "专员"),
        ]
        return asyncio.run(graph.ask(
            "为什么退款这么多,什么原因,该找谁",
            {"business_id": "aurora", "role": "finance_owner"},
        ))

    def test_compound_reason_question_gets_attribution_frame(self, patch_owner_io, monkeypatch):
        out = self._ask_compound(patch_owner_io, monkeypatch)
        assert out["type"] == "result" and out["title"].startswith("归因")
        assert out["rows"][0]["负责人"] == "陈锋(销售部·主管)"  # 归因行自带负责人 = 「该找谁」半问
        assert out["metric"] == "refund_rate"

    def test_fast_track_yields_compound_to_pipeline(self, patch_owner_io):
        """混合分层收敛(2026-10-09):指标目标 × 复合语感(原因/维度泛词/排行)
        → 快轨放行主管线(fluid 语义归管线,快路径只吃定义良好的意图);
        纯「X 该找谁」仍由快轨答 owner 卡。"""
        for q in ("为什么退款这么多,该找谁", "哪个品类卖得最好该找谁", "销量 Top10 该找谁"):
            target = asyncio.run(owner_routing.find_owner_target(q))
            assert target is not None and target.map_type == owner_routing.MAP_METRIC, q
            frame = asyncio.run(graph._owner_route(
                q, {"business_id": "aurora", "role": "finance_owner"}, None,
                graph.Trace("aurora", "finance_owner", q),
            ))
            assert frame is None, f"{q} 应放行主管线"

    def test_pure_owner_lookup_still_fast(self, patch_owner_io):
        """纯查lookup(无复合语感)→ 快轨 owner 卡不变。"""
        patch_owner_io["mappings"] = [("refund_rate", "staff_aftersale_lead")]
        patch_owner_io["staff"] = [_staff("staff_aftersale_lead", "吴敏", "售后部", "主管")]
        out = asyncio.run(graph.ask(
            "退款率该找谁", {"business_id": "aurora", "role": "finance_owner"},
        ))
        assert out["type"] == "result" and "吴敏" in out["summary"]

    def test_reason_words_without_owner_stays_out(self):
        """无找谁词面 → 快轨不触发;原因直通由 composition.reason_reroute 承接。"""
        assert owner_routing.looks_like_owner_ask("为什么退款这么多") is False
        assert owner_routing.has_reason_intent("为什么退款这么多") is True

    def test_reason_reroute_without_owner_word(self, patch_owner_io, monkeypatch):
        """「为什么退款这么多」(无找谁词面)→ L0 命中 refund_rate → 原因直通归因卡
        (此前 unsupported/退榜单)。"""
        monkeypatch.setenv("AI_T1_COMPOSE", "on")
        rows = [{"品类": "潮流鞋靴", "本期": 0.0, "上期": 28.57, "变化": -28.57}]

        async def _fake(self, compiled, session_ctx=None):
            return QueryResult(rows=rows, metric=compiled.metric, unit="%", caliber="组合口径")

        monkeypatch.setattr(graph.MetricQueryEngine, "execute_async", _fake)
        patch_owner_io["mappings"] = [("潮流鞋靴", "staff_sales_lead")]
        patch_owner_io["staff"] = [_staff("staff_sales_lead", "陈锋", "销售部", "主管")]
        out = asyncio.run(graph.ask("为什么退款这么多", {"business_id": "aurora", "role": "finance_owner"}))
        assert out["type"] == "result" and out["title"].startswith("归因")
        assert out["metric"] == "refund_rate"
        assert out["rows"][0]["负责人"] == "陈锋(销售部·主管)"

    def test_reason_reroute_dimension_word_wins(self, monkeypatch):
        """维度泛词显式优先(「各区域…」→ region,owner 列诚实缺席);缺省 category。"""
        monkeypatch.setenv("AI_T1_COMPOSE", "on")
        from engine_py.analytics.composition import reason_reroute
        from engine_py.analytics.engine import StructuredQueryIntent

        intent = StructuredQueryIntent(metric="refund_rate", direction="DESC")
        comp = reason_reroute("各区域退款率为什么涨了", intent)
        assert comp is not None and comp.dimension == "region" and comp.compare_previous is True
        comp2 = reason_reroute("为什么退款这么多", intent)
        assert comp2 is not None and comp2.dimension == "category"

    def test_reason_reroute_rejects_non_composable(self):
        from engine_py.analytics.composition import reason_reroute
        from engine_py.analytics.engine import StructuredQueryIntent

        intent = StructuredQueryIntent(metric="order_overview", direction="DESC")
        assert reason_reroute("为什么这单退款了", intent) is None

    def test_ranking_with_owner_word_gets_owner_column(self, patch_owner_io, monkeypatch):
        """第三载体(2026-10-09):维度泛词 × 排行语感 × 找谁 → 排行卡附负责人列;
        无 compare_previous(看高低非看变化),标题不带「归因」前缀。
        用退货率(无歧义指标);「卖得最好」属 gmv/volume 歧义 → L0 泛指反问
        (GENERIC_HINTS 既有设计),快轨静默选边才是武断。"""
        monkeypatch.setenv("AI_T1_COMPOSE", "on")
        rows = [
            {"品类": "潮流鞋靴", "metricScore": 99.0},
            {"品类": "户外机能", "metricScore": 87.0},
        ]

        async def _fake(self, compiled, session_ctx=None):
            return QueryResult(rows=rows, metric=compiled.metric, unit="%", caliber="组合口径")

        monkeypatch.setattr(graph.MetricQueryEngine, "execute_async", _fake)
        patch_owner_io["mappings"] = [("潮流鞋靴", "staff_sales_lead"), ("户外机能", "staff_sales_1")]
        patch_owner_io["staff"] = [
            _staff("staff_sales_lead", "陈锋", "销售部", "主管"),
            _staff("staff_sales_1", "李芸", "销售部", "专员"),
        ]
        out = asyncio.run(graph.ask(
            "哪个品类退货率最高该找谁", {"business_id": "aurora", "role": "finance_owner"},
        ))
        assert out["type"] == "result" and not out["title"].startswith("归因")
        assert out["rows"][0]["负责人"] == "陈锋(销售部·主管)"

    def test_ambiguous_metric_with_dimension_clarifies(self, patch_owner_io, monkeypatch):
        """「卖得最好」= gmv/volume 歧义 + 维度泛词 → L0 泛指反问(GENERIC_HINTS
        既有诚实设计);收敛前快轨静默选 volume 才是武断。"""
        out = asyncio.run(graph.ask(
            "哪个品类卖得最好该找谁", {"business_id": "aurora", "role": "finance_owner"},
        ))
        assert out["type"] == "clarify"

    def test_passive_ranking_stays_without_owner_column(self, patch_owner_io, monkeypatch):
        """Q10 纪律:无找谁意图的被动排行(「各品类销售额」)不添 owner 列。"""
        monkeypatch.setenv("AI_T1_COMPOSE", "on")
        rows = [{"品类": "潮流鞋靴", "metricScore": 99.0}]

        async def _fake(self, compiled, session_ctx=None):
            return QueryResult(rows=rows, metric=compiled.metric, unit="元", caliber="组合口径")

        monkeypatch.setattr(graph.MetricQueryEngine, "execute_async", _fake)
        patch_owner_io["mappings"] = [("潮流鞋靴", "staff_sales_lead")]
        patch_owner_io["staff"] = [_staff("staff_sales_lead", "陈锋", "销售部", "主管")]
        out = asyncio.run(graph.ask(
            "各品类销售额", {"business_id": "aurora", "role": "finance_owner"},
        ))
        assert out["type"] == "result"
        assert "负责人" not in out["rows"][0]

    def test_t0_spu_rank_attach(self, patch_owner_io, monkeypatch):
        """T0 排行附列(帧级富化层):找谁意图 ∧ spu_rank shape(compile 单源)
        → 按 SPU UUID 解析 owner_id 数据原生列。"""
        rows = [
            {"name": "极光冲锋衣", "productId": "uuid-1", "category": "户外机能", "stock": 5, "metricScore": 9.0},
            {"name": "极光背包", "productId": "uuid-2", "category": "背包收纳", "stock": 3, "metricScore": 7.0},
        ]

        async def _fake(self, compiled, session_ctx=None):
            return QueryResult(rows=rows, metric=compiled.metric, unit="件", caliber="模板口径")

        monkeypatch.setattr(graph.MetricQueryEngine, "execute_async", _fake)
        patch_owner_io["spu_owner_rows"] = [("uuid-1", "staff_sales_1")]  # uuid-2 无主
        patch_owner_io["staff"] = [_staff("staff_sales_1", "李芸", "销售部", "专员")]
        out = asyncio.run(graph.ask(
            "销量 Top10 该找谁", {"business_id": "aurora", "role": "finance_owner"},
        ))
        assert out["type"] == "result" and out["metric"] == "volume"
        assert out["rows"][0]["负责人"] == "李芸(销售部·专员)"
        assert out["rows"][1]["负责人"] == "未登记"

    def test_t0_attach_skipped_without_owner_word(self, patch_owner_io, monkeypatch):
        """Q10:无找谁意图的 T0 排行不添列。"""
        rows = [{"name": "极光冲锋衣", "productId": "uuid-1", "stock": 5, "metricScore": 9.0}]

        async def _fake(self, compiled, session_ctx=None):
            return QueryResult(rows=rows, metric=compiled.metric, unit="件", caliber="模板口径")

        monkeypatch.setattr(graph.MetricQueryEngine, "execute_async", _fake)
        patch_owner_io["spu_owner_rows"] = [("uuid-1", "staff_sales_1")]
        patch_owner_io["staff"] = [_staff("staff_sales_1", "李芸", "销售部", "专员")]
        out = asyncio.run(graph.ask(
            "本月销量 Top10", {"business_id": "aurora", "role": "finance_owner"},
        ))
        assert "负责人" not in out["rows"][0]


# ---------- 归因卡附列 + 速览尾拼(Q11/§4) ----------


class TestAttributionOwnerColumn:
    def _ask(self, patch_owner_io, monkeypatch):
        rows = [
            {"品类": "潮流鞋靴", "本期": 1168.0, "上期": 9989.0, "变化": -8821.0},
            {"品类": "户外机能", "本期": 1299.0, "上期": 7892.0, "变化": -6593.0},
            {"品类": "背包收纳", "本期": 0.0, "上期": 9465.0, "变化": -9465.0},
        ]

        async def _fake(self, compiled, session_ctx=None):
            return QueryResult(rows=rows, metric=compiled.metric, unit="元", caliber="组合口径")

        monkeypatch.setattr(graph.MetricQueryEngine, "execute_async", _fake)
        patch_owner_io["mappings"] = [
            ("潮流鞋靴", "staff_sales_lead"),
            ("户外机能", "staff_sales_1"),
            # 背包收纳故意缺行 → 「未登记」
        ]
        patch_owner_io["staff"] = [
            _staff("staff_sales_lead", "陈锋", "销售部", "主管"),
            _staff("staff_sales_1", "李芸", "销售部", "专员"),
        ]
        comp = CompositionQuery(
            metric="net_sales", dimension="category", compare_previous=True,
            time_window={"kind": "last_month"}, source_question="净销售额各品类环比",
        )
        frame = asyncio.run(graph._composed_frame(
            "净销售额各品类环比", comp, {"business_id": "aurora", "role": "finance_owner"},
            graph.MetricQueryEngine(session_ctx={"business_id": "aurora", "role": "finance_owner"}),
            graph.Trace("aurora", "finance_owner", "净销售额各品类环比"),
        ))
        return frame, rows

    def test_owner_column_attached(self, patch_owner_io, monkeypatch):
        _frame, rows = self._ask(patch_owner_io, monkeypatch)
        assert rows[0]["负责人"] == "陈锋(销售部·主管)"
        assert rows[2]["负责人"] == "未登记"

    def test_summary_tail_names_owner(self, patch_owner_io, monkeypatch):
        """主因(变化绝对值最大 = 背包收纳)未登记 → 尾拼缺席;主因已登记时带「找:」。"""
        frame, _ = self._ask(patch_owner_io, monkeypatch)
        # 背包收纳 -9465 是主因且未登记 → 不拼;次因句子不拼(Q11 只拼主因)
        assert "找:" not in frame["summary"]

        # 主因换成已登记的 → 尾拼出现
        rows2 = [
            {"品类": "潮流鞋靴", "本期": 1168.0, "上期": 9989.0, "变化": -8821.0},
            {"品类": "户外机能", "本期": 1299.0, "上期": 7892.0, "变化": -10000.0},
        ]
        patch_owner_io["mappings"].append(("户外机能", "staff_sales_1"))

        async def _fake2(self, compiled, session_ctx=None):
            return QueryResult(rows=rows2, metric=compiled.metric, unit="元", caliber="组合口径")

        monkeypatch.setattr(graph.MetricQueryEngine, "execute_async", _fake2)
        comp = CompositionQuery(
            metric="net_sales", dimension="category", compare_previous=True,
            time_window={"kind": "last_month"}, source_question="净销售额各品类环比",
        )
        frame2 = asyncio.run(graph._composed_frame(
            "净销售额各品类环比", comp, {"business_id": "aurora", "role": "finance_owner"},
            graph.MetricQueryEngine(session_ctx={"business_id": "aurora", "role": "finance_owner"}),
            graph.Trace("aurora", "finance_owner", "净销售额各品类环比"),
        ))
        assert "找:李芸(销售部·专员)" in frame2["summary"]

    def test_non_owner_dimension_no_column(self, patch_owner_io, monkeypatch):
        """brand/region 等未灌键:整列不附(不留「未登记」噪音列)。"""
        rows = [{"brand": "AURORA", "本期": 10.0, "上期": 20.0, "变化": -10.0}]

        async def _fake(self, compiled, session_ctx=None):
            return QueryResult(rows=rows, metric=compiled.metric, unit="元", caliber="组合口径")

        monkeypatch.setattr(graph.MetricQueryEngine, "execute_async", _fake)
        comp = CompositionQuery(
            metric="net_sales", dimension="brand", compare_previous=True,
            time_window={"kind": "last_month"}, source_question="各品牌净销售额环比",
        )
        asyncio.run(graph._composed_frame(
            "各品牌净销售额环比", comp, {"business_id": "aurora", "role": "finance_owner"},
            graph.MetricQueryEngine(session_ctx={"business_id": "aurora", "role": "finance_owner"}),
            graph.Trace("aurora", "finance_owner", "各品牌净销售额环比"),
        ))
        assert "负责人" not in rows[0]


class TestAttributionSummaryTail:
    def test_tail_appended_only_for_registered_top(self):
        rows = [
            {"品类": "A", "本期": 1.0, "上期": 10.0, "变化": -9.0},
            {"品类": "B", "本期": 2.0, "上期": 8.0, "变化": -6.0},
        ]
        result = QueryResult(rows=rows, metric="net_sales", unit="元", caliber="x")
        with_tail = attribution_summary(result, owners={"A": "陈锋(销售部·主管)"})
        assert "主因:A(-9,占变动的 60%),找:陈锋(销售部·主管)" in with_tail
        # 主因未登记(owners 只配了次因)→ 尾拼缺席
        assert "找:" not in attribution_summary(result, owners={"B": "李芸"})

    def test_none_owners_unchanged(self):
        rows = [{"品类": "A", "本期": 1.0, "上期": 10.0, "变化": -9.0}]
        result = QueryResult(rows=rows, metric="net_sales", unit="元", caliber="x")
        assert attribution_summary(result) == attribution_summary(result, owners=None)
