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
        assert r["input"] not in r["output"]  # 问句不出现在输出里(json.dumps 会转义中文,对它断言恒真)


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


def test_claimed_combinatorial_coverage():
    """钉住 60b74cc 声明的组合面:时间×品类交叉 + Top N 解析。"""
    from engine_py.tools_registry.metric_registry import METRIC_SEMANTIC_REGISTRY

    rows = {r["input"]: json.loads(r["output"]) for r in _rows()}
    # 时间窗 × 品类 交叉(此前缺失的声明覆盖)
    cross = rows.get("近 7 天户外机能差评")
    assert cross, "时间×品类交叉样本缺失"
    assert cross["time_window"] == {"kind": "last_7d"}
    assert cross["category"] == "户外机能"
    assert cross["direction"] == METRIC_SEMANTIC_REGISTRY["review_bad"]["direction"]
    # Top N 词面 → 对应 limit(此前 "Top 20" 会被解析成 10)
    assert rows["差评 Top 20"]["limit"] == 20
    assert rows["差评 Top 10"]["limit"] == 10
    # 无 Top 词面 → 默认 5
    assert rows["差评"]["limit"] == 5
    # 全量品类均出现
    cats = {json.loads(r["output"])["category"] for r in _rows()} - {None}
    from engine_py.tools_registry.metric_registry import METRIC_SEMANTIC_REGISTRY
    valid = {"户外机能", "潮流T恤", "下装裤类", "潮流鞋靴", "背包收纳", "露营装备", "衬衫", "配饰", "运动配件"}
    assert cats <= valid


def test_deterministic():
    a = _rows()
    b = _rows()
    assert [(r["input"], r["output"]) for r in a] == [(r["input"], r["output"]) for r in b]
