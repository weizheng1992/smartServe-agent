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

from . import head_telemetry
from .tools_registry_bridge import metric_semantic_registry

# 域外实体闭集(14 号票):见 resolve 入口闸注释 —— 逐词可举证,宽泛词不入列
_EXTERNAL_ENTITY_RE = re.compile(r"竞品|竞争对手|对手店|同行|供应商|供货商")

# 关系/关联问句闸(闭集诚实律,2026-10-26/27 连续两晚慢性缺口):语义层只答
# 单一注册指标,「坏账和退款的关系」曾被 refund_rate 的 synonym「退款」半吸
# —— 用半题冒充整答。跨指标关系问句一律 unsupported 响亮拒答;词面刻意窄
# (关系/关联/相关性,逐词可举证),「市场份额」类合法问句不含这三词不受扰。
# graph.ask 另有同款图级闸(is_relation_question,注入闸同位)—— L0 拒后
# 原问句仍会走 L2/L3/T1/T2,各层 prompt 无关系守卫,单指标半吸可在更深层
# 复活(2026-10-28 终审实锤),故双层设闸。
_RELATION_Q_RE = re.compile(r"关系|关联|相关性")


def is_relation_question(question: str | None) -> bool:
    """关系/关联问句判定(graph 层闸消费;词面单一事实源在本模块)。"""
    return bool(_RELATION_Q_RE.search(question or ""))


def has_rank_words(question: str | None) -> bool:
    """rank 语感判定(最高/哪些/top-N/排行;21 号票 B 注记消费,graph 层)。"""
    return bool(_RANK_WORDS_RE.search(question or "") or "哪些" in (question or "") or "最高" in (question or ""))


def arbitrate_trend_hit(metric_key: str, clean: str) -> str:
    """趋势命中后的两道降级仲裁(榜单语义/完整时间窗)—— L0 词林命中路与
    分类头 on 接管路共用同一函数(2026-10-28 终审:接管路此前绕过仲裁,
    同题形状两路行为分叉)。

    1. 榜/排行语义优先于趋势(仅 gmv/volume 族,见 _RANK_SHAPED_DOWNGRADE);
    2. 完整时间窗(今天/上月/近30天等闭窗 kind≠last_months)问的是该窗的量
       不是随时间的线:「上个月销量」曾被 volume_trend 的 synonym「月销量」
       子串假命中(上个·月销量·,长词优先);显式趋势语感(_EXPLICIT_TREND_RE,
       含每日/每天日粒度)或月粒度语感(last_months,「近3个月的销量」自动切
       自然月粒度)时趋势指标照旧。
    """
    if not metric_key.endswith("_trend"):
        return metric_key
    if _RANK_WORDS_RE.search(clean):
        return _RANK_SHAPED_DOWNGRADE.get(metric_key, metric_key)
    if not _EXPLICIT_TREND_RE.search(clean):
        _, tw_probe, _ = extract_slots(clean)
        if tw_probe and tw_probe.get("kind") != "last_months":
            return _TREND_DOWNGRADE.get(metric_key, metric_key)
    return metric_key


def category_pattern() -> re.Pattern[str]:
    """品类词表正则(ADR-0010:枚举维度单一事实源 = semantic_model.yaml;
    新增品类改模型 YAML,不改本模块)。惰性构建(进程一次)避免加载环。"""
    global _CATEGORY_PATTERN
    if _CATEGORY_PATTERN is None:
        from .tools_registry_bridge import semantic_model

        values = semantic_model()["dimensions"]["category"]["values"]
        _CATEGORY_PATTERN = re.compile("|".join(values), re.IGNORECASE)
    return _CATEGORY_PATTERN


_CATEGORY_PATTERN: re.Pattern[str] | None = None

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
    ("last_7d", re.compile(r"最近\s*(一|7)\s*天|近\s*7\s*天|(?:最近|近)\s*一?周")),
    ("last_30d", re.compile(r"最近\s*(三十|30)\s*天|近\s*(三十|30)\s*天")),
    # 跨月统计(用户实弹诉求):近/最近/过去 N 个月、「几个月的销量」(N 缺省 6);
    # 纯「每月/按月/月度」无 N 同样切月粒度(N 缺省 6)
    ("last_months", re.compile(r"(?:(?:近|最近|过去)\s*)?(\d{1,2}|[一两二三四五六七八九十几]+)\s*个月的?")),
    ("last_months", re.compile(r"每月|按月|月度")),
    # grill 2026-10-26 P0① 时间窗扩容:常见口语时间词此前全部静默落全历史。
    # 刻意排在预设窗之后 —— clarify 点选回问是「原句(最近7天)」形,预设窗
    # 先命中才能让用户选的口径压过原句里的闭集外时间词(见 unparsed_time_hint)。
    ("today", re.compile(r"今天|今日")),
    ("yesterday", re.compile(r"昨天|昨日")),
    ("this_week", re.compile(r"本周|这一周|这周")),
    ("last_week", re.compile(r"上周|上一周")),
    ("this_month", re.compile(r"本月|这个月|当月")),
    ("this_year", re.compile(r"今年|本年|本?年度|年初至今")),
    ("last_year", re.compile(r"去年|上一年|上年度")),
)
# 时间语感探测(P0① 反问闸):TIME_PATTERNS 未命中后的兜底探测 —— 问句带
# **不可解析**时间词(季度/节日/自定义日期段/星期几/昨晚)→ 由 graph 反问
# 时间口径,严禁静默按全历史聚合出数(「昨天卖了多少」曾拿全时段数冒充)。
# 刻意只收录闭集外语感:今天/昨天/本周/今年等已可解析,入了 hint 会让无指标
# 闲聊(「今天心情如何」)错走时间反问而非 unsupported 诚实拒答。
_TIME_HINT_RE = re.compile(
    r"昨|前天|大前天|礼拜|星期|季度|q[1-4]|半年|"
    r"双十一|双11|双十二|618|年货节|"
    r"\d{4}\s*年|\d{1,2}\s*月份?|\d{1,2}\s*号|\d{1,2}\s*日"
)


def unparsed_time_hint(question: str) -> str | None:
    """extract_slots 未命中时间窗后调用:返回触发反问的时间词面(无则 None)。"""
    m = _TIME_HINT_RE.search(question or "")
    return m.group(0) if m else None
CN_MONTH_NUMS = {"一": 1, "两": 2, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6,
                 "七": 7, "八": 8, "九": 9, "十": 10, "几": 6}
CHART_HINTS = (
    ("line", re.compile(r"折线|曲线|趋势图")),
    ("bar", re.compile(r"柱状|条形|柱形")),
    ("table", re.compile(r"表格")),
)

_TREND_UPGRADE = {"gmv": "gmv_trend", "volume": "volume_trend", "order_count": "orders_trend"}
# 趋势→基础指标降级映射(完整时间窗仲裁消费;程序化派生防手抄漂移)。
# 注意本三元集**不是**趋势族完整单一事实源 —— 规范源是 chart_policy.
# trend_family()(4 元,含 customer_spend_trend);这里只收「有基础指标可
# 降级」的子集,customer_spend_trend 无基础对应故不参与任何降级。
_TREND_DOWNGRADE = {v: k for k, v in _TREND_UPGRADE.items()}
# 榜单语义降级专用子集:仅 gmv/volume 两族(基础指标 shape=spu_rank 真榜单形,
# 「销量趋势榜」问的是榜单);orders_trend→order_count 落点为 total_single
# 单值,top-N 语义无任何承接,降级即丢语感 —— 榜单词 × 订单趋势保持趋势
# (2026-10-28 终审收口:程序化派生全集在此处过度扩员)。
_RANK_SHAPED_DOWNGRADE = {"gmv_trend": "gmv", "volume_trend": "volume"}
_RANK_WORDS_RE = re.compile(r"排行|排名|榜单|榜|top\s*\d*")
# 显式趋势语感词:在场时完整时间窗不降级(问的确实是随时间的线)。含日粒度
# 语感(每日/每天/逐日/按天)—— metrics.yaml 趋势族 synonyms 自身编码了
# 「每日订单/每天订单数/每日销售额」措辞,漏收则「上个月每日销售额」被降级
# 成商品榜,序列粒度整层蒸发(2026-10-28 终审实锤)。
_EXPLICIT_TREND_RE = re.compile(r"趋势|走势|折线|曲线|变化|每日|每天|逐日|按天")


def parse_chart_hint(clean: str) -> str | None:
    """图表类型指令槽(Q3):用户点名图型时覆盖卡片自动推断。"""
    return next((v for v, pat in CHART_HINTS if pat.search(clean)), None)


def extract_slots(clean: str) -> tuple[int, dict | None, str | None]:
    """开放槽位解析(limit/时间窗/品类);L0 命中路与分类头 on 路径共用。"""
    limit_match = LIMIT_RE.search(clean)
    limit = min(max(int(limit_match.group(1)) if limit_match else 5, 1), 50)
    # 多时间词并现取**最右**命中(评审 Spec① 收口,2026-10-28):口径以最后
    # 说出的为准 —— 改写器泄漏旧词(「上个月的销量 按最近7天」)时旧首序
    # 匹配会让上月静默胜出,正是 P0① 要消灭的错答形态;单时间词问句行为不变。
    time_window: dict | None = None
    best: tuple[int, str, re.Match] | None = None
    for kind, pat in TIME_PATTERNS:
        m = pat.search(clean)
        if m and (best is None or m.end() > best[0]):
            best = (m.end(), kind, m)
    if best is not None:
        kind, m = best[1], best[2]
        time_window = {"kind": kind}
        if kind == "last_months":
            raw = m.group(1) if m.groups() else None
            n = int(raw) if raw and raw.isdigit() else CN_MONTH_NUMS.get(raw or "", 6)
            time_window["n"] = min(max(n, 1), 24)
    cat_match = category_pattern().search(clean)
    category = cat_match.group(0) if cat_match else None
    return limit, time_window, category


class LexiconResolver:
    """L0 词表 resolver + 缝②分类头三态(shadow=并行只记日志 / on=未命中接管)。

    分类头懒加载由工厂保证,进程内单例;阈值 AI_METRIC_HEAD_THRESHOLD(默认 0.5)。
    """

    def __init__(self) -> None:
        # 11-D1 缝②:AI_METRIC_HEAD=off|shadow|on(默认不启用)
        from .metric_head import get_metric_head, head_mode

        self._head = get_metric_head()
        self._head_mode = head_mode()  # 遥测标注与工厂同源(仅 head 非 None 时事件才打)
        self._head_threshold = float(os.environ.get("AI_METRIC_HEAD_THRESHOLD", "0.5"))

    def resolve(self, question: str) -> StructuredQueryIntent | Clarify:
        from .engine import Clarify, StructuredQueryIntent, UnsupportedQuery

        clean = (question or "").strip().lower()
        if not clean:
            raise UnsupportedQuery("空问题")

        # 域外实体入口闸(eval-gap-2026-10 14 号票):「竞品卖得怎么样」曾被
        # volume 词面命中后静默丢弃「竞品」限定词、按本店销量榜作答(08-P1
        # 铁律违例)—— 域外限定词在词林匹配**之前**响亮拒绝。词表刻意收紧
        # (逐词可枚举、可举证);「市场/行业」等高碰撞词不入列,防误伤
        # 「市场份额」类合法问句。
        if _EXTERNAL_ENTITY_RE.search(clean):
            raise UnsupportedQuery(
                "「竞品/同行/供应商」类域外数据不在本店分析范围,暂不支持该问题"
                "(数据源仅覆盖本店订单/商品/客户/活动)"
            )

        # 关系问句闸与域外闸同族(入口响亮拒绝,词林匹配之前):
        if _RELATION_Q_RE.search(clean):
            raise UnsupportedQuery(
                "跨指标「关系/关联」类问答暂不支持:语义层为单一注册指标的确定性"
                "口径,无指标间关系数据面;请分别询问单个指标"
            )

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
            # 榜单语义/完整时间窗两道降级仲裁(L0 命中路;规则见 arbitrate_trend_hit)
            hit = (arbitrate_trend_hit(hit[0], clean), hit[1])

        # 分类头同一次 resolve 只打一次分:shadow 对比与 on 接管共用这一次结果。
        # 此前 hit 未命中时上方 shadow 块与下方 on 块各 predict 一遍(同问句双跑)。
        head_call: tuple[str, float] | None = None
        if self._head is not None:
            try:
                head_label, head_conf = self._head.predict(question)
                head_call = (head_label, head_conf)
                if hit is not None:
                    # 遥测:一致只计数不打 print(分歧率 = 分歧/(分歧+一致) 需要分母)
                    head_telemetry.record_event(
                        "shadow_agree" if head_label == hit[0] else "shadow_divergence",
                        question=question, mode=self._head_mode,
                        head_label=head_label, head_conf=head_conf, l0_metric=hit[0],
                    )
                    if head_label != hit[0]:
                        print(
                            f"[MetricHead][shadow] 不一致: L0={hit[0]} head={head_label}({head_conf:.2f})"
                            f" question={question[:40]!r}"
                        )
            except Exception as head_err:
                head_telemetry.record_event("head_error", question=question, mode=self._head_mode)
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
                        head_telemetry.record_event(
                            "head_takeover",
                            question=question, mode=self._head_mode,
                            head_label=head_label, head_conf=head_conf,
                        )
                        # 接管路与 L0 命中路共用同一趋势仲裁(2026-10-28 终审:
                        # 此前接管直接构造意图绕过两道降级,同题两路分叉);
                        # 遥测记录 head 原始判读,仲裁只作用于接管产物。
                        return StructuredQueryIntent(
                            metric=arbitrate_trend_hit(head_label, clean),
                            direction=registry[head_label]["direction"],
                            limit=limit2, time_window=time2, category=cat2,
                            chart_hint=parse_chart_hint(clean),
                        )
                    # 置信不足(或标签出闭集)→ 放行 L3,遥测如实计一笔
                    head_telemetry.record_event(
                        "head_low_conf_pass",
                        question=question, mode=self._head_mode,
                        head_label=head_label, head_conf=head_conf,
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
