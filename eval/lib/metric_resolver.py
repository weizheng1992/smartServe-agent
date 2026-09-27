"""指标语义消歧 resolve(promptfoo 评测预言机)— 旧 MetricSemanticResolver 的 1:1 移植。

f9e737a 把指标注册表外置 metrics.yaml 并从 engine 删除该类(eval 是唯一消费方,
未跟改 → unified 5 例 ImportError)。本模块按旧语义在 eval 侧重建:指标数据全部
读 engine_py.tools_registry.metric_registry.METRIC_SEMANTIC_REGISTRY(YAML 单一
事实源),仅匹配/歧义判定逻辑随 eval 走 —— engine 面保持精简,不回填死代码。

返回形状与旧类逐字兼容:primaryMetric / isExplicit / matchedSynonym /
hasAmbiguity / conflictMetrics;消费方 eval/providers/agent_provider.py 与
eval/scorers/metric_disambiguation.py。
"""

from __future__ import annotations

from engine_py.tools_registry.metric_registry import METRIC_SEMANTIC_REGISTRY

# 泛指模糊提问(未指明具体量度)与量度限定词表 —— f9e737a^ 原文逐字搬移
_GENERIC_PHRASES = ["卖得好", "卖得最好", "最好", "最棒", "表现最好", "排名靠前", "头部商品"]
_DEFINITIVE_WORDS = [
    "金额", "件数", "出货", "销量", "走量", "毛利", "利润", "流水", "营业额", "溢价", "库存", "积压", "滞销",
]


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
