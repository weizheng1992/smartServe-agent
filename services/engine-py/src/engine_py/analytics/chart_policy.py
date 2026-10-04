"""图型仲裁唯一出处(2026-10-03 收口):折线仅趋势族。

收口前「趋势族」有三处独立判定 —— graph._TREND_LINE_METRICS 手抄四元
frozenset、engine 执行/缓存路径 endswith("_trend")、quick_summary 又各自
endswith —— 注册表新增 *_trend 指标时手抄集即陈旧(仲裁拒绝合法折线),
两套判词面靠命名约定碰巧一致。现由指标语义注册表程序化派生,约定即代码;
decide() 是「用户图型指令 × 指标语义 × 缓存图型」的唯一裁决
(2026-09-25 NaN 折线实弹后的仲裁单点:非趋势指标不信 line 指令)。
"""

from __future__ import annotations

from .tools_registry_bridge import metric_semantic_registry


def trend_family() -> frozenset[str]:
    """趋势族指标集(注册表 *_trend 命名约定的程序化投影)。"""
    return frozenset(k for k in metric_semantic_registry() if k.endswith("_trend"))


def is_trend_family(metric: str) -> bool:
    return metric in trend_family()


def auto_chart(metric: str) -> str | None:
    """执行/缓存路径的缺省图型:趋势族折线,其余表格(None = 卡片层缺省)。"""
    return "line" if is_trend_family(metric) else None


def decide(chart_hint: str | None, metric: str, result_chart: str | None) -> str | None:
    """图型裁决(旧 graph._effective_chart 归位):用户指令优先,但 line 仅对
    趋势族生效;缺省随指标语义。"""
    if chart_hint == "line":
        return "line" if is_trend_family(metric) else (result_chart or None)
    return chart_hint or result_chart
