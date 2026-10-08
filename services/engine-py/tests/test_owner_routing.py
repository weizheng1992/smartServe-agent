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
        "spus": [],  # (spu_code, title)
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
        "FROM merchant_spus": list(state["spus"]),
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
