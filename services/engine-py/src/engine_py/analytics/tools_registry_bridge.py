"""metric_registry 桥(避免 tools_registry ↔ analytics 循环导入)。

analytics 侧经本桥读注册表;08-P2 单一事实源语义不变。
"""

from __future__ import annotations

from importlib import import_module


def metric_semantic_registry() -> dict:
    module = import_module("engine_py.tools_registry.metric_registry")
    return module.METRIC_SEMANTIC_REGISTRY


def semantic_model() -> dict:
    """语义模型(ADR-0010:实体/join/维度/债务清单单一事实源)。"""
    module = import_module("engine_py.tools_registry.semantic_model")
    return module.SEMANTIC_MODEL


def valid_dealing_where(alias: str = "o") -> str:
    """有效成交谓词(单一事实源,2026-10-07 架构评审候选二收口):退款/取消单
    不计入真实成交 —— 此前以 SQL 字面散落 semantic_compiler ×3、
    engine._compile_bespoke_family ×8、order_domain 排行工具 ×1,加状态或改
    口径要人肉同步 12 处。状态集与 order_domain._ORDER_STATUS_ZH / 维度枚举
    的互验由 test_metric_registry 钉。"""
    module = import_module("engine_py.tools_registry.semantic_model")
    return module.valid_dealing_where(alias)
