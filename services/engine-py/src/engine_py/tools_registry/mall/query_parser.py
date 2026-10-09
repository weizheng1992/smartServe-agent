"""货架词典解析器(ADR-0012):导购检索词产出从「分块偶然切分」升格为
「块内结构化解析」—— 词素在块不在句的命运由分块边界随机决定(实弹三连:
0927 搭配补脚 / 1001 衣族别名 / 1009 黏词兜底,各修一种措辞形状),本模块把
词典匹配挪进每个块内,分块边界不再决定词素命运。

与 analytics L0 词林同哲学(显式小词典 + 最长匹配 + 确定性可钉面),不同域:
guide 词典 = 静态语言知识(词素/别名,核实纪律:只在核实过货架词素后收录)
∪ 动态品类词(货架运营数据,消费方每回合经 get_shelf_overview 注入,商户改
品类自动跟)。纯函数零 IO:词典、分块、清洗全部注入,消费方
catalog.search_products 装配;AI_GUIDE_PARSER=off 或解析异常时逐字节回退旧
词元路(ADR-0012 决策 1/7)。

块内算法(单块,依序):
1. 词典最长匹配(别名键 ∪ 别名词素 ∪ 品类词,键长降序、块内不重叠消费)
   → 命中键按首现序进 legs;块内剩余胶水(黏在词素上的修饰/量化语)进
   modifiers 只剥不扬(不进检索、不参与排序,ADR-0012 决策 2);
2. 无词典命中 → 场景/修饰册包含命中 → 整块进 modifiers(「天气冷了」「外出
   游玩」类不再发死查询);
3. 否则 → 原块进 legs(「装备」「露营装备」等不在册词保留为脚,recall 不缩;
   品类列宽名靠 ILIKE 子串命中,精确 category 过滤明确不做——「背包」≠
   品类列「背包收纳」,ADR-0012 否决项)。

调用方纪律(ADR-0012 决策 7):解析 legs 为空时**整句回退旧词元路**、严禁
部分混搭 —— 解析器只在有产出时接管,零产出口(全修饰句/未收录口语)保持
今日行为(含 L2 语义/L4 改写对死词元的既有兜底语义)。
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass


@dataclass(frozen=True)
class ParsedShelfQuery:
    """解析产物:legs = 检索脚(轮转消费);modifiers = 只剥不扬的修饰槽
    (v1 不消费,给排序议题留缝);dropped 不设 —— 胶水即 modifiers,观测
    经 [GuideParser] diff 日志走 modifiers 面。"""

    legs: tuple[str, ...]
    modifiers: tuple[str, ...]


def parse_shelf_query(
    query: str | None,
    *,
    wrapper_terms: tuple[str, ...],
    stem_aliases: dict[str, tuple[str, ...]],
    modifier_terms: tuple[str, ...],
    categories: Iterable[str],
    split_chunks: Callable[[str], list[str]],
    clean_chunk: Callable[[str], str],
) -> ParsedShelfQuery:
    """导购问句 → 结构化槽位。词典与文本基元全部注入,本函数零 IO 零正则。

    wrapper 剥词与分块清洗沿用 catalog 既有实现(单一事实源不搬);本模块
    只负责块内词典匹配与三分类(legs / modifiers / 弃胶水)。"""
    if not query:
        return ParsedShelfQuery(legs=(), modifiers=())
    rest = query
    for term in sorted(wrapper_terms, key=len, reverse=True):
        rest = rest.replace(term, " ")

    # 词典 = 别名键 ∪ 别名词素(自映射)∪ 品类词;键长降序 = 最长匹配优先。
    keys: set[str] = set(stem_aliases)
    for stems in stem_aliases.values():
        keys.update(stems)
    keys.update(c for c in categories if c)
    keys.discard("")
    ordered = sorted(keys, key=len, reverse=True)

    legs: list[str] = []
    modifiers: list[str] = []
    for chunk in split_chunks(rest):
        cleaned = clean_chunk(chunk.strip())
        if not cleaned:
            continue
        hits, spans = _match_keys(cleaned, ordered)
        if hits:
            legs.extend(hits)
            leftover = _remove_spans(cleaned, spans).strip()
            if leftover:
                modifiers.append(leftover)
        elif any(m in cleaned for m in modifier_terms):
            modifiers.append(cleaned)
        else:
            legs.append(cleaned)
    return ParsedShelfQuery(
        legs=tuple(dict.fromkeys(legs)),
        modifiers=tuple(dict.fromkeys(modifiers)),
    )


def _match_keys(
    chunk: str, ordered_keys: list[str]
) -> tuple[list[str], list[tuple[int, int]]]:
    """块内词典命中:键长降序扫描,位置不重叠消费(「登山包」整体命中后
    「登山」「背包」让位);同键多处命中只记一词;返回 (命中键首现序, 消费
    区间)。"""
    spans: list[tuple[int, int]] = []
    hits: list[tuple[int, str]] = []
    for key in ordered_keys:
        start = 0
        added = False
        while True:
            idx = chunk.find(key, start)
            if idx < 0:
                break
            start = idx + 1
            end = idx + len(key)
            if any(idx < e and s < end for s, e in spans):
                continue
            spans.append((idx, end))
            if not added:
                hits.append((idx, key))
                added = True
    hits.sort(key=lambda pair: pair[0])
    return [key for _, key in hits], spans


def _remove_spans(chunk: str, spans: list[tuple[int, int]]) -> str:
    """剔除已消费区间,余下即黏词胶水(「一些衣服」→「一些」)。"""
    pieces: list[str] = []
    pos = 0
    for start, end in sorted(spans):
        pieces.append(chunk[pos:start])
        pos = end
    pieces.append(chunk[pos:])
    return "".join(pieces)
