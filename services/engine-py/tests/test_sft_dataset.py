"""SemQL SFT 数据集构建单测(纯逻辑,零 DB/零模型;用户文档路线)。"""

from __future__ import annotations

import json

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "training"))

from sft_dataset import build_sft_rows


def _rows(eval_inputs: set[str] = frozenset()):
    return build_sft_rows(eval_inputs=eval_inputs)


def test_rows_are_valid_semql_json():
    rows = _rows()
    assert rows, "应产出样本"
    for r in rows:
        out = json.loads(r["output"])
        assert out["metric"], r
        assert out["direction"] in ("ASC", "DESC")
        assert "time_window" in out and "category" in out
        assert r["input"] not in json.dumps(r)  # 问句不出现在输出里(自洽)


def test_all_registered_metrics_covered():
    from engine_py.tools_registry.metric_registry import METRIC_SEMANTIC_REGISTRY

    rows = _rows()
    metrics = {json.loads(r["output"])["metric"] for r in rows}
    # order_overview 也入静态 SFT(问句→闭集意图,实体由运行时 PageContext 绑定)
    assert metrics == set(METRIC_SEMANTIC_REGISTRY)


def test_time_window_word_matches_slot():
    rows = _rows()
    # 生成器保证:问句含「近 7 天」⇔ time_window=last_7d(词面与槽位自洽)
    for r in rows:
        q, semql = r["input"], json.loads(r["output"])
        if "近 7 天" in q:
            assert semql["time_window"] == {"kind": "last_7d"}
        if "上个月" in q:
            assert semql["time_window"] == {"kind": "last_month"}


def test_eval_inputs_excluded():
    eval_inputs = {"近 7 天差评"}
    rows = [r for r in _rows(eval_inputs=frozenset(eval_inputs))]
    # 该问句本会生成(近 7 天 + 差评),显式排除后必须消失
    assert all(r["input"] != "近 7 天差评" for r in rows)


def test_deterministic():
    a = _rows()
    b = _rows()
    assert [(r["input"], r["output"]) for r in a] == [(r["input"], r["output"]) for r in b]
