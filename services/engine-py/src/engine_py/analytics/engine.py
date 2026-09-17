"""L0 同义词归一 + MetricQueryEngine 深模块(09-D5 接口冻结;08-D1 路线)。

resolve:问句 → StructuredQueryIntent(闭集标签) | ClarificationRequest(反问);
未命中抛 UnsupportedQuery —— 08-P1:废除静默兜底 gmv。
compile:意图 → CompiledSQL(fragment 闭集 + bindparams;business_id 服务端注入;
LIMIT clamp 1-50;sql_guard 校验后 AST 断言)。
execute:CompiledSQL → QueryResult(只读 reader 引擎;诚实空)。

LLM 的位置在 L3(未来 adapter,接口同 resolve);本模块词面层零 LLM 调用。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from .schema_cards import merchant_schema_card
from .sql_guard import UnsafeSqlError, assert_safe_select
from .tools_registry_bridge import metric_semantic_registry


class UnsupportedQuery(Exception):
    """问句落在已注册指标空间之外(响亮失败,呈现层给可选问法)。"""


@dataclass(frozen=True)
class StructuredQueryIntent:
    metric: str
    direction: str = "DESC"
    limit: int = 5
    time_window: dict | None = None
    category: str | None = None
    entity_ids: list[str] = field(default_factory=list)  # PageContext 选中实体(IN 绑定)


@dataclass
class QueryResult:
    rows: list[dict]
    metric: str
    unit: str
    caliber: str  # 口径注记(呈现层展示;数据诚实铁律)
    source: str = "metric_template"


class MetricQueryEngine:
    """09-D5 冻结接口。session_ctx 由调用方传入(business_id/role);本模块内
    business_id 只进绑定参数,不拼接 SQL 文本。"""

    _LIMIT_RE = re.compile(r"top\s*(\d+)", re.IGNORECASE)
    _REVERSE_WORDS = ("最差", "垫底", "最烂", "卖不动", "不走量", "最低")
    # 反向词族自带指标指向(词表全正向,反向问句不命中同义词 — 03 号票 L0 缺口)
    _REVERSE_METRIC_HINTS = (
        ("卖得最差", "gmv"), ("卖得差", "gmv"), ("销售额最低", "gmv"), ("流水最低", "gmv"),
        ("销量最低", "volume"), ("卖得最少", "volume"), ("件数最少", "volume"),
    )
    _GENERIC_POSITIVE = ("卖得最好", "卖得好", "最好", "爆款", "畅销")
    _GENERIC_HINTS = (("卖得最好", ("gmv", "volume")), ("卖得好", ("gmv", "volume")), ("最好", ("gmv", "volume")))
    _TIME_PATTERNS = (
        ("last_month", re.compile(r"上个月|上月")),
        ("last_7d", re.compile(r"最近(一|7)天|近7天")),
        ("last_30d", re.compile(r"最近(三十|30)天|近30天")),
    )

    def __init__(self, session_ctx: dict | None = None, resolver: Any | None = None) -> None:
        self.session_ctx = session_ctx or {}
        self._resolver = resolver  # 未来:11-D1 缝②指标映射 adapter(closed-set 分类头)

    # ---------------- resolve(L0 词面归一) ----------------
    def resolve(self, question: str, session_ctx: dict | None = None) -> StructuredQueryIntent | dict:
        clean = (question or "").strip().lower()
        if not clean:
            raise UnsupportedQuery("空问题")

        if self._resolver is not None:  # 缝②:训练产物优先
            return self._resolver(question)

        registry = metric_semantic_registry()
        hit: tuple[str, str] | None = None
        matched_words: list[tuple[str, str]] = []
        for phrase, hinted_key in self._REVERSE_METRIC_HINTS:
            if phrase in clean:
                matched_words.append((hinted_key, phrase))
        if not matched_words:
            for phrase, hinted_keys in self._GENERIC_HINTS:
                if phrase in clean:
                    matched_words.extend((k, phrase) for k in hinted_keys)
        for key, metric in registry.items():
            if key in clean or metric["label"].lower() in clean:
                matched_words.append((key, metric["label"]))
            for syn in metric.get("synonyms") or []:
                if syn.lower() in clean:
                    matched_words.append((key, syn))
        if matched_words:
            matched_words.sort(key=lambda p: len(p[1]), reverse=True)
            hit = (matched_words[0][0], matched_words[0][1])

        if hit is None:
            raise UnsupportedQuery(f"未命中已注册指标(闭集={list(registry)})")

        metric_key = hit[0]
        metric = registry[metric_key]

        # 反向词 → 方向翻转(03-L0 决议);正向泛指词 × 多销售指标 → 反问
        reverse = any(w in clean for w in self._REVERSE_WORDS)
        direction = ("ASC" if metric["direction"] == "DESC" else "DESC") if reverse else metric["direction"]

        group = metric.get("conflictGroup") or []
        if group and any(w in clean for w in self._GENERIC_POSITIVE) and not any(
            w in clean for w in ("金额", "件数", "销量", "销售额", "毛利", "利润", "流水", "营业额", "库存")
        ):
            siblings = [m for m in registry.values() if group[0] in (m.get("conflictGroup") or [])]
            if len(siblings) > 1:
                return {
                    "clarify": True,
                    "question": f"「{question[:20]}」是指——",
                    "options": [{"key": m["key"], "label": m["label"], "intent": {"metric": m["key"], "direction": m["direction"]}} for m in siblings],
                }

        limit_match = self._LIMIT_RE.search(clean)
        limit = min(max(int(limit_match.group(1)) if limit_match else 5, 1), 50)

        time_window = next(({"kind": kind} for kind, pat in self._TIME_PATTERNS if pat.search(clean)), None)

        category = None
        cat_match = re.search(r"(户外机能|潮流T恤|下装裤类|潮流鞋靴|背包收纳|露营装备|衬衫|配饰|运动配件)", clean, re.IGNORECASE)
        if cat_match:
            category = cat_match.group(1)

        return StructuredQueryIntent(metric=metric_key, direction=direction, limit=limit, time_window=time_window, category=category)

    # ---------------- compile(模板拼装;LLM 不参与) ----------------
    def compile(self, intent: StructuredQueryIntent | dict, session_ctx: dict | None = None) -> Any:
        ctx = {**self.session_ctx, **(session_ctx or {})}
        business_id = ctx.get("business_id")
        if not business_id:
            raise ValueError("session_ctx.business_id 必传(租户谓词服务端注入,不可缺席)")

        metric = metric_semantic_registry()[intent.metric]
        direction = intent.direction

        # 销售族聚合模板(= query_product_ranking 已验证口径的模板化,阶段②销售族迁移底座):
        # 退款/取消单子查询内排除;明细预聚合防笛卡尔;成本快照不容 COALESCE。
        # 子查询已按 spu 预聚合(qty/price_sum/cost),外层表达式只引用 agg 输出列
        # (防笛卡尔同 query_product_ranking);stock 独走 SKU 汇总。
        metric_expr = {
            "gmv": "COALESCE(MAX(agg.price_sum), 0)::float",
            "volume": "COALESCE(MAX(agg.qty), 0)::int",
            "gross_profit": "(COALESCE(MAX(agg.price_sum), 0) - COALESCE(MAX(agg.cost), 0))::float",
            "margin_rate": (
                "(CASE WHEN COALESCE(MAX(agg.price_sum), 0) > 0 "
                "THEN (COALESCE(MAX(agg.price_sum), 0) - COALESCE(MAX(agg.cost), 0)) * 100.0 "
                "/ MAX(agg.price_sum) ELSE 0 END)::float"
            ),
            "stock_risk": "COALESCE(SUM(k.stock), 0)::int",
        }.get(intent.metric)

        if metric_expr is None:
            # 阶段③新指标族(评价/退货/会话)登记处;未登记 = 不支持
            raise UnsupportedQuery(f"指标 {intent.metric} 尚未登记执行模板")

        sql = (
            'SELECT s.id::text AS "productId", s.title AS "name", s.category, '
            "COALESCE(SUM(k.stock), 0)::int AS stock, "
            f"{metric_expr} AS \"metricScore\" "
            "FROM merchant_spus s "
            "LEFT JOIN merchant_skus k ON k.spu_id = s.id "
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
            'GROUP BY s.id, s.title, s.category '
            "{having_clause}"
            f"ORDER BY \"metricScore\" {direction} "
            "LIMIT :lim"
        )
        params: dict[str, Any] = {"lim": intent.limit}
        time_clause = ""
        if intent.time_window:
            time_clause = "AND o.created_at >= :window_start"
            params["window_start"] = self._window_start(intent.time_window)
        category_clause = ""
        if intent.category:
            category_clause = "AND s.category = :cat"
            params["cat"] = intent.category
        # 零销量 HAVING 口径与旧路径逐位一致(18-D2 冻结):仅 gmv/volume 榜
        # 排除零成交款(诚实空优于误导);毛利/毛利率/库存风险榜保留全量在售。
        having_clause = (
            "HAVING COALESCE(MAX(agg.qty), 0) > 0 " if intent.metric in ("gmv", "volume") else ""
        )

        sql = sql.format(time_clause=time_clause, category_clause=category_clause, having_clause=having_clause)

        # 租户谓词(08-D4):单商户部署下 merchant_orders 无 business_id 列
        # (02 号票实证),部署级隔离由「一部署一库」承担;business_id 缺席即拒编译
        # (接口不变量:调用方必须携租户身份),商户库加列(17 号迁移流程)后
        # 此处即插 :business_id 行级谓词与参数。
        if not business_id:
            raise ValueError("session_ctx.business_id 必传(租户谓词服务端注入,不可缺席)")

        if intent.entity_ids:
            sql = sql.replace("WHERE s.status = 'ON_SALE'", "WHERE s.status = 'ON_SALE' AND s.spu_code = ANY(:entities)")
            params["entities"] = list(intent.entity_ids)[:100]

        try:
            ast = assert_safe_select(sql, merchant_schema_card(), require_business_id="business_id" in sql)
        except UnsafeSqlError as err:
            raise ValueError(f"编译模板未过安全闸(模板缺陷,非用户问题): {err}") from err
        return CompiledSQL(sql=sql, params=params, metric=intent.metric, unit=metric["unit"], ast=ast)

    async def execute_async(self, compiled: Any, session_ctx: dict | None = None) -> QueryResult:
        """异步执行(LangGraph 节点主路径);reader 已带 READ ONLY + 超时(阶段①)。"""
        from sqlalchemy import text

        from ..tools_registry import order_domain

        # 运行时读取模块属性(测试/漂移断言会替换 reader 工厂,静态引用会绕过 patch)
        async with order_domain._merchant_reader_engine().connect() as conn:
            rows = (await conn.execute(text(compiled.sql).bindparams(**compiled.params))).mappings().all()
        return QueryResult(
            rows=[dict(r) for r in rows],
            metric=compiled.metric,
            unit=compiled.unit,
            caliber="有效订单聚合(排除退款/取消单)",
        )

    def execute(self, compiled: Any, session_ctx: dict | None = None) -> QueryResult:
        """同步包装(脚本/评测用);已在事件循环内请用 execute_async。"""
        import asyncio

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self.execute_async(compiled, session_ctx))
        raise RuntimeError("execute() 不能在事件循环内调用;请 await execute_async()")

    def _window_start(self, window: dict) -> datetime:
        kind = window.get("kind")
        now = datetime.now()
        if kind == "last_month":
            first = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            return (first - timedelta(days=1)).replace(day=1)
        if kind == "last_7d":
            return now - timedelta(days=7)
        if kind == "last_30d":
            return now - timedelta(days=30)
        raise UnsupportedQuery(f"未知时间窗 {kind}")


@dataclass(frozen=True)
class CompiledSQL:
    sql: str
    params: dict
    metric: str
    unit: str
    ast: Any = field(default=None, repr=False, compare=False)
