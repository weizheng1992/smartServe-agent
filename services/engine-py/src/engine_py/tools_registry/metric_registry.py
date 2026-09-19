"""指标语义注册表与消歧器 — 移植 packages/tools/src/metricRegistry.ts(1:1)。

词表匹配 | 歧义消解 | SQL 模板渲染;供 promptfoo 指标消歧评测与 NL2SQL 查询引擎复用。
"""

from __future__ import annotations

from typing import Any

METRIC_SEMANTIC_REGISTRY: dict[str, dict[str, Any]] = {
    "gmv": {
        "key": "gmv",
        "label": "总销售额 (GMV)",
        "description": "统计周期内所有已生效订单的实付销售总流水金额,即 SUM(quantity * price_at_purchase)。不扣除进货成本。",
        "domain": "sales",
        "sourceTables": ["products", "order_items", "orders"],
        "expression": "COALESCE(SUM(oi.quantity * oi.price_at_purchase), 0)::float",
        "sqlTemplate": """
      SELECT {dimensions}, {formula} AS "metricValue"
      FROM products p
      LEFT JOIN order_items oi ON p.id = oi.product_id
      {filters}
      GROUP BY {groupBy}
      ORDER BY "metricValue" {direction}
      LIMIT {limit}
    """,
        "businessRules": [
            "仅统计有效销售订单,排除已取消未付款订单",
            "单价取下单时快照 price_at_purchase,防止后续商品改价失真",
        ],
        "direction": "DESC",
        "unit": "元",
        "icon": "💰",
        "aliases": ["gross_merchandise_volume", "total_sales", "turnover"],
        "synonyms": ["卖得好", "销售额", "流水", "业绩", "最卖钱", "成交额", "营业额", "营业收入"],
        "conflictGroup": ["sales_performance_ranking"],
        "sampleQueries": ["帮我查一下我负责商品里面卖得最好的几个", "查看本月销售额最高的商品榜单", "哪个商品流水贡献最大"],
        "availableDimensions": ["p.id", "p.name", "p.category", "p.manager_id"],
        "permissionTag": "sales_viewer",
        "verifiedConfidence": 0.98,
    },
    "volume": {
        "key": "volume",
        "label": "出货销量 (件数)",
        "description": "统计周期内商品实际售出的总件数总量,即 SUM(quantity)。反映商品物理周转频次和爆款热度。",
        "domain": "sales",
        "sourceTables": ["products", "order_items", "orders"],
        "expression": "COALESCE(SUM(oi.quantity), 0)::int",
        "sqlTemplate": """
      SELECT {dimensions}, {formula} AS "metricValue"
      FROM products p
      LEFT JOIN order_items oi ON p.id = oi.product_id
      {filters}
      GROUP BY {groupBy}
      ORDER BY "metricValue" {direction}
      LIMIT {limit}
    """,
        "businessRules": ["退货件数是否扣减需视售后策略而定,默认统计总出货件数"],
        "direction": "DESC",
        "unit": "件",
        "icon": "📦",
        "aliases": ["sales_volume", "total_quantity", "order_units"],
        "synonyms": ["销量", "走量", "爆款", "出货量", "卖得多", "单量最多", "件数最多", "件数", "畅销款"],
        "conflictGroup": ["sales_performance_ranking"],
        "sampleQueries": ["哪几款商品出货量最大", "查看走量最多的爆款商品", "销量排名前三的商品"],
        "availableDimensions": ["p.id", "p.name", "p.category", "p.manager_id"],
        "permissionTag": "warehouse_operator",
        "verifiedConfidence": 0.99,
    },
    "gross_profit": {
        "key": "gross_profit",
        "label": "净毛利润 (收益)",
        "description": "销售总流水减去进货/物料成本后的净收益,即 SUM(quantity * (price_at_purchase - cost_at_purchase))。",
        "domain": "profit",
        "sourceTables": ["products", "order_items", "orders"],
        "expression": (
            "(COALESCE(SUM(oi.quantity * oi.price_at_purchase), 0) "
            "- COALESCE(SUM(oi.quantity * COALESCE(oi.cost_at_purchase, p.cost_price, 0)), 0))::float"
        ),
        "sqlTemplate": """
      SELECT {dimensions}, {formula} AS "metricValue"
      FROM products p
      LEFT JOIN order_items oi ON p.id = oi.product_id
      {filters}
      GROUP BY {groupBy}
      ORDER BY "metricValue" {direction}
      LIMIT {limit}
    """,
        "businessRules": [
            "如果 order_items 存在下单成本 cost_at_purchase 则优先使用,否则降级回退至 product 当前 cost_price",
            "毛利可为负数(当贴钱促销时)",
        ],
        "direction": "DESC",
        "unit": "元",
        "icon": "📈",
        "aliases": ["profit_amount", "gross_margin_dollars"],
        "synonyms": ["最赚钱", "利润最高", "毛利", "毛利润", "净利润", "赚得多", "净赚", "收益最高"],
        "conflictGroup": ["sales_performance_ranking"],
        "sampleQueries": ["哪几款商品真正最赚钱", "净毛利最高的商品排行", "刨去进货成本哪款利润最大"],
        "availableDimensions": ["p.id", "p.name", "p.category", "p.manager_id"],
        "permissionTag": "finance_owner",
        "verifiedConfidence": 0.95,
    },
    "margin_rate": {
        "key": "margin_rate",
        "label": "毛利率 (性价比/溢价率)",
        "description": "净毛利润与总销售额的比率,公式:(毛利润 / NULLIF(总销售额, 0)) * 100。反映单品盈利质量。",
        "domain": "profit",
        "sourceTables": ["products", "order_items"],
        "expression": (
            "CASE WHEN SUM(oi.quantity * oi.price_at_purchase) > 0 THEN "
            "(((SUM(oi.quantity * oi.price_at_purchase) "
            "- SUM(oi.quantity * COALESCE(oi.cost_at_purchase, p.cost_price, 0))) "
            "/ SUM(oi.quantity * oi.price_at_purchase)) * 100)::float ELSE 0.0 END"
        ),
        "sqlTemplate": """
      SELECT {dimensions}, {formula} AS "metricValue"
      FROM products p
      LEFT JOIN order_items oi ON p.id = oi.product_id
      {filters}
      GROUP BY {groupBy}
      ORDER BY "metricValue" {direction}
      LIMIT {limit}
    """,
        "businessRules": ["必须使用 NULLIF 或 CASE WHEN 规避分母为 0 抛出除零异常"],
        "direction": "DESC",
        "unit": "%",
        "icon": "🎯",
        "aliases": ["gross_margin_percentage", "margin_percentage"],
        "synonyms": ["毛利率", "利润率", "溢价最高", "性价比最高", "赚钱效率", "回报率"],
        "conflictGroup": ["sales_performance_ranking"],
        "sampleQueries": ["哪些商品毛利率最高", "溢价空间最大的商品有哪些"],
        "availableDimensions": ["p.id", "p.name", "p.category"],
        "permissionTag": "finance_owner",
        "verifiedConfidence": 0.94,
    },
    "stock_risk": {
        "key": "stock_risk",
        "label": "滞销积压库存",
        "expression": "p.stock::int",
        "sqlTemplate": """
      SELECT {dimensions}, {formula} AS "metricValue"
      FROM products p
      {filters}
      ORDER BY "metricValue" {direction}
      LIMIT {limit}
    """,
        "description": "当前仓库在库物理剩余库存件数,用于排查滞销压货与动销缓慢风险。",
        "domain": "inventory",
        "sourceTables": ["products"],
        "businessRules": ["库存预警默认按绝对剩余量降序排列"],
        "direction": "DESC",
        "unit": "件",
        "icon": "⚠️",
        "aliases": ["inventory_level", "slow_moving_stock"],
        "synonyms": ["滞销", "积压", "卖不出去", "库存最多", "压货", "库存风险", "积压款", "存货最多"],
        "conflictGroup": ["inventory_risk_group"],
        "sampleQueries": ["仓库里哪些商品积压最多", "滞销库存排查", "哪些款压货最严重"],
        "availableDimensions": ["p.id", "p.name", "p.category"],
        "permissionTag": "warehouse_operator",
        "verifiedConfidence": 0.96,
    },
    # ---- 阶段③新指标族(10-D1:评价/退货/会话,登记即全链路可见) ----
    "review_bad": {
        "key": "review_bad",
        "label": "差评榜 (≤2星)",
        "description": "统计周期内差评条数排行(rating <= 2);数据源商户镜像库 merchant_product_reviews。",
        "domain": "review",
        "sourceTables": ["merchant_product_reviews"],
        "expression": "COUNT(*) FILTER (WHERE rating <= 2)",
        "sqlTemplate": "merchant_db",
        "businessRules": ["差评口径 = rating <= 2;商户真实评价,非合成"],
        "direction": "DESC",
        "unit": "条",
        "icon": "👎",
        "aliases": ["bad_reviews"],
        "synonyms": ["差评", "差评最多", "吐槽最多", "评分最低", "最差评"],
        "conflictGroup": ["review_family"],
        "sampleQueries": ["差评最多的 SKU", "最近差评最多的商品"],
        "availableDimensions": ["spu_id"],
        "permissionTag": "sales_viewer",
        "verifiedConfidence": 0.95,
    },
    "refund_rate": {
        "key": "refund_rate",
        "label": "退款率",
        "description": "退款件数 ÷ 有效成交件数 × 100;数据源商户镜像库订单明细。",
        "domain": "refund",
        "sourceTables": ["merchant_order_items", "merchant_orders"],
        "expression": "refunded_qty / valid_qty * 100",
        "sqlTemplate": "merchant_db",
        "businessRules": ["退款单全额计入退款件;有效口径排除 CANCELLED"],
        "direction": "DESC",
        "unit": "%",
        "icon": "↩️",
        "aliases": ["refund_rate_metric"],
        "synonyms": ["退款率", "退货率", "退单率"],
        "conflictGroup": ["refund_family"],
        "sampleQueries": ["近 30 天退款率", "退款率最高的商品"],
        "availableDimensions": ["spu_id"],
        "permissionTag": "sales_viewer",
        "verifiedConfidence": 0.93,
    },
    "session_volume": {
        "key": "session_volume",
        "label": "会话量",
        "description": "统计周期内会话条数;engine 本地 session_metrics 同源真算(与平台大盘口径一致)。",
        "domain": "session",
        "sourceTables": ["session_metrics"],
        "expression": "COUNT(*)",
        "sqlTemplate": "engine_db",
        "businessRules": ["与平台大盘同表同口径"],
        "direction": "DESC",
        "unit": "条",
        "icon": "💬",
        "aliases": ["session_count"],
        "synonyms": ["会话量", "咨询量", "会话数", "客服负载", "负载概况", "客服情况"],
        "conflictGroup": ["session_family"],
        "sampleQueries": ["客服负载概况", "最近会话量"],
        "availableDimensions": [],
        "permissionTag": "sales_viewer",
        "verifiedConfidence": 0.97,
    },
    "promo_orders": {
        "key": "promo_orders",
        "label": "活动核销订单数",
        "description": "统计周期内使用优惠活动的订单笔数,按活动汇总;数据源 promotion_redemptions。",
        "domain": "promotion",
        "sourceTables": ["promotions", "promotion_redemptions"],
        "expression": "COUNT(DISTINCT order_id) GROUP BY promo",
        "sqlTemplate": "merchant_db",
        "businessRules": ["同订单同活动只计一次"],
        "direction": "DESC",
        "unit": "单",
        "icon": "🎯",
        "aliases": ["promo_redemptions"],
        "synonyms": ["核销订单", "活动核销", "核销情况", "活动使用情况", "核销了多少"],
        "conflictGroup": ["promotion_family"],
        "sampleQueries": ["各活动的核销情况", "优惠活动的核销订单数"],
        "availableDimensions": [],
        "permissionTag": "sales_viewer",
        "verifiedConfidence": 0.95,
    },
    "promo_discount_total": {
        "key": "promo_discount_total",
        "label": "活动优惠总额",
        "description": "统计周期内优惠活动抵扣的总金额,按活动汇总;数据源 promotion_redemptions。",
        "domain": "promotion",
        "sourceTables": ["promotions", "promotion_redemptions"],
        "expression": "SUM(discount_amount) GROUP BY promo",
        "sqlTemplate": "merchant_db",
        "businessRules": ["优惠额为结算时服务端计算的实际抵扣"],
        "direction": "DESC",
        "unit": "元",
        "icon": "💸",
        "aliases": ["promo_cost"],
        "synonyms": ["优惠总额", "活动成本", "优惠了多少钱", "补贴了多少", "活动花了多少"],
        "conflictGroup": ["promotion_family"],
        "sampleQueries": ["各活动优惠总额", "活动补贴花了多少钱"],
        "availableDimensions": [],
        "permissionTag": "sales_viewer",
        "verifiedConfidence": 0.95,
    },
    "gmv_trend": {
        "key": "gmv_trend",
        "label": "GMV 趋势",
        "description": "近 30 天每日 GMV 折线;有效订单口径(排除退款/取消),按下单日聚合。",
        "domain": "sales",
        "sourceTables": ["merchant_orders", "merchant_order_items"],
        "expression": "SUM(quantity*price) GROUP BY day",
        "sqlTemplate": "merchant_db",
        "businessRules": ["固定近 30 天窗口;日粒度"],
        "direction": "ASC",
        "unit": "元",
        "icon": "📈",
        "aliases": ["gmv_trend"],
        "synonyms": ["GMV 趋势", "销售额趋势", "每日销售额", "销量趋势", "GMV 走势", "趋势"],
        "conflictGroup": [],
        "sampleQueries": ["近 30 天 GMV 趋势", "每天的销售额走势"],
        "availableDimensions": [],
        "permissionTag": "sales_viewer",
        "verifiedConfidence": 0.95,
    },
    "order_overview": {
        "key": "order_overview",
        "label": "选中订单概览",
        "description": "对页面勾选的订单做笔数/合计金额/平均金额统计;实体集来自 PageContext 选择(必传)。",
        "domain": "sales",
        "sourceTables": ["merchant_orders"],
        "expression": "COUNT/SUM/AVG(total_amount) FILTER order_id = ANY(entities)",
        "sqlTemplate": "merchant_db",
        "businessRules": ["实体集为空时响亮拒绝(请先勾选订单);金额取订单实付"],
        "direction": "DESC",
        "unit": "元",
        "icon": "🧮",
        "aliases": ["selected_orders"],
        "synonyms": ["订单概览", "这几笔订单", "选中订单", "平均金额", "合计金额", "这几单", "勾选订单的统计", "选中订单的概览", "所选订单", "订单对比", "两单对比", "两个订单对比", "这两笔订单对比", "订单比较", "这两笔订单", "勾选的订单"],
        "conflictGroup": [],
        "sampleQueries": ["这几笔订单的平均金额", "选中订单合计多少"],
        "availableDimensions": [],
        "permissionTag": "sales_viewer",
        "verifiedConfidence": 0.94,
    },
    "after_sale_overview": {
        "key": "after_sale_overview",
        "label": "售后工单概况",
        "description": "售后工单按状态分布计数;engine 本地 after_sale_tickets 真算。",
        "domain": "refund",
        "sourceTables": ["after_sale_tickets"],
        "expression": "COUNT(*) GROUP BY status",
        "sqlTemplate": "engine_db",
        "businessRules": ["状态分布:pending_review/approved/rejected/completed 等"],
        "direction": "DESC",
        "unit": "单",
        "icon": "🧾",
        "aliases": ["after_sale_status"],
        "synonyms": ["售后工单", "售后概况", "工单概况", "工单"],
        "conflictGroup": ["refund_family"],
        "sampleQueries": ["售后工单概况", "有多少售后工单"],
        "availableDimensions": [],
        "permissionTag": "sales_viewer",
        "verifiedConfidence": 0.95,
    },
    "ai_resolution_rate": {
        "key": "ai_resolution_rate",
        "label": "AI 自动解决率",
        "description": "resolved_auto 会话 ÷ 总会话 × 100;session_metrics 同源。",
        "domain": "session",
        "sourceTables": ["session_metrics"],
        "expression": "resolved_auto / total * 100",
        "sqlTemplate": "engine_db",
        "businessRules": ["分子 = resolution_status='resolved_auto'"],
        "direction": "DESC",
        "unit": "%",
        "icon": "🤖",
        "aliases": ["auto_resolution"],
        "synonyms": ["自动解决率", "AI 解决率", "解决率"],
        "conflictGroup": ["session_family"],
        "sampleQueries": ["AI 自动解决率多少"],
        "availableDimensions": [],
        "permissionTag": "sales_viewer",
        "verifiedConfidence": 0.96,
    },
    "promo_effect": {
        "key": "promo_effect",
        "label": "活动效果总览",
        "description": "指定运营活动的核销关联口径汇总:核销订单数、核销GMV、优惠总额。需指明活动(核销归因,自然流量不计入)。",
        "domain": "promotion",
        "sourceTables": ["promotions", "promotion_redemptions", "merchant_orders"],
        "expression": "COUNT(DISTINCT order_id), SUM(total_amount), SUM(discount_amount)",
        "sqlTemplate": "",
        "businessRules": ["核销关联口径:仅统计该活动核销记录关联的订单", "优惠总额 = SUM(discount_amount)"],
        "direction": "DESC",
        "unit": "单",
        "aliases": ["campaign_effect"],
        "synonyms": ["活动效果", "活动销量", "活动卖得怎么样", "活动表现", "核销情况"],
        "conflictGroup": [],
        "sampleQueries": ["开学季活动卖得怎么样", "这个活动的核销情况如何"],
        "availableDimensions": [],
        "permissionTag": "sales_viewer",
        "verifiedConfidence": 0.9,
    },
    "promo_sku_compare": {
        "key": "promo_sku_compare",
        "label": "活动内商品对比",
        "description": "指定活动核销订单的商品明细按款聚合:销量/GMV/订单数,可标记目标款对比其他款。需指明活动。",
        "domain": "promotion",
        "sourceTables": ["promotions", "promotion_redemptions", "merchant_orders", "merchant_order_items"],
        "expression": "SUM(quantity), SUM(quantity*price), COUNT(DISTINCT order_id)",
        "sqlTemplate": "",
        "businessRules": ["按活动核销订单的商品明细聚合", "对比分组列标记目标款/其他款"],
        "direction": "DESC",
        "unit": "件",
        "aliases": ["campaign_sku_compare"],
        "synonyms": ["活动里哪款卖得好", "活动商品对比", "活动内对比", "活动里的款"],
        "conflictGroup": [],
        "sampleQueries": ["开学季活动里冲锋衣对比其他款", "这个活动里哪款卖得最好"],
        "availableDimensions": [],
        "permissionTag": "sales_viewer",
        "verifiedConfidence": 0.9,
    },
    "promo_compare": {
        "key": "promo_compare",
        "label": "双活动对比",
        "description": "两个运营活动并排对比:核销订单数、核销GMV、优惠总额。需指明两个活动(核销归因口径)。",
        "domain": "promotion",
        "sourceTables": ["promotions", "promotion_redemptions", "merchant_orders"],
        "expression": "COUNT(DISTINCT order_id), SUM(total_amount), SUM(discount_amount) GROUP BY promotion",
        "sqlTemplate": "",
        "businessRules": ["核销关联口径:各自只统计本活动核销记录关联的订单", "两行并排对比"],
        "direction": "DESC",
        "unit": "单",
        "aliases": ["campaign_compare"],
        "synonyms": ["两个活动对比", "活动对比", "对比两个活动", "活动A对比活动B", "两个活动哪个好"],
        "conflictGroup": [],
        "sampleQueries": ["新客50元券对比背包品类85折", "两个活动哪个效果好"],
        "availableDimensions": [],
        "permissionTag": "sales_viewer",
        "verifiedConfidence": 0.9,
    },
    "customer_orders": {
        "key": "customer_orders",
        "label": "客户订单查询",
        "description": "指定客户名下的订单列表(按下单时间倒序)。需指明客户(姓名/手机号)。",
        "domain": "customer",
        "sourceTables": ["merchant_orders", "merchant_customers"],
        "expression": "order_id, status, total_amount, created_at",
        "sqlTemplate": "",
        "businessRules": ["名下全部订单,不按成交口径过滤(列表展示原状)"],
        "direction": "DESC",
        "unit": "单",
        "aliases": ["customer_recent_orders"],
        "synonyms": ["客户订单", "名下订单"],
        "conflictGroup": [],
        "sampleQueries": ["张三最近的订单", "查一下 13800000001 的订单"],
        "availableDimensions": [],
        "permissionTag": "sales_viewer",
        "verifiedConfidence": 0.9,
    },
}

_GENERIC_PHRASES = ["卖得好", "卖得最好", "最好", "最棒", "表现最好", "排名靠前", "头部商品"]
_DEFINITIVE_WORDS = [
    "金额", "件数", "出货", "销量", "走量", "毛利", "利润", "流水", "营业额", "溢价", "库存", "积压", "滞销",
]


class MetricSemanticResolver:
    """从自然语言问句匹配指标并检测歧义冲突组 — 1:1 镜像 TS MetricSemanticResolver。"""

    @staticmethod
    def resolve(input: str, default_key: str = "gmv") -> dict:
        clean = input.strip().lower()
        matches: list[tuple[dict, str]] = []

        for metric in METRIC_SEMANTIC_REGISTRY.values():
            if metric["key"] in clean:
                matches.append((metric, metric["key"]))
                continue
            if metric["label"].lower() in clean:
                matches.append((metric, metric["label"]))
                continue
            for syn in metric["synonyms"]:
                if syn.lower() in clean:
                    matches.append((metric, syn))
                    break

        # 1. 完全未命中 → Default 兜底(如用户只说了"查几个商品")
        if not matches:
            default_metric = METRIC_SEMANTIC_REGISTRY.get(default_key) or METRIC_SEMANTIC_REGISTRY["gmv"]
            group = default_metric.get("conflictGroup")
            conflict_metrics = (
                [m for m in METRIC_SEMANTIC_REGISTRY.values() if group and group[0] in (m.get("conflictGroup") or [])]
                if group
                else [default_metric]
            )
            return {
                "primaryMetric": default_metric,
                "isExplicit": False,
                "matchedSynonym": None,
                "hasAmbiguity": True,
                "conflictMetrics": conflict_metrics,
            }

        # 2. 命中多个 → 最长匹配词优先(如 "毛利率" 优先于 "毛利")
        matches.sort(key=lambda pair: len(pair[1]), reverse=True)
        primary, matched_synonym = matches[0]

        conflict_group = (primary.get("conflictGroup") or [None])[0]
        conflict_metrics = (
            [m for m in METRIC_SEMANTIC_REGISTRY.values() if conflict_group and conflict_group in (m.get("conflictGroup") or [])]
            if conflict_group
            else [primary]
        )

        # 仅在泛指模糊提问("卖得最好"等)且未指明具体量度时标记歧义
        is_generic = any(g in clean for g in _GENERIC_PHRASES)
        is_definitive = any(w in clean for w in _DEFINITIVE_WORDS)
        has_ambiguity = is_generic and not is_definitive and len(conflict_metrics) > 1

        return {
            "primaryMetric": primary,
            "isExplicit": True,
            "matchedSynonym": matched_synonym,
            "hasAmbiguity": has_ambiguity,
            "conflictMetrics": conflict_metrics,
        }

    @staticmethod
    def render_sql(
        metric: dict,
        dimensions: list[str],
        filters: str,
        limit: int | str,
        group_by: list[str] | None = None,
        direction: str | None = None,
    ) -> str:
        dim_str = ", ".join(dimensions)
        group_str = ", ".join(group_by or dimensions)
        final_direction = direction or metric["direction"]
        sql = metric["sqlTemplate"]
        sql = sql.replace("{dimensions}", dim_str)
        sql = sql.replace("{groupBy}", group_str)
        sql = sql.replace("{formula}", metric["expression"])
        sql = sql.replace("{filters}", filters)
        sql = sql.replace("{direction}", final_direction)
        sql = sql.replace("{limit}", str(limit))
        return sql
