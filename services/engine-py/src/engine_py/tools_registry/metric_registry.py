"""指标语义注册表(闭集事实源 = metrics.yaml;本模块只做加载与校验)。

词面/口径外置 YAML:非 Python 改动也能提词面 PR;加载即校验必填键,
坏条目响亮报错(08-P1 纪律延伸到配置面)。改 YAML 后必跑:
  AI_INTENT_L3=off uv run python -m engine_py.intent_flywheel.run_intent_eval  (闸门 95%)
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

# compose 块嵌套形三键(复购率族二段聚合:内层 per 客户预聚合,外层 outer 求占比)
_COMPOSE_NESTED_KEYS = ("per", "pre", "outer")


def _validate_compose(key: str, block: Any) -> None:
    """compose 块形状闸(2026-10-30 组合面单源化随批):平铺形 {measure} 与
    嵌套形 {per, pre, outer} 至少满足其一,拼错键在此响亮失败 —— 否则指标
    被静默挤出组合闭集,运行期才以「未开放组合」的误导文案拒(双轴评审
    Standards②/Spec(c)2 同点,与 compile 块缺键同律)。"""
    if not isinstance(block, dict):
        raise TypeError(f"metrics.yaml: 指标 {key!r} 的 compose 块必须是映射")
    keys = set(block)
    has_nested_partial = any(k in keys for k in _COMPOSE_NESTED_KEYS)
    if "measure" not in keys and not has_nested_partial:
        raise ValueError(
            f"metrics.yaml: 指标 {key!r} compose 块形状不合法:既无平铺度量 measure "
            f"也无嵌套三键 per/pre/outer(实际键 {sorted(keys)},响亮失败不静默入册)"
        )
    if has_nested_partial:
        missing = [k for k in _COMPOSE_NESTED_KEYS if k not in keys]
        if missing:
            raise ValueError(f"metrics.yaml: 指标 {key!r} compose 嵌套形缺键 {missing}")
    for k in sorted(keys):
        if not isinstance(block[k], str) or not block[k].strip():
            raise ValueError(f"metrics.yaml: 指标 {key!r} compose.{k} 必须为非空字符串")


def _load() -> dict[str, dict[str, Any]]:
    with _YAML_PATH.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    registry: dict[str, dict[str, Any]] = {}
    for key, entry in data.items():
        if not isinstance(entry, dict):
            # 类型错走 TypeError(Python 惯例,ruff TRY004);缺键/不一致仍走 ValueError
            raise TypeError(f"metrics.yaml: 指标 {key!r} 条目必须是映射")
        missing = [k for k in _REQUIRED_KEYS if k not in entry]
        if missing:
            raise ValueError(f"metrics.yaml: 指标 {key!r} 缺必填键 {missing}(响亮失败,不静默跳过)")
        if "compose" in entry:
            _validate_compose(key, entry["compose"])
        if entry.get("key") != key:
            raise ValueError(f"metrics.yaml: 指标 {key!r} 的 key 字段与条目名不一致")
        entry.setdefault("conflictGroup", [])
        entry.setdefault("sampleQueries", [])
        registry[key] = entry
    if not registry:
        raise ValueError("metrics.yaml 为空:闭集不允许为空(响亮失败)")
    return registry


METRIC_SEMANTIC_REGISTRY: dict[str, dict[str, Any]] = _load()
