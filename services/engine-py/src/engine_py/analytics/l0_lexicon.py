"""L0 词面归一(2026-10-03 自 MetricQueryEngine.resolve 归位):词表/槽位/
图表指令/分类头缝②的独居 module —— 与 L2(exemplar_service)/L3(llm_intent)
同粒度,阶梯不再一半住方法体一半住 module。

interface:`resolve_question(question) -> StructuredQueryIntent | Clarify`
(未命中抛 UnsupportedQuery,与 L2/L3 同一响亮失败语义)。MetricQueryEngine.resolve
是本 module 的薄委托(冻结接口 09-D5 不动,调用方零改);`resolver` 注入缝
(训练产物优先)仍由 engine 持有 —— 那是「换整个 L0」的缝,不是本 module 内部。

engine 侧类型经函数内延迟 import 引用(避免 engine ↔ l0_lexicon 顶层环);
与本仓 deferred-import 惯例一致。
"""

from __future__ import annotations

import os
import re
from typing import TYPE_CHECKING

from .tools_registry_bridge import metric_semantic_registry

if TYPE_CHECKING:  # 仅类型位;运行时经函数内延迟 import 防顶层环
    from .engine import Clarify, StructuredQueryIntent

LIMIT_RE = re.compile(r"top\s*(\d+)", re.IGNORECASE)
REVERSE_WORDS = ("最差", "垫底", "最烂", "卖不动", "不走量", "最低", "最少")
# 反向词族自带指标指向(词表全正向,反向问句不命中同义词 — 03 号票 L0 缺口)
REVERSE_METRIC_HINTS = (
    ("卖得最差", "gmv"), ("卖得差", "gmv"), ("销售额最低", "gmv"), ("流水最低", "gmv"),
    ("销量最低", "volume"), ("卖得最少", "volume"), ("件数最少", "volume"),
)
GENERIC_POSITIVE = ("卖得最好", "卖得好", "最好", "爆款", "畅销")
GENERIC_HINTS = (("卖得最好", ("gmv", "volume")), ("卖得好", ("gmv", "volume")), ("最好", ("gmv", "volume")))
TIME_PATTERNS = (
    ("last_month", re.compile(r"上个月|上月")),
    ("last_7d", re.compile(r"最近\s*(一|7)\s*天|近\s*7\s*天")),
    ("last_30d", re.compile(r"最近\s*(三十|30)\s*天|近\s*(三十|30)\s*天")),
    # 跨月统计(用户实弹诉求):近/最近/过去 N 个月、「几个月的销量」(N 缺省 6);
    # 纯「每月/按月/月度」无 N 同样切月粒度(N 缺省 6)
    ("last_months", re.compile(r"(?:(?:近|最近|过去)\s*)?(\d{1,2}|[一两二三四五六七八九十几]+)\s*个月的?")),
    ("last_months", re.compile(r"每月|按月|月度")),
)
CN_MONTH_NUMS = {"一": 1, "两": 2, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6,
                 "七": 7, "八": 8, "九": 9, "十": 10, "几": 6}
CHART_HINTS = (
    ("line", re.compile(r"折线|曲线|趋势图")),
    ("bar", re.compile(r"柱状|条形|柱形")),
    ("table", re.compile(r"表格")),
)

_TREND_UPGRADE = {"gmv": "gmv_trend", "volume": "volume_trend", "order_count": "orders_trend"}


def parse_chart_hint(clean: str) -> str | None:
    """图表类型指令槽(Q3):用户点名图型时覆盖卡片自动推断。"""
    return next((v for v, pat in CHART_HINTS if pat.search(clean)), None)


def extract_slots(clean: str) -> tuple[int, dict | None, str | None]:
    """开放槽位解析(limit/时间窗/品类);L0 命中路与分类头 on 路径共用。"""
    limit_match = LIMIT_RE.search(clean)
    limit = min(max(int(limit_match.group(1)) if limit_match else 5, 1), 50)
    time_window: dict | None = None
    for kind, pat in TIME_PATTERNS:
        m = pat.search(clean)
        if m:
            time_window = {"kind": kind}
            if kind == "last_months":
                raw = m.group(1) if m.groups() else None
                n = int(raw) if raw and raw.isdigit() else CN_MONTH_NUMS.get(raw or "", 6)
                time_window["n"] = min(max(n, 1), 24)
            break
    cat_match = re.search(r"(户外机能|潮流T恤|下装裤类|潮流鞋靴|背包收纳|露营装备|衬衫|配饰|运动配件)", clean, re.IGNORECASE)
    category = cat_match.group(1) if cat_match else None
    return limit, time_window, category


class LexiconResolver:
    """L0 词表 resolver + 缝②分类头三态(shadow=并行只记日志 / on=未命中接管)。

    分类头懒加载由工厂保证,进程内单例;阈值 AI_METRIC_HEAD_THRESHOLD(默认 0.5)。
    """

    def __init__(self) -> None:
        # 11-D1 缝②:AI_METRIC_HEAD=off|shadow|on(默认不启用)
        from .metric_head import get_metric_head

        self._head = get_metric_head()
        self._head_threshold = float(os.environ.get("AI_METRIC_HEAD_THRESHOLD", "0.5"))

    def resolve(self, question: str) -> StructuredQueryIntent | Clarify:
        from .engine import Clarify, StructuredQueryIntent, UnsupportedQuery

        clean = (question or "").strip().lower()
        if not clean:
            raise UnsupportedQuery("空问题")

        registry = metric_semantic_registry()
        hit: tuple[str, str] | None = None
        matched_words: list[tuple[str, str]] = []
        for phrase, hinted_key in REVERSE_METRIC_HINTS:
            if phrase in clean:
                matched_words.append((hinted_key, phrase))
        if not matched_words:
            for phrase, hinted_keys in GENERIC_HINTS:
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

        # 分类头同一次 resolve 只打一次分:shadow 对比与 on 接管共用这一次结果。
        # 此前 hit 未命中时上方 shadow 块与下方 on 块各 predict 一遍(同问句双跑)。
        head_call: tuple[str, float] | None = None
        if self._head is not None:
            try:
                head_label, head_conf = self._head.predict(question)
                head_call = (head_label, head_conf)
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
            if head_call is not None:
                try:
                    head_label, head_conf = head_call
                    if head_label in registry and head_conf >= self._head_threshold:
                        print(f"[MetricHead][on] 接管: {head_label}({head_conf:.2f}) question={question[:40]!r}")
                        limit2, time2, cat2 = extract_slots(clean)
                        return StructuredQueryIntent(
                            metric=head_label, direction=registry[head_label]["direction"],
                            limit=limit2, time_window=time2, category=cat2,
                            chart_hint=parse_chart_hint(clean),
                        )
                except UnsupportedQuery:
                    pass
                except Exception as head_err:
                    print(f"[MetricHead] on 模式打分失败: {head_err}")
            raise UnsupportedQuery(f"未命中已注册指标(闭集={list(registry)})")

        metric_key = hit[0]

        # 折线图指令 × 基础销量/金额指标 → 升级为趋势族(「销量 折线图」问的是
        # 随时间的线,不是榜单);榜单语义(榜/排行/Top)优先,不升级。
        # chart_hint 在此提前解析,兼作升级触发器。
        chart_hint = parse_chart_hint(clean)
        if chart_hint == "line" and metric_key in _TREND_UPGRADE and not re.search(r"排行|排名|榜|top\s*\d*", clean):
            metric_key = _TREND_UPGRADE[metric_key]
        metric = registry[metric_key]

        # 反向词 → 方向翻转(03-L0 决议);正向泛指词 × 多销售指标 → 反问
        reverse = any(w in clean for w in REVERSE_WORDS)
        direction = ("ASC" if metric["direction"] == "DESC" else "DESC") if reverse else metric["direction"]

        group = metric.get("conflictGroup") or []
        if group and any(w in clean for w in GENERIC_POSITIVE) and not any(
            w in clean for w in ("金额", "件数", "销量", "销售额", "毛利", "利润", "流水", "营业额", "库存")
        ):
            siblings = [m for m in registry.values() if group[0] in (m.get("conflictGroup") or [])]
            if len(siblings) > 1:
                return Clarify(
                    kind="metric",
                    question=f"「{question[:20]}」是指——",
                    options=[{"key": m["key"], "label": m["label"], "intent": {"metric": m["key"], "direction": m["direction"]}} for m in siblings],
                )

        limit, time_window, category = extract_slots(clean)

        return StructuredQueryIntent(metric=metric_key, direction=direction, limit=limit, time_window=time_window, category=category, chart_hint=chart_hint)


def resolve_question(question: str) -> StructuredQueryIntent | Clarify:
    """L0 module 级入口(LexiconResolver 每例自持分类头句柄,进程内单例复用)。"""
    return LexiconResolver().resolve(question)
