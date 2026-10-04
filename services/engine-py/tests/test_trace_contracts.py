"""trace 契约册(2026-10-03 C6 补零直测):落库行装配是纯函数
(build_row,行形状契约唯一出处);落库 IO 面失败静默不反噬主流程。"""

from __future__ import annotations

import json

from engine_py.analytics.trace import Trace, new_trace_id


def test_trace_id_shape():
    tid = new_trace_id()
    assert tid.startswith("tr_") and len(tid) == len("tr_") + 12


def test_build_row_contract():
    t = Trace("aurora", "sales_viewer", "销售额排行")
    t.add_layer("L0", metric="gmv")
    t.add_layer("L2", similarity=0.93)
    row = t.build_row("result", final_metric="gmv", final_method="template",
                      sql_template="gmv", row_count=5, cache_hit=False)
    assert row["business_id"] == "aurora" and row["role"] == "sales_viewer"
    assert row["trace_id"] == t.trace_id and row["question"] == "销售额排行"
    layers = json.loads(row["layers"])
    assert layers == [{"layer": "L0", "metric": "gmv"}, {"layer": "L2", "similarity": 0.93}]
    assert row["final_metric"] == "gmv" and row["final_method"] == "template"
    assert row["row_count"] == 5 and row["cache_hit"] is False
    assert row["outcome"] == "result" and isinstance(row["duration_ms"], int)


def test_build_row_question_truncated_at_200():
    t = Trace("aurora", "finance_owner", "长" * 500)
    row = t.build_row("unsupported")
    assert row["question"] == "长" * 200


def test_build_row_final_method_falls_back_to_collected():
    t = Trace("aurora", "finance_owner", "q")
    t.method = "scenario"
    assert t.build_row("multi")["final_method"] == "scenario"
