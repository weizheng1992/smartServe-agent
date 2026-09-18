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
        from engine_py.analytics.engine import MetricQueryEngine, UnsupportedQuery

        vars = (context or {}).get("vars") or {}
        question = vars.get("input")
        expected_kind = vars.get("expectedKind", "intent")
        engine = MetricQueryEngine(session_ctx={"business_id": "aurora", "role": "finance_owner"})

        if expected_kind == "unsupported":
            try:
                engine.resolve(question)
                return {"pass": False, "reason": f"「{question}」应 unsupported(严禁静默兜底)", "score": 0}
            except UnsupportedQuery:
                return {"pass": True, "score": 1}

        try:
            intent = engine.resolve(question)
        except UnsupportedQuery as err:
            return {"pass": False, "reason": f"意外 unsupported:{err}", "score": 0}

        if expected_kind == "clarify":
            ok = isinstance(intent, dict) and intent.get("clarify") is True
            return {"pass": ok, "reason": "应为歧义反问" if not ok else None, "score": 1 if ok else 0}

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
            return {"pass": not mismatches, "reason": ";".join(mismatches) or None, "score": 1 if not mismatches else 0}

        return {"pass": False, "reason": f"意外反问:{intent}", "score": 0}
    except Exception as err:  # noqa: BLE001 — 评测器必须把内部异常也翻成不通过
        return {"pass": False, "reason": f"scorer 内部错误:{err}", "score": 0}
