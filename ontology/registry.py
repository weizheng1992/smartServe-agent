"""本体知识层注册表(ADR-0015,批〇试点)。

声明层(ontology/*.yaml)的加载、校验与编译:

- pydantic v2 模型逐字段校验(类型/闭集/必填/禁未知键),坏声明响亮失败;
- 加载即执行(模块级构建,与 engine semantic_model.py 的 ``SEMANTIC_MODEL = _load()``
  同纪律)——声明漂移让进程起不来,而不是静默运行;
- 编译产物 = 与现行运行时结构同形的 Python 常量(实体/连接/维度投影),
  批一(三面动作闸)与批二(schema 卡/manifest 对拍/generated codegen)的
  消费方从这里取数。

批〇范围:core.yaml + domain/marketing.yaml;与 engine semantic_model 的
parity 由 tests/test_parity_marketing.py 钉死。uv workspace 成员资格与
generated/ 产出随批一首个消费方接入(零调用方不预建装配,ADR-0015 偏差留痕)。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Final

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError, field_validator

ROOT: Final[Path] = Path(__file__).resolve().parent

_ALLOWED_JOIN_TYPES: Final = ("left", "inner")
_ALLOWED_DIMENSION_KINDS: Final = ("enum", "entity", "column", "expression")


# ---------------------------------------------------------------------------
# 声明模型(pydantic v2;冻结 —— 声明是常量,不是运行期配置)
# ---------------------------------------------------------------------------

class _Spec(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class VocabItem(_Spec):
    key: str
    label: str


class CoreFile(_Spec):
    version: int
    domains: list[VocabItem]
    databases: list[VocabItem]
    faces: list[VocabItem]


class EntitySpec(_Spec):
    key: str            # 声明键(= 映射键,由 registry 注入)
    table: str          # 物理表(表列映射锚;批〇 与键同名)
    database: str       # 库路由(必须在 core.databases 闭集内 —— build_ontology 交叉断言)
    alias: str          # SQL 单字母别名(全局唯一)
    label: str
    columns: dict[str, str]   # 列 → 口径注记(与 semantic_model 实体同形)
    notes: str = ""

    @field_validator("columns")
    @classmethod
    def _columns_nonempty(cls, value: dict[str, str]) -> dict[str, str]:
        if not value:
            raise ValueError("columns 必须是非空映射(实体无列即无声称)")
        return value


class JoinSpec(_Spec):
    name: str           # 全局唯一
    table: str          # 被连入实体键(JOIN 侧)
    base: str           # 基实体键(FROM 侧)
    type: str
    condition: str      # 必须同时引用两侧别名(build_ontology 断言)


class DimensionSpec(_Spec):
    label: str
    kind: str
    entity: str
    column: str | None = None
    values: list[str] | None = None
    id_column: str | None = None
    label_column: str | None = None
    description: str | None = None
    expression: str | None = None


class DomainBundle(BaseModel):
    """一个 domain/*.yaml 的编译产物。"""

    model_config = ConfigDict(frozen=True, extra="forbid")
    domain: str
    entities: dict[str, EntitySpec]
    joins: list[JoinSpec]
    dimensions: dict[str, DimensionSpec]


# ---------------------------------------------------------------------------
# 构建(纯函数化,负例测试直接喂坏数据)
# ---------------------------------------------------------------------------

def _read_yaml(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def build_core(data: dict[str, Any]) -> CoreFile:
    if data.get("version") != 1:
        raise ValueError(f"core.yaml: 不支持的版本 {data.get('version')!r}(响亮失败)")
    core = CoreFile(**data)
    for field in ("domains", "databases", "faces"):
        keys = [item.key for item in getattr(core, field)]
        if len(keys) != len(set(keys)):
            raise ValueError(f"core.yaml: {field} 键重复 {keys!r}")
        if not keys:
            raise ValueError(f"core.yaml: {field} 不允许为空(闭集即词汇)")
    return core


def build_ontology(core: CoreFile, domain_datas: list[dict[str, Any]]) -> dict[str, DomainBundle]:
    """校验并编译全部 domain 文件;跨文件断言(闭集/悬空/别名冲突)在此层。"""
    domain_keys = {item.key for item in core.domains}
    database_keys = {item.key for item in core.databases}
    bundles: dict[str, DomainBundle] = {}
    taken_aliases: dict[str, str] = {}   # alias -> entity key
    taken_joins: set[str] = set()

    for data in domain_datas:
        fname = data.get("__file__", "<dict>")
        if data.get("version") != 1:
            raise ValueError(f"{fname}: 不支持的版本 {data.get('version')!r}(响亮失败)")
        domain = data.get("domain")
        if domain not in domain_keys:
            raise ValueError(f"{fname}: 未知领域 {domain!r}(闭集见 core.yaml domains)")
        if domain in bundles:
            raise ValueError(f"{fname}: 领域 {domain!r} 重复声明")

        entities: dict[str, EntitySpec] = {}
        for name, ent in (data.get("entities") or {}).items():
            spec = EntitySpec(key=name, **ent)
            if spec.database not in database_keys:
                raise ValueError(
                    f"{fname}: 实体 {name!r} database {spec.database!r} 不在 core.yaml databases 闭集内"
                )
            if spec.alias in taken_aliases:
                raise ValueError(
                    f"{fname}: 实体 {name!r} 别名 {spec.alias!r} 与 "
                    f"{taken_aliases[spec.alias]!r} 冲突(别名全局唯一)"
                )
            taken_aliases[spec.alias] = name
            entities[name] = spec
        if not entities:
            raise ValueError(f"{fname}: entities 不允许为空(领域无实体即无声称)")

        joins: list[JoinSpec] = []
        for raw in data.get("joins") or []:
            join = JoinSpec(**raw)
            if join.name in taken_joins:
                raise ValueError(f"{fname}: join 名 {join.name!r} 重复")
            if join.type not in _ALLOWED_JOIN_TYPES:
                raise ValueError(f"{fname}: join {join.name!r} type 必须 ∈ {_ALLOWED_JOIN_TYPES}")
            for side in ("table", "base"):
                if getattr(join, side) not in entities:
                    raise ValueError(
                        f"{fname}: join {join.name!r} {side} 悬空引用 {getattr(join, side)!r}"
                        "(批〇 域内引用闭合;跨域 join 随归属域文件落位)"
                    )
            table_alias = entities[join.table].alias
            base_alias = entities[join.base].alias
            if table_alias not in join.condition or base_alias not in join.condition:
                raise ValueError(
                    f"{fname}: join {join.name!r} condition 未同时引用两侧别名 "
                    f"{table_alias}/{base_alias}(condition={join.condition!r})"
                )
            taken_joins.add(join.name)
            joins.append(join)

        dimensions: dict[str, DimensionSpec] = {}
        for dname, raw in (data.get("dimensions") or {}).items():
            dim = DimensionSpec(**raw)
            if dim.entity not in entities:
                raise ValueError(f"{fname}: 维度 {dname!r} 悬空实体引用 {dim.entity!r}")
            if dim.kind not in _ALLOWED_DIMENSION_KINDS:
                raise ValueError(f"{fname}: 维度 {dname!r} kind 必须 ∈ {_ALLOWED_DIMENSION_KINDS}")
            if dim.kind == "enum" and not (dim.column and dim.values):
                raise ValueError(f"{fname}: 枚举维度 {dname!r} 缺 column 或 values")
            if dim.kind == "column" and not dim.column:
                raise ValueError(f"{fname}: 列维度 {dname!r} 缺 column")
            if dim.kind == "expression" and not (dim.expression and dim.description):
                raise ValueError(f"{fname}: 表达式维度 {dname!r} 缺 expression/description")
            if dim.kind == "entity" and not (dim.id_column and dim.label_column):
                raise ValueError(f"{fname}: 实体维度 {dname!r} 缺 id_column/label_column")
            dimensions[dname] = dim

        bundles[domain] = DomainBundle(
            domain=domain, entities=entities, joins=joins, dimensions=dimensions
        )
    return bundles


# ---------------------------------------------------------------------------
# 模块级加载(与 semantic_model.SEMANTIC_MODEL 同纪律:import 即校验)
# ---------------------------------------------------------------------------

_CORE_DATA: Final[dict[str, Any]] = _read_yaml(ROOT / "core.yaml")
CORE: Final[CoreFile] = build_core(_CORE_DATA)

_DOMAIN_DATAS: Final[list[dict[str, Any]]] = [
    _read_yaml(path) | {"__file__": path.name} for path in sorted((ROOT / "domain").glob("*.yaml"))
]
BUNDLES: Final[dict[str, DomainBundle]] = build_ontology(CORE, _DOMAIN_DATAS)

ONTOLOGY_ENTITIES: Final[dict[str, EntitySpec]] = {
    key: spec for bundle in BUNDLES.values() for key, spec in bundle.entities.items()
}


# ---------------------------------------------------------------------------
# 编译投影(消费面;批一批二 从这里接)
# ---------------------------------------------------------------------------

def entity(key: str) -> EntitySpec:
    try:
        return ONTOLOGY_ENTITIES[key]
    except KeyError as err:
        raise KeyError(f"本体未声明实体 {key!r}(已声明: {sorted(ONTOLOGY_ENTITIES)})") from err


def entities_of_domain(domain: str) -> dict[str, EntitySpec]:
    if domain not in BUNDLES:
        raise KeyError(f"本体未声明领域 {domain!r}(已声明: {sorted(BUNDLES)})")
    return dict(BUNDLES[domain].entities)


def semantic_entity_projection(key: str) -> dict[str, Any]:
    """与 engine semantic_model 实体同形的投影(五键);parity 册的对照面。"""
    spec = entity(key)
    return {
        "database": spec.database,
        "alias": spec.alias,
        "label": spec.label,
        "columns": dict(spec.columns),
        "notes": spec.notes,
    }


def semantic_join_projection() -> list[dict[str, Any]]:
    """与 engine semantic_model joins 同形的投影(全领域)。"""
    return [
        {"name": j.name, "table": j.table, "base": j.base, "type": j.type, "condition": j.condition}
        for bundle in BUNDLES.values()
        for j in bundle.joins
    ]


def semantic_dimension_projection() -> dict[str, dict[str, Any]]:
    """与 engine semantic_model dimensions 同形的投影(九键白名单,None 值剔除)。"""
    keep = ("label", "kind", "entity", "column", "values", "id_column", "label_column", "description", "expression")
    out: dict[str, dict[str, Any]] = {}
    for bundle in BUNDLES.values():
        for dname, dim in bundle.dimensions.items():
            dumped = dim.model_dump(exclude_none=True)
            out[dname] = {k: v for k, v in dumped.items() if k in keep}
    return out


__all__ = [
    "CORE",
    "BUNDLES",
    "ONTOLOGY_ENTITIES",
    "EntitySpec",
    "CoreFile",
    "DomainBundle",
    "JoinSpec",
    "DimensionSpec",
    "ValidationError",
    "build_core",
    "build_ontology",
    "entity",
    "entities_of_domain",
    "semantic_entity_projection",
    "semantic_join_projection",
    "semantic_dimension_projection",
]
