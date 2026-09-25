"""确定性速览(自 graph.py 拆出;T6 体验批次)。

从真实结果行算最高/最低/榜首/首尾变化 —— 纯算术不编造,08-D1 精神的
呈现侧延伸;LLM 润色是后续接缝。
"""

from __future__ import annotations


def quick_summary(result, intent) -> str | None:
    """趋势出峰谷与首尾变化;榜单出项数与榜首占比;单行多列不生成(表格自明)。"""
    from .tools_registry_bridge import metric_semantic_registry

    rows = result.rows or []
    if not rows:
        return None
    numeric_cols = [k for k, v in rows[0].items() if isinstance(v, (int, float))]
    if not numeric_cols:
        return None
    vcol = numeric_cols[-1]
    label_col = next((k for k in rows[0] if k != vcol and not isinstance(rows[0][k], (int, float))), vcol)
    unit = metric_semantic_registry().get(intent.metric, {}).get("unit", "")
    vals = [float(r[vcol]) for r in rows if isinstance(r.get(vcol), (int, float))]
    if not vals:
        return None
    # 峰谷/首尾变化只对「多行时间序列」有意义;单行多列统计卡(如活动效果
    # 总览:订单数/GMV/优惠额三列)拿末列当值做峰谷是读数错位(实弹踩坑)
    is_time_series = intent.metric.endswith("_trend")
    if not is_time_series:
        if len(rows) < 2:
            return None
    elif (intent.chart_hint or result.chart) == "line" or intent.metric.endswith("_trend"):
        top_v, low_v = max(vals), min(vals)
        delta = ((vals[-1] - vals[0]) * 100.0 / vals[0]) if vals[0] else None
        trend = "首尾持平" if not delta else f"期末较期初{'升' if delta > 0 else '降'} {abs(delta):.0f}%"
        return f"峰值 {top_v:,.0f}{unit} · 谷值 {low_v:,.0f}{unit};{trend}"
    if len(rows) < 2:
        return None
    total = sum(vals)
    top_label = str(rows[0].get(label_col, ""))
    share = (max(vals) / total * 100) if total else 0
    return f"共 {len(rows)} 项 · 榜首 {top_label} {max(vals):,.0f}{unit}(占 {share:.0f}%)"
