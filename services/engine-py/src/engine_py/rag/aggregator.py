"""文档数据确定性聚合器(aggregator)— 表格/图表计算面的唯一求值点。

铁律(ADR-0010 同源取向):LLM 永不对文档数据做心算。检索面(chunk_text 的
管道表/字幕)只负责召回;计算面(metadata.tableData/chartData 结构化行列)
由本模块**纯代码**求值 —— 意图解析只产闭集选择(哪一列 × 哪个聚合操作),
数值强制经 coerce_number,解析不出数值就诚实 None,严禁猜。

provenance 分级(数据诚实律):
- native:docx 原生 chart 缓存 / 表格结构化,零读数误差,结果直陈;
- vlm:glm-4.6v 读数,结果必须带「读自图表,可能存在读数误差」标注。

入口 try_aggregate(query, rag_results):从检索结果里找带计算面的切片,
规则解析意图,命中即算;歧义/缺列/非数值一律 None(调用方回落原链路,
绝不产出可能错误的数字)。
"""

from __future__ import annotations

import re

# 聚合操作词表(规则意图层;英文同族兜底)
_OP_KEYWORDS: list[tuple[str, str]] = [
    ("sum", ("总计", "一共", "合计", "总和", "加起来", "总共", "累加", "多少积分总和")),
    ("avg", ("平均", "均值", "均价")),
    ("max", ("最大", "最高", "峰值", "顶点")),
    ("min", ("最小", "最低", "谷值")),
    ("count", ("几个", "几项", "多少项", "项数", "行数", "多少行", "几个项目", "多少种")),
]

_NUMERIC_RE = re.compile(r"^[-+]?[\d,]+(?:\.\d+)?%?$")
_UNIT_MULTIPLIERS = {"万": 10_000, "亿": 100_000_000, "千": 1_000}


def coerce_number(text: str) -> float | None:
    """单元格 → 数值;支持千分位/百分号/万/亿/千 后缀;解析不出诚实 None。

    v1 边界:复合表述(「120 万分」「约 45」的「约」)只容忍单位后缀与前后
    空白,其余一律 None —— 猜一个数比承认算不了危害大得多。
    """
    if text is None:
        return None
    cleaned = str(text).strip().replace(",", "").replace("，", "")
    if not cleaned:
        return None
    multiplier = 1.0
    for suffix, factor in _UNIT_MULTIPLIERS.items():
        if cleaned.endswith(suffix):
            multiplier = factor
            cleaned = cleaned[: -len(suffix)].strip()
            break
    if _NUMERIC_RE.match(cleaned):
        value = float(cleaned.rstrip("%"))
        if cleaned.endswith("%"):
            value = value / 100  # 百分比统一小数口径
        return value * multiplier
    return None


def pick_op(query: str) -> str | None:
    """聚合操作意图(词表精确命中;多操作同现属复合意图,交回原链路)。"""
    hits = {op for op, words in _OP_KEYWORDS if any(w in query for w in words)}
    return hits.pop() if len(hits) == 1 else None


def pick_column(headers: list[str], query: str) -> str | None:
    """列选择:精确匹配 > 查询二元组(2-gram)命中列头;多列命中/无命中 → None。

    二元组而非单字:CJK 单字粒度太松(「项目合计」的单字会把不相干列也拖进来),
    二字词元才近似中文语义单位。歧义诚实交回,严禁猜列。
    """
    if not headers:
        return None
    exact = [h for h in headers if h and h in query]
    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:
        return None
    bigrams = {query[i : i + 2] for i in range(len(query) - 1)} - {" "}
    contains = [h for h in headers if h and any(bg and bg in h for bg in bigrams)]
    if len(contains) == 1:
        return contains[0]
    return None  # 无命中或多列命中:歧义诚实交回,严禁猜列


def _numeric_column_index(data: dict, column: str | None) -> int | None:
    """列名 → 可解析数值列下标;列名不存在或整列无数值 → None。

    严禁「未知列回落首个数值列」式的猜测(2026-10-17 实测曾把「不存在的列」
    静默算成别的列的总和)—— 列错答比答不了危害大。
    """
    headers = [str(h) for h in (data.get("headers") or [])]
    rows = data.get("rows") or []
    if column is None:
        return None
    candidates = [i for i, h in enumerate(headers) if h == column]
    for index in candidates:
        values = [row[index] if index < len(row) else "" for row in rows]
        if any(coerce_number(v) is not None for v in values):
            return index
    return None


def aggregate(data: dict, column: str | None, op: str) -> float | None:
    """对 tableData/chartData 做一次确定性聚合;非数值列/空行集诚实 None。

    count 特例:column None 时返回数据行数(数行数不需要列)。
    """
    rows = data.get("rows") or []
    if op == "count":
        return float(len(rows))
    if column is None:
        return None
    index = _numeric_column_index(data, column)
    if index is None:
        return None
    values = [coerce_number(row[index]) for row in rows if index < len(row)]
    values = [v for v in values if v is not None]
    if not values:
        return None
    if op == "sum":
        return sum(values)
    if op == "avg":
        return sum(values) / len(values)
    if op == "max":
        return max(values)
    if op == "min":
        return min(values)
    return None


def _single_numeric_column(data: dict) -> str | None:
    """图表专用:数值列无歧义定位。柱/折/饼图 = 类目 + 单一数值序列,可解析出
    数值的列若恰好只有一列,即为值列(表头可能被 VLM 泛化成「类别/数值」,
    查询词「兑换量」对不上列名 —— 图表的身份匹配已由检索完成,此处按结构定位)。
    多于一个数值列(堆积图等)不猜,交 LLM 闭集或降级。"""
    headers = [str(h) for h in (data.get("headers") or [])]
    rows = data.get("rows") or []
    numeric_indexes = [
        i
        for i in range(len(headers))
        if any(coerce_number(row[i] if i < len(row) else "") is not None for row in rows)
    ]
    if len(numeric_indexes) == 1:
        return headers[numeric_indexes[0]]
    return None


def try_aggregate(query: str, rag_results: list[dict]) -> dict | None:
    """检索结果上的规则意图解析 + 确定性求值(消费方唯一入口)。

    返回 None = 意图不明/无计算面/列歧义/非数值,调用方必须回落原 LLM 链路
    并诚实作答,严禁拿 None 编数。命中返回:
    {"value", "op", "column", "provenance", "source", "headerPath", "annotated"}
    """
    op = pick_op(query)
    if op is None:
        return None
    best: dict | None = None
    for item in rag_results:
        meta = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
        table_data = meta.get("tableData")
        chart_data = meta.get("chartData")
        data = table_data or chart_data
        if not data:
            continue
        column = pick_column([str(h) for h in (data.get("headers") or [])], query)
        if column is None and table_data is None and chart_data is not None:
            # 图表数值列按结构定位(唯一可解析列);表格多列歧义严禁此回落
            column = _single_numeric_column(chart_data)
        value = aggregate(data, column, op)
        if value is None:
            continue
        best = {
            "value": value,
            "op": op,
            "column": column,
            "provenance": (data.get("provenance") or "table"),
            "source": item.get("sourceUrl") or item.get("docTitle") or "",
            "headerPath": item.get("headerPath") or "",
        }
        break  # 首个可算的命中即用(检索序即置信序)
    if best is None:
        return None
    best["annotated"] = best["provenance"] == "vlm"
    return best


def format_result(result: dict) -> str:
    """聚合结果 → 中文一句话(带出处;VLM 读数强制读数误差标注)。"""
    value = result["value"]
    display = f"{value:g}"
    op_label = {"sum": "合计", "avg": "平均值", "max": "最大值", "min": "最小值", "count": "行数"}[result["op"]]
    column_part = f"「{result['column']}」列" if result.get("column") else ""
    annotation = "(数值读自图表,可能存在读数误差)" if result.get("annotated") else ""
    source_part = f"出处:{result['source']}" + (f" > {result['headerPath']}" if result.get("headerPath") else "")
    return f"{column_part}{op_label}为 {display}{annotation}。{source_part}(确定性代码计算,非模型估算)"


def grounding_block(query: str, rag_results: list[dict]) -> str | None:
    """消费方接线助手:计算类问句命中结构化切片时,产出权威计算注入块。

    None = 非计算问句/无计算面/歧义 —— 调用方零渲染零行为变化,原 LLM 链路
    照旧。命中时块内明令「以该结果作答、禁止重新心算」—— 计算权威在代码,
    LLM 只负责组织语言。
    """
    result = try_aggregate(query, rag_results)
    if result is None:
        return None
    return (
        "[DOCUMENT DATA COMPUTATION — AUTHORITATIVE RESULT]\n"
        f"{format_result(result)}\n"
        "如果顾客的问题正是询问此数值:直接以该计算结果作答(保留读数误差标注,如适用),"
        "严禁自行重新加总或修改数字;如果顾客问的是别的,忽略本块。"
    )
