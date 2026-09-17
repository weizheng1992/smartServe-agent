"""metric_registry 桥(避免 tools_registry ↔ analytics 循环导入)。

analytics 侧经本桥读注册表;08-P2 单一事实源语义不变。
"""

from __future__ import annotations

from importlib import import_module


def metric_semantic_registry() -> dict:
    module = import_module("engine_py.tools_registry.metric_registry")
    return module.METRIC_SEMANTIC_REGISTRY
