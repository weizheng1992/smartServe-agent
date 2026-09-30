"""确定性速览(自 graph.py 拆出;T6 体验批次)。

从真实结果行算最高/最低/榜首/首尾变化 —— 纯算术不编造,08-D1 精神的
呈现侧延伸;LLM 润色是后续接缝。
"""

from __future__ import annotations


def quick_summary(result, intent) -> str | None:
    """趋势出峰谷/首尾变化/均值;榜单出多句事实速览(规模/榜首/集中度/末位);
    单行多列不生成(表格自明)。纯算术不编造:每个数字都来自真实结果行。"""
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
    numeric_rows = [r for r in rows if isinstance(r.get(vcol), (int, float))]
    if not numeric_rows:
        return None
    vals = [float(r[vcol]) for r in numeric_rows]
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
        avg = sum(vals) / len(vals)
        return f"峰值 {top_v:,.0f}{unit} · 谷值 {low_v:,.0f}{unit};{trend};期间均值 {avg:,.0f}{unit}"
    if len(rows) < 2:
        return None
    # 榜首/末位随排序方向取行(DESC 头名=最大,ASC「卖得最差」榜头名=最小):
    # 「榜首」是榜面语义不是大小语义,方向中立。
    total = sum(vals)
    head, tail = numeric_rows[0], numeric_rows[-1]
    head_val = vals[0]
    head_label = str(head.get(label_col) or "—")
    parts = [f"本榜共 {len(numeric_rows)} 项、合计 {total:,.0f}{unit}"]
    head_share = (head_val / total * 100) if total else 0
    parts.append(f"榜首 {head_label} {head_val:,.0f}{unit}(占 {head_share:.0f}%)")
    if len(numeric_rows) >= 3:
        top3_share = (sum(vals[:3]) / total * 100) if total else 0
        parts.append(f"前三名合计占 {top3_share:.0f}%")
        tail_label = str(tail.get(label_col) or "—")
        tail_val = vals[-1]
        if tail_val > 0:
            parts.append(f"末位 {tail_label} {tail_val:,.0f}{unit}(约为榜首的 {tail_val / head_val * 100:.0f}%)")
        else:
            parts.append(f"末位 {tail_label} 0{unit}")
    return ";".join(parts) + "。"
