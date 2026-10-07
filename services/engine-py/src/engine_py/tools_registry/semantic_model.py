"""语义模型注册表(ADR-0010:表关联/维度/口径债务的单一事实源 = semantic_model.yaml)。

本模块只做加载与校验,纪律同 metric_registry:缺段/悬空引用/别名冲突一律
raise 响亮失败,不静默跳过。消费方(analytics 编译器/L0 词表/T1 目录/T2 白名单)
经 tools_registry_bridge.semantic_model() 读取。

schema 卡漂移断言(模型实体 ⊆ 编译期安全卡表)在 analytics 侧编译器做 ——
schema_cards 属 analytics 包,本模块保持 tools_registry 内零反向依赖。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .metric_registry import METRIC_SEMANTIC_REGISTRY

_YAML_PATH = Path(__file__).resolve().parent / "semantic_model.yaml"

_ALLOWED_DATABASES = ("merchant_db", "engine_db")
_ALLOWED_JOIN_TYPES = ("left", "inner")
_ALLOWED_DIMENSION_KINDS = ("enum", "entity")


def _load() -> dict[str, Any]:
    with _YAML_PATH.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if data.get("version") != 1:
        raise ValueError(f"semantic_model.yaml: 不支持的模型版本 {data.get('version')!r}(响亮失败)")

    entities: dict[str, Any] = data.get("entities") or {}
    if not entities:
        raise ValueError("semantic_model.yaml: entities 不允许为空(语义层无表即无声称)")
    aliases: set[str] = set()
    for name, ent in entities.items():
        if not isinstance(ent, dict):
            raise TypeError(f"semantic_model.yaml: 实体 {name!r} 必须是映射")
        if ent.get("database") not in _ALLOWED_DATABASES:
            raise ValueError(f"semantic_model.yaml: 实体 {name!r} database 必须 ∈ {_ALLOWED_DATABASES}")
        alias = ent.get("alias")
        if not alias:
            raise ValueError(f"semantic_model.yaml: 实体 {name!r} 缺 alias")
        if alias in aliases:
            raise ValueError(f"semantic_model.yaml: alias {alias!r} 重复(实体 {name!r})")
        aliases.add(alias)
        if not isinstance(ent.get("columns"), dict) or not ent["columns"]:
            raise ValueError(f"semantic_model.yaml: 实体 {name!r} columns 必须是非空映射")

    joins: list[dict[str, Any]] = data.get("joins") or []
    join_names: set[str] = set()
    for join in joins:
        jname = join.get("name")
        if not jname or jname in join_names:
            raise ValueError(f"semantic_model.yaml: join 名缺失或重复: {jname!r}")
        join_names.add(jname)
        if not isinstance(join, dict):
            raise TypeError(f"semantic_model.yaml: join {jname!r} 必须是映射")
        if join.get("type") not in _ALLOWED_JOIN_TYPES:
            raise ValueError(f"semantic_model.yaml: join {jname!r} type 必须 ∈ {_ALLOWED_JOIN_TYPES}")
        for side in ("table", "base"):
            if join.get(side) not in entities:
                raise ValueError(f"semantic_model.yaml: join {jname!r} {side} 悬空引用 {join.get(side)!r}")
        # 键名用 condition 而非 on:PyYAML(YAML 1.1)把裸 on/off 解析成布尔键
        on = str(join.get("condition") or "")
        table_alias = entities[join["table"]]["alias"]
        base_alias = entities[join["base"]]["alias"]
        if table_alias not in on or base_alias not in on:
            raise ValueError(
                f"semantic_model.yaml: join {jname!r} 的 condition 未同时引用两侧别名 "
                f"{table_alias}/{base_alias}(condition={on!r})"
            )

    dimensions: dict[str, Any] = data.get("dimensions") or {}
    for dname, dim in dimensions.items():
        if not isinstance(dim, dict):
            raise TypeError(f"semantic_model.yaml: 维度 {dname!r} 必须是映射")
        if dim.get("kind") not in _ALLOWED_DIMENSION_KINDS:
            raise ValueError(f"semantic_model.yaml: 维度 {dname!r} kind 必须 ∈ {_ALLOWED_DIMENSION_KINDS}")
        if dim.get("entity") not in entities:
            raise ValueError(f"semantic_model.yaml: 维度 {dname!r} 悬空实体引用 {dim.get('entity')!r}")
        if dim["kind"] == "enum":
            if not dim.get("column") or not dim.get("values"):
                raise ValueError(f"semantic_model.yaml: 枚举维度 {dname!r} 缺 column 或 values")
        elif not dim.get("id_column") or not dim.get("label_column"):
            raise ValueError(f"semantic_model.yaml: 实体维度 {dname!r} 缺 id_column/label_column")

    debts: list[dict[str, str]] = data.get("bespoke_debt") or []
    seen: set[str] = set()
    for debt in debts:
        metric = debt.get("metric")
        if not metric or metric in seen:
            raise ValueError(f"semantic_model.yaml: 债务条目 metric 缺失或重复: {metric!r}")
        seen.add(metric)
        if metric not in METRIC_SEMANTIC_REGISTRY:
            raise ValueError(f"semantic_model.yaml: 债务指标 {metric!r} 不在 metrics.yaml 闭集内")
        if not debt.get("reason") or not debt.get("plan"):
            raise ValueError(f"semantic_model.yaml: 债务指标 {metric!r} 缺 reason/plan(债务必须可见可消灭)")

    return data


SEMANTIC_MODEL: dict[str, Any] = _load()
