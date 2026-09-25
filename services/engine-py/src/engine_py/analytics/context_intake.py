"""PageContext 勾选/订单号/标题前缀 intake(T5;自 graph.py 拆出)。

职责单一:把页面上行上下文(类型化勾选 + 人话标签)与问句内联信息(订单号)
合入意图;graph.py 只做编排,不再兼职数据搬运。
"""

from __future__ import annotations

import re

from .engine import StructuredQueryIntent

# 行内商品提及适用闭集(标准商品族:模板支持 spu 过滤);
# graph 的行内扫描与勾选合并共用本定义(单一事实源)
INLINE_SPU_METRICS = frozenset({"gmv", "volume", "gross_profit", "margin_rate", "stock_risk"})

# spu 勾选的作用面 = 标准族榜单 + 趋势族对偶 + 商品对比(勾 ≥2 款并排)
_SPU_FILTERABLE = INLINE_SPU_METRICS | {"volume_trend", "gmv_trend", "spu_compare"}

# 客户族闭集(PageContext customer 勾选的作用面)
_CUSTOMER_SLOT_METRICS = frozenset({
    "customer_orders", "customer_spend_stats", "customer_coupons",
    "customer_profile", "customer_panorama", "customer_spend_trend",
})

# 订单号 token(含 -ORD- 段,如 AURORA-ORD-2026-1737 / E2E-DET-ORD)
_ORDER_ID_RE = re.compile(r"\b[A-Z0-9]+(?:-[A-Z0-9]+)*-ORD(?:-[A-Z0-9]+)*\b")


def parse_raw_selection(raw_sel) -> tuple[list[str], list[str], list[str]]:
    """原始上行 selection → (orders, spus, customers)。

    旧数组形态向后兼容:同时当订单勾选(订单对比)与商品勾选(标准族过滤)。
    """
    if isinstance(raw_sel, dict):
        orders = [str(x) for x in (raw_sel.get("order") or [])][:100]
        spus = [str(x) for x in (raw_sel.get("spu") or [])][:100]
        custs = [str(x) for x in (raw_sel.get("customer") or [])][:100]
    else:
        ids = [str(x) for x in (raw_sel or [])][:100]
        orders, spus, custs = ids, ids, []
    return orders, spus, custs


def inline_order_ids(question: str) -> list[str]:
    """问句里直接写订单号 → 免勾选(上限 20)。"""
    return _ORDER_ID_RE.findall((question or "").upper())[:20]


def merge_into_intent(
    intent: StructuredQueryIntent,
    sel_orders: list[str],
    sel_spu: list[str],
    sel_cust: list[str],
) -> StructuredQueryIntent:
    """按指标族把勾选合入意图(frozen dataclass → 整体重建)。"""
    def _with(slot: dict) -> StructuredQueryIntent:
        return StructuredQueryIntent(
            metric=intent.metric, direction=intent.direction, limit=intent.limit,
            time_window=intent.time_window, category=intent.category,
            entity_ids=(sel_orders if intent.metric == "order_overview" else intent.entity_ids),
            entity_slot=slot, chart_hint=intent.chart_hint,
        )

    if intent.metric == "order_overview" and sel_orders and sel_orders != intent.entity_ids:
        return _with(dict(intent.entity_slot))
    if sel_spu and intent.metric in _SPU_FILTERABLE and not (intent.entity_slot or {}).get("spu"):
        return _with({**intent.entity_slot, "spu": sel_spu})
    if sel_cust and intent.metric in _CUSTOMER_SLOT_METRICS and not (intent.entity_slot or {}).get("customer"):
        return _with({**intent.entity_slot, "customer": sel_cust})
    return intent


def title_prefix(
    intent: StructuredQueryIntent,
    sel_spu: list[str],
    sel_cust: list[str],
    sel_labels: dict,
) -> str:
    """人话标题前缀:勾选标签前置(「极光XX冲锋衣 · 销量趋势 · 件」)。"""
    def _desc(kind: str, ids: list[str]) -> str:
        names = [sel_labels.get(kind, {}).get(i) for i in ids]
        known = [n for n in names if n]
        if not known:
            return f"{len(ids)} 项"
        return known[0] if len(known) == 1 else f"{known[0]} 等 {len(known)} 项"

    if sel_spu and intent.metric in _SPU_FILTERABLE:
        return _desc("spu", sel_spu)
    if sel_cust and intent.metric in _CUSTOMER_SLOT_METRICS:
        return _desc("customer", sel_cust)
    return ""
