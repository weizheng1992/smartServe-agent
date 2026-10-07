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
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

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


class _ComposeOut(BaseModel):
    """组合解析的 LLM 输出形(bind_tools 工具契约;与 L3 同机制)。"""

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
        elif dim["kind"] == "expression":
            dim_lines.append(f"- {dkey}({dim['label']}):{dim['description']}")
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
    from langchain_core.messages import HumanMessage, SystemMessage

    messages = [SystemMessage(content=system), HumanMessage(content=user)]
    out = await _invoke_compose_out(get_chat_model(), messages)
    return _validate(out, allowed, question)


async def _invoke_compose_out(model, messages) -> _ComposeOut:
    """结构化解析主路 = bind_tools(L3 同机制,glm-4.7 兼容由 llm/chat 单点收口);
    live eval 六/八轮实弹:with_structured_output 在 bigmodel 端偶发退化成
    围栏 JSON 文本/空响应 —— 降为文本路径,用 L3 同源 _parse_llm_json 手解
    (剥围栏),仍败才响亮。"""
    from .llm_intent import _content_text, _parse_llm_json

    try:
        tool_model = model.bind_tools([_ComposeOut], tool_choice="required")
        resp = await tool_model.ainvoke(messages)
        for tc in getattr(resp, "tool_calls", None) or []:
            args = tc.get("args") if isinstance(tc, dict) else getattr(tc, "args", None)
            if args:
                return _ComposeOut(**args)
        print("[T1] function calling 未产出工具调用,回落文本解析")
    except Exception as tool_err:
        print(f"[T1] function calling 不可用,回落文本解析: {tool_err}")
    resp = await model.ainvoke(messages)
    return _ComposeOut(**_parse_llm_json(_content_text(resp)))


def _validate(out: Any, allowed: list[str] | None, question: str) -> CompositionQuery:
    """闭集校验:目录外任何成分都响亮拒绝(宁可 unsupported,不做近似组合)。"""
    # 机械槽位先提取(所有分支可用;LLM 漏填的时间/品类由此回填)
    from .l0_lexicon import extract_slots
    from .tools_registry_bridge import metric_semantic_registry, semantic_model

    _, slot_time, slot_category = extract_slots((question or "").strip().lower())

    if out.metric == "__unsupported__" or out.metric not in metric_semantic_registry():
        raise CompositionRejected(f"指标 {out.metric!r} 不在语义层目录内")
    if allowed is not None and out.metric not in allowed:
        raise CompositionRejected(f"当前角色无权查看指标 {out.metric!r}")
    model = semantic_model()
    dims = model["dimensions"]
    if out.dimension is not None:
        out.dimension = out.dimension.strip() or None  # LLM 偶发填空串(live eval 实弹),归一为「无维度」
    if out.dimension is not None and out.dimension not in dims:
        raise CompositionRejected(f"维度 {out.dimension!r} 不在语义层目录内")
    if out.category is None and slot_category:
        out.category = slot_category
    # 维度词回声归一(live eval 九轮实弹):「各品类销售额」的 LLM 把「品类」
    # 这个维度词当过滤值回填 —— 维度词是切片轴不是取值,丢弃
    _DIM_WORDS = {"品类", "品牌", "区域", "城市", "客户", "活动", "类目"}
    if out.category in _DIM_WORDS:
        out.category = None
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
    # 机械槽位确定性兜底(live eval 四轮实弹:LLM 对时间/品类槽位依从性不稳):
    # 语义映射(指标×维度)归 LLM,时间/品类/limit 归 L0 同源正则 —— LLM 漏填
    # 时回填,两源都有以 LLM 为准(它看得到完整问句语境)
    if time_window is None and slot_time:
        time_window = slot_time
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
    from .engine import UnsupportedQuery

    if dim["kind"] == "expression":
        # 表达式维度:模型声明原样渲染(与 compile 块度量同信任级);加载器已
        # 校验引用实体别名,此处再闸实体 = 组合基表(merchant_orders),跨实体
        # 表达式宁可响亮不做错组合
        if dim["entity"] != "merchant_orders":
            raise UnsupportedQuery(f"表达式维度 {dim_key} 仅支持订单基组合")
        return dim["expression"]
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

    # B1 关联指标对照(ADR-0011):双期 CTE 携带同基关联度量(退款率)的同期值
    # —— 两列数字并排呈现「跌的同时发生了什么」,因果判断留给人(08-D1 不破)。
    # 主指标即退款率时不重复携带;差评率需评论-订单跨基 join(扇出风险),留票注。
    related = None if comp.metric == "refund_rate" else _measure_expr("refund_rate")

    def _period(start_param: str, end_clause: str) -> str:
        where = [f"o.created_at >= :{start_param} {end_clause}"]
        if comp.category:
            where.append("AND s.category = :cat")
        extra = f", {related} AS rv" if related else ""
        return (
            f"SELECT {dim_sql} AS dim, {measure}::float AS v{extra} "
            "FROM merchant_orders o "
            f"{_ITEMS_JOIN}"
            f"{join_extra}"
            f"WHERE {' AND '.join(where)} "
            f"GROUP BY {dim_sql}"
        )

    related_cols = (
        ', COALESCE(cur.rv, 0)::float AS "本期退款率", '
        '(COALESCE(cur.rv, 0) - COALESCE(prev.rv, 0))::float AS "退款率变化"'
        if related
        else ""
    )
    sql = (
        "WITH cur AS (" + _period("cur_start", "") + "), "
        "prev AS (" + _period("prev_start", "AND o.created_at < :cur_start") + ") "
        f"SELECT COALESCE(cur.dim, prev.dim) AS \"{label}\", "
        "COALESCE(cur.v, 0)::float AS \"本期\", "
        "COALESCE(prev.v, 0)::float AS \"上期\", "
        "(COALESCE(cur.v, 0) - COALESCE(prev.v, 0))::float AS \"变化\""
        + related_cols +
        " FROM cur FULL OUTER JOIN prev ON prev.dim = cur.dim "
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

# ---------------- B2 归因叙事(ADR-0011;隔离章 + 数字可溯源硬校验) ----------------

NARRATIVE_BADGE = "AI 推断(非数据)"
_NARRATIVE_NUM_RE = re.compile(r"-?\d[\d,]*\.?\d*")


def narrative_enabled() -> bool:
    return os.environ.get("AI_ATTR_NARRATIVE", "off") == "on"


def _narrative_traceable(text: str, rows: list[dict], summary: str | None) -> bool:
    """数字可溯源硬校验:叙事中的每个数字 token 必须能在归因卡数据(行值/速览)
    中找到同值(数值等价,逗号/小数尾形态归一)。违者整段丢弃 —— 叙述只许
    组织措辞,不许引入数据外的事实(ADR-0011 B2 隔离章第一护栏)。"""
    def _numbers(text: str) -> set[float]:
        out = set()
        for token in _NARRATIVE_NUM_RE.findall(text):
            try:
                out.add(float(token.replace(",", "")))
            except ValueError:
                continue
        return out

    allowed = _numbers(str([v for r in rows for v in r.values()])) | (_numbers(summary) if summary else set())

    def _traceable(token: float) -> bool:
        """舍入容差 + 符号自由:LLM 复算百分比常差 0.1(-90.9% vs 卡上 -91.0%);
        中文的方向由动词承载(「净减少 24,879」= 卡上 -24,879),故按绝对值
        比对。舍入级偏差(≤max(0.5, 0.5%))视为同值;超出 = 编造,必死。"""
        return any(abs(abs(token) - abs(a)) <= max(0.5, abs(a) * 0.005) for a in allowed)

    return all(_traceable(t) for t in _numbers(text))


def _narrative_context(comp: CompositionQuery, rows: list[dict], summary: str | None) -> str:
    import json as _json

    from .tools_registry_bridge import metric_semantic_registry

    label = metric_semantic_registry().get(comp.metric, {}).get("label") or comp.metric
    return _json.dumps(
        {"指标": label, "归因数据": rows, "系统速览": summary},
        ensure_ascii=False, default=str,
    )


async def attribute_narrative(comp: CompositionQuery, rows: list[dict], summary: str | None) -> dict | None:
    """B2 归因叙事:LLM 把确定性归因数据组织成因果叙述。

    三重护栏(ADR-0011 隔离章方案):①独立帧区块 + 「AI 推断(非数据)」章
    (前端渲染层);②数字可溯源硬校验 —— 叙事含卡外数字即整段丢弃;
    ③AI_ATTR_NARRATIVE 默认 off。失败/不可溯源一律 None(叙事缺席,数据照常)。
    """
    if not narrative_enabled() or not rows or summary is None:
        return None
    from langchain_core.messages import HumanMessage, SystemMessage

    from .llm_intent import _content_text, get_chat_model

    system = (
        "你是商户数据归因叙述器。把系统确定性算得的归因数据组织成 2-3 句话的归因叙述。\n"
        "硬规则:\n"
        "- 只能引用归因数据 JSON 中出现的数字与名称,绝不引入任何数据外的事实\n"
        "- 主因/次因按「变化」列的正负表述;退款率变化列可以「伴随/同期」描述关联\n"
        "- 结尾可给一句行动建议(基于数据即可,如「建议核查该品类售后」)\n"
        "- 只输出叙述文本,不要标题、不要 markdown\n"
    )
    user = _narrative_context(comp, rows, summary)
    try:
        resp = await get_chat_model().ainvoke([SystemMessage(content=system), HumanMessage(content=user)])
    except Exception as err:
        print(f"[归因叙事] LLM 调用失败(叙事缺席,数据照常): {err}")
        return None
    text = _content_text(resp).strip()
    if not text:
        return None
    if not _narrative_traceable(text, rows, summary):
        print("[归因叙事] 数字不可溯源,整段丢弃(隔离章硬校验)")
        return None
    return {"text": text, "badge": NARRATIVE_BADGE}

# ---------------- 确定性组合升级(维度拆分语感直通;零 LLM) ----------------

# 语感:「各/按 + 维度词」或「维度词 + 分布/对比/排行」;环比/同比 → 时间平移
_BREAKDOWN_RE = re.compile(
    r"(?:各|按)\s*(品牌|区域|城市|品类|客户|活动)"
    r"|(品牌|区域|城市|品类|客户|活动)(?:的)?(?:分布|对比|排行)"
)
_COMPARE_PREV_RE = re.compile(r"环比|同比|对比上期|较上期")
_DIM_WORD_MAP = {"品牌": "brand", "区域": "region", "城市": "city", "品类": "category", "客户": "customer", "活动": "promotion"}


def breakdown_reroute(question: str, intent) -> CompositionQuery | None:
    """维度拆分语感 → 确定性组合升级(live 缺口实弹:「各品牌净销售额对比」被
    L0 词林命中答成总量单行,答非所问但数字没错 —— 最隐蔽的错答形态)。

    触发条件(全部满足):T1 开闸 ∧ 命中指标为总量形(total_single,无法呈现
    拆分)∧ 问句携带维度拆分语感 ∧ 维度在语义模型目录。零 LLM:维度词映射
    与槽位全部确定性提取;不满足返回 None(调用方照常走 T0)。
    """
    from .engine import StructuredQueryIntent
    from .semantic_compiler import _compile_blocks
    from .tools_registry_bridge import semantic_model

    if not (isinstance(intent, StructuredQueryIntent) and composition_enabled()):
        return None
    block = _compile_blocks().get(intent.metric) or {}
    if block.get("shape") != "total_single":
        return None
    match = _BREAKDOWN_RE.search(question or "")
    if not match:
        return None
    word = next((w for w in match.groups() if w), None)
    dimension = _DIM_WORD_MAP.get(word or "")
    if dimension not in semantic_model()["dimensions"]:
        return None
    if intent.category and dimension not in (None, "category", "spu"):
        return None  # 品类过滤挂在 SPU 表:客户/活动/区域维度不可组合,宁可不升级
    time_window = intent.time_window
    compare_previous = bool(_COMPARE_PREV_RE.search(question or ""))
    if time_window is None and compare_previous:
        from .l0_lexicon import extract_slots

        _, slot_time, _slot_category = extract_slots((question or "").strip().lower())
        time_window = slot_time
    return CompositionQuery(
        metric=intent.metric,
        dimension=dimension,
        direction=intent.direction,
        limit=intent.limit,
        time_window=time_window,
        compare_previous=compare_previous,
        category=intent.category,
        source_question=question,
    )


