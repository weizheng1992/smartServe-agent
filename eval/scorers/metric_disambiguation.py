"""指标语义消歧断言(promptfoo python assertion)— 移植 scorers/metricDisambiguation.scorer.ts。

配置引用:`{"type": "python", "value": "file://scorers/metric_disambiguation.py:get_assert"}`。
消歧预言机走 eval/lib/metric_resolver.py(f9e737a 删 engine 侧
MetricSemanticResolver 后的 eval 侧 1:1 重建,数据读 metrics.yaml 注册表)。
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_ENGINE_SRC = _REPO / "services" / "engine-py" / "src"
if str(_ENGINE_SRC) not in sys.path:
    sys.path.insert(0, str(_ENGINE_SRC))
_EVAL_LIB = _REPO / "eval" / "lib"
if str(_EVAL_LIB) not in sys.path:
    sys.path.insert(0, str(_EVAL_LIB))


def get_assert(output, context):
    try:
        from metric_resolver import resolve

        vars = (context or {}).get("vars") or {}
        input = vars.get("input")
        expected_metric = vars.get("expectedMetric")
        expected_ambiguity = vars.get("expectedAmbiguity")
        expected_conflict_group = vars.get("expectedConflictGroup")

        if not input or not expected_metric:
            return {
                "pass": True,
                "score": 1.0,
                "reason": "No input or expectedMetric specified, skipping metric disambiguation check",
            }

        resolution = resolve(input)

        is_metric_match = resolution["primaryMetric"]["key"] == expected_metric
        is_ambiguity_match = expected_ambiguity is None or resolution["hasAmbiguity"] == expected_ambiguity
        is_conflict_group_match = expected_conflict_group is None or any(
            m["key"] == expected_conflict_group for m in resolution["conflictMetrics"]
        )

        if is_metric_match and is_ambiguity_match and is_conflict_group_match:
            return {
                "pass": True,
                "score": 1.0,
                "reason": (
                    f"Successfully resolved metric '{resolution['primaryMetric']['key']}' "
                    f"(Ambiguity: {resolution['hasAmbiguity']}) matching expectation '{expected_metric}'."
                ),
            }

        return {
            "pass": False,
            "score": 0.0,
            "reason": (
                f"Metric mismatch. Expected: metric={expected_metric}, ambiguity={expected_ambiguity}. "
                f"Got: metric={resolution['primaryMetric']['key']}, ambiguity={resolution['hasAmbiguity']}"
            ),
        }
    except Exception as err:  # noqa: BLE001
        return {"pass": False, "score": 0.0, "reason": f"Error in metricDisambiguation scorer: {err}"}
