"""query_exemplars L2 查询示例服务(08-D3;阶段③)。

双池:__global__ 全局共享 + 租户池;检索 = embedding 余弦(经现有
get_embedding_model,与判重缓存同底座);阈值默认 0.90(比意图示例 0.05 严,
分析问句错配代价高)。命中即回放其结构化查询意图 —— L0 未命中处的 few-shot
先例层;低分不兜底(诚实 UnsupportedQuery 路线不变)。
"""

from __future__ import annotations

import json
import uuid

from sqlalchemy import select

from ..db import QueryExemplar, get_session
from ..triage.semantic_cache import cosine_similarity

GLOBAL_POOL = "__global__"
MATCH_THRESHOLD = 0.90


async def add_exemplar(business_id: str, question: str, intent: dict, source: str = "manual") -> str:
    """登记示例(意图为结构化查询意图 dict;embedding 现算入库)。"""
    from ..llm import get_embedding_model

    vector = await get_embedding_model().aembed_query(question)
    async with get_session() as session:
        row = QueryExemplar(
            id=f"qx_{uuid.uuid4().hex[:12]}",
            business_id=business_id or GLOBAL_POOL,
            question=question,
            intent_json=json.dumps(intent, ensure_ascii=False),
            embedding=vector,
            source=source,
            is_active=True,
        )
        session.add(row)
        await session.commit()
        return row.id


async def search_exemplar(question: str, business_id: str, limit: int = 3) -> dict | None:
    """双池检索(全局 + 租户):最高分 ≥ 阈值才返回 {question, intent, similarity}。

    embedding 生成失败/无示例 → None(调用方走 L0/UnsupportedQuery,不静默兜底)。
    """
    from ..llm import get_embedding_model

    try:
        vector = await get_embedding_model().aembed_query(question)
    except Exception as err:
        print(f"[QueryExemplar] embedding 失败,示例层放行: {err}")
        return None

    async with get_session() as session:
        rows = (
            await session.execute(
                select(QueryExemplar).where(
                    QueryExemplar.is_active.is_(True),
                    QueryExemplar.business_id.in_([GLOBAL_POOL, business_id or GLOBAL_POOL]),
                )
            )
        ).scalars().all()

    best: dict | None = None
    for row in rows:
        if not row.embedding:
            continue
        score = cosine_similarity(vector, row.embedding)
        if score >= MATCH_THRESHOLD and (best is None or score > best["similarity"]):
            best = {"question": row.question, "intent": json.loads(row.intent_json), "similarity": score}
    return best
