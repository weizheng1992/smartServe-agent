"""T1 组合通道(ADR-0010 分层信任架构):LLM 在语义层内自由组合,
编译器确定性拼 SQL —— 长尾覆盖主力,信任级介于 verified 与 explored 之间。

铁律精神不变:LLM 只产「组合查询」(认证指标 × 声明维度 × 过滤 × 时间平移),
绝不产 SQL 文本;一切组合必须落在 semantic_model.yaml 与 metrics.yaml 闭集内,
违者响亮失败落 agent_unanswered(与 L3 同纪律,严禁近似兜底)。

`AI_T1_COMPOSE=off|on`(默认 off)灰度开关;角色权限 = 组成指标 ∈
allowed_metrics_for_role 闭集交集(不新增权限面)。
compare_previous 时间平移算子:本期 vs 上期并排(泛化自 gmv_mom/attribution
双期 CTE 模式),是 ADR-0005「模板矩阵化」欠账的机制化偿还。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # 运行时惰性 import(engine ↔ composition 防环)
    from .engine import CompiledSQL


def composition_enabled() -> bool:
    return os.environ.get("AI_T1_COMPOSE", "off") == "on"


@dataclass(frozen=True)
class CompositionQuery:
    """语义层组合查询(闭集可表示的组合空间;LLM 只填充此结构)。"""

    metric: str  # 认证指标键(metrics.yaml 闭集 ∩ 角色权限)
    dimension: str | None = None  # 语义模型维度键(category/order_status/spu/customer/promotion)
    direction: str = "DESC"
    limit: int = 10
    time_window: dict | None = None  # 同 StructuredQueryIntent:kind ∈ last_month/last_7d/last_30d/last_months
    compare_previous: bool = False  # 时间平移:本期 vs 上期并排
    category: str | None = None  # 便捷过滤(枚举维度值闭集)
    entity_kind: str | None = None  # 实体提及种类(spu/customer/promotion)
    entity_mention: str | None = None  # 实体提及原文(落库解析确定性,用户输入不进 SQL)
    source_question: str = ""


class CompositionRejected(Exception):
    """组合查询落在语义层闭集之外(响亮失败;呈现层归 unsupported,落库飞轮)。"""


# ---------------- 解析(LLM 组合理解;grounding = 语义模型目录) ----------------

def composition_catalog() -> str:
    """组合目录(进提示词的闭集清单):认证指标 × 维度 × 时间窗 × 平移开关。"""
    from .tools_registry_bridge import metric_semantic_registry, semantic_model

    registry = metric_semantic_registry()
    model = semantic_model()
    metric_lines = [
        f"- {key}: {entry['label']}(单位 {entry['unit']})"
        for key, entry in registry.items()
    ]
    dim_lines = []
    for dkey, dim in model["dimensions"].items():
        if dim["kind"] == "enum":
            dim_lines.append(f"- {dkey}({dim['label']}):取值 {'/'.join(dim['values'])}")
        else:
            dim_lines.append(f"- {dkey}({dim['label']}):实体维度,问句中的具体名称会确定性绑定")
    return "指标目录:\n" + "\n".join(metric_lines) + "\n维度目录:\n" + "\n".join(dim_lines)


async def compose_resolve(question: str, allowed: list[str] | None) -> CompositionQuery:
    """问句 → CompositionQuery(LLM 结构化输出;闭集校验在此之后)。

    校验不合格(闭集外指标/维度/品类)抛 CompositionRejected —— 响亮失败,
    绝不静默映射到最近似组合(08-P1;ADR-0005 否决项同源)。
    """
    import json as _json

    from .llm_intent import get_chat_model

    system = (
        "你是商户数据问答的组合规划器。把问题解析为「指标 × 维度 × 过滤 × 时间窗」的语义层组合。\n"
        "规则:\n"
        "- 你的职责是【组合】:优先产出「指标 × 维度」配对(如 品类×销售额 → metric=gmv, dimension=category);\n"
        "  不要映射到目录中的成品指标(customer_spend_top/order_overview/category_gmv_top 等)——\n"
        "  闭集路由在你之前已经试过并失败,再映射成品指标等于重复失败\n"
        "- metric 只能取指标目录中的键;dimension 只能取维度目录中的键;问题确实不含维度拆分时才留空\n"
        "- 时间窗 kind ∈ last_month/last_7d/last_30d/last_months(附 n);问句出现「近/最近/上个月/N 个月」必须提取;\n"
        "  问「同比/环比/上期对比/变化」时 compare_previous=true\n"
        "- 问题里的具体商品/客户/活动名称写进 entity_mention(附 entity_kind=spu/customer/promotion),不要改写;\n"
        "  出现目录枚举中的品类词(衬衫/配饰等)写进 category\n"
        "- 组合不出目录内的查询 → metric 输出 \"__unsupported__\",绝不猜\n"
        + composition_catalog()
    )
    user = _json.dumps({"question": question, "allowed_metrics": allowed}, ensure_ascii=False)
    from pydantic import BaseModel

    class _ComposeOut(BaseModel):
        metric: str
        dimension: str | None = None
        direction: str = "DESC"
        limit: int = 10
        time_kind: str | None = None
        time_n: int | None = None
        compare_previous: bool = False
        category: str | None = None
        entity_kind: str | None = None
        entity_mention: str | None = None

    model = get_chat_model().with_structured_output(_ComposeOut)
    from langchain_core.messages import HumanMessage, SystemMessage

    out: _ComposeOut = await model.ainvoke([SystemMessage(content=system), HumanMessage(content=user)])
    return _validate(out, allowed, question)


def _validate(out: Any, allowed: list[str] | None, question: str) -> CompositionQuery:
    """闭集校验:目录外任何成分都响亮拒绝(宁可 unsupported,不做近似组合)。"""
    from .tools_registry_bridge import metric_semantic_registry, semantic_model

    if out.metric == "__unsupported__" or out.metric not in metric_semantic_registry():
        raise CompositionRejected(f"指标 {out.metric!r} 不在语义层目录内")
    if allowed is not None and out.metric not in allowed:
        raise CompositionRejected(f"当前角色无权查看指标 {out.metric!r}")
    model = semantic_model()
    dims = model["dimensions"]
    if out.dimension is not None and out.dimension not in dims:
        raise CompositionRejected(f"维度 {out.dimension!r} 不在语义层目录内")
    if out.category is not None:
        enum_values = dims.get("category", {}).get("values") or []
        if out.category not in enum_values:
            raise CompositionRejected(f"品类 {out.category!r} 不在枚举闭集内")
    if out.entity_kind is not None and out.entity_kind not in ("spu", "customer", "promotion"):
        raise CompositionRejected(f"实体种类 {out.entity_kind!r} 不在闭集内")
    time_window = None
    if out.time_kind in ("last_month", "last_7d", "last_30d", "last_months"):
        time_window = {"kind": out.time_kind}
        if out.time_kind == "last_months":
            time_window["n"] = min(max(int(out.time_n or 6), 1), 24)
    # 品类过滤挂在 SPU 维度表上:维度是客户/活动/订单状态时没有 s 别名,拒绝
    # (组合合法性 = join 图可达,宁可响亮不做错组合)
    if out.category is not None and out.dimension not in (None, "category", "spu"):
        raise CompositionRejected(f"品类过滤与维度 {out.dimension!r} 不可组合(品类过滤仅支持商品/品类维度)")
    return CompositionQuery(
        metric=out.metric,
        dimension=out.dimension,
        direction="ASC" if out.direction == "ASC" else "DESC",
        limit=min(max(int(out.limit or 10), 1), 50),
        time_window=time_window,
        compare_previous=bool(out.compare_previous),
        category=out.category,
        entity_kind=out.entity_kind,
        entity_mention=out.entity_mention,
        source_question=question,
    )


# ---------------- 编译(声明渲染;LLM 不参与) ----------------

def compile_composition(comp: CompositionQuery, business_id: str, entity_ids: list[str] | None = None) -> CompiledSQL:
    """CompositionQuery → CompiledSQL。

    主形态 = dim_rank(指标 × 声明维度聚合榜);compare_previous = 双期 CTE
    FULL OUTER JOIN(attribution 模式泛化);无维度 = total 单行(+平移出
    本期/上期/环比%)。SQL 全部绑定参数,用户输入永不进文本。
    """
    from .engine import CompiledSQL
    from .schema_cards import compile_safe_schema_card
    from .sql_guard import UnsafeSqlError, assert_safe_select
    from .tools_registry_bridge import metric_semantic_registry, semantic_model

    registry = metric_semantic_registry()
    entry = registry[comp.metric]
    model = semantic_model()
    unit = entry["unit"]

    if comp.dimension is None:
        sql, params = _compose_total(comp, business_id)
    else:
        dim = model["dimensions"][comp.dimension]
        if comp.compare_previous:
            sql, params = _compose_period_compare(comp, dim, business_id, entity_ids or [])
        else:
            sql, params = _compose_rank(comp, dim, business_id, entity_ids or [])

    try:
        ast = assert_safe_select(sql, compile_safe_schema_card(), require_business_id="business_id" in sql)
    except UnsafeSqlError as err:
        raise ValueError(f"组合查询未过安全闸(组合缺陷,非用户问题): {err}") from err
    return CompiledSQL(
        sql=sql,
        params=params,
        metric=comp.metric,
        unit=unit,
        ast=ast,
        chart_hint=None,  # 组合面 v1 不带图型指令(折线仲裁留给趋势族核验指标)
        target_db="merchant_db",
    )


def _measure_expr(metric: str) -> str:
    """认证指标 → 组合面度量表达式(声明式,新指标登记即组合可用)。"""
    return {
        "gmv": "COALESCE(SUM(oi.quantity * oi.price), 0)",
        "net_sales": "COALESCE(SUM(o.total_amount), 0)",
        "volume": "COALESCE(SUM(oi.quantity), 0)",
        "order_count": "COUNT(DISTINCT o.order_id)",
        "aov": "COALESCE(SUM(oi.quantity * oi.price), 0) / GREATEST(COUNT(DISTINCT o.order_id), 1)",
        "refund_rate": (
            "ROUND(COALESCE(SUM(CASE WHEN o.status = 'REFUNDED' THEN oi.quantity ELSE 0 END), 0)::numeric "
            "* 100 / GREATEST(SUM(CASE WHEN o.status <> 'CANCELLED' THEN oi.quantity ELSE 0 END), 1), 2)"
        ),
    }.get(metric, "")


# 可组合指标闭集(度量表达式已声明;未声明 = 组合目录外,响亮拒绝)
COMPOSABLE_METRICS = frozenset({"gmv", "net_sales", "volume", "order_count", "aov", "refund_rate"})

_ITEMS_JOIN = "LEFT JOIN merchant_order_items oi ON oi.order_id = o.order_id "
_VALID_STATUS = "o.status NOT IN ('REFUNDED', 'CANCELLED')"


def _base_join(metric: str, dim: dict, entity_kind: str | None, entity_ids: list[str]) -> tuple[str, dict]:
    """FROM/JOIN 子句:明细 join(金额/件数族)+ 维度表 join + 实体过滤(入 ON 保零点)。"""
    params: dict[str, Any] = {}
    joins = ""
    if entity_kind == "spu" and entity_ids:
        joins += "AND oi.spu_id = ANY(:entities) "
        params["entities"] = entity_ids[:50]
    dim_join = ""
    tbl = dim["entity"]
    if tbl == "merchant_spus":
        # 明细 spu_id 存的是 spu_code(02 号票口径),维度走 spu_code 关联
        dim_join = "LEFT JOIN merchant_spus s ON s.spu_code = oi.spu_id "
    elif tbl == "merchant_customers":
        dim_join = "LEFT JOIN merchant_customers c ON c.customer_id = o.customer_id "
    elif tbl == "promotions":
        dim_join = (
            "LEFT JOIN promotion_redemptions rd ON rd.order_id = o.order_id "
            "LEFT JOIN promotions p ON p.id = rd.promotion_id "
        )
    return joins + dim_join, params


def _dim_expr(dim_key: str, dim: dict) -> str:
    alias_by_entity = {"merchant_spus": "s", "merchant_customers": "c", "promotions": "p", "merchant_orders": "o"}
    alias = alias_by_entity[dim["entity"]]
    if dim["kind"] in ("enum", "column"):
        return f"{alias}.{dim['column']}"
    return f"{alias}.{dim.get('label_column') or dim['id_column']}"


def _dim_label(dim_key: str, dim: dict) -> str:
    return dim["label"]


def _compose_rank(comp: CompositionQuery, dim: dict, business_id: str, entity_ids: list[str]) -> tuple[str, dict[str, Any]]:
    from .engine import UnsupportedQuery, window_start

    measure = _measure_expr(comp.metric)
    if not measure or comp.metric not in COMPOSABLE_METRICS:
        raise UnsupportedQuery(f"指标 {comp.metric} 未开放语义层组合")
    dim_sql = _dim_expr(_dim_key(comp), dim)
    label = _dim_label(_dim_key(comp), dim)
    join_extra, params = _base_join(comp.metric, dim, comp.entity_kind, entity_ids)
    where_parts = [f"WHERE {_VALID_STATUS} "]
    if comp.category:
        where_parts.append("AND s.category = :cat ")
        params["cat"] = comp.category
    if comp.time_window:
        where_parts.append("AND o.created_at >= :window_start ")
        params["window_start"] = window_start(comp.time_window)
    params["lim"] = comp.limit
    sql = (
        f'SELECT {dim_sql} AS "{label}", {measure}::float AS "metricScore" '
        "FROM merchant_orders o "
        f"{_ITEMS_JOIN}"
        f"{join_extra}"
        f"{''.join(where_parts)}"
        f'GROUP BY {dim_sql} ORDER BY "metricScore" {comp.direction} LIMIT :lim'
    )
    return sql, params


def _dim_key(comp: CompositionQuery) -> str:
    assert comp.dimension  # _validate 闭集校验已保证
    return comp.dimension


def _period_bounds(window: dict | None, now: datetime | None = None) -> tuple[datetime, datetime]:
    """(本期起点, 上期起点):时间平移的通用算术(与 window_start 同源 UTC 钟)。"""
    now = now or datetime.now(UTC).replace(tzinfo=None)
    kind = (window or {}).get("kind")
    if kind == "last_7d":
        return now - timedelta(days=7), now - timedelta(days=14)
    if kind == "last_30d":
        return now - timedelta(days=30), now - timedelta(days=60)
    if kind == "last_months":
        n = max(int((window or {}).get("n") or 6), 1)
        first = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        cur = first
        for _ in range(n - 1):
            cur = (cur - timedelta(days=1)).replace(day=1)
        prev = cur
        for _ in range(n):
            prev = (prev - timedelta(days=1)).replace(day=1)
        return cur, prev
    # last_month / 缺省:本月 vs 上月(gmv_mom 语义)
    first = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    cur = (first - timedelta(days=1)).replace(day=1) if kind == "last_month" else first
    prev = (cur - timedelta(days=1)).replace(day=1)
    return cur, prev


def _compose_period_compare(comp: CompositionQuery, dim: dict, business_id: str, entity_ids: list[str]) -> tuple[str, dict[str, Any]]:
    from .engine import UnsupportedQuery

    measure = _measure_expr(comp.metric)
    if not measure or comp.metric not in COMPOSABLE_METRICS:
        raise UnsupportedQuery(f"指标 {comp.metric} 未开放语义层组合")
    dim_sql = _dim_expr(_dim_key(comp), dim)
    label = _dim_label(_dim_key(comp), dim)
    join_extra, base_params = _base_join(comp.metric, dim, comp.entity_kind, entity_ids)
    now = datetime.now(UTC).replace(tzinfo=None)
    cur_start, prev_start = _period_bounds(comp.time_window, now)
    params: dict[str, Any] = {
        **base_params,
        "cur_start": cur_start,
        "prev_start": prev_start,
        "lim": comp.limit,
    }
    if comp.category:
        params["cat"] = comp.category

    def _period(start_param: str, end_clause: str) -> str:
        where = [f"o.created_at >= :{start_param} {end_clause}"]
        if comp.category:
            where.append("AND s.category = :cat")
        return (
            f"SELECT {dim_sql} AS dim, {measure}::float AS v "
            "FROM merchant_orders o "
            f"{_ITEMS_JOIN}"
            f"{join_extra}"
            f"WHERE {' AND '.join(where)} "
            f"GROUP BY {dim_sql}"
        )

    sql = (
        "WITH cur AS (" + _period("cur_start", "") + "), "
        "prev AS (" + _period("prev_start", "AND o.created_at < :cur_start") + ") "
        f"SELECT COALESCE(cur.dim, prev.dim) AS \"{label}\", "
        "COALESCE(cur.v, 0)::float AS \"本期\", "
        "COALESCE(prev.v, 0)::float AS \"上期\", "
        "(COALESCE(cur.v, 0) - COALESCE(prev.v, 0))::float AS \"变化\" "
        "FROM cur FULL OUTER JOIN prev ON prev.dim = cur.dim "
        "ORDER BY ABS(COALESCE(cur.v, 0) - COALESCE(prev.v, 0)) DESC LIMIT :lim"
    )
    return sql, params


def _compose_total(comp: CompositionQuery, business_id: str) -> tuple[str, dict[str, Any]]:
    from .engine import UnsupportedQuery, window_start

    measure = _measure_expr(comp.metric)
    if not measure or comp.metric not in COMPOSABLE_METRICS:
        raise UnsupportedQuery(f"指标 {comp.metric} 未开放语义层组合")
    params: dict[str, Any] = {}
    where = [f"WHERE {_VALID_STATUS} "]
    joins = ""
    if comp.category:
        # 品类过滤挂在 SPU 表(验证层已保证 category 过滤只在无维度/商品/品类维度
        # 组合中出现),此处补 join
        joins = "LEFT JOIN merchant_spus s ON s.spu_code = oi.spu_id "
        where.append("AND s.category = :cat ")
        params["cat"] = comp.category
    if comp.time_window:
        where.append("AND o.created_at >= :window_start ")
        params["window_start"] = window_start(comp.time_window)
    sql = (
        f"SELECT '__total__' AS \"productId\", {measure}::float AS \"metricScore\" "
        "FROM merchant_orders o "
        f"{_ITEMS_JOIN}"
        f"{joins}"
        f"{''.join(where)}"
        "LIMIT 1"
    )
    return sql, params


# ---------------- 呈现语义(章与口径注记;机器语义走字段) ----------------

COMPOSED_TRUST = "composed"
COMPOSED_CALIBER = "组合查询:认证指标 × 声明维度的语义层组合(编译器确定性拼装,口径与核验指标同源)"
