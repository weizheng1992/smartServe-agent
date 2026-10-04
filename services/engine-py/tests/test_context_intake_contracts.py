"""context_intake 契约册(2026-10-03 C6 补零直测):PageContext 上行的
勾选封顶/旧数组兼容/内联单号/按族合入意图/人话标题前缀 —— 全纯函数,
此前仅经 graph.ask 间接触达。"""

from __future__ import annotations

from engine_py.analytics.context_intake import (
    inline_order_ids,
    merge_into_intent,
    parse_raw_selection,
    title_prefix,
)
from engine_py.analytics.engine import StructuredQueryIntent


def _intent(metric: str, **kw) -> StructuredQueryIntent:
    return StructuredQueryIntent(metric=metric, **kw)


class TestParseRawSelection:
    def test_typed_dict_form_with_cap(self):
        raw = {"order": [f"O{i}" for i in range(150)],
               "spu": [f"S{i}" for i in range(150)],
               "customer": [f"C{i}" for i in range(150)]}
        orders, spus, custs = parse_raw_selection(raw)
        assert (len(orders), len(spus), len(custs)) == (100, 100, 100)  # 各 ≤100

    def test_legacy_array_form_dual_bind(self):
        """旧数组形态:同时当订单勾选(订单对比)与商品勾选(标准族过滤)。"""
        orders, spus, custs = parse_raw_selection(["A", "B"])
        assert orders == ["A", "B"] and spus == ["A", "B"] and custs == []

    def test_none_is_empty(self):
        assert parse_raw_selection(None) == ([], [], [])


class TestInlineOrderIds:
    def test_extracts_dash_token(self):
        assert inline_order_ids("对比 AURORA-ORD-2026-1737 和 AURORA-ORD-2026-9081") == [
            "AURORA-ORD-2026-1737", "AURORA-ORD-2026-9081",
        ]

    def test_cap_twenty(self):
        ids = [f"AURORA-ORD-2026-{i}" for i in range(30)]
        assert len(inline_order_ids(" ".join(ids))) == 20


class TestMergeIntoIntent:
    def test_spu_selection_enters_filterable_family_only(self):
        hit = merge_into_intent(_intent("volume"), [], ["S1"], [])
        assert hit.entity_slot["spu"] == ["S1"]
        untouched = merge_into_intent(_intent("refund_rate"), [], ["S1"], [])
        assert untouched.entity_slot == {}

    def test_customer_selection_enters_customer_family(self):
        hit = merge_into_intent(_intent("customer_orders"), [], [], ["C1"])
        assert hit.entity_slot["customer"] == ["C1"]

    def test_existing_slot_not_overridden(self):
        intent = _intent("volume", entity_slot={"spu": ["L3-BOUND"]})
        hit = merge_into_intent(intent, [], ["SEL-1"], [])
        assert hit.entity_slot["spu"] == ["L3-BOUND"], "L3/行内绑定优先于页面勾选"

    def test_order_overview_selection_becomes_entity_ids(self):
        hit = merge_into_intent(_intent("order_overview"), ["O1", "O2"], [], [])
        assert hit.entity_ids == ["O1", "O2"]


class TestTitlePrefix:
    def test_single_label(self):
        p = title_prefix(_intent("volume_trend"), ["SPU-1"], [],
                         {"spu": {"SPU-1": "极光冲锋衣"}})
        assert p == "极光冲锋衣"

    def test_multi_labels(self):
        p = title_prefix(_intent("spu_compare"), ["SPU-1", "SPU-2"], [],
                         {"spu": {"SPU-1": "甲", "SPU-2": "乙"}})
        assert p == "甲 等 2 项"

    def test_unknown_ids_fall_back_to_count(self):
        p = title_prefix(_intent("volume_trend"), ["X1", "X2"], [], {})
        assert p == "2 项"
