"""向量纯函数单一实现:余弦相似度 + embedding 列解析。

此前同一对纯函数在全仓存在 5 份逐字拷贝(memory/long_memory、
memory/episodic_memory、rag/contextual_rag、tools_registry/mall_domain、
triage/semantic_cache 正本),零范数/维度不等的防御口径各自漂移风险高
—— 2026-10-02 夜审收敛到本模块,旧位一律转发导入(semantic_cache 保留
公开名 cosine_similarity 供 triage/analytics 两个 exemplar_service 消费)。"""

from __future__ import annotations

import json
import math


def cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    """余弦相似度;维度不等或零范数诚实返回 0(与历史各份语义一致,严禁抛异常)。"""
    if len(vec_a) != len(vec_b):
        return 0
    dot = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = math.sqrt(sum(a * a for a in vec_a))
    norm_b = math.sqrt(sum(b * b for b in vec_b))
    denom = norm_a * norm_b
    return dot / denom if denom else 0


def parse_embedding(raw: object) -> list[float] | None:
    """embedding 列(JSON 串 / 已反序列化 list)→ list[float];坏值诚实 None。"""
    if not raw:
        return None
    try:
        value = json.loads(raw) if isinstance(raw, str) else raw
        return value if isinstance(value, list) else None
    except Exception:
        return None
