"""本体知识层注册表(ADR-0015;批〇试点 + 批一四域全量/动作面/codegen)。

声明层(ontology/*.yaml)的加载、校验、编译与代码生成:

- pydantic v2 模型逐字段校验(类型/必填/禁未知键),坏声明响亮失败;
- 加载即执行(模块级构建,与 engine semantic_model.py 同纪律)——声明漂移
  让进程起不来,而不是静默运行;
- 两阶段构建:先收集全域实体(库路由/别名全局唯一),再对 join/维度做
  **全局**校验 —— join 声明在 base 侧(FROM 表)所属域,table 可跨域引用;
- `emit_python()` 把动作面与资金闸缺省编译为
  ``services/engine-py/src/engine_py/ontology_generated.py``(自包含、零依赖,
  engine/gateway 运行时消费该生成物而非本包;漂移门 = test_codegen_sync)。

消费方:批一 gatekeeper/step_execution_engine/approval_actions;批二
schema 卡与 manifest 对拍(经 semantic_*_projection);批三 CI regen 门。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Final

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError, field_validator

ROOT: Final[Path] = Path(__file__).resolve().parent
GENERATED_PY_PATH: Final[Path] = (
    ROOT.parent / "services" / "engine-py" / "src" / "engine_py" / "ontology_generated.py"
)

_ALLOWED_JOIN_TYPES: Final = ("left", "inner")
_ALLOWED_DIMENSION_KINDS: Final = ("enum", "entity", "column", "expression")
# 表达式维度禁单冒号:SQLAlchemy text() 会当绑定参数吞掉(semantic_model 同款守卫)
_SINGLE_COLON_RE: Final = re.compile(r"(?<!:):(?!:)")


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
    table: str          # 物理表(表列映射锚;批一与键同名)
    database: str       # 库路由(core.databases 闭集 —— build_ontology 交叉断言)
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
    table: str          # 被连入实体键(JOIN 侧;可跨域引用)
    base: str           # 基实体键(FROM 侧;join 声明在 base 所属域文件)
    type: str
    condition: str      # 必须同时引用两侧别名(build_ontology 全局断言)


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


class ActionSpec(_Spec):
    label: str
    faces: list[str]          # ⊆ core.faces(build_application 断言)
    permission: str | None = None   # RBAC perm 锚(None = 面身份闸即足;真实性断言在契约册)
    roles: list[str]          # resolved_by_role 白名(gatekeeper 归一化的子集)
    requires_approval_id: bool = True
    notes: str = ""


class PolicyDefaults(_Spec):
    refund_auto_approval_limit: float


class ApplicationFile(_Spec):
    version: int
    actions: dict[str, ActionSpec]
    defaults: PolicyDefaults
    ts_ghost_actions: list[str] = []   # 冻结面已知差异(packages/types approval.ts)


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
    """两阶段校验并编译全部 domain 文件。

    阶段一:逐文件收集实体(域闭集/库闭集/别名全局唯一);
    阶段二:对 join/维度做**全局**校验(跨域引用在全域实体表上解析,
    悬空引用与 condition 别名缺失在此层响亮失败)。
    """
    domain_keys = {item.key for item in core.domains}
    database_keys = {item.key for item in core.databases}

    raw_bundles: list[tuple[str, dict[str, EntitySpec], list[JoinSpec], dict[str, DimensionSpec]]] = []
    bundles: dict[str, DomainBundle] = {}
    taken_aliases: dict[str, str] = {}   # alias -> entity key(全域唯一)
    all_entities: dict[str, EntitySpec] = {}

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
            all_entities[name] = spec
        if not entities:
            raise ValueError(f"{fname}: entities 不允许为空(领域无实体即无声称)")

        joins: list[JoinSpec] = [JoinSpec(**raw) for raw in data.get("joins") or []]
        dimensions = {
            dname: DimensionSpec(**raw) for dname, raw in (data.get("dimensions") or {}).items()
        }
        raw_bundles.append((fname, entities, joins, dimensions))
        bundles[domain] = DomainBundle(
            domain=domain, entities=entities, joins=joins, dimensions=dimensions
        )

    # ---- 阶段二:全局校验(join/维度引用在全域实体表上解析) ----
    taken_joins: set[str] = set()
    for fname, entities, joins, dimensions in raw_bundles:
        for join in joins:
            if join.name in taken_joins:
                raise ValueError(f"{fname}: join 名 {join.name!r} 重复")
            if join.type not in _ALLOWED_JOIN_TYPES:
                raise ValueError(f"{fname}: join {join.name!r} type 必须 ∈ {_ALLOWED_JOIN_TYPES}")
            for side in ("table", "base"):
                if getattr(join, side) not in all_entities:
                    raise ValueError(
                        f"{fname}: join {join.name!r} {side} 悬空引用 {getattr(join, side)!r}"
                        "(全域实体表内无此键;跨域引用须先在归属域文件声明实体)"
                    )
            table_alias = all_entities[join.table].alias
            base_alias = all_entities[join.base].alias
            if table_alias not in join.condition or base_alias not in join.condition:
                raise ValueError(
                    f"{fname}: join {join.name!r} condition 未同时引用两侧别名 "
                    f"{table_alias}/{base_alias}(condition={join.condition!r})"
                )
            taken_joins.add(join.name)

        for dname, dim in dimensions.items():
            if dim.entity not in all_entities:
                raise ValueError(f"{fname}: 维度 {dname!r} 悬空实体引用 {dim.entity!r}")
            if dim.kind not in _ALLOWED_DIMENSION_KINDS:
                raise ValueError(f"{fname}: 维度 {dname!r} kind 必须 ∈ {_ALLOWED_DIMENSION_KINDS}")
            if dim.kind == "enum" and not (dim.column and dim.values):
                raise ValueError(f"{fname}: 枚举维度 {dname!r} 缺 column 或 values")
            if dim.kind == "column" and not dim.column:
                raise ValueError(f"{fname}: 列维度 {dname!r} 缺 column")
            if dim.kind == "expression":
                if not (dim.expression and dim.description):
                    raise ValueError(f"{fname}: 表达式维度 {dname!r} 缺 expression/description")
                if _SINGLE_COLON_RE.search(dim.expression):
                    raise ValueError(
                        f"{fname}: 表达式维度 {dname!r} 含单冒号 —— SQLAlchemy text() 会当"
                        "绑定参数吞掉;只允许 '::' 类型转换"
                    )
            if dim.kind == "entity" and not (dim.id_column and dim.label_column):
                raise ValueError(f"{fname}: 实体维度 {dname!r} 缺 id_column/label_column")
    return bundles


def build_application(core: CoreFile, data: dict[str, Any]) -> ApplicationFile:
    if data.get("version") != 1:
        raise ValueError(f"application/actions.yaml: 不支持的版本 {data.get('version')!r}(响亮失败)")
    app = ApplicationFile(**{k: v for k, v in data.items() if k != "version"} | {"version": 1})
    face_keys = {item.key for item in core.faces}
    for name, spec in app.actions.items():
        unknown = set(spec.faces) - face_keys
        if unknown:
            raise ValueError(f"application/actions.yaml: 动作 {name!r} 声明未知面 {sorted(unknown)}(闭集见 core.yaml faces)")
        if not spec.faces:
            raise ValueError(f"application/actions.yaml: 动作 {name!r} faces 不允许为空(无面即无曝光)")
        if not spec.roles:
            raise ValueError(f"application/actions.yaml: 动作 {name!r} roles 白名为空")
    ghosts = set(app.ts_ghost_actions)
    overlap = ghosts & set(app.actions)
    if overlap:
        raise ValueError(f"application/actions.yaml: ts_ghost_actions 与受理集重叠 {sorted(overlap)}(幽灵 = 后端不受理)")
    return app


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

_APPLICATION_DATA: Final[dict[str, Any]] = _read_yaml(ROOT / "application" / "actions.yaml")
APPLICATION: Final[ApplicationFile] = build_application(CORE, _APPLICATION_DATA)
ACTION_SPECS: Final[dict[str, ActionSpec]] = dict(APPLICATION.actions)

TS_GHOST_ACTIONS: Final[frozenset[str]] = frozenset(APPLICATION.ts_ghost_actions)
DEFAULT_REFUND_AUTO_APPROVAL_LIMIT: Final[float] = APPLICATION.defaults.refund_auto_approval_limit


def _face_actions(face: str) -> frozenset[str]:
    return frozenset(name for name, spec in ACTION_SPECS.items() if face in spec.faces)


CUSTOMER_ACTIONS: Final[frozenset[str]] = _face_actions("customer")
OPERATOR_ACTIONS: Final[frozenset[str]] = _face_actions("operator")
STAFF_REVIEW_ACTIONS: Final[frozenset[str]] = _face_actions("staff_review")
SPI_ACTIONS: Final[frozenset[str]] = _face_actions("spi")
ENGINE_HANDLED_ACTIONS: Final[frozenset[str]] = frozenset(ACTION_SPECS)


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


# ---------------------------------------------------------------------------
# 代码生成(批一):动作面 + 资金闸缺省 → engine_py.ontology_generated
# ---------------------------------------------------------------------------

def _py_str(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def emit_python() -> str:
    """确定性发射 engine_py/ontology_generated.py 全文(禁时间戳,保 diff 稳定)。"""
    lines: list[str] = [
        '"""本体知识层编译产物 —— GENERATED,手改无效(漂移门 test_codegen_sync 钉死)。',
        "",
        "源头:ontology/{core,domain,application}/*.yaml,经 ontology/registry.py 编译;",
        "再生成:仓库根执行 `services/.venv/bin/python ontology/registry.py --write`。",
        "消费方(ADR-0015 批一):engine approvals/gatekeeper(受理集+早退 400+阈值缺省)、",
        "graph/nodes/step_execution_engine(免签限额)、gateway approval_actions(四词表派生再出口)。",
        '"""',
        "",
        "from __future__ import annotations",
        "",
        "from typing import Final",
        "",
        "# --- 动作面(application/actions.yaml)--------------------------------------",
        "APPROVAL_ACTIONS: Final[dict[str, dict[str, object]]] = {",
    ]
    for name, spec in ACTION_SPECS.items():
        lines.append(f"    {_py_str(name)}: {{")
        lines.append(f"        'label': {_py_str(spec.label)},")
        lines.append(f"        'faces': {tuple(spec.faces)!r},")
        lines.append(f"        'permission': {spec.permission!r},")
        lines.append(f"        'roles': {tuple(spec.roles)!r},")
        lines.append(f"        'requires_approval_id': {spec.requires_approval_id!r},")
        lines.append(f"        'notes': {_py_str(spec.notes)},")
        lines.append("    },")
    lines.extend([
        "}",
        "",
        "CUSTOMER_ACTIONS: Final[frozenset[str]] = " + f"frozenset({sorted(CUSTOMER_ACTIONS)!r})",
        "OPERATOR_ACTIONS: Final[frozenset[str]] = " + f"frozenset({sorted(OPERATOR_ACTIONS)!r})",
        "STAFF_REVIEW_ACTIONS: Final[frozenset[str]] = " + f"frozenset({sorted(STAFF_REVIEW_ACTIONS)!r})",
        "SPI_ACTIONS: Final[frozenset[str]] = " + f"frozenset({sorted(SPI_ACTIONS)!r})",
        "ENGINE_HANDLED_ACTIONS: Final[frozenset[str]] = frozenset(APPROVAL_ACTIONS)",
        "TS_GHOST_ACTIONS: Final[frozenset[str]] = " + f"frozenset({sorted(TS_GHOST_ACTIONS)!r})",
        "",
        "# --- 资金闸缺省(application/actions.yaml defaults)-------------------------",
        "# 考古注记:历史六处分叉 50/100 —— 统一 50(收紧方向,ADR-0015 决策 4);",
        "# 租户级显式覆写(nike=150/adidas=120)通道语义不变,本常量只钉缺省。",
        f"DEFAULT_REFUND_AUTO_APPROVAL_LIMIT: Final[float] = {DEFAULT_REFUND_AUTO_APPROVAL_LIMIT!r}",
        "",
        "__all__ = [",
        '    "APPROVAL_ACTIONS",',
        '    "CUSTOMER_ACTIONS",',
        '    "DEFAULT_REFUND_AUTO_APPROVAL_LIMIT",',
        '    "ENGINE_HANDLED_ACTIONS",',
        '    "OPERATOR_ACTIONS",',
        '    "SPI_ACTIONS",',
        '    "STAFF_REVIEW_ACTIONS",',
        '    "TS_GHOST_ACTIONS",',
        "]",
        "",
    ])
    return "\n".join(lines)


def write_generated(path: Path = GENERATED_PY_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(emit_python(), encoding="utf-8")
    return path


if __name__ == "__main__":  # pragma: no cover - 手动再生成入口
    import sys

    if "--write" in sys.argv:
        print(f"written: {write_generated()}")
    else:
        sys.stdout.write(emit_python())
