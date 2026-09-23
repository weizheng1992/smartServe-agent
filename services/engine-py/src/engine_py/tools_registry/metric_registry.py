"""指标语义注册表(闭集事实源 = metrics.yaml;本模块只做加载与校验)。

词面/口径外置 YAML:非 Python 改动也能提词面 PR;加载即校验必填键,
坏条目响亮报错(08-P1 纪律延伸到配置面)。改 YAML 后必跑:
  AI_INTENT_L3=off uv run python scripts/run_intent_eval.py  (闸门 95%)
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

_YAML_PATH = Path(__file__).resolve().parent / "metrics.yaml"

_REQUIRED_KEYS = (
    "key", "label", "description", "domain", "unit",
    "direction", "synonyms", "permissionTag",
)


def _load() -> dict[str, dict[str, Any]]:
    with _YAML_PATH.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    registry: dict[str, dict[str, Any]] = {}
    for key, entry in data.items():
        if not isinstance(entry, dict):
            raise ValueError(f"metrics.yaml: 指标 {key!r} 条目必须是映射")
        missing = [k for k in _REQUIRED_KEYS if k not in entry]
        if missing:
            raise ValueError(f"metrics.yaml: 指标 {key!r} 缺必填键 {missing}(响亮失败,不静默跳过)")
        if entry.get("key") != key:
            raise ValueError(f"metrics.yaml: 指标 {key!r} 的 key 字段与条目名不一致")
        entry.setdefault("aliases", [])
        entry.setdefault("conflictGroup", [])
        entry.setdefault("sampleQueries", [])
        entry.setdefault("availableDimensions", [])
        registry[key] = entry
    if not registry:
        raise ValueError("metrics.yaml 为空:闭集不允许为空(响亮失败)")
    return registry


METRIC_SEMANTIC_REGISTRY: dict[str, dict[str, Any]] = _load()
