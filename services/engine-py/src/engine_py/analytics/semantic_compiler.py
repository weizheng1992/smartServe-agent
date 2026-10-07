"""语义编译器(ADR-0010 分层信任架构):声明模型 + 指标 compile 块 → CompiledSQL。

指标(SQL 怎么算)声明在 metrics.yaml 每条的 compile 块(shape/度量/HAVING 口径),
表关联/维度声明在 semantic_model.yaml;本模块把它们确定性拼装为 SQL —— join 不再
逐模板手抄,新登记维度改 YAML 不改代码。LLM 永不参与编译(铁律精神,T0 核验通道)。

形状闭集(shape)= 查询形态;每种形状一个确定性渲染函数:
- spu_rank:销售族商品榜(agg 预聚合防笛卡尔;销售族差分对拍的字节级基准)

安全链不变:每条编译产物必经 assert_safe_select(表白名单对照 compile_safe_schema_card,
require_business_id 断言);模型实体 ⊆ 安全卡表漂移断言在每次编译前执行 —— 模型
登记是新表进 SQL 的唯一门。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .schema_cards import compile_safe_schema_card
from .sql_guard import UnsafeSqlError, assert_safe_select
from .tools_registry_bridge import metric_semantic_registry, semantic_model

if TYPE_CHECKING:  # 仅类型位;运行时惰性 import 防 engine ↔ compiler 环
    from .engine import CompiledSQL, StructuredQueryIntent


def _model() -> dict[str, Any]:
    return semantic_model()


def _compile_blocks() -> dict[str, dict[str, Any]]:
    """metric key → compile 块。有块的指标 = 编译器可承接(engine.compile 据此分流)。"""
    return {
        key: entry["compile"]
        for key, entry in metric_semantic_registry().items()
        if isinstance(entry.get("compile"), dict)
    }


def can_compile(metric: str) -> bool:
    return metric in _compile_blocks()


def _assert_model_matches_card() -> None:
    """模型实体 ⊆ 编译期安全卡表(漂移断言):模型登记新表必须先登记 schema 卡,
    否则任何引用该表的编译产物都会被表白名单拒绝 —— 与断言同源,缺卡在编译期
    响亮暴露而非执行期。"""
    card_tables = set(compile_safe_schema_card()["tables"])
    model_tables = set(_model()["entities"])
    missing = model_tables - card_tables
    if missing:
        raise ValueError(f"语义模型实体未登记 schema 卡(表白名单将拒绝): {sorted(missing)}")


def compile_metric(intent: StructuredQueryIntent, business_id: str, chart_hint: str | None = None) -> CompiledSQL:
    """T0 核验通道编译入口:意图(闭集)→ 声明渲染 → 安全闸 → CompiledSQL。"""
    from .engine import CompiledSQL, UnsupportedQuery

    _assert_model_matches_card()
    block = _compile_blocks().get(intent.metric)
    if block is None:
        raise UnsupportedQuery(f"指标 {intent.metric} 未接入声明编译")

    shape = block.get("shape")
    if shape == "spu_rank":
        sql, params = _shape_spu_rank(intent, block, business_id)
    elif shape == "dim_rank":
        sql, params = _shape_dim_rank(intent, block, business_id)
    elif shape == "total_single":
        sql, params = _shape_total_single(intent, block, business_id)
    elif shape == "trend":
        sql, params = _shape_trend(intent, block, business_id)
    else:
        raise UnsupportedQuery(f"指标 {intent.metric} 声明了未知编译形状 {shape!r}")

    try:
        ast = assert_safe_select(sql, compile_safe_schema_card(), require_business_id="business_id" in sql)
    except UnsafeSqlError as err:
        raise ValueError(f"编译模板未过安全闸(模板缺陷,非用户问题): {err}") from err
    return CompiledSQL(
        sql=sql,
        params=params,
        metric=intent.metric,
        unit=metric_semantic_registry()[intent.metric]["unit"],
        ast=ast,
        chart_hint=chart_hint if chart_hint is not None else intent.chart_hint,
        target_db=block.get("target_db") or "merchant_db",
    )


def _join(name: str) -> dict[str, Any]:
    """按名取声明 join(悬空名 = 模型/指标声明不一致,编译期响亮)。"""
    for join in _model()["joins"]:
        if join["name"] == name:
            return join
    raise ValueError(f"语义模型未声明 join {name!r}(compile 块引用悬空)")


def _join_clause(names: list[str]) -> str:
    """声明 join → SQL JOIN 子句串(table=被连入表,base=FROM 侧;全部来自模型)。"""
    parts = []
    for name in names:
        j = _join(name)
        kind = "LEFT JOIN" if j["type"] == "left" else "JOIN"
        parts.append(f"{kind} {j['table']} {_model()['entities'][j['table']]['alias']} ON {j['condition']} ")
    return "".join(parts)


def _where_parts(
    intent: StructuredQueryIntent, block: dict[str, Any], business_id: str
) -> tuple[list[str], dict[str, Any]]:
    """dim_rank/total_single 共用过滤拼装:声明常量口径(where)+ 时间窗
    (time_column)+ engine_db 实体自动租户谓词。用户输入永不进文本(全部绑参)。"""
    from .engine import window_start

    base = block["base"]
    alias = _model()["entities"][base]["alias"]
    parts = list(block.get("where") or [])
    params: dict[str, Any] = {}
    if intent.time_window and block.get("time_column"):
        parts.append(f"{block['time_column']} >= :window_start")
        params["window_start"] = window_start(intent.time_window)
    if _model()["entities"][base]["database"] == "engine_db":
        parts.append(f"{alias}.business_id = :business_id")
        params["business_id"] = business_id
    return parts, params


def _shape_dim_rank(intent: StructuredQueryIntent, block: dict[str, Any], business_id: str) -> tuple[str, dict[str, Any]]:
    """通用「维度×度量」榜:声明 select 输出列/join 路径/常量口径/分组列,
    渲染 GROUP BY + ORDER BY "metricScore" + LIMIT :lim。"""
    select_parts = [f'{col["expr"]} AS "{col["as"]}"' for col in block["select"]]
    select_parts.append(f'{block["measure"]} AS "metricScore"')
    base = block["base"]
    alias = _model()["entities"][base]["alias"]
    sql = (
        f'SELECT {", ".join(select_parts)} '
        f"FROM {base} {alias} "
        f"{_join_clause(block.get('joins') or [])}"
    )
    where_parts, params = _where_parts(intent, block, business_id)
    params["lim"] = intent.limit
    if where_parts:
        sql += f"WHERE {' AND '.join(where_parts)} "
    sql += f"GROUP BY {', '.join(block['group_by'])} "
    return sql + f'ORDER BY "metricScore" {intent.direction} LIMIT :lim', params


def _shape_total_single(intent: StructuredQueryIntent, block: dict[str, Any], business_id: str) -> tuple[str, dict[str, Any]]:
    """总量单行('__total__'):limit_mode=param 走 :lim 槽位,one 字面 LIMIT 1
    (单行聚合天然有界,aov/order_count 形态)。"""
    base = block["base"]
    alias = _model()["entities"][base]["alias"]
    sql = f"SELECT '__total__' AS \"productId\", {block['measure']} AS \"metricScore\" FROM {base} {alias} "
    where_parts, params = _where_parts(intent, block, business_id)
    if where_parts:
        sql += f"WHERE {' AND '.join(where_parts)} "
    if block.get("limit_mode", "param") == "one":
        return sql + "LIMIT 1", params
    params["lim"] = intent.limit
    return sql + "LIMIT :lim", params


# 趋势族日历脊:默认近 30 天按日;「近 N 个月」切自然月粒度(含当月共 N 个月)
_TREND_DAY_SPINE = (
    "FROM generate_series(CURRENT_DATE - INTERVAL '29 days', CURRENT_DATE, INTERVAL '1 day') d(day) "
    "LEFT JOIN merchant_orders o ON o.created_at::date = d.day "
)
_TREND_MONTH_SPINE = (
    "FROM generate_series(date_trunc('month', CURRENT_DATE) - "
    "INTERVAL '{months} months', date_trunc('month', CURRENT_DATE), "
    "INTERVAL '1 month') d(month) "
    "LEFT JOIN merchant_orders o ON date_trunc('month', o.created_at) = d.month "
)


def _shape_trend(intent: StructuredQueryIntent, block: dict[str, Any], business_id: str) -> tuple[str, dict[str, Any]]:
    """趋势族(阶段⑥⑦⑧ 口径逐字保留):明细 LEFT JOIN 无条件追加(零点保线
    不断);实体过滤入 JOIN ON 而非 WHERE(无销售日照常出零点);时间序列窗口
    固定,字面 LIMIT 50 兜底行数。"""
    spu_ids = (intent.entity_slot or {}).get("spu") or []
    params: dict[str, Any] = {}
    items_join = "LEFT JOIN merchant_order_items oi ON oi.order_id = o.order_id "
    if spu_ids and block.get("spu_filter_via_items"):
        items_join += "AND oi.spu_id = ANY(:spu_ids) "
        params["spu_ids"] = spu_ids[:50]
    cust_ids = (intent.entity_slot or {}).get("customer") or []
    customer_clause = ""
    if cust_ids and block.get("customer_filter"):
        customer_clause = "AND o.customer_id = ANY(:entities) "
        params["entities"] = cust_ids[:20]
    window = intent.time_window or {}
    n = int(window.get("n") or 0) if window.get("kind") == "last_months" else 0
    if n >= 2:
        months = min(n, 24) - 1  # 含当月共 n 个月;倍数已钳 1-24,字面插值安全
        sql = (
            "SELECT to_char(d.month, 'YYYY-MM') AS \"月份\", "
            f"{block['measure']} AS \"{block['label']}\" "
            + _TREND_MONTH_SPINE.format(months=months)
            + f"AND o.status NOT IN ('REFUNDED', 'CANCELLED') {customer_clause}"
            f"{items_join}"
            "GROUP BY d.month ORDER BY d.month LIMIT 50"
        )
    else:
        sql = (
            "SELECT to_char(d.day, 'MM-DD') AS \"日期\", "
            f"{block['measure']} AS \"{block['label']}\" "
            + _TREND_DAY_SPINE
            + f"AND o.status NOT IN ('REFUNDED', 'CANCELLED') {customer_clause}"
            f"{items_join}"
            "GROUP BY d.day ORDER BY d.day LIMIT 50"
        )
    return sql, params


# ---------------- 形状:spu_rank(销售族商品榜;字节级复刻 legacy 模板) ----------------

def _shape_spu_rank(intent: StructuredQueryIntent, block: dict[str, Any], business_id: str) -> tuple[str, dict[str, Any]]:
    """销售族模板(= query_product_ranking 已验证口径的模板化):明细先按 spu
    预聚合进子查询防笛卡尔;title 先于 id 出列(实弹 2026-09-30);零销量 HAVING
    口径按指标声明(gmv/volume 排除零成交,毛利/毛利率/库存保留全量在售)。

    join/别名/表名全部取自语义模型声明;度量与 HAVING 口径来自 metrics.yaml
    compile 块 —— 本函数只拥有「查询形态」。
    """
    from .engine import window_start

    entities_tbl = _model()["entities"]
    base = "merchant_spus"
    base_alias = entities_tbl[base]["alias"]  # s
    sku_join = _join("sku_of_spu")  # LEFT JOIN merchant_skus k ON k.spu_id = s.id

    measure = block["measure"]
    direction = intent.direction
    sql = (
        # title 必须先于 id 出列:条形图标签/速览榜首/表格首列全部取首个文本列,
        # s.id 是商户库 UUID,首列放它 = 排行卡全变 UUID(实弹 2026-09-30)
        f'SELECT {base_alias}.title AS "name", {base_alias}.id::text AS "productId", {base_alias}.category, '
        "COALESCE(SUM(k.stock), 0)::int AS stock, "
        f'{measure} AS "metricScore" '
        f"FROM {base} {base_alias} "
        f"LEFT JOIN {sku_join['table']} k ON {sku_join['condition']} "
        "LEFT JOIN ("
        "SELECT oi.spu_id, SUM(oi.quantity) AS qty, SUM(oi.quantity * oi.price) AS price_sum, "
        "SUM(oi.quantity * oi.cost_at_purchase) AS cost, "
        "SUM(oi.quantity) AS metric_score "
        "FROM merchant_order_items oi "
        "JOIN merchant_orders o ON o.order_id = oi.order_id "
        "WHERE o.status NOT IN ('REFUNDED', 'CANCELLED') {time_clause} "
        "GROUP BY oi.spu_id"
        ") agg ON agg.spu_id = s.spu_code "
        "WHERE s.status = 'ON_SALE' {category_clause} "
        f"GROUP BY {base_alias}.id, {base_alias}.title, {base_alias}.category "
        "{having_clause}"
        f'ORDER BY "metricScore" {direction} '
        "LIMIT :lim"
    )
    params: dict[str, Any] = {"lim": intent.limit}
    time_clause = ""
    if intent.time_window:
        time_clause = "AND o.created_at >= :window_start"
        params["window_start"] = window_start(intent.time_window)
    category_clause = ""
    if intent.category:
        category_clause = f"AND {base_alias}.category = :cat"
        params["cat"] = intent.category
    # 零销量 HAVING 口径与旧路径逐位一致(18-D2 冻结):由 compile 块声明,
    # 非 Python 字面元组(注册表新增销售指标时声明即代码)
    having_clause = "HAVING COALESCE(MAX(agg.qty), 0) > 0 " if block.get("zero_sales_having") else ""

    sql = sql.format(time_clause=time_clause, category_clause=category_clause, having_clause=having_clause)

    # 实体过滤:PageContext 勾选优先;其次 L3/行内绑定解析出的 spu 实体槽
    # (「这款商品卖多少」问法)—— 两者同走 IN 绑定,长度上限 100。
    entity_ids = list(intent.entity_ids) or list((intent.entity_slot or {}).get("spu") or [])
    if entity_ids:
        sql = sql.replace(
            "WHERE s.status = 'ON_SALE'",
            f"WHERE {base_alias}.status = 'ON_SALE' AND {base_alias}.spu_code = ANY(:entities)",
        )
        params["entities"] = entity_ids[:100]
    return sql, params
