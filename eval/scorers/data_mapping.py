"""dataMapping 四要素断言(18-D1;promptfoo python assertion)。

配置引用:`{"type": "python", "value": "file://scorers/data_mapping.py:get_assert"}`。
被测面 = engine_py.analytics.engine.MetricQueryEngine.resolve(直调,与
metric_disambiguation 直调 resolver 同模式)。四要素:metric/direction/
timeWindow/limit;expectedKind = intent|clarify|unsupported。
评测集冻结为纯门、永不入训(06-D3;prepare_data 近邻过滤的 blocklist 源)。
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_ENGINE_SRC = _REPO / "services" / "engine-py" / "src"
if str(_ENGINE_SRC) not in sys.path:
    sys.path.insert(0, str(_ENGINE_SRC))


def get_assert(output, context):
    try:
        from engine_py.analytics.engine import Clarify, MetricQueryEngine, UnsupportedQuery

        vars = (context or {}).get("vars") or {}
        question = vars.get("input")
        expected_kind = vars.get("expectedKind", "intent")
        engine = MetricQueryEngine(session_ctx={"business_id": "aurora", "role": "finance_owner"})

        if expected_kind == "unsupported":
            try:
                engine.resolve(question)
                return {"pass": False, "reason": f"「{question}」应 unsupported(严禁静默兜底)", "score": 0}
            except UnsupportedQuery:
                return {"pass": True, "score": 1, "reason": "响亮拒绝(符合预期)"}

        try:
            intent = engine.resolve(question)
        except UnsupportedQuery as err:
            return {"pass": False, "reason": f"意外 unsupported:{err}", "score": 0}

        if expected_kind == "clarify":
            # 引擎 Clarify 是 frozen dataclass(engine.py:75;kind/question/options);
            # 旧 dict+"clarify":True 形状在引擎帧归一时已删除,此处曾检死形状致
            # clarify 用例恒红(2026-10-23 随 data 册入门禁时修复)
            ok = isinstance(intent, Clarify)
            # reason 必须 always-string:promptfoo isGradingResult 对 null reason 整体
            # 拒收(assertions/python.js:66),成功路径回 None 会把通过误翻成执行失败
            return {"pass": ok, "reason": "歧义反问(符合预期)" if ok else "应为歧义反问", "score": 1 if ok else 0}

        if isinstance(intent, Clarify):
            return {"pass": False, "reason": f"意外反问:{intent.question}", "score": 0}

        if not isinstance(intent, dict):
            mismatches = []
            if vars.get("expectedMetric") and intent.metric != vars["expectedMetric"]:
                mismatches.append(f"metric={intent.metric} 期望 {vars['expectedMetric']}")
            if vars.get("expectedDirection") and intent.direction != vars["expectedDirection"]:
                mismatches.append(f"direction={intent.direction} 期望 {vars['expectedDirection']}")
            tw = intent.time_window.get("kind") if intent.time_window else None
            if vars.get("expectedTimeWindow") and tw != vars["expectedTimeWindow"]:
                mismatches.append(f"timeWindow={tw} 期望 {vars['expectedTimeWindow']}")
            if vars.get("expectedLimit") is not None and intent.limit != vars["expectedLimit"]:
                mismatches.append(f"limit={intent.limit} 期望 {vars['expectedLimit']}")
            return {
                "pass": not mismatches,
                "reason": ";".join(mismatches) if mismatches else "四要素全对齐",
                "score": 1 if not mismatches else 0,
            }

        return {"pass": False, "reason": f"意外反问:{intent}", "score": 0}
    except Exception as err:  # noqa: BLE001 — 评测器必须把内部异常也翻成不通过
        return {"pass": False, "reason": f"scorer 内部错误:{err}", "score": 0}
