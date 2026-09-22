"""L0 同义词归一 + MetricQueryEngine 深模块(09-D5 接口冻结;08-D1 路线)。

resolve:问句 → StructuredQueryIntent(闭集标签) | ClarificationRequest(反问);
未命中抛 UnsupportedQuery —— 08-P1:废除静默兜底 gmv。
compile:意图 → CompiledSQL(fragment 闭集 + bindparams;business_id 服务端注入;
LIMIT clamp 1-50;sql_guard 校验后 AST 断言)。
execute:CompiledSQL → QueryResult(只读 reader 引擎;诚实空)。

LLM 的位置在 L3(未来 adapter,接口同 resolve);本模块词面层零 LLM 调用。
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from .schema_cards import compile_safe_schema_card
from .sql_guard import UnsafeSqlError, assert_safe_select
from .tools_registry_bridge import metric_semantic_registry

_CALIBERS = {
    "review_bad": "差评口径 = rating ≤ 2(商户真实评价)",
    "refund_rate": "退款率 = 退款件 ÷ (有效+退款)件 × 100;CANCELLED 不计分母",
    "session_volume": "会话量 = session_metrics 计数(与平台大盘同源)",
    "ai_resolution_rate": "AI 解决率 = resolved_auto ÷ 总会话 × 100(session_metrics 同源)",
    "after_sale_overview": "售后工单按状态分布计数(after_sale_tickets 真算)",
    "order_overview": "对页面勾选订单逐笔展示(订单号/状态/金额/时间),合计与均值随行列出,便于两单对比",
    "promo_effect": "活动口径 = 核销记录关联订单(真实归因;自然流量不计入),GMV 为核销订单实付合计",
    "promo_sku_compare": "活动内对比 = 该活动核销订单的商品明细聚合;目标款在「对比分组」列标记",
    "customer_orders": "客户订单 = 名下全部订单按下单时间倒序",
    "promo_compare": "双活动对比 = 各自核销记录关联订单聚合(真实归因;自然流量不计入)",
}


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
    # 命名实体槽(ADR-0005):LLM/L2 解析后的实体 ID 集合,如
    # {"promotion": ["<uuid>"], "customer": ["CUST-8801"], "spu": ["AURORA-SPU-1"]}
    entity_slot: dict[str, list[str]] = field(default_factory=dict)


@dataclass
class QueryResult:
    rows: list[dict]
    metric: str
    unit: str
    caliber: str  # 口径注记(呈现层展示;数据诚实铁律)
    source: str = "metric_template"
    chart: str | None = None  # line=折线(时间序列);None=默认表格


class MetricQueryEngine:
    """09-D5 冻结接口。session_ctx 由调用方传入(business_id/role);本模块内
    business_id 只进绑定参数,不拼接 SQL 文本。"""

    _LIMIT_RE = re.compile(r"top\s*(\d+)", re.IGNORECASE)
    _REVERSE_WORDS = ("最差", "垫底", "最烂", "卖不动", "不走量", "最低", "最少")
    # 反向词族自带指标指向(词表全正向,反向问句不命中同义词 — 03 号票 L0 缺口)
    _REVERSE_METRIC_HINTS = (
        ("卖得最差", "gmv"), ("卖得差", "gmv"), ("销售额最低", "gmv"), ("流水最低", "gmv"),
        ("销量最低", "volume"), ("卖得最少", "volume"), ("件数最少", "volume"),
    )
    _GENERIC_POSITIVE = ("卖得最好", "卖得好", "最好", "爆款", "畅销")
    _GENERIC_HINTS = (("卖得最好", ("gmv", "volume")), ("卖得好", ("gmv", "volume")), ("最好", ("gmv", "volume")))
    _TIME_PATTERNS = (
        ("last_month", re.compile(r"上个月|上月")),
        ("last_7d", re.compile(r"最近\s*(一|7)\s*天|近\s*7\s*天")),
        ("last_30d", re.compile(r"最近\s*(三十|30)\s*天|近\s*(三十|30)\s*天")),
        # 跨月统计(用户实弹诉求):近/最近/过去 N 个月、「几个月的销量」(N 缺省 6);
        # 纯「每月/按月/月度」无 N 同样切月粒度(N 缺省 6)
        ("last_months", re.compile(r"(?:(?:近|最近|过去)\s*)?(\d{1,2}|[一两二三四五六七八九十几]+)\s*个月的?")),
        ("last_months", re.compile(r"每月|按月|月度")),
    )
    _CN_MONTH_NUMS = {"一": 1, "两": 2, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6,
                      "七": 7, "八": 8, "九": 9, "十": 10, "几": 6}

    def __init__(self, session_ctx: dict | None = None, resolver: Any | None = None) -> None:
        self.session_ctx = session_ctx or {}
        self._resolver = resolver  # 注入式 resolver(测试/显式 adapter)
        # 11-D1 缝②:分类头三态(shadow=并行打分只记日志 / on=L0 未命中处接管;
        # 默认不启用)。懒加载由工厂保证,进程内单例。
        from .metric_head import get_metric_head

        self._head = get_metric_head()
        self._head_threshold = float(os.environ.get("AI_METRIC_HEAD_THRESHOLD", "0.5"))

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
            # 匹配词记录实际命中的词面(key/label 各自),不记整段 label —— 否则
            # key 命中会以 label 长度参与最长优先,压过更具体的趋势类条目(实弹修)
            if key in clean:
                matched_words.append((key, key))
            elif metric["label"].lower() in clean:
                matched_words.append((key, metric["label"]))
            for syn in metric.get("synonyms") or []:
                if syn.lower() in clean:
                    matched_words.append((key, syn))
        if matched_words:
            matched_words.sort(key=lambda p: len(p[1]), reverse=True)
            hit = (matched_words[0][0], matched_words[0][1])
            # 榜/排行语义优先于趋势:「上个月的销量排行」问的是榜单不是折线;
            # 时间窗照常生效(_trend → 对应榜单指标),趋势问法不受影响。
            if hit[0].endswith("_trend") and re.search(r"排行|排名|榜单|榜|top\s*\d*", clean):
                hit = ({"gmv_trend": "gmv", "volume_trend": "volume"}.get(hit[0], hit[0]), hit[1])

        if self._head is not None:
            try:
                head_label, head_conf = self._head.predict(question)
                if hit is not None and head_label != hit[0]:
                    print(
                        f"[MetricHead][shadow] 不一致: L0={hit[0]} head={head_label}({head_conf:.2f})"
                        f" question={question[:40]!r}"
                    )
            except Exception as head_err:
                print(f"[MetricHead] 打分失败(放行 L0/L3): {head_err}")

        if hit is None:
            # 缝② on 模式:L0 未命中 → 分类头接管(低置信仍放行 L3,不许静默错分);
            # 槽位(limit/时间窗/品类)与 L0 命中路同源解析(0014 缺口修复)
            if self._head is not None:
                try:
                    head_label, head_conf = self._head.predict(question)
                    if head_label in registry and head_conf >= self._head_threshold:
                        print(f"[MetricHead][on] 接管: {head_label}({head_conf:.2f}) question={question[:40]!r}")
                        limit2, time2, cat2 = self._extract_slots(clean)
                        return StructuredQueryIntent(
                            metric=head_label, direction=registry[head_label]["direction"],
                            limit=limit2, time_window=time2, category=cat2,
                        )
                except UnsupportedQuery:
                    pass
                except Exception as head_err:
                    print(f"[MetricHead] on 模式打分失败: {head_err}")
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

        limit, time_window, category = self._extract_slots(clean)

        return StructuredQueryIntent(metric=metric_key, direction=direction, limit=limit, time_window=time_window, category=category)

    def _extract_slots(self, clean: str) -> tuple[int, dict | None, str | None]:
        """开放槽位解析(limit/时间窗/品类);L0 命中路与分类头 on 路径共用。"""
        limit_match = self._LIMIT_RE.search(clean)
        limit = min(max(int(limit_match.group(1)) if limit_match else 5, 1), 50)
        time_window: dict | None = None
        for kind, pat in self._TIME_PATTERNS:
            m = pat.search(clean)
            if m:
                time_window = {"kind": kind}
                if kind == "last_months":
                    raw = m.group(1) if m.groups() else None
                    n = int(raw) if raw and raw.isdigit() else self._CN_MONTH_NUMS.get(raw or "", 6)
                    time_window["n"] = min(max(n, 1), 24)
                break
        cat_match = re.search(r"(户外机能|潮流T恤|下装裤类|潮流鞋靴|背包收纳|露营装备|衬衫|配饰|运动配件)", clean, re.IGNORECASE)
        category = cat_match.group(1) if cat_match else None
        return limit, time_window, category

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
            # 阶段③新指标族(评价/退货/会话):独立模板族,非销售族形状
            return self._compile_special_family(intent, business_id)

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

        # 实体过滤:PageContext 勾选优先;其次 L3/行内绑定解析出的 spu 实体槽
        # (「这款商品卖多少」问法)—— 两者同走 IN 绑定,长度上限 100。
        entities = list(intent.entity_ids) or list((intent.entity_slot or {}).get("spu") or [])
        if entities:
            sql = sql.replace("WHERE s.status = 'ON_SALE'", "WHERE s.status = 'ON_SALE' AND s.spu_code = ANY(:entities)")
            params["entities"] = entities[:100]

        try:
            ast = assert_safe_select(sql, compile_safe_schema_card(), require_business_id="business_id" in sql)
        except UnsafeSqlError as err:
            raise ValueError(f"编译模板未过安全闸(模板缺陷,非用户问题): {err}") from err
        return CompiledSQL(sql=sql, params=params, metric=intent.metric, unit=metric["unit"], ast=ast)

    def _compile_special_family(self, intent: StructuredQueryIntent, business_id: str) -> CompiledSQL:
        """阶段③新族模板:评价/退货(商户库)、会话(engine 本地库)。

        闭集 fragment + bindparams 同销售族;差评/退款族输出商品排行形状,
        会话族输出总量单行(productId=__total__)。未登记指标仍响亮 Unsupported。
        """
        direction = intent.direction
        # merchant 路无租户列(02 号实证):business_id 只进 engine_db 路参数
        params: dict[str, Any] = {"lim": intent.limit}
        if intent.metric in ("session_volume", "ai_resolution_rate"):
            params["business_id"] = business_id
        time_clause = ""

        if intent.metric == "review_bad":
            if intent.time_window:
                time_clause = "AND r.created_at >= :window_start"
                params["window_start"] = self._window_start(intent.time_window)
            sql = (
                'SELECT s.title AS "productId", COUNT(*) AS "metricScore" '
                "FROM merchant_product_reviews r JOIN merchant_spus s ON s.id = r.spu_id "
                f"WHERE r.rating <= 2 {time_clause} "
                f'GROUP BY s.id, s.title ORDER BY "metricScore" {direction} LIMIT :lim'
            )
        elif intent.metric == "refund_rate":
            if intent.time_window:
                time_clause = "AND o.created_at >= :window_start"
                params["window_start"] = self._window_start(intent.time_window)
            sql = (
                'SELECT oi.spu_id AS "productId", '
                "ROUND(COALESCE(SUM(CASE WHEN o.status = 'REFUNDED' THEN oi.quantity ELSE 0 END), 0)::numeric "
                "* 100 / GREATEST(SUM(CASE WHEN o.status <> 'CANCELLED' THEN oi.quantity ELSE 0 END), 1), 2)::float AS \"metricScore\" "
                "FROM merchant_order_items oi JOIN merchant_orders o ON o.order_id = oi.order_id "
                f"WHERE o.status <> 'CANCELLED' {time_clause} "
                f'GROUP BY oi.spu_id ORDER BY "metricScore" {direction} LIMIT :lim'
            )
        elif intent.metric == "session_volume":
            if intent.time_window:
                time_clause = "AND created_at >= :window_start"
                params["window_start"] = self._window_start(intent.time_window)
            sql = (
                "SELECT '__total__' AS \"productId\", COUNT(*)::int AS \"metricScore\" "
                f"FROM session_metrics WHERE business_id = :business_id {time_clause} LIMIT :lim"
            )
        elif intent.metric in ("promo_orders", "promo_discount_total"):
            if intent.time_window:
                time_clause = "AND r.created_at >= :window_start"
                params["window_start"] = self._window_start(intent.time_window)
            value_expr = (
                "COUNT(DISTINCT r.order_id)" if intent.metric == "promo_orders" else "COALESCE(SUM(r.discount_amount), 0)::float"
            )
            sql = (
                "SELECT p.name AS \"productId\", "
                f"{value_expr} AS \"metricScore\" "
                "FROM promotion_redemptions r JOIN promotions p ON p.id = r.promotion_id "
                f"WHERE 1=1 {time_clause} "
                f'GROUP BY p.name ORDER BY "metricScore" {direction} LIMIT :lim'
            )
        elif intent.metric == "after_sale_overview":
            if intent.time_window:
                time_clause = "AND created_at >= :window_start"
                params["window_start"] = self._window_start(intent.time_window)
            sql = (
                'SELECT status AS "productId", COUNT(*)::int AS "metricScore" '
                f"FROM after_sale_tickets WHERE business_id = :business_id {time_clause} "
                f'GROUP BY status ORDER BY "metricScore" {direction} LIMIT :lim'
            )
        elif intent.metric in ("gmv_trend", "volume_trend"):
            # 趋势族(阶段⑥升级):默认近 30 天按日;「近 N 个月」切自然月粒度
            params.pop("lim", None)  # 时间序列窗口固定,仍以显式 LIMIT 兜底行数
            value_expr = (
                "COALESCE(SUM(oi.quantity * oi.price), 0)::float"
                if intent.metric == "gmv_trend"
                else "COALESCE(SUM(oi.quantity), 0)::float"
            )
            label = "GMV" if intent.metric == "gmv_trend" else "销量"
            window = intent.time_window or {}
            n = int(window.get("n") or 0) if window.get("kind") == "last_months" else 0
            if n >= 2:
                months = min(n, 24) - 1  # 含当月共 n 个月;倍数已钳 1-24,字面插值安全
                sql = (
                    "SELECT to_char(d.month, 'YYYY-MM') AS \"月份\", "
                    f"{value_expr} AS \"{label}\" "
                    "FROM generate_series(date_trunc('month', CURRENT_DATE) - "
                    f"INTERVAL '{months} months', date_trunc('month', CURRENT_DATE), "
                    "INTERVAL '1 month') d(month) "
                    "LEFT JOIN merchant_orders o ON date_trunc('month', o.created_at) = d.month "
                    "AND o.status NOT IN ('REFUNDED', 'CANCELLED') "
                    "LEFT JOIN merchant_order_items oi ON oi.order_id = o.order_id "
                    f"GROUP BY d.month ORDER BY d.month LIMIT 50"
                )
            else:
                sql = (
                    "SELECT to_char(d.day, 'MM-DD') AS \"日期\", "
                    f"{value_expr} AS \"{label}\" "
                    "FROM generate_series(CURRENT_DATE - INTERVAL '29 days', CURRENT_DATE, INTERVAL '1 day') d(day) "
                    "LEFT JOIN merchant_orders o ON o.created_at::date = d.day "
                    "AND o.status NOT IN ('REFUNDED', 'CANCELLED') "
                    "LEFT JOIN merchant_order_items oi ON oi.order_id = o.order_id "
                    f"GROUP BY d.day ORDER BY d.day LIMIT 50"
                )
        elif intent.metric == "order_overview":
            # ADR-0005:升级为逐笔行 + 合计/均值窗口列 —— 「两个订单对比」等
            # 对比类问法可直接看每单差异;实体来自 PageContext 勾选(必传)。
            params.pop("lim", None)  # 逐笔展示无 LIMIT 槽位,显式 50 行双保险
            if not intent.entity_ids:
                raise UnsupportedQuery("请先在订单列表中勾选订单,再问对比/概览(实体集必传)")
            sql = (
                'SELECT o.order_id AS "订单号", o.status AS "状态", '
                'o.total_amount::float AS "金额", '
                "to_char(o.created_at, 'MM-DD HH24:MI') AS \"created_at\", "
                'ROUND(SUM(o.total_amount) OVER (), 2)::float AS "合计金额", '
                'ROUND(AVG(o.total_amount) OVER (), 2)::float AS "平均金额" '
                'FROM merchant_orders o WHERE o.order_id = ANY(:entities) '
                'ORDER BY o.created_at DESC LIMIT 50'
            )
            params["entities"] = list(intent.entity_ids)[:100]
        elif intent.metric == "promo_compare":
            # ADR-0005 登记流水线首批:双活动并排对比(核销关联口径)
            params.pop("lim", None)  # 并排两行无 LIMIT 槽位
            promo_ids = (intent.entity_slot or {}).get("promotion") or []
            if len(promo_ids) < 2:
                raise UnsupportedQuery("请指明两个活动,如「活动A 对比 活动B」")
            params["entities"] = promo_ids[:10]
            sql = (
                'SELECT p.name AS "活动", '
                'COUNT(DISTINCT r.order_id) AS "核销订单数", '
                'COALESCE(SUM(o.total_amount), 0)::float AS "核销GMV", '
                'COALESCE(SUM(r.discount_amount), 0)::float AS "优惠总额" '
                'FROM promotion_redemptions r '
                'JOIN promotions p ON p.id = r.promotion_id '
                'JOIN merchant_orders o ON o.order_id = r.order_id '
                'WHERE p.id = ANY(:entities) '
                'GROUP BY p.name, p.id ORDER BY "核销GMV" DESC'
            )
        elif intent.metric == "ai_resolution_rate":
            if intent.time_window:
                time_clause = "AND created_at >= :window_start"
                params["window_start"] = self._window_start(intent.time_window)
            sql = (
                "SELECT '__total__' AS \"productId\", ROUND(COALESCE(SUM(CASE WHEN resolution_status = 'resolved_auto' "
                "THEN 1 ELSE 0 END), 0)::numeric * 100 / GREATEST(COUNT(*), 1), 2)::float AS \"metricScore\" "
                f"FROM session_metrics WHERE business_id = :business_id {time_clause} LIMIT :lim"
            )
        elif intent.metric == "promo_effect":
            # ADR-0005 活动效果总览(核销关联口径:真实归因,自然流量不计入)
            params.pop("lim", None)
            promo_ids = (intent.entity_slot or {}).get("promotion") or []
            if not promo_ids:
                raise UnsupportedQuery("请先指明活动(如「开学季活动卖得怎么样」)")
            if intent.time_window:
                time_clause = "AND r.created_at >= :window_start"
                params["window_start"] = self._window_start(intent.time_window)
            params["entities"] = promo_ids[:20]
            sql = (
                'SELECT COUNT(DISTINCT r.order_id) AS "核销订单数", '
                'COALESCE(SUM(o.total_amount), 0)::float AS "核销GMV", '
                'COALESCE(SUM(r.discount_amount), 0)::float AS "优惠总额" '
                'FROM promotion_redemptions r JOIN merchant_orders o ON o.order_id = r.order_id '
                'WHERE r.promotion_id = ANY(:entities) {time_clause}'
            )
            sql = sql.format(time_clause=time_clause)
        elif intent.metric == "promo_sku_compare":
            # ADR-0005 活动内商品对比:核销订单的商品明细按款聚合;可标目标款
            promo_ids = (intent.entity_slot or {}).get("promotion") or []
            if not promo_ids:
                raise UnsupportedQuery("请先指明活动(如「开学季活动里冲锋衣对比其他款」)")
            params["entities"] = promo_ids[:20]
            params["targets"] = (intent.entity_slot or {}).get("spu") or []
            sql = (
                'SELECT oi.spu_id AS "productId", MAX(oi.title) AS "name", '
                'SUM(oi.quantity)::int AS "销量", '
                'COALESCE(SUM(oi.quantity * oi.price), 0)::float AS "GMV", '
                'COUNT(DISTINCT o.order_id)::int AS "订单数", '
                "MAX(CASE WHEN oi.spu_id = ANY(:targets) THEN '目标款' ELSE '其他款' END) AS \"对比分组\" "
                'FROM promotion_redemptions r '
                'JOIN merchant_orders o ON o.order_id = r.order_id '
                'JOIN merchant_order_items oi ON oi.order_id = r.order_id '
                'WHERE r.promotion_id = ANY(:entities) '
                f'GROUP BY oi.spu_id ORDER BY "销量" {direction} LIMIT :lim'
            )
        elif intent.metric == "customer_orders":
            # ADR-0005 客户订单列表(实体列表卡;前端订单行可跳订单管理)
            cust_ids = (intent.entity_slot or {}).get("customer") or []
            if not cust_ids:
                raise UnsupportedQuery("请先指明客户(如「张三最近的订单」)")
            params["entities"] = cust_ids[:20]
            sql = (
                'SELECT o.order_id AS "order_id", o.status AS "status", '
                'o.total_amount::float AS "total_amount", '
                "to_char(o.created_at, 'MM-DD HH24:MI') AS \"created_at\" "
                'FROM merchant_orders o WHERE o.customer_id = ANY(:entities) '
                'ORDER BY o.created_at DESC LIMIT :lim'
            )
        elif intent.metric in ("aov", "order_count"):
            # 阶段⑥对话出口族:总量单行(客单价/订单量;有效成交口径,单行天然有界)
            params.pop("lim", None)  # 单行聚合,LIMIT 1 字面兜底
            if intent.time_window:
                time_clause = "AND o.created_at >= :window_start"
                params["window_start"] = self._window_start(intent.time_window)
            value_expr = (
                "ROUND(AVG(o.total_amount), 2)::float" if intent.metric == "aov" else "COUNT(*)::int"
            )
            sql = (
                f'SELECT \'__total__\' AS "productId", {value_expr} AS "metricScore" '
                "FROM merchant_orders o WHERE o.status NOT IN ('REFUNDED', 'CANCELLED') "
                f"{time_clause} LIMIT 1"
            )
        elif intent.metric == "review_good":
            # 好评榜(与差评榜对偶:rating ≥ 4;评价表 spu_id 为 uuid,join 取商品标题)
            if intent.time_window:
                time_clause = "AND r.created_at >= :window_start"
                params["window_start"] = self._window_start(intent.time_window)
            sql = (
                'SELECT s.title AS "productId", COUNT(*) AS "metricScore" '
                "FROM merchant_product_reviews r JOIN merchant_spus s ON s.id = r.spu_id "
                f"WHERE r.rating >= 4 {time_clause} "
                f'GROUP BY s.id, s.title ORDER BY "metricScore" {direction} LIMIT :lim'
            )
        elif intent.metric == "zero_sales":
            # 零销量在售款(NOT EXISTS 确定性判零),库存降序暴露压货交叉风险
            sql = (
                'SELECT s.title AS "productId", s.category AS "category", '
                'COALESCE(SUM(k.stock), 0)::int AS "metricScore" '
                "FROM merchant_spus s LEFT JOIN merchant_skus k ON k.spu_id = s.id "
                "WHERE s.status = 'ON_SALE' AND NOT EXISTS ("
                "SELECT 1 FROM merchant_order_items oi WHERE oi.spu_id = s.spu_code) "
                f'GROUP BY s.id, s.title, s.category ORDER BY "metricScore" {direction} LIMIT :lim'
            )
        elif intent.metric == "category_gmv_top":
            if intent.time_window:
                time_clause = "AND o.created_at >= :window_start"
                params["window_start"] = self._window_start(intent.time_window)
            sql = (
                'SELECT s.category AS "productId", '
                'COALESCE(SUM(oi.quantity * oi.price), 0)::float AS "metricScore" '
                "FROM merchant_spus s JOIN merchant_order_items oi ON oi.spu_id = s.spu_code "
                "JOIN merchant_orders o ON o.order_id = oi.order_id "
                "WHERE s.status = 'ON_SALE' AND o.status NOT IN ('REFUNDED', 'CANCELLED') "
                f"{time_clause} GROUP BY s.category "
                f'ORDER BY "metricScore" {direction} LIMIT :lim'
            )
        elif intent.metric == "customer_spend_top":
            if intent.time_window:
                time_clause = "AND o.created_at >= :window_start"
                params["window_start"] = self._window_start(intent.time_window)
            sql = (
                'SELECT c.name AS "productId", c.phone AS "phone", '
                'COALESCE(SUM(o.total_amount), 0)::float AS "metricScore" '
                "FROM merchant_orders o JOIN merchant_customers c ON c.customer_id = o.customer_id "
                "WHERE o.status NOT IN ('REFUNDED', 'CANCELLED') "
                f"{time_clause} GROUP BY c.customer_id, c.name, c.phone "
                f'ORDER BY "metricScore" {direction} LIMIT :lim'
            )
        else:
            raise UnsupportedQuery(f"指标 {intent.metric} 尚未登记执行模板")

        # 安全闸补齐(review 修复):special-family 与销售族同闸 —— AST 白名单
        # (联合卡表单点)+ 危险函数黑名单;含 business_id 的模板(会话/售后)
        # 同时断言租户谓词不可剥离。响亮失败,绝不带病执行。
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
            target_db=(
                "engine_db"
                if intent.metric in ("session_volume", "ai_resolution_rate", "after_sale_overview")
                else "merchant_db"
            ),
        )

    async def execute_async(self, compiled: Any, session_ctx: dict | None = None) -> QueryResult:
        """异步执行(LangGraph 节点主路径);按 target_db 路由执行位。

        merchant_db → 只读 reader(READ ONLY + 超时,阶段①);engine_db → 引擎
        本地会话(get_session,同样只读查询)。两路均诚实空、均带口径注记。
        """
        from sqlalchemy import text

        if getattr(compiled, "target_db", "merchant_db") == "engine_db":
            from ..db import get_session

            async with get_session() as session:
                rows = (await session.execute(text(compiled.sql).bindparams(**compiled.params))).mappings().all()
        else:
            from ..tools_registry import order_domain

            # 运行时读取模块属性(测试替换 reader 工厂,静态引用会绕过 patch)
            async with order_domain._merchant_reader_engine().connect() as conn:
                rows = (await conn.execute(text(compiled.sql).bindparams(**compiled.params))).mappings().all()
        caliber = _CALIBERS.get(compiled.metric, "有效订单聚合(排除退款/取消单)")
        chart = "line" if compiled.metric.endswith("_trend") else None
        return QueryResult(
            rows=[dict(r) for r in rows],
            metric=compiled.metric,
            unit=compiled.unit,
            caliber=caliber,
            chart=chart,
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
        if kind == "last_months":
            # 含当月共 n 个月 → 起点 = n-1 个月前的月初(月对齐)
            first = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            month = first
            for _ in range(max(int(window.get("n") or 6), 1) - 1):
                month = (month - timedelta(days=1)).replace(day=1)
            return month
        raise UnsupportedQuery(f"未知时间窗 {kind}")


@dataclass(frozen=True)
class CompiledSQL:
    sql: str
    params: dict
    metric: str
    unit: str
    target_db: str = "merchant_db"  # merchant_db | engine_db(阶段③数据源路由)
    ast: Any = field(default=None, repr=False, compare=False)
    _schema_card: Any = field(default=None, repr=False, compare=False)
