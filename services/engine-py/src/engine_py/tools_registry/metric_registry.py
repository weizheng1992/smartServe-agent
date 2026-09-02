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
