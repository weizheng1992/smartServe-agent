"""意图飞轮包内可导入冒烟(架构评审候选#2 收编钉,2026-10-02)。

七个 CLI module 必须零路径 hack、常规 import 即可导入 —— 这条 seam 由本
测试钉死:谁往包里加脚本又带 sys.path 引导(或 import 侧产生环境副作用),
此处红。run_intent_eval 的 AI_INTENT_L3 缺省在 main() 内 setdefault
(读取点 analytics/llm_intent 惰性查 env),import 侧零环境副作用。
"""

from __future__ import annotations

import importlib

import pytest

_FLYWHEEL_MODULES = (
    "backhaul_unanswered",
    "backfill_outcome_from_rules",
    "calibrate_semantic_routes",
    "export_intent_data",
    "gen_intent_cases",
    "review_badcase",
    "run_intent_eval",
)


@pytest.mark.parametrize("name", _FLYWHEEL_MODULES)
def test_flywheel_module_importable(name: str) -> None:
    module = importlib.import_module(f"engine_py.intent_flywheel.{name}")
    assert module.__doc__, "包内 CLI 须带模块 docstring(用法行是唯一入口文档)"
