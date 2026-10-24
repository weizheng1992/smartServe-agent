"""意图评测集注册表契约(eval-gap-2026-10 07 号票)。

572 行中 82%(slot_generated 406 + t2_longtail 65)来自一次性手工扩充、生成器
未入库 —— ``gen_intent_cases`` 重跑曾可静默覆写回 ~101 行(灭顶)。双护栏:
①本册钉结构不变量(行数单调地板:有意缩减须有意识地改地板并评审,同
ontology 一致性册纪律;question 全唯一;source 六源闭集;每行至少一个期望键);
②``common.write_jsonl`` 覆写护栏(存量行数 > 载荷行数即拒,--force 显式放行)。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from engine_py.intent_flywheel.common import EVAL_CASES_PATH, write_jsonl

# 单调地板(2026-10-24 = 572):扩集只增;有意缩减(去重/清理)须显式改此数并评审
LINE_FLOOR = 572
_SOURCES = {"registry", "edge", "entity", "longtail", "slot_generated", "t2_longtail"}
_EXPECT_KEYS = ("expect_metric", "expect_clarify", "expect_unsupported",
                "expect_direction", "expect_time", "expect_chart")


def _rows() -> list[dict]:
    return [json.loads(line) for line in EVAL_CASES_PATH.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_registry_line_floor_monotonic():
    """行数地板:静默缩水(生成器回退/误删)即红;扩集免维护。"""
    rows = _rows()
    assert len(rows) >= LINE_FLOOR, f"意图评测集缩水至 {len(rows)} 行(地板 {LINE_FLOOR})—— 生成器回退灭顶?"


def test_questions_unique():
    rows = _rows()
    questions = [r["question"] for r in rows]
    assert len(questions) == len(set(questions)), "question 重复(评测集去重不变量被破)"


def test_source_closed_set():
    bad = {r.get("source") for r in _rows()} - _SOURCES
    assert not bad, f"source 闭集外出现: {bad}"


def test_every_case_has_expectation():
    rows = _rows()
    no_expect = [r["question"] for r in rows if not any(r.get(k) is not None for k in _EXPECT_KEYS)]
    assert not no_expect, f"无任何期望键的用例: {no_expect[:5]}"


def test_write_jsonl_shrink_guard(tmp_path: Path):
    """覆写护栏:存量行数 > 载荷行数拒绝盲覆写;--force(allow_shrink)放行。"""
    target = tmp_path / "cases.jsonl"
    write_jsonl([{"q": f"q{i}"} for i in range(5)], target)
    with pytest.raises(RuntimeError, match="覆写护栏"):
        write_jsonl([{"q": "only-one"}], target)
    write_jsonl([{"q": "only-one"}], target, allow_shrink=True)
    assert len(target.read_text(encoding="utf-8").splitlines()) == 1
    # 增长写不受护栏影响
    write_jsonl([{"q": f"n{i}"} for i in range(3)], target)
    assert len(target.read_text(encoding="utf-8").splitlines()) == 3
