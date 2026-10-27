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

from pydantic import BaseModel, ValidationError

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
    time_window: dict | None = None  # 同 StructuredQueryIntent:kind 见 engine.window_start(P0① 扩容后 11 种)
    compare_previous: bool = False  # 时间平移:本期 vs 上期并排
    category: str | None = None  # 便捷过滤(枚举维度值闭集)
    entity_kind: str | None = None  # 实体提及种类(spu/customer/promotion)
    entity_mention: str | None = None  # 实体提及原文(落库解析确定性,用户输入不进 SQL)
    source_question: str = ""


# 成品指标闭集(15 号票):T1 组合的职责是「指标×维度」新组合,成品指标
# (闭集路由既有形态)在此前路由已试过并失败 —— prompt 规则是软约束,
# _validate 硬闸兜底(live 实弹:LLM 偶发仍映射 order_overview)
# 成品指标禁选集:闭集路由已试过,组合面也编译不了(bespoke 族);attribution_*
# 双胞胎(grill 2026-10-26 实弹)——为什么型问句曾被映射过去,组合编译必拒
_PRODUCT_METRICS = frozenset({
    "customer_spend_top", "order_overview", "category_gmv_top",
    "attribution_sales", "attribution_refund",
})


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
        f"  不要映射到目录中的成品指标({'/'.join(sorted(_PRODUCT_METRICS))} 等)——\n"
        "  闭集路由在你之前已经试过并失败,再映射成品指标等于重复失败\n"
        "- metric 只能取指标目录中的键;dimension 只能取维度目录中的键;问题确实不含维度拆分时才留空\n"
        "- 时间窗 kind ∈ last_month/last_7d/last_30d/last_months(附 n)/today/yesterday/"
        "this_week/last_week/this_month/this_year/last_year;问句出现「近/最近/上个月/N 个月/"
        "今天/昨天/本周/上周/本月/今年/去年」必须提取;季度/节日/自定义日期段等闭集外时间留空\n"
        "  问「同比/环比/上期对比/变化」或「为什么/什么原因/怎么回事」(= 问变化看涨跌)时 compare_previous=true\n"
        "- 问题里的具体商品/客户/活动名称写进 entity_mention(附 entity_kind=spu/customer/promotion),不要改写;\n"
        "  出现目录枚举中的具体品类值(衬衫/配饰等)才写进 category —— 「品类/品牌/区域/客户/活动」"
        "是维度词不是品类值,严禁把维度词或指标短语写进 category,未提及具体品类留空\n"
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
    try:
        return _ComposeOut(**_parse_llm_json(_content_text(resp)))
    except ValidationError as err:
        # LLM 偶发产出不合契约的成分类型(实测 dimension=非字符串,live eval
        # eval-gap-2026-10 16 号票)—— 垃圾输出 = 组合失败,驯化为响亮拒绝,
        # 严禁裸 ValidationError 逃逸成调用方无法分类的"断言器异常"
        raise CompositionRejected(f"组合解析输出不合契约: {err}") from err


def _validate(out: Any, allowed: list[str] | None, question: str) -> CompositionQuery:
    """闭集校验:目录外任何成分都响亮拒绝(宁可 unsupported,不做近似组合)。"""
    # 机械槽位先提取(所有分支可用;LLM 漏填的时间/品类由此回填)
    from .l0_lexicon import extract_slots
    from .tools_registry_bridge import metric_semantic_registry, semantic_model

    _, slot_time, slot_category = extract_slots((question or "").strip().lower())

    if out.metric == "__unsupported__" or out.metric not in metric_semantic_registry():
        raise CompositionRejected(f"指标 {out.metric!r} 不在语义层目录内")
    if out.metric in _PRODUCT_METRICS:
        raise CompositionRejected(f"成品指标 {out.metric!r} 由闭集路由承担,T1 组合不重复映射(重复失败)")
    if allowed is not None and out.metric not in allowed:
        raise CompositionRejected(f"当前角色无权查看指标 {out.metric!r}")
    model = semantic_model()
    dims = model["dimensions"]
    if out.dimension is not None:
        out.dimension = out.dimension.strip() or None  # LLM 偶发填空串(live eval 实弹),归一为「无维度」
    if out.dimension is not None and out.dimension not in dims:
        raise CompositionRejected(f"维度 {out.dimension!r} 不在语义层目录内")
    # 维度漏填确定性回填(eval-gap-2026-10 15/16 实弹):LLM 偶发把「各品类的
    # 成交额」「订单都处于什么状态」类拆分句式组合成无维度总量 —— 拆分语感
    # 词表单一事实源(_BREAKDOWN_RE)先验兜底,与时间/品类机械槽位回填同律;
    # 只兜漏填(dimension=None),绝不覆盖 LLM 显式输出
    if out.dimension is None:
        _m = _BREAKDOWN_RE.search(question or "")
        if _m:
            _word = next((w for w in _m.groups() if w), None)
            _dim = _DIM_WORD_MAP.get(_word or "")
            if _dim in dims:
                out.dimension = _dim
    # 环比/同比确定性置位(15 号票):问句明示环比词而 LLM 漏标 compare_previous
    # 是错判不是风格差异 —— 与时间/品类机械回填同律,词面命中即置 True
    # (composition.py 模块级 _COMPARE_PREV_RE 与 breakdown_reroute 同源)
    if _COMPARE_PREV_RE.search(question or ""):
        out.compare_previous = True
    if out.category is None and slot_category:
        out.category = slot_category
    # 维度词回声归一(live eval 九轮实弹):「各品类销售额」的 LLM 把「品类」
    # 这个维度词当过滤值回填 —— 维度词是切片轴不是取值,丢弃
    _DIM_WORDS = {"品类", "品牌", "区域", "城市", "客户", "活动", "类目"}
    if out.category is not None:
        _cat = out.category.strip()
        # LLM 垃圾串归一(15 号票三跑三红实证:'各品类'/'null'/'' 各不同变体):
        # 各/每/所有/全部 前缀 + 维度词、JSON null 字面串、裸维度词 —— 都不是
        # 过滤值;真实枚举值(衬衫/户外机能)不受影响
        for _p in ("各", "每", "所有", "全部"):
            if _cat.startswith(_p):
                _cat = _cat[len(_p):].strip()
                break
        if _cat.lower() in ("null", "none", "true", "false", "无", "") or _cat in _DIM_WORDS:
            out.category = None
        else:
            out.category = _cat
    if out.category is not None:
        enum_values = dims.get("category", {}).get("values") or []
        if out.category not in enum_values:
            # LLM 垃圾串(15 号票三跑三红同族;grill 2026-10-26 再实证 JSON blob
            # 与指标描述串):先子串救回真实枚举值(「衬衫类」→衬衫),救不回
            # 回落 L0 确定性槽位,再不行视为未提及 —— 垃圾串绝不毙掉整张组合
            _sub = next((v for v in enum_values if v in out.category), None)
            if _sub is not None:
                out.category = _sub
            elif slot_category and slot_category in enum_values:
                print(f"[T1] 品类槽位垃圾串 {out.category!r} 回落 L0 槽位 {slot_category!r}")
                out.category = slot_category
            else:
                print(f"[T1] 品类槽位垃圾串 {out.category!r} 丢弃(视为未提及)")
                out.category = None
    # entity_kind 裸 null 字面串(live 实弹:函数调用参数偶发把 null 输出成
    # 字符串)归一为未提及;真越闭集值仍响亮拒绝
    if isinstance(out.entity_kind, str) and out.entity_kind.strip().lower() in ("null", "none", ""):
        out.entity_kind = None
    if out.entity_kind is not None and out.entity_kind not in ("spu", "customer", "promotion"):
        raise CompositionRejected(f"实体种类 {out.entity_kind!r} 不在闭集内")
    time_window = None
    if out.time_kind in (
        "last_month", "last_7d", "last_30d", "last_months",
        "today", "yesterday", "this_week", "last_week", "this_month", "this_year", "last_year",
    ):
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
    """认证指标 → 组合面度量表达式(声明式,新指标登记即组合可用)。

    grill 2026-10-27 组合面扩容:毛利/毛利率入列(finance_owner 闭集,
    _validate 的 allowed 闸兜底角色越权)。"""
    return {
        "gmv": "COALESCE(SUM(oi.quantity * oi.price), 0)",
        "net_sales": "COALESCE(SUM(o.total_amount), 0)",
        "volume": "COALESCE(SUM(oi.quantity), 0)",
        "order_count": "COUNT(DISTINCT o.order_id)",
        "aov": "COALESCE(SUM(oi.quantity * oi.price), 0) / GREATEST(COUNT(DISTINCT o.order_id), 1)",
        "gross_profit": "COALESCE(SUM(oi.quantity * (oi.price - oi.cost_at_purchase)), 0)",
        "margin_rate": (
            "ROUND(COALESCE(SUM(oi.quantity * (oi.price - oi.cost_at_purchase)), 0)::numeric * 100 "
            "/ GREATEST(COALESCE(SUM(oi.quantity * oi.price), 0), 1), 2)"
        ),
        "refund_rate": (
            "ROUND(COALESCE(SUM(CASE WHEN o.status = 'REFUNDED' THEN oi.quantity ELSE 0 END), 0)::numeric "
            "* 100 / GREATEST(SUM(CASE WHEN o.status <> 'CANCELLED' THEN oi.quantity ELSE 0 END), 1), 2)"
        ),
    }.get(metric, "")


# 二段聚合度量(grill 2026-10-27 票:复购率入组合面):单层「GROUP BY 维度」
# 表达不了「每客户订单数 → 复购占比」的嵌套 —— 内层按(维度,客户)先聚,
# 外层在内层产物上求比率;行集/有效成交口径与平铺度量同源(订单×明细),
# DISTINCT 订单号保证明细扇出不虚增计数。
_NESTED_MEASURES = {
    "repeat_purchase_rate": {
        "per": "o.customer_id",
        "pre": "COUNT(DISTINCT o.order_id) AS orders_n",
        "outer": "ROUND(COALESCE(100.0 * SUM(CASE WHEN orders_n >= 2 THEN 1 ELSE 0 END) / GREATEST(COUNT(*), 1), 0), 2)::float",
    },
}

# 可组合指标闭集(平铺或嵌套度量已声明;未声明 = 组合目录外,响亮拒绝)
COMPOSABLE_METRICS = frozenset({
    "gmv", "net_sales", "volume", "order_count", "aov", "refund_rate",
    "gross_profit", "margin_rate", "repeat_purchase_rate",
})

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
    from .engine import UnsupportedQuery, window_bounds_predicates

    measure = _measure_expr(comp.metric)
    # 目录外(未入组合闭集)与形状未开放两义分形,拒绝文案随因 —— 否则
    # repeat_purchase_rate 走总计时谎称「未开放组合」(夜评 2026-10-27 Standards)
    if comp.metric not in COMPOSABLE_METRICS:
        raise UnsupportedQuery(f"指标 {comp.metric} 未开放语义层组合")
    if not measure and comp.metric not in _NESTED_MEASURES:
        raise UnsupportedQuery(f"指标 {comp.metric} 未开放排行形状的组合")
    dim_sql = _dim_expr(_dim_key(comp), dim)
    label = _dim_label(_dim_key(comp), dim)
    join_extra, params = _base_join(comp.metric, dim, comp.entity_kind, entity_ids)
    where_parts = [f"WHERE {_VALID_STATUS} "]
    if comp.category:
        where_parts.append("AND s.category = :cat ")
        params["cat"] = comp.category
    if comp.time_window:
        pred, p = window_bounds_predicates("o.created_at", comp.time_window)
        where_parts.append(f"AND {pred} ")
        params.update(p)
    params["lim"] = comp.limit
    nested = _NESTED_MEASURES.get(comp.metric)
    if nested:
        # 二段聚合(复购率族):内层(维度×客户)先聚订单数,外层求复购占比
        inner = (
            f"SELECT {dim_sql} AS dim, {nested['per']}, {nested['pre']} "
            "FROM merchant_orders o "
            f"{_ITEMS_JOIN}"
            f"{join_extra}"
            f"{''.join(where_parts)}"
            f"GROUP BY {dim_sql}, {nested['per']}"
        )
        return (
            f'SELECT dim AS "{label}", {nested["outer"]} AS "metricScore" '
            f"FROM ({inner}) per_cust GROUP BY dim "
            f'ORDER BY "metricScore" {comp.direction} LIMIT :lim'
        ), params
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
    """(本期起点, 上期起点):时间平移的通用算术(与 window_start 同源 UTC 钟)。

    P0① 扩容 kind 的双期映射:today↔昨日全天 / yesterday↔前天全天 /
    this_week↔上周 / last_week↔上上周 / this_month↔上月 / this_year↔去年 /
    last_year↔前年;上期一律由 SQL 以 `< :cur_start` 封口(等长对齐)。"""
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
    floor = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if kind == "today":
        return floor, floor - timedelta(days=1)
    if kind == "yesterday":
        return floor - timedelta(days=1), floor - timedelta(days=2)
    if kind == "this_week":
        week_start = floor - timedelta(days=now.weekday())
        return week_start, week_start - timedelta(days=7)
    if kind == "last_week":
        week_start = floor - timedelta(days=now.weekday() + 7)
        return week_start, week_start - timedelta(days=7)
    if kind == "this_month":
        first = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        return first, (first - timedelta(days=1)).replace(day=1)
    if kind == "this_year":
        year_start = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        return year_start, year_start.replace(year=year_start.year - 1)
    if kind == "last_year":
        year_start = now.replace(year=now.year - 1, month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        return year_start, year_start.replace(year=year_start.year - 2)
    # last_month / 缺省:本月 vs 上月(gmv_mom 语义)
    first = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    cur = (first - timedelta(days=1)).replace(day=1) if kind == "last_month" else first
    prev = (cur - timedelta(days=1)).replace(day=1)
    return cur, prev


def _compose_period_compare(comp: CompositionQuery, dim: dict, business_id: str, entity_ids: list[str]) -> tuple[str, dict[str, Any]]:
    from .engine import UnsupportedQuery, window_end

    measure = _measure_expr(comp.metric)
    nested = _NESTED_MEASURES.get(comp.metric)
    if comp.metric not in COMPOSABLE_METRICS:
        raise UnsupportedQuery(f"指标 {comp.metric} 未开放语义层组合")
    if not measure and nested is None:
        raise UnsupportedQuery(f"指标 {comp.metric} 未开放对比形状的组合")
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
    # 主指标即退款率不重复携带;嵌套度量(复购率族)内层是(维度×客户)预聚合,
    # 退款率列挂不上平铺行集 —— 只由差评率 CTE 独立承担对照。
    related = None if (comp.metric == "refund_rate" or nested) else _measure_expr("refund_rate")

    # 完整过去段(昨天/上周/上个月/去年)本期同样带排他上界(P0①):此前 cur 段
    # 开口到当前时刻,「上个月为什么跌」把当月数据静默并进本期对照
    cur_end = window_end(comp.time_window, now)
    cur_end_clause = ""
    if cur_end is not None:
        params["cur_end"] = cur_end
        cur_end_clause = "AND o.created_at < :cur_end"

    def _period(start_param: str, end_clause: str) -> str:
        where = [f"o.created_at >= :{start_param} {end_clause}"]
        if comp.category:
            where.append("AND s.category = :cat")
        extra = f", {related} AS rv" if related else ""
        if nested:
            # 二段聚合(复购率族):内层(维度×客户)先聚订单数,外层求占比
            inner = (
                f"SELECT {dim_sql} AS dim, {nested['per']}, {nested['pre']} "
                "FROM merchant_orders o "
                f"{_ITEMS_JOIN}"
                f"{join_extra}"
                f"WHERE {' AND '.join(where)} "
                f"GROUP BY {dim_sql}, {nested['per']}"
            )
            return f"SELECT dim, {nested['outer']} AS v FROM ({inner}) per_cust GROUP BY dim"
        return (
            f"SELECT {dim_sql} AS dim, {measure}::float AS v{extra} "
            "FROM merchant_orders o "
            f"{_ITEMS_JOIN}"
            f"{join_extra}"
            f"WHERE {' AND '.join(where)} "
            f"GROUP BY {dim_sql}"
        )

    # B1 差评率对照(留票注收口,grill 2026-10-26):差评率度量基座是评价表,
    # 与订单基不存在无扇出 join —— 独立 CTE 按同维度聚合后并排。仅对 join
    # 路径可达的维度(品类/商品)且无实体过滤时附列,其余诚实缺列不造零。
    # join 条件从语义模型 review_of_spu 声明派生(评审收口:手抄 SQL 与模型
    # 声明双向漂移,trend_family 反手抄同族);评价基右界须用 r.created_at
    # (订单基的 cur_end_clause 是 o. 前缀)。
    badrate_ctes = badrate_cols = badrate_joins = ""
    if comp.dimension in ("category", "spu") and not entity_ids:
        from .tools_registry_bridge import semantic_model

        review_join = next(
            (j["condition"] for j in semantic_model()["joins"] if j["name"] == "review_of_spu"), None
        )
        if review_join is None:
            raise UnsupportedQuery("语义模型未声明 review_of_spu join(差评率对照不可组合)")
        bad_dim_sql = "s.category" if comp.dimension == "category" else "s.title"
        bad_expr = (
            "ROUND(COALESCE(SUM(CASE WHEN r.rating <= 2 THEN 1 ELSE 0 END), 0) * 100.0 "
            "/ GREATEST(COUNT(*), 1), 2)"
        )
        cur_end_clause_r = "AND r.created_at < :cur_end" if cur_end is not None else ""

        def _badrate(start_param: str, end_clause: str) -> str:
            return (
                f"SELECT {bad_dim_sql} AS dim, {bad_expr}::float AS br "
                f"FROM merchant_product_reviews r "
                f"LEFT JOIN merchant_spus s ON {review_join} "
                f"WHERE r.created_at >= :{start_param} {end_clause} "
                f"GROUP BY {bad_dim_sql}"
            )

        badrate_ctes = (
            ", badcur AS (" + _badrate("cur_start", cur_end_clause_r) + ")"
            ", badprev AS (" + _badrate("prev_start", "AND r.created_at < :cur_start") + ")"
        )
        badrate_cols = (
            ', COALESCE(badcur.br, 0)::float AS "本期差评率", '
            '(COALESCE(badcur.br, 0) - COALESCE(badprev.br, 0))::float AS "差评率变化"'
        )
        badrate_joins = (
            " LEFT JOIN badcur ON badcur.dim = COALESCE(cur.dim, prev.dim) "
            "LEFT JOIN badprev ON badprev.dim = COALESCE(cur.dim, prev.dim) "
        )

    related_cols = (
        ', COALESCE(cur.rv, 0)::float AS "本期退款率", '
        '(COALESCE(cur.rv, 0) - COALESCE(prev.rv, 0))::float AS "退款率变化"'
        if related
        else ""
    )
    sql = (
        "WITH cur AS (" + _period("cur_start", cur_end_clause) + "), "
        "prev AS (" + _period("prev_start", "AND o.created_at < :cur_start") + ")"
        + badrate_ctes +
        f" SELECT COALESCE(cur.dim, prev.dim) AS \"{label}\", "
        "COALESCE(cur.v, 0)::float AS \"本期\", "
        "COALESCE(prev.v, 0)::float AS \"上期\", "
        "(COALESCE(cur.v, 0) - COALESCE(prev.v, 0))::float AS \"变化\""
        + related_cols + badrate_cols +
        " FROM cur FULL OUTER JOIN prev ON prev.dim = cur.dim"
        + badrate_joins +
        " ORDER BY ABS(COALESCE(cur.v, 0) - COALESCE(prev.v, 0)) DESC LIMIT :lim"
    )
    return sql, params


def _compose_total(comp: CompositionQuery, business_id: str) -> tuple[str, dict[str, Any]]:
    from .engine import UnsupportedQuery, window_bounds_predicates

    measure = _measure_expr(comp.metric)
    if comp.metric not in COMPOSABLE_METRICS:
        raise UnsupportedQuery(f"指标 {comp.metric} 未开放语义层组合")
    if not measure:
        # 已入组合目录但仅嵌套度量(如 repeat_purchase_rate)—— 总计形状
        # 不消费维度分组,诚实拒形状而非谎称目录外
        raise UnsupportedQuery(f"指标 {comp.metric} 未开放总计形状")
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
        pred, p = window_bounds_predicates("o.created_at", comp.time_window)
        where.append(f"AND {pred} ")
        params.update(p)
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
        "- 主因/次因按「变化」列的正负表述;退款率/差评率变化列以「伴随/同期」描述关联对照\n"
        "- 结尾可给一句行动建议与一个值得核查的追问方向(基于数据即可,如「建议核查该品类售后」)\n"
        "- 只说同期对照,不下因果定论(因果判断留给人,08-D1)\n"
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

# 语感:「各/按 + 维度词」或「维度词 + 分布/对比/排行」或「(处于)什么/哪些状态」;
# 环比/同比 → 时间平移。状态→order_status(2026-10-23 扩:订单状态分布问句的
# 拆分语感,eval-gap-2026-10 15/16 实弹 LLM 偶发漏提 dimension)
_BREAKDOWN_RE = re.compile(
    r"(?:各|按)\s*(品牌|区域|城市|品类|客户|活动|状态)"
    r"|(品牌|区域|城市|品类|客户|活动|状态)(?:的)?(?:分布|对比|排行)"
    r"|(?:处于)?(?:什么|哪些)(状态)"
)
_COMPARE_PREV_RE = re.compile(r"环比|同比|对比上期|较上期")
_DIM_WORD_MAP = {
    "品牌": "brand",
    "区域": "region",
    "城市": "city",
    "品类": "category",
    "客户": "customer",
    "活动": "promotion",
    "状态": "order_status",
}


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


# 原因语感(2026-10-08 实弹:「为什么退款这么多」曾 unsupported/退榜单)。因果正则
# 单源在此,owner_routing.has_reason_intent 委派本处。另:「怎么」单字太宽(「退款率
# 怎么算」是口径问不是归因),只收因果词形。
REASON_RE = re.compile(r"为什么|什么原因|原因|为啥|为何|咋|怎么回事")
# 排行/枚举语感(2026-10-09 第三载体):最好/最差/Top/榜…… 与维度泛词同现时
# 表示「按该维度看高低」→ 组合排行(owner 列载体),而非 T0 的 SPU 默认维度。
# 对比/分布入列(grill 2026-10-27 实弹:「各品牌毛利率对比」曾走 T0 商品榜,
# 维度词被静默丢弃 —— 维度×对比语感升组合面按维度作答)
RANKING_RE = re.compile(r"top\s*\d*|榜|排行|排名|最好|最差|最高|最低|哪些|分别|最好卖|对比|分布", re.IGNORECASE)


def dimension_word_of(question: str) -> str | None:
    """问句中的维度泛词 → 语义维度键(_DIM_WORD_MAP 单点);无泛词返回 None。"""
    for word, dim in _DIM_WORD_MAP.items():
        if word in (question or ""):
            return dim
    return None


# 原因语感 × T0 榜单指标 → 可组合基指标(grill 2026-10-26):「为什么各品类
# 销售额跌了」被 L0 词林命中 category_gmv_top(dim_rank,不可组合)后
# reason_reroute 拒之门外 → 答成当期品类榜,「为什么」被静默吞掉(笼统感的
# 直接来源)。归因时榜单指标降维到基度量,口径同源语义模型,双期对照由组合面承担。
_REASON_METRIC_ALIASES = {"category_gmv_top": "gmv"}


def reason_reroute(question: str, intent) -> CompositionQuery | None:
    """复合语感 → 确定性组合升级(不依赖找谁词面;7babb61 语感直通同族)。

    触发(T1 开闸 ∧ 指标在 COMPOSABLE_METRICS):①原因语感(为什么 = 看变化 →
    compare_previous 归因);②维度泛词 × 排行语感(「哪个品类卖得最好」 = 按维度
    看高低 → dim_rank 排行)。维度泛词显式优先,缺省 category。纯维度泛词不触发
    (「各品类销售额」由 L0 词面/场景包既有路承接,此处抢跑会改既有行为)。
    零 LLM;不满足返回 None(调用方照常走 T0)。"""
    from .engine import StructuredQueryIntent
    from .tools_registry_bridge import semantic_model

    if not (isinstance(intent, StructuredQueryIntent) and composition_enabled()):
        return None
    base_metric = _REASON_METRIC_ALIASES.get(intent.metric, intent.metric)
    if base_metric not in COMPOSABLE_METRICS:
        return None
    reason = bool(REASON_RE.search(question or ""))
    dim_word = dimension_word_of(question or "")
    ranking = bool(RANKING_RE.search(question or ""))
    if not (reason or (dim_word and ranking)):
        return None
    dimension = dim_word or "category"
    if dimension not in semantic_model()["dimensions"]:
        return None
    if intent.category and dimension not in (None, "category", "spu"):
        return None  # 品类过滤挂在 SPU 表:客户/活动/区域维度不可组合,宁可不升级
    time_window = intent.time_window
    if time_window is None:
        from .l0_lexicon import extract_slots

        _, slot_time, _slot_category = extract_slots((question or "").strip().lower())
        time_window = slot_time
    return CompositionQuery(
        metric=base_metric,
        dimension=dimension or "category",
        direction=intent.direction,
        limit=intent.limit,
        time_window=time_window,
        compare_previous=reason,  # 原因问的就是变化;纯排行看高低不出双期
        category=intent.category,
        source_question=question,
    )


